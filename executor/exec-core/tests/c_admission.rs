//! C2/C3 pure money-core preflight is advisory; real T1/T2 and POST are absent.
use exec_core::c_admission::{
    assess_entry, assess_exit, Blocker, EntryCheck, ExitCheck,
};
use exec_core::Mode;

fn entry() -> EntryCheck {
    EntryCheck {
        current_epoch: 7, proposal_epoch: 7, stop_mode: Mode::Disarmed,
        requested_quote_quanta: 100, verified_available_quote_quanta: 500,
        per_order_cap_quanta: 200, session_remaining_quanta: 300,
        account_reconciled: true, quote_fresh: true,
        venue_open: true, method_certified: true,
        operator_approval_verified: true, has_unknown_order: false,
    }
}

#[test]
fn all_positive_c2_inputs_remain_nonfunded_until_separate_service_authority() {
    let report = assess_entry(entry());
    assert!(!report.funded_authority);
    // The pure core cannot authenticate that an asserted T1 approval is real.
    assert_eq!(report.blocker, Some(Blocker::MissingExecutorAuthority));
}

#[test]
fn pending_unknown_missing_certification_or_stale_epoch_always_veto() {
    let mut c = entry();
    c.has_unknown_order = true;
    assert_eq!(assess_entry(c).blocker, Some(Blocker::UnknownOrder));
    c = entry(); c.proposal_epoch = 6;
    assert_eq!(assess_entry(c).blocker, Some(Blocker::StaleRuntime));
    c = entry(); c.method_certified = false;
    assert_eq!(assess_entry(c).blocker, Some(Blocker::UncertifiedMethod));
    c = entry(); c.account_reconciled = false;
    assert_eq!(assess_entry(c).blocker, Some(Blocker::Unreconciled));
    c = entry(); c.verified_available_quote_quanta = 99;
    assert_eq!(assess_entry(c).blocker, Some(Blocker::InsufficientQuantity));
    c = entry(); c.requested_quote_quanta = 201;
    assert_eq!(assess_entry(c).blocker, Some(Blocker::ExceededCap));
}

fn exit() -> ExitCheck {
    ExitCheck {
        current_epoch: 7, proposal_epoch: 7,
        stop_mode: Mode::ExitOnly, requested_base_quanta: 10,
        independently_verified_base_quanta: 12,
        same_instrument_unresolved: false, other_instrument_entry_unresolved: true,
        venue_open: true, quote_fresh: true, method_certified: true,
        credential_integrity_verified: true,
    }
}

#[test]
fn protective_exit_skips_entry_only_gates_but_has_no_funded_token() {
    let result = assess_exit(exit());
    assert_eq!(result.blocker, Some(Blocker::MissingExecutorAuthority));
    assert!(!result.funded_authority);
}

#[test]
fn protective_exit_never_ignores_quantity_window_or_same_asset_order() {
    let mut e = exit();
    e.requested_base_quanta = 13;
    assert_eq!(assess_exit(e).blocker, Some(Blocker::InsufficientQuantity));
    e = exit(); e.same_instrument_unresolved = true;
    assert_eq!(assess_exit(e).blocker, Some(Blocker::UnknownOrder));
    e = exit(); e.venue_open = false;
    assert_eq!(assess_exit(e).blocker, Some(Blocker::VenueUnavailable));
    e = exit(); e.stop_mode = Mode::Halted;
    assert_eq!(assess_exit(e).blocker, Some(Blocker::Halted));
    e = exit(); e.credential_integrity_verified = false;
    assert_eq!(assess_exit(e).blocker, Some(Blocker::CredentialIntegrity));
    e = exit(); e.proposal_epoch = 6;
    assert_eq!(assess_exit(e).blocker, Some(Blocker::StaleRuntime));
}
