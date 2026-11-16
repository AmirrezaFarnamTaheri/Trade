//! Native reviewed LIMIT admission. No network or automatic retry lives here.
use crate::{
    account_observation::{AccountKind, AccountObservation},
    arm_control::{ArmController, ArmEvidence, PolicyLease},
    balance_receipts::BalanceReceipts,
    native_market::MarketObservation,
    offline_recovery::{DurableOrderJournal, IntentPreparation, RecoveryError},
    StopGate,
};
use exec_core::{kernel::Exact, orders::BalanceSnapshot};
use exec_ipc::{review::Ticket, review_v2::valid_submit_client_id, StopMode};
use std::{cmp::Ordering, collections::BTreeMap};

pub struct NativeInputs<'a> {
    pub arm: &'a ArmEvidence,
    pub balances: &'a BalanceReceipts,
    pub fees: &'a AccountObservation,
    pub market: &'a MarketObservation,
    pub own_inventory: &'a BTreeMap<String, Exact>,
    pub net_debits_quote: Exact,
}

#[must_use = "retain the policy lease and recheck immediately before venue bytes"]
pub struct AdmittedOrder {
    pub ticket: Ticket,
    pub body: Vec<u8>,
    lease: PolicyLease,
    valid_until_ms: u64,
}
impl AdmittedOrder {
    pub fn allows_effect_at(&self, gate: &StopGate, now_ms: u64) -> bool {
        now_ms < self.valid_until_ms && self.lease.allows_effect_at(gate, now_ms)
    }
}

pub fn amount(quanta: u64, decimals: u8) -> Exact {
    Exact {
        mantissa: u128::from(quanta),
        scale: u32::from(decimals),
    }
}
pub fn rounded_quanta(value: Exact, decimals: u8, up: bool) -> Option<u64> {
    let floor = value.floor(u32::from(decimals))?;
    let extra = up && value.cmp_value(floor)? == Ordering::Greater;
    floor
        .mantissa
        .checked_add(u128::from(extra))?
        .try_into()
        .ok()
}
fn number(quanta: u64, decimals: u8) -> String {
    if decimals == 0 {
        return quanta.to_string();
    }
    let scale = 10u64.pow(u32::from(decimals));
    format!(
        "{}.{:0width$}",
        quanta / scale,
        quanta % scale,
        width = usize::from(decimals)
    )
}

