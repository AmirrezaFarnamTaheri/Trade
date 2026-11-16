//! Service receipt order is local; only a native producer can establish this fence and dual copies.
use exec_core::available::{
    verified_available, Available, AvailableError, Journal, ObservedBalance, ReceiptFence,
};

fn fence() -> ReceiptFence {
    ReceiptFence {
        credential_generation: [1; 16],
        runtime_epoch: 9,
        activity_seq: 0,
        not_before_ms: 1_000,
    }
}

fn receipt(seq: u64, at: u64, amount: u64, fence: ReceiptFence) -> Vec<ObservedBalance> {
    [Journal::Credentials, Journal::Ledger]
        .into_iter()
        .map(|journal| ObservedBalance {
            journal,
            account: "main".into(),
            asset: "USDT".into(),
            available_quanta: amount,
            locked_quanta: 0,
            receipt_seq: seq,
            fence,
            request_id: [seq as u8; 16],
            response_digest: [seq as u8; 32],
            started_at_ms: at - 10,
            received_at_ms: at,
        })
        .collect()
}

fn pair() -> Vec<ObservedBalance> {
    [
        receipt(1, 1_100, 100, fence()),
        receipt(2, 1_200, 100, fence()),
    ]
    .concat()
}

#[test]
fn agreeing_dual_copies_subtract_open_holds_from_the_two_read_floor() {
    assert_eq!(
        verified_available(&pair(), "main", "USDT", fence(), 1_500, 120_000, 30),
        Ok(Available {
            available_quanta: 70,
            receipt_seq: 2,
            age_ms: 400
        })
    );
    assert_eq!(
        verified_available(&pair(), "main", "USDT", fence(), 1_500, 120_000, u64::MAX)
            .unwrap()
            .available_quanta,
        0
    );
}

#[test]
fn one_read_or_one_journal_cannot_establish_available() {
    let seen = pair();
    for missing in [seen[..2].to_vec(), vec![seen[0].clone(), seen[2].clone()]] {
        assert_eq!(
            verified_available(&missing, "main", "USDT", fence(), 1_500, 120_000, 0),
            Err(AvailableError::Missing)
        );
    }
    assert_eq!(
        verified_available(&seen, "main", "BTC", fence(), 1_500, 120_000, 0),
        Err(AvailableError::Missing)
    );
}

#[test]
fn a_mismatching_journal_copy_disarms() {
    for case in 0..5 {
        let mut seen = pair();
        match case {
            0 => seen[1].available_quanta = 101,
            1 => seen[1].response_digest = [3; 32],
            2 => seen[1].request_id = [3; 16],
            3 => seen[1].started_at_ms = 1_050,
            _ => seen[1].received_at_ms = 1_110,
        }
        let error =
            verified_available(&seen, "main", "USDT", fence(), 1_500, 120_000, 0).unwrap_err();
        assert_eq!(error, AvailableError::Disagreement { receipt_seq: 1 });
        assert!(error.disarms());
    }
}

#[test]
fn unequal_consecutive_reads_disarm_even_with_agreeing_journal_copies() {
    let seen = [
        receipt(1, 1_100, 100, fence()),
        receipt(2, 1_200, 90, fence()),
    ]
    .concat();
    let error = verified_available(&seen, "main", "USDT", fence(), 1_500, 120_000, 0).unwrap_err();
    assert_eq!(error, AvailableError::Disagreement { receipt_seq: 2 });
    assert!(error.disarms());
    let mut locks = pair();
    locks[2].locked_quanta = 10;
    locks[3].locked_quanta = 10;
    assert!(
        verified_available(&locks, "main", "USDT", fence(), 1_500, 120_000, 0)
            .unwrap_err()
            .disarms()
    );
}

#[test]
fn own_activity_needs_two_new_reads_after_its_fence() {
    let current = ReceiptFence {
        activity_seq: 1,
        not_before_ms: 1_300,
        ..fence()
    };
    let mut seen = pair();
    seen.extend(receipt(3, 1_400, 90, current));
    assert_eq!(
        verified_available(&seen, "main", "USDT", current, 1_600, 120_000, 20),
        Err(AvailableError::Missing)
    );
    seen.extend(receipt(4, 1_500, 90, current));
    assert_eq!(
        verified_available(&seen, "main", "USDT", current, 1_600, 120_000, 20)
            .unwrap()
            .available_quanta,
        70
    );
}

#[test]
fn restart_or_credential_rotation_cannot_reuse_a_pair() {
    for current in [
        ReceiptFence {
            runtime_epoch: 10,
            ..fence()
        },
        ReceiptFence {
            credential_generation: [2; 16],
            ..fence()
        },
    ] {
        assert_eq!(
            verified_available(&pair(), "main", "USDT", current, 1_500, 120_000, 0),
            Err(AvailableError::Missing)
        );
    }
}

#[test]
fn both_reads_must_be_fresh_and_the_bound_never_exceeds_120_seconds() {
    assert_eq!(
        verified_available(&pair(), "main", "USDT", fence(), 1_500, 399, 0),
        Err(AvailableError::Stale { age_ms: 400 })
    );
    assert_eq!(
        verified_available(&pair(), "main", "USDT", fence(), 121_101, 300_000, 0),
        Err(AvailableError::Stale { age_ms: 120_001 })
    );
    assert!(!AvailableError::Stale { age_ms: 1 }.disarms());
}

#[test]
fn invalid_or_replayed_receipt_metadata_never_supplies_balance() {
    for case in 0..7 {
        let mut seen = pair();
        match case {
            0 => {
                seen[2].request_id = seen[0].request_id;
                seen[3].request_id = seen[1].request_id;
            }
            1 => {
                seen[2].received_at_ms = 1_501;
                seen[3].received_at_ms = 1_501;
            }
            2 => {
                seen[2].started_at_ms = 1_050;
                seen[3].started_at_ms = 1_050;
            }
            3 => {
                seen[0].started_at_ms = 999;
                seen[1].started_at_ms = 999;
            }
            4 => {
                seen[2].response_digest = [0; 32];
                seen[3].response_digest = [0; 32];
            }
            5 => {
                seen[2].receipt_seq = 0;
                seen[3].receipt_seq = 0;
            }
            _ => {
                seen[2].locked_quanta = u64::MAX;
                seen[3].locked_quanta = u64::MAX;
            }
        }
        let error =
            verified_available(&seen, "main", "USDT", fence(), 1_500, 120_000, 0).unwrap_err();
        assert!(error.disarms(), "case {case}: {error:?}");
    }
}
