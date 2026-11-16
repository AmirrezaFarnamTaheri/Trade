use exec_core::available::AvailableError;
use exec_svc::account_observation::{AccountKind, AccountObservation};
use exec_svc::balance_receipts::{BalanceReceipts, ReceiptError};
use exec_svc::offline_recovery::{CredentialMetadata, CredentialPermission, DurableOrderJournal};
use std::sync::atomic::{AtomicU64, Ordering};

fn journals() -> (DurableOrderJournal, DurableOrderJournal) {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let root = std::env::temp_dir().join(format!(
        "gym-native-receipts-{}-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir(&root).unwrap();
    let mut credentials = DurableOrderJournal::open(root.join("credentials.sqlite")).unwrap();
    credentials
        .commit_credential(CredentialMetadata {
            generation: [3; 16],
            ciphertext_digest: [4; 32],
            permission: CredentialPermission::Unverified,
        })
        .unwrap();
    let ledger = DurableOrderJournal::open(root.join("execution.sqlite")).unwrap();
    (credentials, ledger)
}

fn observed(id: u8, start: u64, value: &str, locked: &str) -> AccountObservation {
    let body = serde_json::to_vec(&serde_json::json!({"success": true,
        "result": {"balances": {"USDT": {"value": value, "locked": locked}}}}))
    .unwrap();
    AccountObservation::from_response(
        AccountKind::Balances,
        &body,
        [3; 16],
        10,
        [id; 16],
        start,
        start + 10,
    )
    .unwrap()
}

fn commit(
    producer: &mut BalanceReceipts,
    credentials: &mut DurableOrderJournal,
    ledger: &mut DurableOrderJournal,
    id: u8,
    start: u64,
    value: &str,
    locked: &str,
) -> bool {
    let read = producer.begin([3; 16], 10, [id; 16], start).unwrap();
    producer
        .complete(
            read,
            observed(id, start, value, locked),
            credentials,
            Some(ledger),
        )
        .unwrap()
        .disagreed
}

#[test]
fn admission_needs_two_durable_native_reads_and_subtracts_locked_and_own_holds() {
    let (mut credentials, mut ledger) = journals();
    let mut producer = BalanceReceipts::default();
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        1,
        1000,
        "10.005",
        "1.001",
    );
    assert_eq!(
        producer.available("USDT", 2, 0, 1010, 120_000),
        Err(AvailableError::Missing)
    );
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        2,
        1020,
        "010.0050",
        "01.0010",
    );
    let available = producer.available("USDT", 2, 50, 1030, 120_000).unwrap();
    assert_eq!(available.available_quanta, 849);
    assert_eq!(available.age_ms, 20);
    assert!(available.receipt_seq > 0);
    assert_eq!(
        ledger.credential_metadata(),
        credentials.credential_metadata()
    );
    assert_eq!(
        producer
            .available("USDT", 2, 9999, 1030, 120_000)
            .unwrap()
            .available_quanta,
        0
    );
    assert!(matches!(
        producer.available("USDT", 2, 0, 121_011, 999_999),
        Err(AvailableError::Stale { .. })
    ));
}

#[test]
fn no_execution_journal_is_observation_only_and_never_supplies_a_pair() {
    let (mut credentials, _) = journals();
    let mut producer = BalanceReceipts::default();
    for (id, start) in [(1, 1000), (2, 1020)] {
        let read = producer.begin([3; 16], 10, [id; 16], start).unwrap();
        let saved = producer
            .complete(read, observed(id, start, "10", "0"), &mut credentials, None)
            .unwrap();
        assert!(!saved.paired);
    }
    assert_eq!(
        producer.available("USDT", 2, 0, 1040, 120_000),
        Err(AvailableError::Missing)
    );
}

#[test]
fn consecutive_changes_disarm_even_below_the_requested_quantum() {
    let (mut credentials, mut ledger) = journals();
    let mut producer = BalanceReceipts::default();
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        1,
        1000,
        "10.001",
        "0",
    );
    assert!(commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        2,
        1020,
        "10.002",
        "0"
    ));
    assert_eq!(
        producer.available("USDT", 2, 0, 1030, 120_000),
        Err(AvailableError::Missing)
    );
    assert!(!commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        3,
        1040,
        "10.002",
        "0"
    ));
    assert!(producer.available("USDT", 2, 0, 1050, 120_000).is_ok());
    assert!(commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        4,
        1060,
        "10.002",
        "0.00001"
    ));
}

#[test]
fn own_activity_invalidates_the_pair_and_any_read_in_flight() {
    let (mut credentials, mut ledger) = journals();
    let mut producer = BalanceReceipts::default();
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        1,
        1000,
        "10",
        "0",
    );
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        2,
        1020,
        "10",
        "0",
    );
    let read = producer.begin([3; 16], 10, [3; 16], 1040).unwrap();
    producer.own_activity(1045).unwrap();
    assert!(matches!(
        producer.complete(
            read,
            observed(3, 1040, "10", "0"),
            &mut credentials,
            Some(&mut ledger)
        ),
        Err(ReceiptError::ActivityChanged)
    ));
    assert_eq!(
        producer.available("USDT", 2, 0, 1050, 120_000),
        Err(AvailableError::Missing)
    );
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        4,
        1060,
        "9",
        "0",
    );
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        5,
        1080,
        "9",
        "0",
    );
    assert_eq!(
        producer
            .available("USDT", 2, 0, 1090, 120_000)
            .unwrap()
            .available_quanta,
        900
    );
}

