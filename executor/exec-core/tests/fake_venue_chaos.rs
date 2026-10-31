//! Deterministic B2 Fake Venue chaos fixtures: no I/O or funded POST.
use exec_core::orders::{
    Attempt, EconomicEffect, Event, FailureStage, Lifecycle, OrderError,
    Settlement, SlotError, Slots,
};

#[test]
fn chaos_01_ack_lost_after_bytes_keeps_slot_and_blocks_retry() {
    let mut attempt = Attempt::new(15).unwrap();
    attempt.apply(Event::BeginSend).unwrap();
    attempt.apply(Event::TransportFailed(FailureStage::AfterFirstByte)).unwrap();
    for _ in 0..100 {
        attempt.apply(Event::MissingFromList).unwrap();
        assert_eq!(attempt.lifecycle, Lifecycle::Unknown);
        assert!(attempt.holds_slot());
        assert_eq!(attempt.apply(Event::BeginSend), Err(OrderError::RetryForbidden));
    }
    attempt.apply(Event::Acknowledged).unwrap();
    attempt.apply(Event::CumulativeFilled(15)).unwrap();
    attempt.apply(Event::TerminalReported).unwrap();
    assert_eq!(attempt.effect, EconomicEffect::Full);
    assert_eq!(attempt.settlement, Settlement::Pending);
    assert!(attempt.holds_slot());
    attempt.apply(Event::SettlementVerified).unwrap();
    assert_eq!(attempt.lifecycle, Lifecycle::Closed);
}

#[test]
fn chaos_02_late_fill_after_terminal_cancel_stays_pending_until_settled() {
    let mut attempt = Attempt::new(100).unwrap();
    attempt.apply(Event::BeginSend).unwrap();
    attempt.apply(Event::Acknowledged).unwrap();
    attempt.apply(Event::TerminalReported).unwrap();
    attempt.apply(Event::CumulativeFilled(23)).unwrap();
    assert_eq!(attempt.effect, EconomicEffect::Partial);
    assert_eq!(attempt.settlement, Settlement::Pending);
    assert_eq!(attempt.lifecycle, Lifecycle::TerminalReported);
    assert!(attempt.holds_slot());
    // Same cumulative quantity from duplicate REST/socket update is idempotent.
    attempt.apply(Event::CumulativeFilled(23)).unwrap();
    assert_eq!(attempt.filled_quanta, 23);
    let previous = attempt;
    assert_eq!(attempt.apply(Event::CumulativeFilled(22)), Err(OrderError::FillRegression));
    assert_eq!(attempt, previous);
    attempt.apply(Event::SettlementVerified).unwrap();
    assert!(!attempt.holds_slot());
}

#[test]
fn chaos_03_transport_prebyte_failure_is_bounded_not_unlimited() {
    let mut attempt = Attempt::new(7).unwrap();
    for _ in 0..2 {
        attempt.apply(Event::BeginSend).unwrap();
        attempt.apply(Event::TransportFailed(FailureStage::BeforeFirstByte)).unwrap();
    }
    assert_eq!(attempt.lifecycle, Lifecycle::NotSent);
    assert!(!attempt.can_retry_same_identity());
    assert_eq!(attempt.apply(Event::BeginSend), Err(OrderError::RetryForbidden));
}

#[test]
fn chaos_04_overfill_and_premature_settlement_do_not_change_state() {
    let mut attempt = Attempt::new(12).unwrap();
    attempt.apply(Event::BeginSend).unwrap();
    attempt.apply(Event::Acknowledged).unwrap();
    let before = attempt;
    assert_eq!(attempt.apply(Event::CumulativeFilled(13)), Err(OrderError::InvalidQuantity));
    assert_eq!(attempt, before);
    assert_eq!(attempt.apply(Event::SettlementVerified), Err(OrderError::IllegalTransition));
    assert_eq!(attempt, before);
}

#[test]
fn chaos_05_cross_asset_protective_exit_is_independent_of_entry() {
    let mut slots = Slots::default();
    slots.try_hold("main", "BTCUSDT", true, false).unwrap();
    assert_eq!(slots.try_hold("main", "ETHUSDT", true, false), Err(SlotError::Conflict));
    assert!(slots.try_hold("main", "ETHUSDT", false, true).is_ok());
    assert_eq!(slots.try_hold("main", "BTCUSDT", false, true), Err(SlotError::Conflict));
    assert_eq!(slots.try_hold("main", "XRPUSDT", false, false), Err(SlotError::UnverifiedExit));
    assert!(slots.entry_allowed("credit-account", "BTCUSDT"));
}

#[test]
fn chaos_06_restart_always_disarmed_even_if_old_run_halted() {
    use exec_core::{Mode, State, StopCommand, StopRequest, step};
    let (old, _) = step(State::new(5), StopRequest {
        runtime_epoch: 5, command: StopCommand::Halt,
    });
    assert_eq!(old.mode, Mode::Halted);
    let restart = State::new(6);
    assert_eq!(restart.mode, Mode::Disarmed);
    let (unchanged, stale) = step(restart, StopRequest {
        runtime_epoch: 5, command: StopCommand::PauseEntries,
    });
    assert_eq!(unchanged, restart);
    assert!(matches!(stale, exec_core::StopResult::StaleRuntime { .. }));
}

#[test]
fn chaos_07_conflicting_before_byte_failure_cannot_erase_observed_fill() {
    let mut attempt = Attempt::new(10).unwrap();
    attempt.apply(Event::BeginSend).unwrap();
    // A late venue feed proves execution could have occurred. It is unsafe
    // to classify the same attempt as definitively NOT_SENT afterward.
    attempt.apply(Event::CumulativeFilled(4)).unwrap();
    let prior = attempt;
    assert_eq!(attempt.apply(Event::TransportFailed(FailureStage::BeforeFirstByte)),
               Err(OrderError::IllegalTransition));
    assert_eq!(attempt, prior);
    assert!(attempt.holds_slot());
    assert_eq!(attempt.apply(Event::BeginSend), Err(OrderError::RetryForbidden));
}
