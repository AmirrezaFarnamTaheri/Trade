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
    Denied,   // local gate: no venue request
    Rejected, // explicit venue refusal, still requires settlement evidence
    Closed,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EconomicEffect { None, NoneObserved, Partial, Full, Unverified }
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Settlement { Unverified, Pending, Anomaly, Verified, Settled }
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
    Denied,
    VenueRejected,
    SettlementAnomaly,
    AnomalyReconciled { expected_available_quanta: u64, observed_available_quanta: u64 },
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrderError { InvalidQuantity, RetryForbidden, IllegalTransition, FillRegression, UnreconciledAnomaly }
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Attempt {
    pub requested_quanta: u64,
    pub filled_quanta: u64,
    pub lifecycle: Lifecycle,
    pub effect: EconomicEffect,
    pub settlement: Settlement,
    pub attempts: u8,
    anomaly_reconciled: bool,
}
impl Attempt {
    pub fn new(requested_quanta: u64) -> Result<Self, OrderError> {
        if requested_quanta == 0 { return Err(OrderError::InvalidQuantity); }
        Ok(Self { requested_quanta, filled_quanta: 0,
            lifecycle: Lifecycle::IntentLogged, effect: EconomicEffect::None,
            settlement: Settlement::Unverified, attempts: 0,
            anomaly_reconciled: false })
    }
    pub fn lifecycle(&self) -> Lifecycle { self.lifecycle }
    pub fn effect(&self) -> EconomicEffect { self.effect }
    pub fn settlement(&self) -> Settlement { self.settlement }
    /// Safe transport-only same-client-ID retry, at most once, before a first
    /// request byte. The caller must still retain the original durable intent.
    pub fn can_retry_same_identity(&self) -> bool {
        self.lifecycle == Lifecycle::NotSent && self.attempts == 1
    }
    pub fn holds_slot(&self) -> bool {
        !matches!(self.lifecycle, Lifecycle::Closed | Lifecycle::Denied)
    }
    pub fn apply(&mut self, event: Event) -> Result<(), OrderError> {
        use Event::*;
        // Copy-then-commit: invalid transitions never partially alter state.
        let mut next = *self;
        match event {
            Denied => {
                if next.lifecycle != Lifecycle::IntentLogged || next.attempts != 0 {
                    return Err(OrderError::IllegalTransition);
                }
                next.lifecycle = Lifecycle::Denied;
                next.effect = EconomicEffect::NoneObserved;
            }
            VenueRejected => {
                if !matches!(next.lifecycle, Lifecycle::Submitting | Lifecycle::Unknown)
                    || next.filled_quanta != 0 {
                    return Err(OrderError::IllegalTransition);
                }
                next.lifecycle = Lifecycle::Rejected;
                next.effect = EconomicEffect::NoneObserved;
                next.settlement = Settlement::Pending;
            }
            SettlementAnomaly => {
                if matches!(next.lifecycle, Lifecycle::IntentLogged | Lifecycle::NotSent
                    | Lifecycle::Denied | Lifecycle::Closed) {
                    return Err(OrderError::IllegalTransition);
                }
                next.settlement = Settlement::Anomaly;
                next.anomaly_reconciled = false;
            }
            AnomalyReconciled { expected_available_quanta, observed_available_quanta } => {
                if next.settlement != Settlement::Anomaly {
                    return Err(OrderError::IllegalTransition);
                }
                if expected_available_quanta != observed_available_quanta {
                    return Err(OrderError::UnreconciledAnomaly);
                }
                next.settlement = Settlement::Pending;
                next.anomaly_reconciled = true;
            }
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
                if matches!(next.lifecycle, Lifecycle::IntentLogged | Lifecycle::NotSent
                    | Lifecycle::Denied | Lifecycle::Rejected | Lifecycle::Closed) {
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
                    if next.settlement != Settlement::Anomaly {
                        next.settlement = Settlement::Pending;
                    }
                }
            }
            TerminalReported => match next.lifecycle {
                Lifecycle::Acknowledged | Lifecycle::Working | Lifecycle::Unknown | Lifecycle::Submitting =>
                    next.lifecycle = Lifecycle::TerminalReported,
                _ => return Err(OrderError::IllegalTransition),
            },
            SettlementVerified => {
                if !matches!(next.lifecycle, Lifecycle::TerminalReported | Lifecycle::Rejected)
                    || next.effect == EconomicEffect::Unverified
                    || next.settlement == Settlement::Anomaly
                {
                    return Err(OrderError::IllegalTransition);
                }
                next.settlement = if next.anomaly_reconciled {
                    Settlement::Settled
                } else {
                    Settlement::Verified
                };
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


// The following exact-quanta book is an offline B2 admission model, NOT
// the service's persistent spending authority. All balances have explicit
// accounts, assets and monotonic observation sequences. No float units.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ReservationError {
    InvalidEvidence,
    InsufficientAvailable,
    DuplicateIntent,
    OrderNotFresh,
    OrderNotSettled,
    StaleBalance,
    StillLocked,
    BalanceMismatch,
    UnknownIntent,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BalanceSnapshot {
    pub account: String,
    pub asset: String,
    pub available_quanta: u64,
    pub sequence: u64,
}
fn valid_name(value: &str) -> bool {
    !value.is_empty() && value.len() <= 96 &&
        value.bytes().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_' | b':' | b'.'))
}
impl BalanceSnapshot {
    pub fn new(account: &str, asset: &str, available_quanta: u64, sequence: u64)
        -> Result<Self, ReservationError>
    {
        if !valid_name(account) || !valid_name(asset) || sequence == 0 {
            return Err(ReservationError::InvalidEvidence);
        }
        Ok(Self { account: account.into(), asset: asset.into(), available_quanta, sequence })
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SettlementEvidence {
    pub account: String,
    pub asset: String,
    pub sequence: u64,
    pub complete: bool,
    pub locked_quanta: u64,
    pub spent_quanta: u64,
    pub available_quanta: u64,
}
impl SettlementEvidence {
    #[allow(clippy::too_many_arguments)]
    pub fn new(account: &str, asset: &str, sequence: u64, complete: bool,
        locked_quanta: u64, spent_quanta: u64, available_quanta: u64)
        -> Result<Self, ReservationError>
    {
        if !valid_name(account) || !valid_name(asset) || sequence == 0 || !complete {
            return Err(ReservationError::InvalidEvidence);
        }
        Ok(Self {
            account: account.into(), asset: asset.into(), sequence, complete,
            locked_quanta, spent_quanta, available_quanta,
        })
    }
}
#[derive(Clone, Debug)]
struct LocalReservation {
    intent: String,
    account: String,
    asset: String,
    quanta: u64,
    initial_available: u64,
    snapshot_seq: u64,
}
#[derive(Default, Debug)]
pub struct ReservationBook {
    entries: Vec<LocalReservation>,
}
impl ReservationBook {
    pub fn reserved(&self, account: &str, asset: &str) -> u64 {
        self.entries.iter().filter(|e| e.account == account && e.asset == asset)
            .map(|e| e.quanta).sum()
    }
    pub fn reserve(&mut self, intent: &str, account: &str, asset: &str,
        quanta: u64, snapshot: &BalanceSnapshot, order: &Attempt)
        -> Result<(), ReservationError>
    {
        if !valid_name(intent) || quanta == 0 || snapshot.account != account
            || snapshot.asset != asset || snapshot.sequence == 0 {
            return Err(ReservationError::InvalidEvidence);
        }
        if self.entries.iter().any(|e| e.intent == intent) {
            return Err(ReservationError::DuplicateIntent);
        }
        if order.lifecycle != Lifecycle::IntentLogged || order.attempts != 0 {
            return Err(ReservationError::OrderNotFresh);
        }
        let after = self.reserved(account, asset)
            .checked_add(quanta).ok_or(ReservationError::InsufficientAvailable)?;
        if after > snapshot.available_quanta {
            return Err(ReservationError::InsufficientAvailable);
        }
        self.entries.push(LocalReservation {
            intent: intent.into(), account: account.into(), asset: asset.into(),
            quanta, initial_available: snapshot.available_quanta,
            snapshot_seq: snapshot.sequence,
        });
        Ok(())
    }
    pub fn release_settled(&mut self, intent: &str, order: &Attempt,
        evidence: &SettlementEvidence) -> Result<(), ReservationError>
    {
        let reservation = self.entries.iter().find(|e| e.intent == intent)
            .ok_or(ReservationError::UnknownIntent)?;
        if order.lifecycle != Lifecycle::Closed ||
            !matches!(order.settlement, Settlement::Settled | Settlement::Verified) {
            return Err(ReservationError::OrderNotSettled);
        }
        if evidence.account != reservation.account || evidence.asset != reservation.asset
            || !evidence.complete {
            return Err(ReservationError::InvalidEvidence);
        }
        if evidence.sequence <= reservation.snapshot_seq {
            return Err(ReservationError::StaleBalance);
        }
        if evidence.locked_quanta != 0 {
            return Err(ReservationError::StillLocked);
        }
        if evidence.spent_quanta > reservation.quanta ||
            evidence.available_quanta.checked_add(evidence.spent_quanta)
                != Some(reservation.initial_available) {
            return Err(ReservationError::BalanceMismatch);
        }
        self.entries.retain(|e| e.intent != intent);
        Ok(())
    }
}
