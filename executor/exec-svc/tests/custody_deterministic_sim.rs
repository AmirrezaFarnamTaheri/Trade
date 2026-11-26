//! Seeded Deterministic Simulation Testing (DST) for Rust custody & offline recovery (REL-01).
//!
//! Exercises multi-seed randomized fault injection over `DurableOrderJournal`:
//! - Mid-fill / post-submit crashes and restarts (`drop` + `DurableOrderJournal::open`)
//! - Duplicate exchange acknowledgments & duplicate client order ID replays
//! - Partial fills, settled releases, and exact hold/reservation conservation
//! - Regressed/skewed evidence sequences failing closed without releasing active holds
use exec_core::orders::{
    BalanceSnapshot, Event, FailureStage, Lifecycle, OrderError, SettlementEvidence,
};
use exec_svc::offline_recovery::{DurableOrderJournal, RecoveryError};
use tempfile::tempdir;

/// Deterministic SplitMix64 PRNG so every DST failure is 100% reproducible from its seed.
struct Rng(u64);

impl Rng {
    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn range(&mut self, upper: u64) -> u64 {
        self.next_u64() % upper
    }
}

fn run_seeded_custody_simulation(seed: u64) {
    let dir = tempdir().unwrap();
    let path = dir.path().join(format!("dst-{seed}.sqlite"));
    let mut rng = Rng(seed);
    let mut journal = DurableOrderJournal::open(&path).unwrap();

    let anchor_available: u64 = 100_000;
    let mut settled_spent: u64 = 0;
    let mut expected_reserved: u64 = 0;
    let mut seq: u64 = 1;

    for step in 0..20u64 {
        let id = format!("dst-{seed}-{step}");
        let amount = 50 + rng.range(150);
        seq += 1 + rng.range(3);

        // 1. Admit intent & verify duplicate intent ID always fails closed.
        journal.create_intent(&id, "main", "USDT", amount).unwrap();
        assert_eq!(
            journal.create_intent(&id, "main", "USDT", amount),
            Err(RecoveryError::DuplicateIdentity),
            "seed={seed} step={step}: duplicate client intent must be rejected"
        );

        // 2. Reserve funds against anchor snapshot & assert exact reservation conservation.
        let snap = BalanceSnapshot::new("main", "USDT", anchor_available, seq).unwrap();
        journal.reserve_intent(&id, amount, &snap).unwrap();
        expected_reserved += amount;
        assert_eq!(journal.reserved("main", "USDT"), expected_reserved);

        // 3. Branch into randomized exchange outcome:
        //    0 => BeginSend + Acknowledged + duplicate ack + partial fill + crash + settlement release
        //    1 => Denied before send + release_denied_reservation
        //    2 => BeginSend + TransportFailed(AfterFirstByte) -> Unknown (hold MUST stay locked!)
        match rng.range(3) {
            0 => {
                journal.record_event(&id, Event::BeginSend).unwrap();
                if rng.range(2) == 0 {
                    let _ = journal.checkpoint();
                    drop(journal);
                    journal = DurableOrderJournal::open(&path).unwrap();
                    assert_eq!(journal.reserved("main", "USDT"), expected_reserved);
                }
                journal.record_event(&id, Event::Acknowledged).unwrap();
                // Duplicate exchange ack must be rejected cleanly without corrupting state.
                let dup = journal.record_event(&id, Event::Acknowledged);
                assert!(
                    matches!(
                        dup,
                        Err(RecoveryError::Order(OrderError::IllegalTransition))
                    ),
                    "seed={seed} step={step}: duplicate Acknowledged must fail closed, got {dup:?}"
                );
                // Partial fill + crash + reopen + full fill + terminal + settlement verified
                let partial = (amount / 2).max(1);
                journal
                    .record_event(&id, Event::CumulativeFilled(partial))
                    .unwrap();
                drop(journal);
                journal = DurableOrderJournal::open(&path).unwrap();
                assert_eq!(journal.reserved("main", "USDT"), expected_reserved);

                journal
                    .record_event(&id, Event::CumulativeFilled(amount))
                    .unwrap();
                journal.record_event(&id, Event::TerminalReported).unwrap();
                journal
                    .record_event(&id, Event::SettlementVerified)
                    .unwrap();

                // Regressed/stale sequence evidence must fail closed and keep hold intact.
                let stale = SettlementEvidence::new(
                    "main",
                    "USDT",
                    seq.saturating_sub(1).max(1),
                    true,
                    0,
                    amount,
                    anchor_available.saturating_sub(settled_spent + amount),
                )
                .unwrap();
                assert!(
                    journal.release_settled_reservation(&id, &stale).is_err(),
                    "seed={seed} step={step}: stale sequence settlement evidence must fail closed"
                );
                assert_eq!(journal.reserved("main", "USDT"), expected_reserved);

                // Monotone newer sequence evidence settles and releases the hold cleanly.
                seq += 1;
                settled_spent += amount;
                let evidence = SettlementEvidence::new(
                    "main",
                    "USDT",
                    seq,
                    true,
                    0,
                    settled_spent,
                    anchor_available.saturating_sub(settled_spent),
                )
                .unwrap();
                journal.release_settled_reservation(&id, &evidence).unwrap();
                expected_reserved -= amount;
                if expected_reserved == 0 {
                    settled_spent = 0;
                }
                assert_eq!(journal.reserved("main", "USDT"), expected_reserved);
            }
            1 => {
                journal.record_event(&id, Event::Denied).unwrap();
                journal.release_denied_reservation(&id).unwrap();
                expected_reserved -= amount;
                if expected_reserved == 0 {
                    settled_spent = 0;
                }
                assert_eq!(journal.reserved("main", "USDT"), expected_reserved);
            }
            _ => {
                journal.record_event(&id, Event::BeginSend).unwrap();
                journal
                    .record_event(&id, Event::TransportFailed(FailureStage::AfterFirstByte))
                    .unwrap();
                // Crash & reopen: Unknown outcome MUST keep funds locked (fail-closed custody).
                drop(journal);
                journal = DurableOrderJournal::open(&path).unwrap();
                assert_eq!(
                    journal.get(&id).unwrap().attempt.lifecycle(),
                    Lifecycle::Unknown
                );
                assert_eq!(journal.reserved("main", "USDT"), expected_reserved);
                // Attempting to release_denied an Unknown order MUST fail closed.
                assert!(journal.release_denied_reservation(&id).is_err());
            }
        }
    }

    // Final crash + reopen consistency check across the entire seed run.
    let final_count = journal.record_count();
    drop(journal);
    let reopened = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(reopened.record_count(), final_count);
    assert_eq!(reopened.reserved("main", "USDT"), expected_reserved);
}

#[test]
fn seeded_deterministic_custody_simulation_preserves_invariants_across_20_seeds() {
    for seed in 1..=20u64 {
        run_seeded_custody_simulation(seed * 7919);
    }
}
