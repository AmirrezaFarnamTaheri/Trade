//! C-series pure admission *advice*, not an Executor permission or venue POST.
//!
//! Callers may assert that a method or T1 approval was verified, but a plain
//! Rust value carries no principal/credential proof. No combination of these
//! booleans yields funded authority. The separate restricted service must
//! authenticate and re-evaluate each money action with durable reservations.
use crate::Mode;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Blocker {
    StaleRuntime,
    Halted,
    EntriesPaused,
    ExitNotPreauthorized,
    InvalidQuantity,
    UnknownOrder,
    Unreconciled,
    UncertifiedMethod,
    StaleQuote,
    VenueUnavailable,
    ExceededCap,
    InsufficientQuantity,
    CredentialIntegrity,
    MissingOperatorConsent,
    MissingExecutorAuthority,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Advisory {
    pub blocker: Option<Blocker>,
    /// Deliberately always false; no authority token exists in the pure model.
    pub funded_authority: bool,
}

impl Advisory {
    fn blocked(reason: Blocker) -> Self {
        Self { blocker: Some(reason), funded_authority: false }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EntryCheck {
    pub current_epoch: u64,
    pub proposal_epoch: u64,
    pub stop_mode: Mode,
    pub requested_quote_quanta: u64,
    pub verified_available_quote_quanta: u64,
    pub per_order_cap_quanta: u64,
    pub session_remaining_quanta: u64,
    pub account_reconciled: bool,
    pub quote_fresh: bool,
    pub venue_open: bool,
    pub method_certified: bool,
    pub operator_approval_verified: bool,
    pub has_unknown_order: bool,
}

/// Preflight vetoes are useful even before real T1/T2 attestation is built.
/// A DISARMED startup cannot send, even if every asserted value is true.
pub fn assess_entry(c: EntryCheck) -> Advisory {
    use Blocker::*;
    if c.current_epoch == 0 || c.proposal_epoch != c.current_epoch {
        return Advisory::blocked(StaleRuntime);
    }
    if c.stop_mode == Mode::Halted {
        return Advisory::blocked(Halted);
    }
    if matches!(c.stop_mode, Mode::Paused | Mode::ExitOnly) {
        return Advisory::blocked(EntriesPaused);
    }
    if c.has_unknown_order {
        return Advisory::blocked(UnknownOrder);
    }
    if !c.account_reconciled {
        return Advisory::blocked(Unreconciled);
    }
    if !c.method_certified {
        return Advisory::blocked(UncertifiedMethod);
    }
    if !c.venue_open {
        return Advisory::blocked(VenueUnavailable);
    }
    if !c.quote_fresh {
        return Advisory::blocked(StaleQuote);
    }
    if c.requested_quote_quanta == 0 {
        return Advisory::blocked(InvalidQuantity);
    }
    if c.requested_quote_quanta > c.per_order_cap_quanta
        || c.requested_quote_quanta > c.session_remaining_quanta
    {
        return Advisory::blocked(ExceededCap);
    }
    if c.requested_quote_quanta > c.verified_available_quote_quanta {
        return Advisory::blocked(InsufficientQuantity);
    }
    if !c.operator_approval_verified {
        return Advisory::blocked(MissingOperatorConsent);
    }
    Advisory::blocked(MissingExecutorAuthority)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ExitCheck {
    pub current_epoch: u64,
    pub proposal_epoch: u64,
    pub stop_mode: Mode,
    pub requested_base_quanta: u64,
    pub independently_verified_base_quanta: u64,
    pub same_instrument_unresolved: bool,
    /// An entry in ANOTHER instrument is not a protective-exit veto.
    pub other_instrument_entry_unresolved: bool,
    pub venue_open: bool,
    pub quote_fresh: bool,
    pub method_certified: bool,
    pub credential_integrity_verified: bool,
}

pub fn assess_exit(c: ExitCheck) -> Advisory {
    use Blocker::*;
    if c.current_epoch == 0 || c.proposal_epoch != c.current_epoch {
        return Advisory::blocked(StaleRuntime);
    }
    if c.stop_mode == Mode::Halted {
        return Advisory::blocked(Halted);
    }
    if c.stop_mode != Mode::ExitOnly {
        return Advisory::blocked(ExitNotPreauthorized);
    }
    if !c.credential_integrity_verified {
        return Advisory::blocked(CredentialIntegrity);
    }
    if c.same_instrument_unresolved {
        return Advisory::blocked(UnknownOrder);
    }
    if !c.method_certified {
        return Advisory::blocked(UncertifiedMethod);
    }
    if !c.venue_open {
        return Advisory::blocked(VenueUnavailable);
    }
    if !c.quote_fresh {
        return Advisory::blocked(StaleQuote);
    }
    if c.requested_base_quanta == 0 {
        return Advisory::blocked(InvalidQuantity);
    }
    if c.requested_base_quanta > c.independently_verified_base_quanta {
        return Advisory::blocked(InsufficientQuantity);
    }
    // No boolean supplied by an unprivileged process grants funded access.
    Advisory::blocked(MissingExecutorAuthority)
}
