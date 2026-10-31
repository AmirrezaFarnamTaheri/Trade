//! B2 typed reservations and authority tiers; no venue network or funded order API.
use exec_core::orders::{
    Attempt, BalanceSnapshot, EconomicEffect, Event, FailureStage, Lifecycle,
    OrderError, ReservationBook, ReservationError, Settlement, SettlementEvidence,
    SlotError, Slots,
};
use exec_core::authority::{permits, Action, AuthorityTier};

#[test]
fn locally_denied_intent_is_not_a_venue_rejection_or_open_slot() {
    let mut attempt = Attempt::new(10).unwrap();
    attempt.apply(Event::Denied).unwrap();
    assert_eq!(attempt.lifecycle(), Lifecycle::Denied);
    assert_eq!(attempt.effect(), EconomicEffect::NoneObserved);
    assert!(!attempt.holds_slot());
    assert_eq!(attempt.apply(Event::BeginSend), Err(OrderError::RetryForbidden));
}

#[test]
fn venue_rejection_is_separate_from_local_denial_and_requires_settlement() {
    let mut attempt = Attempt::new(10).unwrap();
    attempt.apply(Event::BeginSend).unwrap();
    attempt.apply(Event::VenueRejected).unwrap();
    assert_eq!(attempt.lifecycle(), Lifecycle::Rejected);
    assert_eq!(attempt.effect(), EconomicEffect::NoneObserved);
    assert_eq!(attempt.settlement(), Settlement::Pending);
    assert!(attempt.holds_slot());
    attempt.apply(Event::SettlementVerified).unwrap();
    assert_eq!(attempt.lifecycle(), Lifecycle::Closed);
}

#[test]
fn settlement_anomaly_freezes_until_exact_balance_reconciliation() {
    let mut attempt = Attempt::new(10).unwrap();
    attempt.apply(Event::BeginSend).unwrap();
    attempt.apply(Event::Acknowledged).unwrap();
    attempt.apply(Event::TerminalReported).unwrap();
    attempt.apply(Event::CumulativeFilled(3)).unwrap();
    attempt.apply(Event::SettlementAnomaly).unwrap();
    assert_eq!(attempt.settlement(), Settlement::Anomaly);
    assert!(attempt.holds_slot());
    assert_eq!(attempt.apply(Event::SettlementVerified), Err(OrderError::IllegalTransition));
    assert_eq!(attempt.apply(Event::AnomalyReconciled {
        expected_available_quanta: 97, observed_available_quanta: 96,
    }), Err(OrderError::UnreconciledAnomaly));
    attempt.apply(Event::AnomalyReconciled {
        expected_available_quanta: 97, observed_available_quanta: 97,
    }).unwrap();
    assert_eq!(attempt.settlement(), Settlement::Pending);
    attempt.apply(Event::SettlementVerified).unwrap();
    assert_eq!(attempt.settlement(), Settlement::Settled);
    assert!(!attempt.holds_slot());
}

#[test]
fn reservation_book_prevents_double_spend_and_scopes_assets_and_accounts() {
    let mut attempt = Attempt::new(10).unwrap();
    let mut book = ReservationBook::default();
    let snapshot = BalanceSnapshot::new("main", "USDT", 1000, 10).unwrap();
    book.reserve("intent-a", "main", "USDT", 600, &snapshot, &attempt).unwrap();
    assert_eq!(
        book.reserve("intent-b", "main", "USDT", 401, &snapshot, &attempt),
        Err(ReservationError::InsufficientAvailable)
    );
    book.reserve("intent-b", "main", "USDT", 400, &snapshot, &attempt).unwrap();
    book.reserve("intent-c", "main", "BTC", 10, &BalanceSnapshot::new("main", "BTC", 10, 10).unwrap(), &attempt).unwrap();
    book.reserve("intent-d", "subaccount:credit-1", "USDT", 1000,
        &BalanceSnapshot::new("subaccount:credit-1", "USDT", 1000, 10).unwrap(), &attempt).unwrap();
    assert_eq!(book.reserved("main", "USDT"), 1000);
    assert_eq!(book.reserved("main", "BTC"), 10);
    assert_eq!(book.reserved("subaccount:credit-1", "USDT"), 1000);
}