/// All inputs come from the native host; the durable reviewed ticket is the only order description.
pub fn admit(
    controller: &mut ArmController,
    gate: &StopGate,
    ledger: &mut DurableOrderJournal,
    context: IntentPreparation,
    native: NativeInputs<'_>,
) -> Result<AdmittedOrder, RecoveryError> {
    let invalid = || RecoveryError::InvalidIdentity;
    if gate.mode() != StopMode::Armed
        || context.mode != StopMode::Armed
        || context.runtime_epoch != gate.runtime_epoch()
        || ledger.get(&context.client_id).is_some()
        || !native
            .balances
            .matches_context(context.credential_generation, context.runtime_epoch)
    {
        return Err(invalid());
    }
    let ticket = ledger
        .operator_approval(&context.client_id)
        .ok_or_else(invalid)?
        .approval
        .ticket
        .clone();
    ticket.validate().map_err(|_| invalid())?;
    valid_submit_client_id(&ticket.client_id).map_err(|_| invalid())?;
    if ticket.account != "main"
        || native.fees.kind() != AccountKind::Fees
        || !native.fees.is_fresh(
            context.credential_generation,
            context.runtime_epoch,
            context.recorded_at_ms,
            30_000,
        )
    {
        return Err(invalid());
    }
    let policy = controller.policy().ok_or_else(invalid)?;
    let symbol = format!("{}{}", ticket.base, ticket.quote);
    let stale_ms = u64::from(policy.stale_data_seconds)
        .saturating_mul(1000)
        .min(120_000);
    if ticket.quote != policy.quote_asset
        || native.market.symbol() != symbol
        || !native.market.is_fresh(context.recorded_at_ms, stale_ms)
    {
        return Err(invalid());
    }
    let mut fee = amount(0, 0);
    for field in ["makerFeeRate", "takerFeeRate"] {
        let rate = native.fees.data()["result"][&symbol][field]
            .as_str()
            .and_then(Exact::parse)
            .ok_or_else(invalid)?;
        if rate
            .cmp_value(amount(1, 0))
            .is_none_or(|order| order != Ordering::Less)
        {
            return Err(invalid());
        }
        if rate.cmp_value(fee).ok_or_else(invalid)? == Ordering::Greater {
            fee = rate;
        }
    }
    let quantity = amount(ticket.quantity_quanta, ticket.base_decimals);
    let gross = quantity
        .checked_mul(amount(ticket.worst_price_quanta, ticket.price_decimals))
        .ok_or_else(invalid)?;
    let gross_fee = gross.checked_mul(fee).ok_or_else(invalid)?;
    let required = if ticket.buy {
        let debit = gross.checked_add(gross_fee).ok_or_else(invalid)?;
        if debit
            .cmp_value(amount(ticket.max_quote_debit, ticket.quote_decimals))
            .is_none_or(|order| order == Ordering::Greater)
        {
            return Err(invalid());
        }
        ticket.max_quote_debit
    } else {
        let credit = gross.checked_sub(gross_fee).ok_or_else(invalid)?;
        if credit
            .cmp_value(amount(ticket.min_quote_credit, ticket.quote_decimals))
            .is_none_or(|order| order == Ordering::Less)
        {
            return Err(invalid());
        }
        rounded_quanta(
            quantity
                .checked_mul(amount(1, 0).checked_add(fee).ok_or_else(invalid)?)
                .ok_or_else(invalid)?,
            ticket.base_decimals,
            true,
        )
        .ok_or_else(invalid)?
    };
    let asset = if ticket.buy {
        &ticket.quote
    } else {
        &ticket.base
    };
    let decimals = if ticket.buy {
        ticket.quote_decimals
    } else {
        ticket.base_decimals
    };
    let holds = ledger.reserved(&ticket.account, asset);
    if !ticket.buy {
        let own = native
            .own_inventory
            .get(&ticket.base)
            .copied()
            .ok_or_else(invalid)?;
        let owned_quanta = rounded_quanta(own, decimals, false).ok_or_else(invalid)?;
        if required > owned_quanta.saturating_sub(holds) {
            return Err(invalid());
        }
    }
    let raw = native
        .balances
        .available(asset, decimals, 0, context.recorded_at_ms, stale_ms)
        .map_err(|_| invalid())?;
    if required > raw.available_quanta.saturating_sub(holds) {
        return Err(invalid());
    }
    if ticket.buy {
        let (_, limit) = ledger.installation_ceiling().ok_or_else(invalid)?;
        let committed = native
            .net_debits_quote
            .checked_add(amount(holds, ticket.quote_decimals))
            .and_then(|value| value.checked_add(amount(required, ticket.quote_decimals)))
            .ok_or_else(invalid)?;
        if committed
            .cmp_value(amount(limit.ceiling.capital_quanta, limit.ceiling.decimals))
            .is_none_or(|order| order == Ordering::Greater)
        {
            return Err(invalid());
        }
    }
    // Buy admission caps the entire reviewed debit, including fees and rounding.
    let notional = if ticket.buy {
        amount(ticket.max_quote_debit, ticket.quote_decimals)
    } else {
        gross
    };
    let lease = controller
        .admit_order(gate, native.arm, context.recorded_at_ms, &symbol, notional)
        .map_err(|_| invalid())?;
    let valid_until_ms = ticket
        .expires_at_ms
        .min(
            context
                .recorded_at_ms
                .checked_add(stale_ms.saturating_sub(raw.age_ms))
                .ok_or_else(invalid)?,
        )
        .min(
            native
                .fees
                .received_at_ms()
                .checked_add(30_000)
                .ok_or_else(invalid)?,
        )
        .min(
            native
                .market
                .received_at_ms()
                .checked_add(stale_ms)
                .ok_or_else(invalid)?,
        );
    let body=serde_json::to_vec(&serde_json::json!({"symbol":symbol,"type":"LIMIT",
        "side":if ticket.buy {"BUY"} else {"SELL"},"price":number(ticket.worst_price_quanta,ticket.price_decimals),
        "quantity":number(ticket.quantity_quanta,ticket.base_decimals),"client_id":ticket.client_id})).map_err(|_|invalid())?;
    if !lease.allows_effect_at(gate, context.recorded_at_ms) {
        return Err(invalid());
    }
    let snapshot = BalanceSnapshot::new(
        &ticket.account,
        asset,
        raw.available_quanta,
        raw.receipt_seq,
    )
    .map_err(RecoveryError::Reservation)?;
    ledger.reserve_prepared_with_hold(context, &snapshot, required)?;
    Ok(AdmittedOrder {
        ticket,
        body,
        lease,
        valid_until_ms,
    })
}
