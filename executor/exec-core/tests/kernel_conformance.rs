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