#[test]
fn reservation_release_requires_closed_order_and_exact_new_balance_evidence() {
    let mut attempt = Attempt::new(10).unwrap();
    let mut book = ReservationBook::default();
    let snapshot = BalanceSnapshot::new("main", "USDT", 1000, 10).unwrap();
    book.reserve("intent-a", "main", "USDT", 100, &snapshot, &attempt).unwrap();
    let wrong = SettlementEvidence::new("main", "USDT", 11, true, 0, 40, 959).unwrap();
    assert_eq!(book.release_settled("intent-a", &attempt, &wrong), Err(ReservationError::OrderNotSettled));
    attempt.apply(Event::BeginSend).unwrap();
    attempt.apply(Event::Acknowledged).unwrap();
    attempt.apply(Event::TerminalReported).unwrap();
    attempt.apply(Event::CumulativeFilled(4)).unwrap();
    attempt.apply(Event::SettlementVerified).unwrap();
    let stale = SettlementEvidence::new("main", "USDT", 10, true, 0, 40, 960).unwrap();
    assert_eq!(book.release_settled("intent-a", &attempt, &stale), Err(ReservationError::StaleBalance));
    let still_locked = SettlementEvidence::new("main", "USDT", 11, true, 1, 40, 960).unwrap();
    assert_eq!(book.release_settled("intent-a", &attempt, &still_locked), Err(ReservationError::StillLocked));
    let wrong_delta = SettlementEvidence::new("main", "USDT", 11, true, 0, 40, 961).unwrap();
    assert_eq!(book.release_settled("intent-a", &attempt, &wrong_delta), Err(ReservationError::BalanceMismatch));
    let evidence = SettlementEvidence::new("main", "USDT", 11, true, 0, 40, 960).unwrap();
    book.release_settled("intent-a", &attempt, &evidence).unwrap();
    assert_eq!(book.reserved("main", "USDT"), 0);
}

#[test]
fn reservation_rejects_duplicate_intents_and_unverified_or_empty_balance_snapshots() {
    let mut attempt = Attempt::new(10).unwrap();
    let mut book = ReservationBook::default();
    let snapshot = BalanceSnapshot::new("main", "USDT", 100, 4).unwrap();
    book.reserve("intent-a", "main", "USDT", 50, &snapshot, &attempt).unwrap();
    assert_eq!(book.reserve("intent-a", "main", "USDT", 10, &snapshot, &attempt), Err(ReservationError::DuplicateIntent));
    assert_eq!(BalanceSnapshot::new("", "USDT", 100, 4), Err(ReservationError::InvalidEvidence));
    assert_eq!(BalanceSnapshot::new("main", "USDT", 100, 0), Err(ReservationError::InvalidEvidence));
    let mut already_sent = Attempt::new(10).unwrap();
    already_sent.apply(Event::BeginSend).unwrap();
    assert_eq!(book.reserve("intent-b", "main", "USDT", 10, &snapshot, &already_sent),
               Err(ReservationError::OrderNotFresh));
}

#[test]
fn authority_tiers_are_monotone_and_high_impact_actions_require_t2() {
    assert!(permits(AuthorityTier::T0, Action::PauseEntries));
    assert!(permits(AuthorityTier::T0, Action::ExitOnly));
    assert!(permits(AuthorityTier::T0, Action::Halt));
    assert!(!permits(AuthorityTier::T0, Action::ApproveProposal));
    assert!(!permits(AuthorityTier::T0, Action::Flatten));
    assert!(permits(AuthorityTier::T1, Action::ApproveProposal));
    assert!(permits(AuthorityTier::T1, Action::Flatten));
    assert!(!permits(AuthorityTier::T1, Action::ProvisionCredential));
    assert!(!permits(AuthorityTier::T1, Action::ResolveUnknownOrder));
    assert!(!permits(AuthorityTier::T1, Action::HardStop));
    assert!(permits(AuthorityTier::T2, Action::ProvisionCredential));
    assert!(permits(AuthorityTier::T2, Action::ResolveUnknownOrder));
    assert!(permits(AuthorityTier::T2, Action::HardStop));
}

