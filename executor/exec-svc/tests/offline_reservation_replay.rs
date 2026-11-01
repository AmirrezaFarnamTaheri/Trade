//! Committed offline reservation holds share the order journal's hash chain.
//! These tests do NOT grant venue credentials, POST, or funded authority.
use exec_core::orders::{BalanceSnapshot, Event, ReservationError, SettlementEvidence};
use exec_svc::offline_recovery::{DurableOrderJournal, RecoveryError};
use std::time::{SystemTime, UNIX_EPOCH};

fn db_path(test: &str) -> std::path::PathBuf {
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    std::env::temp_dir().join(format!("tg-b2-reserved-{test}-{}-{nonce}.sqlite", std::process::id()))
}
fn balance(available: u64, seq: u64) -> BalanceSnapshot {
    BalanceSnapshot::new("main", "USDT", available, seq).unwrap()
}
fn settlement(seq: u64, spent: u64, available: u64) -> SettlementEvidence {
    SettlementEvidence::new("main", "USDT", seq, true, 0, spent, available).unwrap()
}
fn close(journal: &mut DurableOrderJournal, id: &str, filled: u64) {
    journal.record_event(id, Event::BeginSend).unwrap();
    journal.record_event(id, Event::Acknowledged).unwrap();
    journal.record_event(id, Event::CumulativeFilled(filled)).unwrap();
    journal.record_event(id, Event::TerminalReported).unwrap();
    journal.record_event(id, Event::SettlementVerified).unwrap();
}

#[test]
fn committed_hold_survives_crash_and_blocks_over_reservation() {
    let path = db_path("holds");
    {
        let mut journal = DurableOrderJournal::open(&path).unwrap();
        journal.create_intent("a", "main", "USDT", 6).unwrap();
        journal.reserve_intent("a", 60, &balance(100, 10)).unwrap();
    }
    let mut recovered = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(recovered.reserved("main", "USDT"), 60);
    recovered.create_intent("b", "main", "USDT", 5).unwrap();
    assert_eq!(
        recovered.reserve_intent("b", 50, &balance(100, 10)),
        Err(RecoveryError::Reservation(ReservationError::InsufficientAvailable))
    );
    assert_eq!(recovered.reserved("main", "USDT"), 60);
    recovered.reserve_intent("b", 40, &balance(100, 10)).unwrap();
    drop(recovered);
    let final_journal = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(final_journal.reserved("main", "USDT"), 100);
}

#[test]
fn conflicting_identity_and_forged_account_do_not_append() {
    let path = db_path("identity");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.create_intent("a", "main", "USDT", 6).unwrap();
    let original = journal.record_count();
    assert_eq!(
        journal.reserve_intent("a", 40, &BalanceSnapshot::new("other", "USDT", 100, 2).unwrap()),
        Err(RecoveryError::Reservation(ReservationError::InvalidEvidence))
    );
    assert_eq!(journal.record_count(), original);
    journal.reserve_intent("a", 40, &balance(100, 2)).unwrap();
    assert_eq!(
        journal.reserve_intent("a", 1, &balance(100, 2)),
        Err(RecoveryError::Reservation(ReservationError::DuplicateIntent))
    );
    assert_eq!(journal.reserved("main", "USDT"), 40);
    assert_eq!(journal.record_count(), original + 1);
}

#[test]
fn denied_order_release_is_durable_but_old_snapshot_stays_stale() {
    let path = db_path("denied");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.create_intent("denied", "main", "USDT", 1).unwrap();
    journal.reserve_intent("denied", 80, &balance(100, 11)).unwrap();
    assert_eq!(
        journal.release_denied_reservation("denied"),
        Err(RecoveryError::Reservation(ReservationError::OrderNotSettled))
    );
    journal.record_event("denied", Event::Denied).unwrap();
    journal.release_denied_reservation("denied").unwrap();
    drop(journal);

    let mut recovered = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(recovered.reserved("main", "USDT"), 0);
    recovered.create_intent("new", "main", "USDT", 1).unwrap();
    assert_eq!(
        recovered.reserve_intent("new", 10, &balance(100, 10)),
        Err(RecoveryError::Reservation(ReservationError::StaleBalance))
    );
    recovered.reserve_intent("new", 10, &balance(100, 12)).unwrap();
}

#[test]
fn two_orders_release_against_one_aggregate_evidence_and_replay() {
    let path = db_path("aggregate");
    let evidence = settlement(11, 100, 0);
    {
        let mut journal = DurableOrderJournal::open(&path).unwrap();
        journal.create_intent("a", "main", "USDT", 6).unwrap();
        journal.create_intent("b", "main", "USDT", 4).unwrap();
        journal.reserve_intent("a", 60, &balance(100, 10)).unwrap();
        journal.reserve_intent("b", 40, &balance(100, 10)).unwrap();
        close(&mut journal, "a", 6);
        close(&mut journal, "b", 4);
        journal.release_settled_reservation("a", &evidence).unwrap();
        assert_eq!(journal.reserved("main", "USDT"), 40);
    }
    let mut recovered = DurableOrderJournal::open(&path).unwrap();
    assert_eq!(recovered.reserved("main", "USDT"), 40);
    recovered.release_settled_reservation("b", &evidence).unwrap();
    drop(recovered);
    assert_eq!(DurableOrderJournal::open(&path).unwrap().reserved("main", "USDT"), 0);
}

#[test]
fn unknown_settlement_does_not_free_committed_hold() {
    let path = db_path("unknown");
    let mut journal = DurableOrderJournal::open(&path).unwrap();
    journal.create_intent("a", "main", "USDT", 1).unwrap();
    journal.reserve_intent("a", 100, &balance(100, 10)).unwrap();
    journal.record_event("a", Event::BeginSend).unwrap();
    assert_eq!(
        journal.release_settled_reservation("a", &settlement(11, 100, 0)),
        Err(RecoveryError::Reservation(ReservationError::OrderNotSettled))
    );
    assert_eq!(journal.reserved("main", "USDT"), 100);
    drop(journal);
    assert_eq!(DurableOrderJournal::open(&path).unwrap().reserved("main", "USDT"), 100);
}
