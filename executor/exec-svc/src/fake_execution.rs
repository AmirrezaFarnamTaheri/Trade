//! Durable service integration fixture. There is deliberately no network transport or key input.
use crate::{
    offline_recovery::{
        DurableOrderJournal, ExecutionIdentity, ExecutionSettlement, Purpose, RecoveryError, Side,
    },
    StopGate,
};
use exec_core::orders::{BalanceSnapshot, Event, FailureStage, Lifecycle, SettlementEvidence};
use exec_ipc::StopMode;
use std::{collections::BTreeMap, path::Path, sync::Arc};

#[derive(Clone, Debug)]
pub struct FakeMarket {
    pub base: String,
    pub quote: String,
    pub price: u64,
    pub observed_at_ms: u64,
    pub open: bool,
    pub rules_version: String,
    pub method: String,
    pub certified_until_ms: u64,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Dispatch {
    Acknowledge,
    BeforeFirstByte,
    LoseAcknowledgement,
}
#[derive(Debug, PartialEq)]
pub enum ExecutionError {
    Journal(RecoveryError),
    InvalidInput,
    Stopped,
    Expired,
    StaleMarket,
    Closed,
    Uncertified,
    RulesChanged,
    OutsideEnvelope,
    Conflict,
    InsufficientBalance,
    UnknownIntent,
    RetryForbidden,
    NotTerminal,
}
impl From<RecoveryError> for ExecutionError {
    fn from(error: RecoveryError) -> Self {
        Self::Journal(error)
    }
}
#[derive(Clone)]
struct FakeOrder {
    account: String,
    quantity: u64,
    identity: ExecutionIdentity,
    filled: u64,
    fee_asset: String,
    fee: u64,
    price: u64,
    terminal: bool,
}
#[derive(Default)]
pub struct FakeVenue {
    markets: BTreeMap<String, FakeMarket>,
    balances: BTreeMap<(String, String), (u64, u64)>,
    orders: BTreeMap<String, FakeOrder>,
    posts: usize,
}
impl FakeVenue {
    pub fn set_market(&mut self, market: FakeMarket) {
        self.markets
            .insert(format!("{}{}", market.base, market.quote), market);
    }
    pub fn set_balance(&mut self, account: &str, asset: &str, available: u64, sequence: u64) {
        self.balances
            .insert((account.into(), asset.into()), (available, sequence));
    }
    pub fn balance(&self, account: &str, asset: &str) -> Option<(u64, u64)> {
        self.balances.get(&(account.into(), asset.into())).copied()
    }
    pub fn post_count(&self) -> usize {
        self.posts
    }
    pub fn order_count(&self) -> usize {
        self.orders.len()
    }
    fn place(
        &mut self,
        id: &str,
        account: &str,
        quantity: u64,
        identity: &ExecutionIdentity,
        dispatch: Dispatch,
    ) -> Result<Event, ExecutionError> {
        if dispatch == Dispatch::BeforeFirstByte {
            return Ok(Event::TransportFailed(FailureStage::BeforeFirstByte));
        }
        if self.orders.contains_key(id) {
            return Err(ExecutionError::RetryForbidden);
        }
        let market = self
            .markets
            .get(&identity.instrument)
            .ok_or(ExecutionError::InvalidInput)?;
        self.orders.insert(
            id.into(),
            FakeOrder {
                account: account.into(),
                quantity,
                identity: identity.clone(),
                filled: 0,
                fee_asset: identity.quote.clone(),
                fee: 0,
                price: market.price,
                terminal: false,
            },
        );
        self.posts += 1;
        Ok(if dispatch == Dispatch::LoseAcknowledgement {
            Event::TransportFailed(FailureStage::AfterFirstByte)
        } else {
            Event::Acknowledged
        })
    }
    /// External venue action, not an Executor command. Cumulative fills may arrive after HALT.
    pub fn fill(
        &mut self,
        id: &str,
        cumulative: u64,
        fee_asset: &str,
        fee: u64,
        terminal: bool,
    ) -> Result<(), ExecutionError> {
        let previous = self
            .orders
            .get(id)
            .ok_or(ExecutionError::UnknownIntent)?
            .clone();
        let identity = &previous.identity;
        if previous.terminal
            || cumulative < previous.filled
            || cumulative > previous.quantity
            || (fee_asset != identity.base && fee_asset != identity.quote)
            || fee_asset != previous.fee_asset && previous.fee != 0
            || fee < previous.fee
            || cumulative == 0 && fee != 0
            || fee_asset == identity.base && fee > cumulative
        {
            return Err(ExecutionError::InvalidInput);
        }
        let gross = cumulative
            .checked_mul(previous.price)
            .ok_or(ExecutionError::InvalidInput)?;
        let old_gross = previous
            .filled
            .checked_mul(previous.price)
            .ok_or(ExecutionError::InvalidInput)?;
        let direction: i128 = if identity.side == Side::Buy { 1 } else { -1 };
        let base_delta = direction * i128::from(cumulative - previous.filled)
            - if fee_asset == identity.base {
                i128::from(fee - previous.fee)
            } else {
                0
            };
        let quote_delta = -direction * i128::from(gross - old_gross)
            - if fee_asset == identity.quote {
                i128::from(fee - previous.fee)
            } else {
                0
            };
        let mut balances = self.balances.clone();
        for (asset, delta) in [(&identity.base, base_delta), (&identity.quote, quote_delta)] {
            let balance = balances
                .get_mut(&(previous.account.clone(), asset.clone()))
                .ok_or(ExecutionError::InsufficientBalance)?;
            balance.0 = u64::try_from(i128::from(balance.0) + delta)
                .map_err(|_| ExecutionError::InsufficientBalance)?;
            balance.1 = balance
                .1
                .checked_add(1)
                .ok_or(ExecutionError::InvalidInput)?;
        }
        let order = self.orders.get_mut(id).expect("looked up above");
        order.filled = cumulative;
        order.fee_asset = fee_asset.into();
        order.fee = fee;
        order.terminal = terminal;
        self.balances = balances;
        Ok(())
    }
    fn cancel(&mut self, id: &str) -> Result<(), ExecutionError> {
        let order = self
            .orders
            .get_mut(id)
            .ok_or(ExecutionError::UnknownIntent)?;
        order.terminal = true;
        Ok(())
    }
    fn receipt(&mut self, id: &str) -> Result<ExecutionSettlement, ExecutionError> {
        let order = self
            .orders
            .get(id)
            .ok_or(ExecutionError::UnknownIntent)?
            .clone();
        if !order.terminal {
            return Err(ExecutionError::NotTerminal);
        }
        let identity = &order.identity;
        let asset = if identity.side == Side::Buy {
            &identity.quote
        } else {
            &identity.base
        };
        let observed = self
            .balances
            .get_mut(&(order.account.clone(), asset.clone()))
            .ok_or(ExecutionError::InsufficientBalance)?;
        observed.1 = observed
            .1
            .checked_add(1)
            .ok_or(ExecutionError::InvalidInput)?;
        let (available, sequence) = *observed;
        let gross = if identity.side == Side::Buy {
            order
                .filled
                .checked_mul(order.price)
                .ok_or(ExecutionError::InvalidInput)?
        } else {
            order.filled
        };
        let spent = gross
            .checked_add(if order.fee_asset == *asset {
                order.fee
            } else {
                0
            })
            .ok_or(ExecutionError::InvalidInput)?;
        let balance =
            SettlementEvidence::new(&order.account, asset, sequence, true, 0, spent, available)
                .map_err(|_| ExecutionError::InvalidInput)?;
        Ok(ExecutionSettlement {
            filled_quanta: order.filled,
            gross_quote_quanta: order
                .filled
                .checked_mul(order.price)
                .ok_or(ExecutionError::InvalidInput)?,
            fee_asset: order.fee_asset.clone(),
            fee_quanta: order.fee,
            balance,
        })
    }
}

/// Only this fixture can create these approvals. This is NOT an authenticated live T1 token.
#[derive(Clone)]
pub struct ApprovedFakeIntent {
    id: String,
    account: String,
    quantity: u64,
    identity: ExecutionIdentity,
}
pub struct FakeExecution {
    journal: DurableOrderJournal,
    gate: Arc<StopGate>,
}
impl FakeExecution {
    pub fn open(path: impl AsRef<Path>, gate: Arc<StopGate>) -> Result<Self, ExecutionError> {
        Ok(Self {
            journal: DurableOrderJournal::open(path)?,
            gate,
        })
    }
    pub fn journal(&self) -> &DurableOrderJournal {
        &self.journal
    }
    fn stop_check(&self, purpose: Purpose) -> Result<(), ExecutionError> {
        match self.gate.mode() {
            StopMode::Halted => Err(ExecutionError::Stopped),
            StopMode::Paused | StopMode::ExitOnly if purpose != Purpose::ProtectiveExit => {
                Err(ExecutionError::Stopped)
            }
            _ => Ok(()),
        }
    }
    #[allow(clippy::too_many_arguments)]
    pub fn approve(
        &self,
        venue: &FakeVenue,
        id: &str,
        account: &str,
        instrument: &str,
        quantity: u64,
        purpose: Purpose,
        side: Side,
        max_quote_quanta: u64,
        expires_at_ms: u64,
        now_ms: u64,
    ) -> Result<ApprovedFakeIntent, ExecutionError> {
        let market = venue
            .markets
            .get(instrument)
            .ok_or(ExecutionError::InvalidInput)?;
        let identity = ExecutionIdentity {
            instrument: instrument.into(),
            base: market.base.clone(),
            quote: market.quote.clone(),
            side,
            purpose,
            method: market.method.clone(),
            approval: format!("fake-{}-{id}", self.gate.runtime_epoch()),
            rules_version: market.rules_version.clone(),
            runtime_epoch: self.gate.runtime_epoch(),
            expires_at_ms,
            limit_price: market.price,
            max_quote_quanta,
        };
        let approved = ApprovedFakeIntent {
            id: id.into(),
            account: account.into(),
            quantity,
            identity,
        };
        self.preflight(venue, &approved, now_ms)?;
        Ok(approved)
    }
    fn preflight(
        &self,
        venue: &FakeVenue,
        approved: &ApprovedFakeIntent,
        now_ms: u64,
    ) -> Result<(), ExecutionError> {
        let identity = &approved.identity;
        self.stop_check(identity.purpose)?;
        if identity.purpose == Purpose::ProtectiveExit && identity.side != Side::Sell {
            return Err(ExecutionError::InvalidInput);
        }
        if identity.runtime_epoch != self.gate.runtime_epoch() || now_ms >= identity.expires_at_ms {
            return Err(ExecutionError::Expired);
        }
        let market = venue
            .markets
            .get(&identity.instrument)
            .ok_or(ExecutionError::InvalidInput)?;
        if !market.open {
            return Err(ExecutionError::Closed);
        }
        if market.observed_at_ms > now_ms || now_ms - market.observed_at_ms > 2_000 {
            return Err(ExecutionError::StaleMarket);
        }
        if now_ms >= market.certified_until_ms || market.method != identity.method {
            return Err(ExecutionError::Uncertified);
        }
        if market.rules_version != identity.rules_version
            || market.base != identity.base
            || market.quote != identity.quote
        {
            return Err(ExecutionError::RulesChanged);
        }
        let gross = approved
            .quantity
            .checked_mul(market.price)
            .ok_or(ExecutionError::OutsideEnvelope)?;
        if approved.quantity == 0
            || market.price == 0
            || identity.max_quote_quanta == 0
            || (identity.side == Side::Buy
                && (market.price > identity.limit_price || gross > identity.max_quote_quanta))
            || (identity.side == Side::Sell && market.price < identity.limit_price)
        {
            return Err(ExecutionError::OutsideEnvelope);
        }
        let asset = if identity.side == Side::Buy {
            &identity.quote
        } else {
            &identity.base
        };
        let (available, _) = venue
            .balance(&approved.account, asset)
            .ok_or(ExecutionError::InsufficientBalance)?;
        let reserved = if identity.side == Side::Buy {
            identity.max_quote_quanta
        } else {
            approved.quantity
        };
        if available < reserved {
            return Err(ExecutionError::InsufficientBalance);
        }
        for id in self.journal.pending_ids() {
            if id == approved.id {
                continue;
            }
            let pending = self.journal.get(id).expect("pending journal identity");
            if pending.account != approved.account {
                continue;
            }
            let Some(other) = &pending.execution else {
                return Err(ExecutionError::Conflict);
            };
            if other.instrument == identity.instrument
                || other.base == identity.base
                || other.quote == identity.base
                || identity.purpose != Purpose::ProtectiveExit
            {
                return Err(ExecutionError::Conflict);
            }
        }
        Ok(())
    }
    pub fn submit(
        &mut self,
        venue: &mut FakeVenue,
        approved: ApprovedFakeIntent,
        now_ms: u64,
        dispatch: Dispatch,
    ) -> Result<(), ExecutionError> {
        self.preflight(venue, &approved, now_ms)?;
        let asset = if approved.identity.side == Side::Buy {
            &approved.identity.quote
        } else {
            &approved.identity.base
        };
        let (available, sequence) = venue
            .balance(&approved.account, asset)
            .ok_or(ExecutionError::InsufficientBalance)?;
        let snapshot = BalanceSnapshot::new(&approved.account, asset, available, sequence)
            .map_err(|_| ExecutionError::InvalidInput)?;
        self.journal.create_execution(
            &approved.id,
            &approved.account,
            approved.quantity,
            &approved.identity,
            &snapshot,
        )?;
        if let Err(error) = self.stop_check(approved.identity.purpose) {
            self.journal.record_event(&approved.id, Event::Denied)?;
            self.journal.release_denied_reservation(&approved.id)?;
            return Err(error);
        }
        self.dispatch(venue, &approved, now_ms, dispatch)
    }
    fn dispatch(
        &mut self,
        venue: &mut FakeVenue,
        approved: &ApprovedFakeIntent,
        now_ms: u64,
        dispatch: Dispatch,
    ) -> Result<(), ExecutionError> {
        self.preflight(venue, approved, now_ms)?;
        self.journal.record_event(&approved.id, Event::BeginSend)?;
        if let Err(error) = self.stop_check(approved.identity.purpose) {
            self.journal.record_event(
                &approved.id,
                Event::TransportFailed(FailureStage::BeforeFirstByte),
            )?;
            return Err(error);
        }
        let event = venue.place(
            &approved.id,
            &approved.account,
            approved.quantity,
            &approved.identity,
            dispatch,
        )?;
        self.journal.record_event(&approved.id, event)?;
        Ok(())
    }
    pub fn retry(
        &mut self,
        venue: &mut FakeVenue,
        id: &str,
        now_ms: u64,
        dispatch: Dispatch,
    ) -> Result<(), ExecutionError> {
        let order = self.journal.get(id).ok_or(ExecutionError::UnknownIntent)?;
        if !order.attempt.can_retry_same_identity() {
            return Err(ExecutionError::RetryForbidden);
        }
        let approved = ApprovedFakeIntent {
            id: id.into(),
            account: order.account.clone(),
            quantity: order.attempt.requested_quanta(),
            identity: order
                .execution
                .clone()
                .ok_or(ExecutionError::InvalidInput)?,
        };
        self.dispatch(venue, &approved, now_ms, dispatch)
    }
    pub fn cancel(&mut self, venue: &mut FakeVenue, id: &str) -> Result<(), ExecutionError> {
        if self.gate.mode() == StopMode::Halted {
            return Err(ExecutionError::Stopped);
        }
        let order = self.journal.get(id).ok_or(ExecutionError::UnknownIntent)?;
        if !order.attempt.holds_slot() {
            return Err(ExecutionError::NotTerminal);
        }
        venue.cancel(id)
    }
    /// Read-only reconciliation is still permitted after HALT.
    pub fn reconcile(&mut self, venue: &mut FakeVenue, id: &str) -> Result<(), ExecutionError> {
        if self
            .journal
            .get(id)
            .is_some_and(|order| order.execution_settlement.is_some())
        {
            return Ok(());
        }
        self.journal.settle_execution(id, &venue.receipt(id)?)?;
        Ok(())
    }
    pub fn lifecycle(&self, id: &str) -> Option<Lifecycle> {
        self.journal.get(id).map(|order| order.attempt.lifecycle())
    }
}