#[test]
fn reservation_rejects_older_snapshots_even_when_they_claim_more_available() {
    let mut book = ReservationBook::default();
    let order = Attempt::new(10).unwrap();
    let fresh = BalanceSnapshot::new("main", "USDT", 100, 12).unwrap();
    book.reserve("first", "main", "USDT", 50, &fresh, &order).unwrap();
    let stale = BalanceSnapshot::new("main", "USDT", 1000, 10).unwrap();
    assert_eq!(book.reserve("second", "main", "USDT", 200, &stale, &order),
        Err(ReservationError::StaleBalance));
    assert_eq!(book.reserved("main", "USDT"), 50);
}

#[test]
fn two_concurrent_fully_settled_orders_reconcile_against_account_totals() {
    let mut book = ReservationBook::default();
    let snapshot = BalanceSnapshot::new("main", "USDT", 1000, 10).unwrap();
    let mut first = Attempt::new(6).unwrap();
    let mut second = Attempt::new(4).unwrap();
    book.reserve("first", "main", "USDT", 600, &snapshot, &first).unwrap();
    book.reserve("second", "main", "USDT", 400, &snapshot, &second).unwrap();
    for (attempt, filled) in [(&mut first, 6), (&mut second, 4)] {
        attempt.apply(Event::BeginSend).unwrap();
        attempt.apply(Event::Acknowledged).unwrap();
        attempt.apply(Event::CumulativeFilled(filled)).unwrap();
        attempt.apply(Event::TerminalReported).unwrap();
        attempt.apply(Event::SettlementVerified).unwrap();
    }
    // Account-level evidence covers BOTH orders, not just one reservation.
    let evidence = SettlementEvidence::new("main", "USDT", 11, true, 0, 1000, 0).unwrap();
    book.release_settled("first", &first, &evidence).unwrap();
    assert_eq!(book.reserved("main", "USDT"), 400);
    book.release_settled("second", &second, &evidence).unwrap();
    assert_eq!(book.reserved("main", "USDT"), 0);
}

#[test]
fn completed_settlement_keeps_observation_watermark_after_last_release() {
    let mut book = ReservationBook::default();
    let mut order = Attempt::new(1).unwrap();
    let initial = BalanceSnapshot::new("main", "USDT", 100, 10).unwrap();
    book.reserve("first", "main", "USDT", 100, &initial, &order).unwrap();
    order.apply(Event::BeginSend).unwrap();
    order.apply(Event::Acknowledged).unwrap();
    order.apply(Event::CumulativeFilled(1)).unwrap();
    order.apply(Event::TerminalReported).unwrap();
    order.apply(Event::SettlementVerified).unwrap();
    let evidence = SettlementEvidence::new("main", "USDT", 11, true, 0, 100, 0).unwrap();
    book.release_settled("first", &order, &evidence).unwrap();
    let next = Attempt::new(1).unwrap();
    assert_eq!(book.reserve("second", "main", "USDT", 50, &initial, &next),
        Err(ReservationError::StaleBalance));
}

#[test]
fn locally_denied_reservation_can_release_without_settlement_evidence() {
    let mut book = ReservationBook::default();
    let mut denied = Attempt::new(10).unwrap();
    let first = BalanceSnapshot::new("main", "USDT", 100, 10).unwrap();
    book.reserve("denied-hold", "main", "USDT", 60, &first, &denied).unwrap();
    assert_eq!(book.release_denied("denied-hold", &denied), Err(ReservationError::OrderNotSettled));
    denied.apply(Event::Denied).unwrap();
    book.release_denied("denied-hold", &denied).unwrap();
    assert_eq!(book.reserved("main", "USDT"), 0);
    let fresh = BalanceSnapshot::new("main", "USDT", 75, 11).unwrap();
    book.reserve("new-hold", "main", "USDT", 70, &fresh, &Attempt::new(10).unwrap()).unwrap();
    assert_eq!(book.reserved("main", "USDT"), 70);
}
