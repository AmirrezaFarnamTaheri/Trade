use exec_core::kernel::Exact;
use exec_svc::native_market::MarketObservation;

#[test]
fn exact_json_number_lexemes_and_strings_produce_the_same_native_prices() {
    let quote = MarketObservation::from_response("BTCUSDT", br#"{"success":true,"result":{"bid":[{"price":99999.123456789012345678,"quantity":"0.01"}],"ask":[{"price":"99999.123456789012345679","quantity":0.01}]}}"#, 1000, 1010).unwrap();
    assert_eq!(
        quote.bid(),
        Exact::parse("99999.123456789012345678").unwrap()
    );
    assert_eq!(
        quote.ask(),
        Exact::parse("99999.123456789012345679").unwrap()
    );
    assert!(quote.is_fresh(121010, 999999));
    assert!(!quote.is_fresh(121011, 999999));
    assert!(!quote.is_fresh(1009, 120000));
}

#[test]
fn malformed_duplicate_unordered_crossed_or_inexact_depth_is_refused() {
    for raw in [
        r#"{"success":false,"result":{"bid":[],"ask":[]}}"#,
        r#"{"success":true,"success":true,"result":{"bid":[],"ask":[]}}"#,
        r#"{"success":true,"result":{"bid":[{"price":2,"quantity":1}],"ask":[{"price":1,"quantity":1}]}}"#,
        r#"{"success":true,"result":{"bid":[{"price":1e9,"quantity":1}],"ask":[{"price":2,"quantity":1}]}}"#,
        r#"{"success":true,"result":{"bid":[{"price":1,"quantity":0}],"ask":[{"price":2,"quantity":1}]}}"#,
        r#"{"success":true,"result":{"bid":[{"price":1,"price":2,"quantity":1}],"ask":[{"price":3,"quantity":1}]}}"#,
        r#"{"success":true,"result":{"bid":[{"price":1,"quantity":1},{"price":2,"quantity":1}],"ask":[{"price":3,"quantity":1}]}}"#,
    ] {
        assert!(
            MarketObservation::from_response("BTCUSDT", raw.as_bytes(), 1000, 1010).is_err(),
            "{raw}"
        );
    }
}

#[test]
fn numeric_exponents_are_scaled_as_exact_integers_without_binary_rounding() {
    let quote=MarketObservation::from_response("BTCUSDT",br#"{"success":true,"result":{"bid":[{"price":1.23e2,"quantity":1e-8}],"ask":[{"price":1.24e2,"quantity":1e-8}]}}"#,1000,1010).unwrap();
    assert_eq!(
        quote.bid().cmp_value(Exact::parse("123").unwrap()),
        Some(std::cmp::Ordering::Equal)
    );
    assert_eq!(
        quote
            .liquidation_value(Exact::parse("0.00000001").unwrap())
            .unwrap()
            .cmp_value(Exact::parse("0.00000123").unwrap()),
        Some(std::cmp::Ordering::Equal)
    );
}
