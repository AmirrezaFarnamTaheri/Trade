//! Offline Fake Venue/transport recovery contract: never sends a real order.
use exec_core::orders::{
    Attempt, Cancellation, EconomicEffect, Event, FailureStage, Lifecycle, OrderError, Settlement,
    SlotError, Slots,
};

#[test]
fn cancellation_ack_and_lost_ack_never_erase_late_fills_or_release_the_slot() {
    let mut order = Attempt::new(100).unwrap();
    assert!(order.apply(Event::BeginCancel).is_err());
    order.apply(Event::BeginSend).unwrap();
    order.apply(Event::Acknowledged).unwrap();
    order.apply(Event::CumulativeFilled(20)).unwrap();
    order.apply(Event::BeginCancel).unwrap();
    order
        .apply(Event::CancelTransportFailed(FailureStage::AfterFirstByte))
        .unwrap();
    assert_eq!(order.cancellation(), Cancellation::Unknown);
    assert_eq!(
        order.apply(Event::BeginCancel),
        Err(OrderError::RetryForbidden)
    );
    order.apply(Event::CumulativeFilled(30)).unwrap();
    order.apply(Event::CancelAcknowledged).unwrap();
    order.apply(Event::CancelAcknowledged).unwrap();
    assert_eq!(order.lifecycle(), Lifecycle::Acknowledged);
    assert!(order.holds_slot());
    assert!(order.apply(Event::SettlementVerified).is_err());
    order.apply(Event::TerminalReported).unwrap();
    order.apply(Event::CumulativeFilled(40)).unwrap();
    assert_eq!(order.filled_quanta(), 40);
    order.apply(Event::SettlementVerified).unwrap();
    assert!(!order.holds_slot());
    assert_eq!(order.cancellation(), Cancellation::Acknowledged);
}

#[test]
fn cancel_prebyte_retry_is_bounded_and_independent_of_entry_fill_evidence() {
    let mut order = Attempt::new(100).unwrap();
    order.apply(Event::BeginSend).unwrap();
    order.apply(Event::Acknowledged).unwrap();
    for fill in [20, 30] {
        order.apply(Event::BeginCancel).unwrap();
        order.apply(Event::CumulativeFilled(fill)).unwrap();
        order
            .apply(Event::CancelTransportFailed(FailureStage::BeforeFirstByte))
            .unwrap();
        assert_eq!(order.lifecycle(), Lifecycle::Acknowledged);
        assert_eq!(order.cancellation(), Cancellation::NotSent);
    }
    let saved = order;
    assert_eq!(
        order.apply(Event::BeginCancel),
        Err(OrderError::RetryForbidden)
    );
    assert_eq!(order, saved);
    assert_eq!(order.filled_quanta(), 30);
}

#[test]
fn before_bytes_can_attempt_one_same_identity_retry_only() {
    let mut o = Attempt::new(10).unwrap();
    o.apply(Event::BeginSend).unwrap();
    o.apply(Event::TransportFailed(FailureStage::BeforeFirstByte))
        .unwrap();
    assert_eq!(o.lifecycle(), Lifecycle::NotSent);
    assert!(o.can_retry_same_identity());
    o.apply(Event::BeginSend).unwrap();
    o.apply(Event::TransportFailed(FailureStage::BeforeFirstByte))
        .unwrap();
    assert!(!o.can_retry_same_identity());
    assert_eq!(o.apply(Event::BeginSend), Err(OrderError::RetryForbidden));
}

#[test]
fn after_bytes_is_unknown_and_never_automatically_retries() {
    let mut o = Attempt::new(10).unwrap();
    o.apply(Event::BeginSend).unwrap();
    o.apply(Event::TransportFailed(FailureStage::AfterFirstByte))
        .unwrap();
    assert_eq!(o.lifecycle(), Lifecycle::Unknown);
    assert_eq!(o.effect(), EconomicEffect::Unverified);
    assert_eq!(o.apply(Event::BeginSend), Err(OrderError::RetryForbidden));
    o.apply(Event::MissingFromList).unwrap();
    assert_eq!(o.lifecycle(), Lifecycle::Unknown);
    assert_eq!(o.settlement(), Settlement::Unverified);
}

#[test]
fn canceled_partially_filled_order_keeps_fill_and_reservation_until_settlement() {
    let mut o = Attempt::new(100).unwrap();
    o.apply(Event::BeginSend).unwrap();
    o.apply(Event::Acknowledged).unwrap();
    o.apply(Event::CumulativeFilled(25)).unwrap();
    o.apply(Event::TerminalReported).unwrap();
    assert_eq!(o.lifecycle(), Lifecycle::TerminalReported);
    assert_eq!(o.effect(), EconomicEffect::Partial);
    assert_eq!(o.settlement(), Settlement::Pending);
    assert!(o.holds_slot());
    assert_eq!(
        o.apply(Event::CumulativeFilled(20)),
        Err(OrderError::FillRegression)
    );
    o.apply(Event::SettlementVerified).unwrap();
    assert_eq!(o.lifecycle(), Lifecycle::Closed);
    assert_eq!(o.filled_quanta(), 25);
    assert!(!o.holds_slot());
}

#[test]
fn terminal_report_does_not_close_without_settlement_evidence() {
    let mut o = Attempt::new(7).unwrap();
    o.apply(Event::BeginSend).unwrap();
    o.apply(Event::Acknowledged).unwrap();
    o.apply(Event::TerminalReported).unwrap();
    assert_eq!(o.lifecycle(), Lifecycle::TerminalReported);
    assert!(o.holds_slot());
    assert_eq!(o.apply(Event::BeginSend), Err(OrderError::RetryForbidden));
}

#[test]
fn fills_cannot_exceed_requested_quantity_or_appear_before_submit() {
    assert_eq!(Attempt::new(0), Err(OrderError::InvalidQuantity));
    let mut o = Attempt::new(10).unwrap();
    assert_eq!(
        o.apply(Event::CumulativeFilled(1)),
        Err(OrderError::IllegalTransition)
    );
    o.apply(Event::BeginSend).unwrap();
    assert_eq!(
        o.apply(Event::CumulativeFilled(11)),
        Err(OrderError::InvalidQuantity)
    );
}

#[test]
fn one_unresolved_entry_per_account_but_independent_verified_exit() {
    let mut slots = Slots::default();
    assert!(slots.entry_allowed("main", "A"));
    slots.try_hold("main", "A", true, false).unwrap();
    assert!(!slots.entry_allowed("main", "B"));
    assert!(!slots.exit_allowed("main", "A", true));
    assert!(slots.exit_allowed("main", "B", true));
    assert!(!slots.exit_allowed("main", "B", false));
    assert!(slots.entry_allowed("credit", "B"));
    assert_eq!(
        slots.release_verified("main", "A", false),
        Err(SlotError::Unsettled)
    );
    slots.release_verified("main", "A", true).unwrap();
    assert!(slots.entry_allowed("main", "B"));
}

#[test]
fn callers_cannot_hold_conflicting_entries_or_unverified_exits() {
    let mut slots = Slots::default();
    slots.try_hold("main", "A", true, false).unwrap();
    assert_eq!(
        slots.try_hold("main", "B", true, false),
        Err(SlotError::Conflict)
    );
    assert_eq!(
        slots.try_hold("main", "A", false, true),
        Err(SlotError::Conflict)
    );
    assert_eq!(
        slots.try_hold("main", "B", false, false),
        Err(SlotError::UnverifiedExit)
    );
    slots.try_hold("main", "B", false, true).unwrap();
    assert!(!slots.entry_allowed("main", "B"));
}
