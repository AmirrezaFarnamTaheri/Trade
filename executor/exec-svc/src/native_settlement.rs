//! Native fill reconciliation. Only complete terminal receipts and later balance pairs release a hold.
use crate::{
    account_observation::AccountObservation,
    balance_receipts::BalanceReceipts,
    native_admission::{amount, rounded_quanta},
    native_risk::{fills, matches_ticket},
    offline_recovery::{DurableOrderJournal, RecoveryError},
};
use exec_core::{
    kernel::Exact,
    orders::{Event, Lifecycle},
};
use exec_ipc::review::Ticket;
use std::cmp::Ordering;

pub struct FillSummary {
    pub filled_quanta: u64,
    pub spent_quanta: u64,
    pub terminal: bool,
}
fn text(row: &serde_json::Value, field: &str) -> Result<Exact, &'static str> {
    row[field]
        .as_str()
        .and_then(Exact::parse)
        .ok_or("missing exact fill amount")
}
fn add(a: Exact, b: Exact) -> Result<Exact, &'static str> {
    a.checked_add(b).ok_or("fill amount overflow")
}
fn mul(a: Exact, b: Exact) -> Result<Exact, &'static str> {
    a.checked_mul(b).ok_or("fill amount overflow")
}
pub fn summarize(
    ticket: &Ticket,
    observation: &AccountObservation,
) -> Result<FillSummary, &'static str> {
    ticket.validate()?;
    if !matches_ticket(ticket, observation) {
        return Err("fill receipt identity differs from review");
    }
    let row = &observation.data()["result"];
    let terminal = match row["status"].as_str() {
        Some("NEW" | "PARTIALLY_FILLED") => false,
        Some("FILLED" | "CANCELED" | "CANCELLED" | "REJECTED" | "EXPIRED") => true,
        _ => return Err("unknown own order status"),
    };
    let mut quantity = amount(0, 0);
    let mut spent = amount(0, 0);
    let mut credit = amount(0, 0);
    let limit = amount(ticket.worst_price_quanta, ticket.price_decimals);
    for fill in fills(row)? {
        let q = text(fill, "quantity")?;
        let price = text(fill, "price")?;
        let fee = text(fill, "fee")?;
        let asset = fill["feeAsset"].as_str().ok_or("missing fee asset")?;
        if asset != ticket.base && asset != ticket.quote {
            return Err("unpriced fee asset");
        }
        let cmp = price.cmp_value(limit).ok_or("fill price overflow")?;
        if (ticket.buy && cmp == Ordering::Greater) || (!ticket.buy && cmp == Ordering::Less) {
            return Err("fill breached reviewed limit price");
        }
        // Settlement uses the venue's actual gross cash amount, including its rounding.
        let gross = text(fill, "sum")?;
        if gross.is_zero() {
            return Err("zero gross fill");
        }
        quantity = add(quantity, q)?;
        if ticket.buy {
            if asset == ticket.base
                && fee
                    .cmp_value(q)
                    .is_none_or(|order| order == Ordering::Greater)
            {
                return Err("base fee exceeds fill");
            }
            spent = add(
                spent,
                if asset == ticket.quote {
                    add(gross, fee)?
                } else {
                    gross
                },
            )?;
        } else {
            spent = add(
                spent,
                if asset == ticket.base {
                    add(q, fee)?
                } else {
                    q
                },
            )?;
            credit = add(
                credit,
                if asset == ticket.quote {
                    gross.checked_sub(fee).ok_or("fee exceeds proceeds")?
                } else {
                    gross
                },
            )?;
        }
    }
    let executed = text(row, "executedQty")?;
    if quantity.cmp_value(executed) != Some(Ordering::Equal) {
        return Err("incomplete native fills");
    }
    let filled =
        rounded_quanta(executed, ticket.base_decimals, false).ok_or("fill precision overflow")?;
    if executed.cmp_value(amount(filled, ticket.base_decimals)) != Some(Ordering::Equal)
        || filled > ticket.quantity_quanta
    {
        return Err("fill precision or status mismatch");
    }
    let decimals = if ticket.buy {
        ticket.quote_decimals
    } else {
        ticket.base_decimals
    };
    let spent_quanta = rounded_quanta(spent, decimals, true).ok_or("spent amount overflow")?;
    if ticket.buy {
        if spent_quanta > ticket.max_quote_debit {
            return Err("debit exceeds reviewed envelope");
        }
    } else if mul(credit, amount(ticket.quantity_quanta, ticket.base_decimals))?
        .cmp_value(mul(
            amount(ticket.min_quote_credit, ticket.quote_decimals),
            quantity,
        )?)
        .is_none_or(|order| order == Ordering::Less)
    {
        return Err("proceeds below reviewed envelope");
    }
    Ok(FillSummary {
        filled_quanta: filled,
        spent_quanta,
        terminal,
    })
}

pub fn recover_unsent(ledger: &mut DurableOrderJournal) -> Result<(), RecoveryError> {
    for id in ledger.reviewed_pending_ids() {
        match ledger.get(&id).unwrap().attempt.lifecycle() {
            Lifecycle::IntentLogged => {
                ledger.record_event(&id, Event::Denied)?;
                ledger.release_denied_reservation(&id)?;
            }
            Lifecycle::NotSent => {
                ledger.record_event(&id, Event::AbandonUnsent)?;
                ledger.release_denied_reservation(&id)?;
            }
            Lifecycle::Denied => ledger.release_denied_reservation(&id)?,
            _ => {}
        }
    }
    Ok(())
}

pub fn reconcile(
    ledger: &mut DurableOrderJournal,
    balances: &BalanceReceipts,
    generation: [u8; 16],
    epoch: u64,
    now: u64,
) -> Result<bool, RecoveryError> {
    let mut clean = true;
    for id in ledger.reviewed_pending_ids() {
        let Some(observation) = ledger
            .latest_known_order(&id)
            .filter(|read| read.is_fresh(generation, epoch, now, 30_000))
            .cloned()
        else {
            clean = false;
            continue;
        };
        let ticket = ledger.get(&id).unwrap().review_ticket.as_ref().unwrap();
        let Ok(summary) = summarize(ticket, &observation) else {
            clean = false;
            continue;
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
        if summary.terminal {
            let Some(balance) = balances
                .settlement_evidence(
                    asset,
                    decimals,
                    summary.spent_quanta,
                    observation.received_at_ms(),
                    now,
                )
                .ok()
                .filter(|balance| {
                    balance.locked_quanta == 0 && balances.matches_context(generation, epoch)
                })
            else {
                clean = false;
                continue;
            };
            match ledger.settle_reviewed(&id, summary.filled_quanta, &balance) {
                Ok(()) => {}
                Err(RecoveryError::Ledger(error)) => return Err(RecoveryError::Ledger(error)),
                Err(_) => clean = false,
            }
        } else {
            let state = ledger.get(&id).unwrap().attempt.lifecycle();
            if matches!(state, Lifecycle::Unknown | Lifecycle::Submitting) {
                ledger.record_event(&id, Event::Acknowledged)?;
            }
            let current = ledger.get(&id).unwrap().attempt;
            if current.filled_quanta() != summary.filled_quanta {
                ledger.record_event(&id, Event::CumulativeFilled(summary.filled_quanta))?;
            }
            if ledger.get(&id).unwrap().attempt.lifecycle() == Lifecycle::Acknowledged {
                ledger.record_event(&id, Event::Working)?;
            }
        }
    }
    Ok(clean && ledger.reconciliation_ready())
}
