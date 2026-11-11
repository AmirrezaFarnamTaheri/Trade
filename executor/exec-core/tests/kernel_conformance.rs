//! The Rust reference money rules agree with the Python simulator on the shared fixtures (ADR 0005).
use exec_core::kernel::{sellable, Exact};

fn exact(value: &serde_json::Value) -> Option<Exact> {
    value
        .as_str()
        .map(|text| Exact::parse(text).expect("fixture decimal"))
}

#[test]
fn sellable_quantity_matches_the_shared_fixture() {
    let fixture: serde_json::Value =
        serde_json::from_str(include_str!("../../../contracts/v1/fixtures/sizing.json")).unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let got = sellable(
            exact(&case["quantity"]).unwrap(),
            case["qty_decimals"].as_u64().map(|d| d as u32),
            exact(&case["min_qty"]),
            exact(&case["min_notional"]),
            exact(&case["bid"]).unwrap(),
        )
        .expect("no overflow in fixture");
        let want = exact(&case["sellable"]).unwrap();
        assert_eq!(
            got.cmp_value(want),
            Some(std::cmp::Ordering::Equal),
            "{case}"
        );
    }
}

#[test]
fn malformed_decimals_are_refused() {
    for bad in ["", "-1", "1.", ".5", "1e5", "1,5", "0x10"] {
        assert!(Exact::parse(bad).is_none(), "{bad}");
    }
}

#[test]
fn cash_and_holdings_sizing_match_shared_vectors() {
    use exec_core::kernel::{cash_quantity, holdings_quantity};
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../contracts/v1/fixtures/order-sizing.json"
    ))
    .unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let levels: Vec<(Exact, Exact)> = case["levels"]
            .as_array()
            .unwrap()
            .iter()
            .map(|l| (exact(&l[0]).unwrap(), exact(&l[1]).unwrap()))
            .collect();
        let fraction = exact(&case["fraction"]).unwrap();
        let decimals = case["qty_decimals"].as_u64().unwrap() as u32;
        assert_eq!(
            cash_quantity(
                exact(&case["cash"]).unwrap(),
                fraction,
                exact(&case["price"]).unwrap(),
                &levels,
                decimals
            )
            .unwrap()
            .to_string(),
            case["buy"].as_str().unwrap(),
            "{case}"
        );
        assert_eq!(
            holdings_quantity(exact(&case["holdings"]).unwrap(), fraction, decimals)
                .unwrap()
                .to_string(),
            case["sell"].as_str().unwrap(),
            "{case}"
        );
    }
    let one = Exact::parse("1").unwrap();
    let zero = Exact::parse("0").unwrap();
    assert!(cash_quantity(one, one, zero, &[], 8).is_none());
    assert!(cash_quantity(one, one, one, &[], 39).is_none());
    assert!(holdings_quantity(one, Exact::parse("1.1").unwrap(), 8).is_none());
}

#[test]
fn walk_and_settlement_match_the_shared_fixture() {
    use exec_core::kernel::{settle, walk};
    let fixture: serde_json::Value =
        serde_json::from_str(include_str!("../../../contracts/v1/fixtures/fills.json")).unwrap();
    let equal = |a: Exact, b: &serde_json::Value| {
        let text = b.as_str().unwrap();
        let (negative, digits) = text
            .strip_prefix('-')
            .map_or((false, text), |rest| (true, rest));
        (
            a.cmp_value(Exact::parse(digits).unwrap()) == Some(std::cmp::Ordering::Equal),
            negative,
        )
    };
    for case in fixture["cases"].as_array().unwrap() {
        let levels: Vec<(Exact, Exact)> = case["levels"]
            .as_array()
            .unwrap()
            .iter()
            .map(|l| (exact(&l[0]).unwrap(), exact(&l[1]).unwrap()))
            .collect();
        let quantity = exact(&case["quantity"]).unwrap();
        let notional = walk(&levels, quantity).expect("enough depth");
        assert_eq!(equal(notional, &case["notional"]), (true, false), "{case}");
        let (fee, base, quote) = settle(
            case["side"] == "BUY",
            quantity,
            notional,
            exact(&case["fee_rate"]).unwrap(),
        )
        .unwrap();
        assert!(equal(fee, &case["fee"]).0, "{case}");
        assert_eq!(equal(base.0, &case["base_delta"]), (true, base.1), "{case}");
        assert_eq!(
            equal(quote.0, &case["quote_delta"]),
            (true, quote.1),
            "{case}"
        );
    }
    let shallow = [(Exact::parse("100").unwrap(), Exact::parse("1").unwrap())];
    assert!(walk(&shallow, Exact::parse("1.5").unwrap()).is_none());
}

#[test]
fn price_guard_matches_the_shared_fixture() {
    use exec_core::kernel::trips_price_guard;
    let fixture: serde_json::Value = serde_json::from_str(include_str!(
        "../../../contracts/v1/fixtures/price-guard.json"
    ))
    .unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let levels: Vec<(Exact, Exact)> = case["levels"]
            .as_array()
            .unwrap()
            .iter()
            .map(|l| (exact(&l[0]).unwrap(), exact(&l[1]).unwrap()))
            .collect();
        let trips = trips_price_guard(&levels, exact(&case["quantity"]).unwrap()).unwrap();
        assert_eq!(trips, case["trips"].as_bool().unwrap(), "{case}");
    }
}
