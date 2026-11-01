//! Synthetic durable recovery; no transport, key access, or funded execution.
use exec_core::orders::{Event, FailureStage, Lifecycle, OrderError, Settlement};
use exec_svc::offline_recovery::{DurableOrderJournal, RecoveryError};
use std::time::{SystemTime, UNIX_EPOCH};

fn db_path(test: &str) -> std::path::PathBuf {
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    std::env::temp_dir().join(format!("tradinggym-b2-{test}-{}-{nonce}.sqlite", std::process::id()))
}

#[test]
fn recovery_never_resends_ambiguous_or_inflight_orders() {
    let path = db_path("ack-lost");
    {
        let mut journal = DurableOrderJournal::open(&path).unwrap();
        journal.create_intent("client-a", "main", "USDT", 10).unwrap();
        journal.record_event("client-a", Event::BeginSend).unwrap();
        journal.record_event("client-a", Event::TransportFailed(FailureStage::AfterFirstByte)).unwrap();
    }
    let mut restarted = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(restarted.get("client-a").unwrap().attempt.lifecycle(), Lifecycle::Unknown);
    assert_eq!(restarted.record_event("client-a", Event::BeginSend),
        Err(RecoveryError::Order(OrderError::RetryForbidden)));
    assert_eq!(restarted.pending_ids(), vec!["client-a"]);
    restarted.record_event("client-a", Event::Acknowledged).unwrap();
    restarted.record_event("client-a", Event::TerminalReported).unwrap();
    restarted.record_event("client-a", Event::CumulativeFilled(0)).unwrap();
    restarted.record_event("client-a", Event::SettlementVerified).unwrap();
    drop(restarted);
    let recovered = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(recovered.get("client-a").unwrap().attempt.lifecycle(), Lifecycle::Closed);
    assert_eq!(recovered.get("client-a").unwrap().attempt.settlement(), Settlement::Verified);
    assert!(recovered.pending_ids().is_empty());
}

#[test]
fn crash_after_begin_send_before_dispatch_proof_is_not_retryable() {
    let path = db_path("inflight");
    {
        let mut journal = DurableOrderJournal::open(&path).unwrap();
        journal.create_intent("client-b", "main", "BTC", 2).unwrap();
        journal.record_event("client-b", Event::BeginSend).unwrap();
    }
    let mut restarted = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(restarted.get("client-b").unwrap().attempt.lifecycle(), Lifecycle::Submitting);
    assert_eq!(restarted.record_event("client-b", Event::BeginSend),
        Err(RecoveryError::Order(OrderError::RetryForbidden)));
    assert_eq!(restarted.pending_ids(), vec!["client-b"]);
}

#[test]
fn invalid_transition_does_not_append_to_durable_ledger() {
    let path = db_path("atomic");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.create_intent("client-c", "main", "USDT", 25).unwrap();
    assert_eq!(journal.record_event("client-c", Event::SettlementVerified),
        Err(RecoveryError::Order(OrderError::IllegalTransition)));
    let before = journal.get("client-c").unwrap().attempt;
    assert_eq!(journal.create_intent("client-c", "main", "USDT", 25),
        Err(RecoveryError::DuplicateIdentity));
    drop(journal);
    let recovered = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(recovered.get("client-c").unwrap().attempt, before);
    assert_eq!(recovered.record_count(), 1);
}

#[test]
fn unrecognized_persisted_event_bytes_fail_closed_during_replay() {
    let path = db_path("tampered");
    {
        let mut raw = exec_store::Ledger::open(&path).unwrap();
        raw.append(b"unregistered order journal bytes").unwrap();
    }
    let result = DurableOrderJournal::open(&path);
    assert!(matches!(result, Err(RecoveryError::MalformedEvent)));
}

#[test]
fn exact_account_and_asset_identity_survives_restart() {
    let path = db_path("scoped");
    {
        let mut journal = DurableOrderJournal::open(&path).unwrap();
        journal.create_intent("independent", "subaccount:credit-1", "BTC", 17).unwrap();
        journal.record_event("independent", Event::Denied).unwrap();
    }
    let restarted = DurableOrderJournal::open(&path).unwrap();
    let order = restarted.get("independent").unwrap();
    assert_eq!(order.account, "subaccount:credit-1");
    assert_eq!(order.asset, "BTC");
    assert_eq!(order.attempt.requested_quanta(), 17);
    assert_eq!(order.attempt.lifecycle(), Lifecycle::Denied);
}

#[test]
fn recovered_inflight_attempt_cannot_claim_prebyte_failure_after_crash() {
    let path = db_path("crash-prebyte");
    {
        let mut writer = DurableOrderJournal::open(&path).unwrap();
        writer.create_intent("client-crash", "main", "BTC", 5).unwrap();
        writer.record_event("client-crash", Event::BeginSend).unwrap();
    }
    for _ in 0..2 {
        let mut restarted = DurableOrderJournal::open(&path).unwrap();
        assert_eq!(restarted.record_count(), 2);
        assert_eq!(
            restarted.record_event("client-crash",
                Event::TransportFailed(FailureStage::BeforeFirstByte)),
            Err(RecoveryError::Order(OrderError::IllegalTransition))
        );
        assert_eq!(restarted.record_count(), 2);
        assert_eq!(restarted.get("client-crash").unwrap().attempt.lifecycle(),
            Lifecycle::Submitting);
        assert_eq!(restarted.record_event("client-crash", Event::BeginSend),
            Err(RecoveryError::Order(OrderError::RetryForbidden)));
    }
    let mut restarted = DurableOrderJournal::open(&path).unwrap();
    restarted.record_event("client-crash",
        Event::TransportFailed(FailureStage::AfterFirstByte)).unwrap();
    assert_eq!(restarted.get("client-crash").unwrap().attempt.lifecycle(),
        Lifecycle::Unknown);
}

#[test]
fn continuous_process_may_record_proven_prebyte_failure_once() {
    let path = db_path("same-process-prebyte");
    let mut writer = DurableOrderJournal::open(&path).unwrap();
    writer.create_intent("client-proven", "main", "USDT", 10).unwrap();
    writer.record_event("client-proven", Event::BeginSend).unwrap();
    writer.record_event("client-proven",
        Event::TransportFailed(FailureStage::BeforeFirstByte)).unwrap();
    assert!(writer.get("client-proven").unwrap().attempt.can_retry_same_identity());
    writer.record_event("client-proven", Event::BeginSend).unwrap();
    writer.record_event("client-proven",
        Event::TransportFailed(FailureStage::BeforeFirstByte)).unwrap();
    assert!(!writer.get("client-proven").unwrap().attempt.can_retry_same_identity());
}
