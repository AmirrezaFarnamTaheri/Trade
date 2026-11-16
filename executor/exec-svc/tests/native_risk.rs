use exec_core::kernel::Exact;
use exec_ipc::provision::AccountResource;
use exec_ipc::review::Ticket;
use exec_svc::account_observation::AccountObservation;
use exec_svc::native_market::MarketObservation;
use exec_svc::native_risk::{measure, OwnOrder};
use std::collections::BTreeMap;

fn ticket(id: &str, buy: bool, quantity: u64) -> Ticket {
    Ticket {
        client_id: id.into(),
        account: "main".into(),
        base: "BTC".into(),
        quote: "USDT".into(),
        buy,
        base_decimals: 2,
        price_decimals: 2,
        quote_decimals: 2,
        base_epoch: 1,
        quote_epoch: 1,
        runtime_epoch: 10,
        ceiling_sequence: 1,
        expires_at_ms: 2000,
        quantity_quanta: quantity,
        worst_price_quanta: 10000,
        max_quote_debit: if buy { 11000 } else { 0 },
        min_quote_credit: if buy { 0 } else { 1 },
        preview_hash: [5; 32],
        rules_hash: [6; 32],
        credential_generation: [3; 16],
    }
}
fn order(
    id: &str,
    buy: bool,
    quantity: &str,
    price: &str,
    fee: &str,
    status: &str,
) -> AccountObservation {
    let raw = serde_json::to_vec(&serde_json::json!({"success":true,"result":{
    "clientOrderId":id,"symbol":"BTCUSDT","side":if buy {"BUY"} else {"SELL"},
    "status":status,"origQty":quantity,"executedQty":quantity,"fills":[{
        "quantity":quantity,"price":price,"fee":fee,"feeAsset":"USDT","timestamp":1700000000000u64
    }]}}))
    .unwrap();
    AccountObservation::from_order_response(id, &raw, [3; 16], 10, [1; 16], 1000, 1010).unwrap()
}
fn open(ids: &[&str]) -> AccountObservation {
    let rows = ids
        .iter()
        .map(|id| {
            serde_json::json!({"clientOrderId":id,"symbol":"BTCUSDT","side":"BUY",
        "status":"NEW","origQty":"1","executedQty":"0","fills":[]})
        })
        .collect::<Vec<_>>();
    let raw =
        serde_json::to_vec(&serde_json::json!({"success":true,"result":{"BTCUSDT":rows}})).unwrap();
    AccountObservation::from_page_response(
        &AccountResource::OpenOrders {
            page: 1,
            per_page: 100,
        },
        &raw,
        [3; 16],
        10,
        [2; 16],
        1000,
        1010,
    )
    .unwrap()
}
fn markets(quantity: &str) -> BTreeMap<String, MarketObservation> {
    let raw = serde_json::to_vec(&serde_json::json!({"success":true,"result":{
        "bid":[{"price":"90","quantity":quantity}],"ask":[{"price":"91","quantity":"10"}]}}))
    .unwrap();
    BTreeMap::from([(
        "BTCUSDT".into(),
        MarketObservation::from_response("BTCUSDT", &raw, 1000, 1010).unwrap(),
    )])
}
fn eq(a: Exact, text: &str) {
    assert_eq!(
        a.cmp_value(Exact::parse(text).unwrap()),
        Some(std::cmp::Ordering::Equal)
    );
}

#[test]
fn loss_uses_own_fills_fees_and_liquidation_depth_without_account_credits() {
    let buy = ticket("buy", true, 100);
    let observed = order("buy", true, "1", "100", "1", "FILLED");
    let orders = [OwnOrder {
        ticket: &buy,
        observation: &observed,
        submitted_at_ms: 1000,
    }];
    let result = measure(
        &orders,
        &open(&[]),
        &markets("10"),
        "USDT",
        Exact::parse("0.01").unwrap(),
        1020,
    )
    .unwrap();
    eq(result.loss_quote, "11.9");
    assert_eq!(result.open_orders, 0);
    assert_eq!(result.orders_today, 1);
    assert!(measure(
        &orders,
        &open(&[]),
        &markets("0.1"),
        "USDT",
        Exact::parse("0.01").unwrap(),
        1020
    )
    .is_err());
}

