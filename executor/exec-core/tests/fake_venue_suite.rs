use exec_core::fake_venue::{run, FIXTURES};
use exec_core::orders::{Lifecycle, Settlement};

#[test]
fn spec_example_lost_ack_then_settled_fill_seed_717() {
    let o = run("lost_ack_then_settled_fill", 717);
    assert!(o.violations.is_empty(), "{:?}", o.violations);
    assert_eq!((o.funded_post_count, o.venue_orders), (1, 1));
    assert_eq!(o.recognized_filled, o.venue_filled);
    assert_eq!((o.lifecycle, o.settlement), (Lifecycle::Closed, Settlement::Verified));
    assert!(o.reservation_released && !o.frozen);
    assert!(o.trace.iter().any(|t| t == "RESEND_REFUSED"));
}

#[test]
fn unresolved_variants_freeze_with_incident_never_forced_success() {
    for f in ["lost_ack_unresolved", "delayed_unblock_expired", "unknown_new_status"] {
        for seed in 1..=50 {
            let o = run(f, seed);
            assert!(o.violations.is_empty(), "{f}/{seed}: {:?}", o.violations);
            assert!(o.frozen && o.incident.is_some() && !o.reservation_released, "{f}/{seed}");
        }
    }
}

#[test]
fn every_fixture_holds_invariants_across_seeded_permutations() {
    for f in FIXTURES {
        for seed in 1..=500 {
            let o = run(f, seed);
            assert!(o.violations.is_empty(), "{f}/{seed}: {:?}\n{:?}", o.violations, o.trace);
            assert!(o.venue_orders <= 1 && o.funded_post_count <= 1);
            assert!(o.recognized_filled <= o.venue_filled);
            assert_eq!(run(f, seed), o, "{f}/{seed} not deterministic");
        }
    }
}

#[test]
fn resolvable_fixtures_settle_to_exact_venue_truth() {
    for f in ["connect_refused_then_resend", "duplicate_out_of_order_status",
              "ignored_filter_paginated_list", "malformed_response", "cancel_fill_race",
              "canceled_with_partial_fill", "delayed_unblock_expected"] {
        for seed in 1..=100 {
            let o = run(f, seed);
            assert!(o.reservation_released, "{f}/{seed}: {:?}", o.trace);
            assert_eq!(o.recognized_filled, o.venue_filled, "{f}/{seed}");
        }
    }
}
