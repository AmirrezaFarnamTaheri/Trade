//! Offline B2 recovery state machine: no network, clock, keys, or side effects.
//! The venue's status strings must be verified before mapping them to these
//! evidence events. Missing a list row is never an absence proof.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Lifecycle {
    IntentLogged,
    Submitting,
    NotSent,
    Acknowledged,
    Working,
    Unknown,
    TerminalReported,
    Closed,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EconomicEffect { None, Partial, Full, Unverified }
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Settlement { Unverified, Pending, Verified }
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FailureStage { BeforeFirstByte, AfterFirstByte }
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Event {
    BeginSend,
    TransportFailed(FailureStage),
    Acknowledged,
    Working,
    MissingFromList,
    CumulativeFilled(u64),
    TerminalReported,
    SettlementVerified,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderError { InvalidQuantity, RetryForbidden, IllegalTransition, FillRegression }
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Attempt {
    pub requested_quanta: u64,
    pub filled_quanta: u64,
    pub lifecycle: Lifecycle,
    pub effect: EconomicEffect,
    pub settlement: Settlement,
    pub attempts: u8,
}
impl Attempt {
    pub fn new(requested_quanta: u64) -> Result<Self, OrderError> {
        if requested_quanta == 0 { return Err(OrderError::InvalidQuantity); }
        Ok(Self { requested_quanta, filled_quanta: 0,
            lifecycle: Lifecycle::IntentLogged, effect: EconomicEffect::None,
            settlement: Settlement::Unverified, attempts: 0 })
    }
    /// Safe transport-only same-client-ID retry, at most once, before a first
    /// request byte. The caller must still retain the original durable intent.
    pub fn can_retry_same_identity(&self) -> bool {
        self.lifecycle == Lifecycle::NotSent && self.attempts == 1
    }
    pub fn holds_slot(&self) -> bool { self.lifecycle != Lifecycle::Closed }
    pub fn apply(&mut self, event: Event) -> Result<(), OrderError> {
        use Event::*;
        // Copy-then-commit: invalid transitions never partially alter state.
        let mut next = *self;
        match event {
            BeginSend => match next.lifecycle {
                Lifecycle::IntentLogged if next.attempts == 0 => {
                    next.lifecycle = Lifecycle::Submitting; next.attempts = 1;
                }
                Lifecycle::NotSent if next.can_retry_same_identity() => {
                    next.lifecycle = Lifecycle::Submitting; next.attempts = 2;
                }
                _ => return Err(OrderError::RetryForbidden),
            },
            TransportFailed(stage) => {
                if next.lifecycle != Lifecycle::Submitting { return Err(OrderError::IllegalTransition); }
                match stage {
                    FailureStage::BeforeFirstByte => {
                        // Any credible venue-side fill contradicts a proven
                        // no-byte dispatch. Never restore retry authority.
                        if next.filled_quanta != 0 || next.effect != EconomicEffect::None {
                            return Err(OrderError::IllegalTransition);
                        }
                        next.lifecycle = Lifecycle::NotSent;
                    }
                    FailureStage::AfterFirstByte => {
                        next.lifecycle = Lifecycle::Unknown;
                        if next.filled_quanta == 0 { next.effect = EconomicEffect::Unverified; }
                    }
                }
            }
            Acknowledged => match next.lifecycle {
                Lifecycle::Submitting | Lifecycle::Unknown => next.lifecycle = Lifecycle::Acknowledged,
                _ => return Err(OrderError::IllegalTransition),
            },
            Working => match next.lifecycle {
                Lifecycle::Acknowledged | Lifecycle::Unknown => next.lifecycle = Lifecycle::Working,
                _ => return Err(OrderError::IllegalTransition),
            },
            MissingFromList => {
                // Unfiltered/partial/paginated GETs never prove absence.
            }
            CumulativeFilled(quantity) => {
                if matches!(next.lifecycle, Lifecycle::IntentLogged | Lifecycle::NotSent | Lifecycle::Closed) {
                    return Err(OrderError::IllegalTransition);
                }
                if quantity < next.filled_quanta { return Err(OrderError::FillRegression); }
                if quantity > next.requested_quanta { return Err(OrderError::InvalidQuantity); }
                next.filled_quanta = quantity;
                if quantity > 0 {
                    next.effect = if quantity == next.requested_quanta {
                        EconomicEffect::Full
                    } else {
                        EconomicEffect::Partial
                    };
                    next.settlement = Settlement::Pending;
                }
            }
            TerminalReported => match next.lifecycle {
                Lifecycle::Acknowledged | Lifecycle::Working | Lifecycle::Unknown | Lifecycle::Submitting =>
                    next.lifecycle = Lifecycle::TerminalReported,
                _ => return Err(OrderError::IllegalTransition),
            },
            SettlementVerified => {
                if next.lifecycle != Lifecycle::TerminalReported
                    || next.effect == EconomicEffect::Unverified {
                    return Err(OrderError::IllegalTransition);
                }
                next.settlement = Settlement::Verified;
                next.lifecycle = Lifecycle::Closed;
            }
        }
        *self = next;
        Ok(())
    }
}

/// Slots cannot grant funded execution; they only veto conflicting simulated
/// intents. Holding/releasing a slot requires independently verified evidence.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SlotError { Conflict, UnverifiedExit, Unsettled }
#[derive(Debug, Default)]
pub struct Slots {
    active: Vec<(String, String, bool)>,
}
impl Slots {
    /// Admission and slot acquisition are one indivisible operation.
    /// This is a pure model; the final Executor must bind verified balance
    /// evidence and durable intent to this decision before any venue POST.
    pub fn try_hold(
        &mut self, account: &str, instrument: &str, entry: bool, verified_base: bool,
    ) -> Result<(), SlotError> {
        if entry {
            if !self.entry_allowed(account, instrument) { return Err(SlotError::Conflict); }
        } else {
            if !verified_base { return Err(SlotError::UnverifiedExit); }
            if !self.exit_allowed(account, instrument, true) { return Err(SlotError::Conflict); }
        }
        self.active.push((account.to_owned(), instrument.to_owned(), entry));
        Ok(())
    }
    /// Never silently free a reservation for an UNKNOWN or terminal-but-
    /// unsettled attempt. The caller must bring reconciliation evidence.
    pub fn release_verified(
        &mut self, account: &str, instrument: &str, settled: bool,
    ) -> Result<(), SlotError> {
        if !settled { return Err(SlotError::Unsettled); }
        self.active.retain(|(a, i, _)| a != account || i != instrument);
        Ok(())
    }
    pub fn entry_allowed(&self, account: &str, instrument: &str) -> bool {
        !self.active.iter().any(|(a, i, entry)| {
            a == account && (*entry || i == instrument)
        })
    }
    pub fn exit_allowed(&self, account: &str, instrument: &str, verified_base: bool) -> bool {
        verified_base && !self.active.iter().any(|(a, i, _)| a == account && i == instrument)
    }
}
