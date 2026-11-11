//! OD-5: admission's available amount comes from the newest observation, bounded in age, and blocks (and disarms)
//! when the two vault journals disagree.
use exec_core::available::{
    verified_available, Available, AvailableError, Journal, ObservedBalance,
};

fn obs(journal: Journal, available: u64, sequence: u64, at: u64) -> ObservedBalance {
    ObservedBalance {
        journal,
        account: "main".into(),
        asset: "USDT".into(),
        available_quanta: available,
        sequence,
        received_at_ms: at,
    }
}

#[test]
fn the_newest_sequence_wins_across_journals() {
    let seen = [
        obs(Journal::Ledger, 900, 4, 1_000),
        obs(Journal::Credentials, 950, 5, 900), // newer venue sequence, older host stamp (clock stepped back)
        obs(Journal::Credentials, 800, 3, 2_000),
    ];
    assert_eq!(
        verified_available(&seen, "main", "USDT", 1_500, 5_000),
        Ok(Available {
            available_quanta: 950,
            sequence: 5,
            age_ms: 600
        })
    );
}

#[test]
fn a_stale_or_missing_observation_blocks() {
    let seen = [obs(Journal::Ledger, 900, 4, 1_000)];
    assert_eq!(
        verified_available(&seen, "main", "USDT", 7_001, 6_000),
        Err(AvailableError::Stale { age_ms: 6_001 })
    );
    assert_eq!(
        verified_available(&seen, "main", "TMN", 1_000, 6_000),
        Err(AvailableError::Missing)
    );
    assert!(!AvailableError::Stale { age_ms: 1 }.disarms());
}

#[test]
fn journals_disagreeing_on_a_sequence_block_and_disarm() {
    let seen = [
        obs(Journal::Ledger, 900, 4, 1_000),
        obs(Journal::Credentials, 901, 4, 1_000),
        obs(Journal::Ledger, 950, 5, 1_100),
    ];
    let error = verified_available(&seen, "main", "USDT", 1_200, 5_000).unwrap_err();
    assert_eq!(error, AvailableError::Disagreement { sequence: 4 });
    assert!(error.disarms());
    // The same amount recorded in both journals is agreement, not a fault.
    let agree = [
        obs(Journal::Ledger, 900, 4, 1_000),
        obs(Journal::Credentials, 900, 4, 1_010),
    ];
    assert_eq!(
        verified_available(&agree, "main", "USDT", 1_100, 5_000)
            .unwrap()
            .available_quanta,
        900
    );
}
