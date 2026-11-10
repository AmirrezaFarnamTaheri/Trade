//! OD-2 validation: arming refused when any preflight item fails, the digest binds the limits, expiry and every
//! kill rule disarm, and a restart comes up disarmed.
use exec_core::arming::{
    approve, ArmPolicy, ArmRefusal, KillInputs, KillReason, OrderRefusal, PolicyError, Preflight,
    Verdict, PREFLIGHT_ITEMS,
};
use exec_core::kernel::Exact;

fn x(s: &str) -> Exact {
    Exact::parse(s).unwrap()
}

fn fixture() -> serde_json::Value {
    let raw = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../contracts/v1/fixtures/arm-record.json"
    ))
    .unwrap();
    serde_json::from_str(&raw).unwrap()
}

fn unhex(s: &str) -> [u8; 32] {
    let mut out = [0u8; 32];
    for (i, b) in out.iter_mut().enumerate() {
        *b = u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap();
    }
    out
}

fn cost_probe() -> ArmPolicy {
    ArmPolicy {
        policy_sha256: unhex(fixture()["policy_sha256"].as_str().unwrap()),
        venue: "wallex".into(),
        quote_asset: "USDT".into(),
        symbols: vec!["ETHUSDT".into(), "BTCUSDT".into()],
        loss_cap_quote: x("10"),
        max_order_quote: x("5"),
        max_orders_per_day: 10,
        kill_max_loss_quote: x("5"),
        stale_data_seconds: 10,
        max_open_orders: 1,
        expires_days: 7,
    }
}

fn ready() -> Preflight {
    Preflight::passing(&PREFLIGHT_ITEMS)
}

const NOW: u64 = 1_794_000_000_000;

fn calm(now_ms: u64) -> KillInputs {
    KillInputs {
        now_ms,
        runtime_epoch: 3,
        loss_quote: x("0"),
        newest_data_age_ms: 1_000,
        open_orders: 0,
        orders_today: 0,
        reconciliation_clean: true,
        privileged_fault: false,
    }
}

#[test]
fn digest_matches_the_shared_fixture() {
    let f = fixture();
    let record = approve(cost_probe(), &ready(), "owner", 3, NOW).unwrap();
    assert_eq!(record.expires_at_ms, f["expires_at_ms"].as_u64().unwrap());
    assert_eq!(record.canonical(), f["canonical"].as_str().unwrap());
    assert_eq!(record.digest_hex(), f["digest"].as_str().unwrap());
}

#[test]
fn any_failing_preflight_item_refuses_and_names_it() {
    for missing in PREFLIGHT_ITEMS {
        let passed: Vec<_> = PREFLIGHT_ITEMS
            .iter()
            .copied()
            .filter(|i| *i != missing)
            .collect();
        assert_eq!(
            approve(cost_probe(), &Preflight::passing(&passed), "owner", 3, NOW),
            Err(ArmRefusal::Blocked(vec![missing]))
        );
    }
    assert!(matches!(
        approve(cost_probe(), &Preflight::default(), "owner", 3, NOW),
        Err(ArmRefusal::Blocked(items)) if items.len() == PREFLIGHT_ITEMS.len()
    ));
    assert_eq!(
        approve(cost_probe(), &ready(), "", 3, NOW),
        Err(ArmRefusal::Approver)
    );
}

#[test]
fn incoherent_policies_are_refused() {
    let mut p = cost_probe();
    p.max_order_quote = x("11");
    assert_eq!(p.validate(), Err(PolicyError::MaxOrder));
    let mut p = cost_probe();
    p.kill_max_loss_quote = x("10.01");
    assert_eq!(p.validate(), Err(PolicyError::KillLoss));
    let mut p = cost_probe();
    p.expires_days = 0;
    assert_eq!(p.validate(), Err(PolicyError::Expiry));
    let mut p = cost_probe();
    p.symbols = vec!["ETHTMN".into()];
    assert_eq!(p.validate(), Err(PolicyError::Symbols));
}

#[test]
fn changing_the_cap_changes_the_digest() {
    let base = approve(cost_probe(), &ready(), "owner", 3, NOW).unwrap();
    let mut other = cost_probe();
    other.policy_sha256[0] ^= 1; // a different policy file, e.g. a raised cap
    let changed = approve(other, &ready(), "owner", 3, NOW).unwrap();
    assert_ne!(base.digest(), changed.digest());
}

#[test]
fn expiry_restart_and_every_kill_rule_disarm() {
    let r = approve(cost_probe(), &ready(), "owner", 3, NOW).unwrap();
    assert_eq!(r.check(&calm(NOW + 1)), Verdict::Armed);
    let cases: [(KillInputs, KillReason); 8] = [
        (calm(r.expires_at_ms), KillReason::Expired),
        (
            KillInputs {
                runtime_epoch: 4,
                ..calm(NOW)
            },
            KillReason::RuntimeRestarted,
        ),
        (
            KillInputs {
                loss_quote: x("5"),
                ..calm(NOW)
            },
            KillReason::KillLoss,
        ),
        (
            KillInputs {
                loss_quote: x("10"),
                ..calm(NOW)
            },
            KillReason::LossCap,
        ),
        (
            KillInputs {
                newest_data_age_ms: 10_001,
                ..calm(NOW)
            },
            KillReason::StaleData,
        ),
        (
            KillInputs {
                open_orders: 2,
                ..calm(NOW)
            },
            KillReason::TooManyOpenOrders,
        ),
        (
            KillInputs {
                reconciliation_clean: false,
                ..calm(NOW)
            },
            KillReason::ReconciliationMismatch,
        ),
        (
            KillInputs {
                privileged_fault: true,
                ..calm(NOW)
            },
            KillReason::PrivilegedFault,
        ),
    ];
    for (inputs, reason) in cases {
        assert_eq!(r.check(&inputs), Verdict::Disarm(reason));
    }
    assert_eq!(
        r.check(&KillInputs {
            loss_quote: x("4.99"),
            ..calm(NOW)
        }),
        Verdict::Armed
    );
}

#[test]
fn orders_are_held_inside_the_per_order_limits() {
    let r = approve(cost_probe(), &ready(), "owner", 3, NOW).unwrap();
    assert_eq!(r.admit_order("ETHUSDT", x("5"), &calm(NOW)), Ok(()));
    assert_eq!(
        r.admit_order("ETHUSDT", x("5.01"), &calm(NOW)),
        Err(OrderRefusal::MaxOrder)
    );
    assert_eq!(
        r.admit_order("SOLUSDT", x("1"), &calm(NOW)),
        Err(OrderRefusal::Symbol)
    );
    assert_eq!(
        r.admit_order(
            "ETHUSDT",
            x("1"),
            &KillInputs {
                orders_today: 10,
                ..calm(NOW)
            }
        ),
        Err(OrderRefusal::OrdersPerDay)
    );
    assert_eq!(
        r.admit_order(
            "ETHUSDT",
            x("1"),
            &KillInputs {
                open_orders: 1,
                ..calm(NOW)
            }
        ),
        Err(OrderRefusal::OpenOrders)
    );
    assert_eq!(
        r.admit_order("ETHUSDT", x("1"), &calm(r.expires_at_ms)),
        Err(OrderRefusal::Disarmed(KillReason::Expired))
    );
}
