//! Native own-fill accounting. External deposits never offset an executor loss.
use crate::account_observation::{AccountKind, AccountObservation};
use crate::native_market::MarketObservation;
use exec_core::kernel::Exact;
use exec_ipc::review::Ticket;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Debug)]
pub struct NativeRisk {
    pub loss_quote: Exact,
    pub open_orders: u32,
    pub orders_today: u32,
    pub own_inventory: BTreeMap<String, Exact>,
}

fn zero() -> Exact {
    Exact {
        mantissa: 0,
        scale: 0,
    }
}
fn plus(a: Exact, b: Exact) -> Result<Exact, &'static str> {
    a.checked_add(b).ok_or("risk amount overflow")
}
fn minus(a: Exact, b: Exact) -> Result<Exact, &'static str> {
    a.checked_sub(b).ok_or("unreconciled debit or inventory")
}
fn text(value: &serde_json::Value, name: &str) -> Result<Exact, &'static str> {
    Exact::parse(value[name].as_str().ok_or("inexact own-order amount")?)
        .ok_or("own-order amount overflow")
}

pub struct OwnOrder<'a> {
    pub ticket: &'a Ticket,
    pub observation: &'a AccountObservation,
    pub submitted_at_ms: u64,
}

pub fn measure(
    orders: &[OwnOrder<'_>],
    open: &AccountObservation,
    markets: &BTreeMap<String, MarketObservation>,
    quote_asset: &str,
    exit_fee: Exact,
    now_ms: u64,
) -> Result<NativeRisk, &'static str> {
    if open.kind() != AccountKind::OpenOrders
        || open.data()["request"]["page"].as_u64() != Some(1)
        || open.data()["request"]["per_page"].as_u64() != Some(100)
        || exit_fee
            .cmp_value(Exact {
                mantissa: 1,
                scale: 0,
            })
            .is_none_or(|order| order != std::cmp::Ordering::Less)
    {
        return Err("incomplete native risk sources");
    }
    let current_open = open.data()["result"]["orders"]
        .as_array()
        .ok_or("missing native open orders")?;
    if current_open.len() >= 100 {
        return Err("unbounded native open orders");
    }
    let open_ids: BTreeSet<&str> = current_open
        .iter()
        .map(|row| row["clientOrderId"].as_str().ok_or("invalid open identity"))
        .collect::<Result<_, _>>()?;
    if open_ids.len() != current_open.len() {
        return Err("duplicate open identity");
    }
    let mut expected_open = BTreeSet::new();
    let mut identities = BTreeSet::new();
    let mut debits = zero();
    let mut credits = zero();
    let mut inventory: BTreeMap<&str, (Exact, Exact)> = BTreeMap::new();
    let mut orders_today = 0u32;
    let day_start = now_ms / 86_400_000 * 86_400_000;
    for own in orders {
        let ticket = own.ticket;
        ticket.validate()?;
        if ticket.account != "main"
            || ticket.quote != quote_asset
            || !identities.insert(ticket.client_id.as_str())
            || own.submitted_at_ms == 0
            || own.submitted_at_ms > now_ms
            || own.observation.kind() != AccountKind::KnownClientOrder
        {
            return Err("invalid native own-order context");
        }
        // Review preparation precedes submission by at most its 30-second window; overcount a day boundary.
        if own.submitted_at_ms >= day_start.saturating_sub(30_000) {
            orders_today = orders_today.checked_add(1).ok_or("order count overflow")?;
        }
        let row = &own.observation.data()["result"];
        let symbol = format!("{}{}", ticket.base, ticket.quote);
        if row["clientOrderId"].as_str() != Some(&ticket.client_id)
            || row["symbol"].as_str() != Some(&symbol)
            || row["side"].as_str() != Some(if ticket.buy { "BUY" } else { "SELL" })
            || text(row, "origQty")?.cmp_value(Exact {
                mantissa: u128::from(ticket.quantity_quanta),
                scale: u32::from(ticket.base_decimals),
            }) != Some(std::cmp::Ordering::Equal)
        {
            return Err("native order disagrees with reviewed identity");
        }
        match row["status"].as_str() {
            Some("NEW" | "PARTIALLY_FILLED") => {
                expected_open.insert(ticket.client_id.as_str());
                if current_open
                    .iter()
                    .find(|current| current["clientOrderId"].as_str() == Some(&ticket.client_id))
                    != Some(row)
                {
                    return Err("own fill changed between native reads");
                }
            }
            Some("FILLED" | "CANCELED" | "CANCELLED" | "REJECTED" | "EXPIRED") => {}
            _ => return Err("unknown native order status"),
        }
        let fills = row["fills"].as_array().ok_or("missing own fills")?;
        let mut total = zero();
        for fill in fills {
            let quantity = text(fill, "quantity")?;
            let price = text(fill, "price")?;
            let fee = text(fill, "fee")?;
            let fee_asset = fill["feeAsset"].as_str().ok_or("missing fill fee asset")?;
            if fee_asset != ticket.base && fee_asset != ticket.quote {
                return Err("unpriced fee asset");
            }
            total = plus(total, quantity)?;
            let gross = quantity
                .checked_mul(price)
                .ok_or("fill notional overflow")?;
            let base_fee = if fee_asset == ticket.base {
                fee
            } else {
                zero()
            };
            let quote_fee = if fee_asset == ticket.quote {
                fee
            } else {
                zero()
            };
            let holding = inventory
                .entry(ticket.base.as_str())
                .or_insert((zero(), zero()));
            if ticket.buy {
                debits = plus(debits, plus(gross, quote_fee)?)?;
                holding.0 = plus(holding.0, minus(quantity, base_fee)?)?;
            } else {
                credits = plus(credits, minus(gross, quote_fee)?)?;
                holding.1 = plus(holding.1, plus(quantity, base_fee)?)?;
            }
        }
        if total.cmp_value(text(row, "executedQty")?) != Some(std::cmp::Ordering::Equal) {
            return Err("incomplete native fill reconciliation");
        }
    }
    if open_ids != expected_open {
        return Err("venue and executor open orders disagree");
    }
    let mut marked = zero();
    let mut own_inventory = BTreeMap::new();
    let after_fee = minus(
        Exact {
            mantissa: 1,
            scale: 0,
        },
        exit_fee,
    )?;
    for (base, (bought, sold)) in inventory {
        let quantity = minus(bought, sold)?;
        own_inventory.insert(base.to_owned(), quantity);
        if !quantity.is_zero() {
            let book = markets
                .get(&format!("{base}{quote_asset}"))
                .filter(|book| book.is_fresh(now_ms, 120_000))
                .ok_or("unpriced own inventory")?;
            marked = plus(
                marked,
                book.liquidation_value(quantity)
                    .and_then(|value| value.checked_mul(after_fee))
                    .ok_or("insufficient liquidation depth or overflow")?,
            )?;
        }
    }
    let covered = plus(credits, marked)?;
    let loss_quote = match debits
        .cmp_value(covered)
        .ok_or("loss comparison overflow")?
    {
        std::cmp::Ordering::Greater => minus(debits, covered)?,
        _ => zero(),
    };
    Ok(NativeRisk {
        loss_quote,
        open_orders: open_ids
            .len()
            .try_into()
            .map_err(|_| "open count overflow")?,
        orders_today,
        own_inventory,
    })
}