#[test]
fn overlapping_reads_replay_and_clock_regression_are_refused() {
    let (mut credentials, mut ledger) = journals();
    let mut producer = BalanceReceipts::default();
    let first = producer.begin([3; 16], 10, [1; 16], 1000).unwrap();
    assert!(producer.begin([3; 16], 10, [2; 16], 1001).is_err());
    producer
        .complete(
            first,
            observed(1, 1000, "10", "0"),
            &mut credentials,
            Some(&mut ledger),
        )
        .unwrap();
    assert!(producer.begin([3; 16], 10, [2; 16], 1009).is_err());
    assert!(producer.begin([3; 16], 10, [1; 16], 1020).is_err());
    assert!(producer.begin([0; 16], 10, [3; 16], 1020).is_err());
}

#[test]
fn partial_second_commit_poisoning_never_falls_back_to_an_older_pair() {
    let (mut credentials, mut ledger) = journals();
    let mut producer = BalanceReceipts::default();
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        1,
        1000,
        "10",
        "0",
    );
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        2,
        1020,
        "10",
        "0",
    );
    ledger
        .record_account_observation(observed(3, 1040, "10", "0"))
        .unwrap();
    let read = producer.begin([3; 16], 10, [3; 16], 1040).unwrap();
    assert!(matches!(
        producer.complete(
            read,
            observed(3, 1040, "10", "0"),
            &mut credentials,
            Some(&mut ledger)
        ),
        Err(ReceiptError::CommitUncertain)
    ));
    assert_eq!(
        producer.available("USDT", 2, 0, 1050, 120_000),
        Err(AvailableError::InvalidReceipt)
    );
    assert!(producer.begin([3; 16], 10, [4; 16], 1060).is_err());
    assert_eq!(
        BalanceReceipts::default().available("USDT", 2, 0, 1050, 120_000),
        Err(AvailableError::Missing)
    );
}

#[test]
fn aborted_read_and_runtime_or_credential_change_require_two_new_reads() {
    let (mut credentials, mut ledger) = journals();
    let mut producer = BalanceReceipts::default();
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        1,
        1000,
        "10",
        "0",
    );
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        2,
        1020,
        "10",
        "0",
    );
    let read = producer.begin([3; 16], 10, [3; 16], 1040).unwrap();
    producer.abort(read);
    assert_eq!(
        producer.available("USDT", 2, 0, 1050, 120_000),
        Err(AvailableError::Missing)
    );
    let read = producer.begin([3; 16], 11, [4; 16], 1060).unwrap();
    assert_eq!(
        producer.available("USDT", 2, 0, 1060, 120_000),
        Err(AvailableError::Missing)
    );
    producer.abort(read);
    let read = producer.begin([9; 16], 11, [5; 16], 1080).unwrap();
    assert_eq!(
        producer.available("USDT", 2, 0, 1080, 120_000),
        Err(AvailableError::Missing)
    );
    producer.abort(read);
}

#[test]
fn malformed_large_or_unknown_units_never_create_spendable_funds() {
    let (mut credentials, mut ledger) = journals();
    let mut producer = BalanceReceipts::default();
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        1,
        1000,
        "18446744073709551616",
        "0",
    );
    commit(
        &mut producer,
        &mut credentials,
        &mut ledger,
        2,
        1020,
        "18446744073709551616",
        "0",
    );
    assert_eq!(
        producer.available("USDT", 0, 0, 1030, 120_000),
        Err(AvailableError::InvalidReceipt)
    );
    assert_eq!(
        producer.available("USDT", 19, 0, 1030, 120_000),
        Err(AvailableError::InvalidReceipt)
    );
    assert_eq!(
        producer.available("BTC", 8, 0, 1030, 120_000),
        Err(AvailableError::Missing)
    );
}

#[test]
fn receipt_context_and_sanitized_shape_are_checked_before_either_commit() {
    for field in ["request_id", "runtime_epoch", "started_at_ms", "data"] {
        let (mut credentials, mut ledger) = journals();
        let mut producer = BalanceReceipts::default();
        let read = producer.begin([3; 16], 10, [1; 16], 1000).unwrap();
        let mut raw = serde_json::to_value(observed(1, 1000, "10", "0")).unwrap();
        raw[field] = match field {
            "request_id" => serde_json::to_value([2u8; 16]).unwrap(),
            "data" => serde_json::json!({"success": true, "result": {"balances": []}}),
            _ => serde_json::json!(999),
        };
        let value: AccountObservation = serde_json::from_value(raw).unwrap();
        let before = credentials.record_count();
        assert!(producer
            .complete(read, value, &mut credentials, Some(&mut ledger))
            .is_err());
        assert_eq!(credentials.record_count(), before);
        assert_eq!(ledger.record_count(), 0);
    }
}

#[test]
fn only_the_latest_two_complete_reads_contribute_to_the_freshness_bound() {
    let (mut credentials, mut ledger) = journals();
    let mut producer = BalanceReceipts::default();
    for (id, start) in [(1, 1000), (2, 1020), (3, 1040)] {
        commit(
            &mut producer,
            &mut credentials,
            &mut ledger,
            id,
            start,
            "10",
            "0",
        );
    }
    assert_eq!(
        producer
            .available("USDT", 2, 0, 1050, 120_000)
            .unwrap()
            .age_ms,
        20
    );
    let read = producer.begin([3; 16], 10, [4; 16], 1060).unwrap();
    assert_eq!(
        producer.available("USDT", 2, 0, 1060, 120_000),
        Err(AvailableError::Missing)
    );
    producer.abort(read);
}