#[test]
fn sparse_zero_fill_pages_match_progress_and_native_gross_cash_retains_venue_rounding() {
    let buy = ticket("buy", true, 100);
    let raw=br#"{"success":true,"result":{"clientOrderId":"buy","symbol":"BTCUSDT","side":"BUY","status":"NEW","origQty":"01.000","executedQty":"0.000"}}"#;
    let observed =
        AccountObservation::from_order_response("buy", raw, [3; 16], 10, [4; 16], 1000, 1010)
            .unwrap();
    assert!(measure(
        &[OwnOrder {
            ticket: &buy,
            observation: &observed,
            submitted_at_ms: 1000
        }],
        &open(&["buy"]),
        &markets("10"),
        "USDT",
        Exact::parse("0.01").unwrap(),
        1020
    )
    .is_ok());
    let original = order("buy", true, "1", "100", "1", "FILLED");
    let mut raw = original.data().clone();
    raw["result"]["fills"][0]["sum"] = "100.01".into();
    let rounded = AccountObservation::from_order_response(
        "buy",
        &serde_json::to_vec(&raw).unwrap(),
        [3; 16],
        10,
        [5; 16],
        1000,
        1010,
    )
    .unwrap();
    eq(
        measure(
            &[OwnOrder {
                ticket: &buy,
                observation: &rounded,
                submitted_at_ms: 1000,
            }],
            &open(&[]),
            &markets("10"),
            "USDT",
            Exact::parse("0.01").unwrap(),
            1020,
        )
        .unwrap()
        .loss_quote,
        "11.91",
    );
}

#[test]
fn partial_sale_and_profitable_close_keep_exact_cash_and_inventory() {
    let buy = ticket("buy", true, 100);
    let bought = order("buy", true, "1", "100", "1", "FILLED");
    let sell = ticket("sell", false, 50);
    let sold = order("sell", false, "0.5", "110", "0.55", "FILLED");
    let orders = [
        OwnOrder {
            ticket: &buy,
            observation: &bought,
            submitted_at_ms: 1000,
        },
        OwnOrder {
            ticket: &sell,
            observation: &sold,
            submitted_at_ms: 1000,
        },
    ];
    eq(
        measure(
            &orders,
            &open(&[]),
            &markets("10"),
            "USDT",
            Exact::parse("0.01").unwrap(),
            1020,
        )
        .unwrap()
        .loss_quote,
        "2",
    );
    let sell = ticket("sell", false, 100);
    let sold = order("sell", false, "1", "110", "1.1", "FILLED");
    let orders = [
        OwnOrder {
            ticket: &buy,
            observation: &bought,
            submitted_at_ms: 1000,
        },
        OwnOrder {
            ticket: &sell,
            observation: &sold,
            submitted_at_ms: 1000,
        },
    ];
    eq(
        measure(
            &orders,
            &open(&[]),
            &markets("10"),
            "USDT",
            Exact::parse("0.01").unwrap(),
            1020,
        )
        .unwrap()
        .loss_quote,
        "0",
    );
}

#[test]
fn unknown_orders_missing_fills_wrong_identity_or_external_inventory_block() {
    let buy = ticket("buy", true, 100);
    let bought = order("buy", true, "1", "100", "1", "FILLED");
    let run = |ticket: &Ticket, observation: &AccountObservation| {
        measure(
            &[OwnOrder {
                ticket,
                observation,
                submitted_at_ms: 1000,
            }],
            &open(&[]),
            &markets("10"),
            "USDT",
            Exact::parse("0.01").unwrap(),
            1020,
        )
    };
    assert!(measure(
        &[OwnOrder {
            ticket: &buy,
            observation: &bought,
            submitted_at_ms: 1000
        }],
        &open(&["foreign"]),
        &markets("10"),
        "USDT",
        Exact::parse("0.01").unwrap(),
        1020
    )
    .is_err());
    let mut wrong = buy.clone();
    wrong.client_id = "different".into();
    assert!(run(&wrong, &bought).is_err());
    let sell = ticket("sell", false, 100);
    let sold = order("sell", false, "1", "110", "1.1", "FILLED");
    assert!(run(&sell, &sold).is_err());
    let mut raw = serde_json::to_value(&bought).unwrap();
    raw["data"]["result"]["fills"] = serde_json::json!([]);
    let missing: AccountObservation = serde_json::from_value(raw).unwrap();
    assert!(run(&buy, &missing).is_err());
    let too_late = measure(
        &[OwnOrder {
            ticket: &buy,
            observation: &bought,
            submitted_at_ms: 1000,
        }],
        &open(&[]),
        &markets("10"),
        "USDT",
        Exact::parse("0.01").unwrap(),
        121011,
    );
    assert!(too_late.is_err());
}

#[test]
fn same_open_identity_with_different_cumulative_fills_still_blocks() {
    let buy = ticket("buy", true, 100);
    let earlier = order("buy", true, "1", "100", "1", "NEW");
    assert!(measure(
        &[OwnOrder {
            ticket: &buy,
            observation: &earlier,
            submitted_at_ms: 1000
        }],
        &open(&["buy"]),
        &markets("10"),
        "USDT",
        Exact::parse("0.01").unwrap(),
        1020
    )
    .is_err());
}
