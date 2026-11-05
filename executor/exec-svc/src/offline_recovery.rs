//! B2 offline, durably logged order identity and evidence projection.
//! No transport or funded authority: restarting this journal never submits an order.
//! All records are appended to exec-store's FULL-synchronous hash-chained ledger
//! before an Attempt projection changes. Unknown bytes or illegal replay fail closed.
use exec_core::orders::{
    Attempt, BalanceSnapshot, Event, FailureStage, OrderError, ReservationBook, ReservationError,
    SettlementEvidence,
};
use exec_store::{Ledger, LedgerError};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

const MAGIC: &[u8; 5] = b"TGOR1";
const CREATE: u8 = 1;
const EVIDENCE: u8 = 2;
const HOLD: u8 = 3;
const RELEASE_DENIED: u8 = 4;
const RELEASE_SETTLED: u8 = 5;
const EXECUTION: u8 = 6;
const EXECUTION_SETTLED: u8 = 7;
const CREDENTIAL: u8 = 8;
const CEILING: u8 = 9;
const APPROVAL: u8 = 10;
const REVOKE_APPROVAL: u8 = 11;
const PREPARE_INTENT: u8 = 12;
const RESERVE_REVIEW: u8 = 13;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OperatorApproval {
    pub ticket: exec_ipc::review::Ticket,
    pub principal: String,
    pub logon: String,
    pub recorded_at_ms: u64,
    pub request_id: [u8; 16],
    pub mode: exec_ipc::StopMode,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ApprovalView {
    pub sequence: u64,
    pub approval: OperatorApproval,
    pub revoked_at_ms: Option<u64>,
    pub prepared_at_ms: Option<u64>,
}
/// Consumes a review for durable preparation only; never reserves funds or permits transport.
#[derive(Clone, Debug)]
pub struct IntentPreparation {
    pub client_id: String,
    pub expected_sequence: u64,
    pub principal: String,
    pub logon: String,
    pub runtime_epoch: u64,
    pub credential_generation: [u8; 16],
    pub recorded_at_ms: u64,
    pub request_id: [u8; 16],
    pub mode: exec_ipc::StopMode,
}
impl IntentPreparation {
    fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
        validate_review_actor(
            &self.principal,
            &self.logon,
            self.recorded_at_ms,
            self.request_id,
        )?;
        if self.expected_sequence == 0
            || self.runtime_epoch == 0
            || self.credential_generation == [0; 16]
        {
            return Err(RecoveryError::InvalidIdentity);
        }
        let mut raw = MAGIC.to_vec();
        raw.push(PREPARE_INTENT);
        add_name(&mut raw, &self.client_id)?;
        raw.extend_from_slice(&self.expected_sequence.to_be_bytes());
        add_name(&mut raw, &self.principal)?;
        add_name(&mut raw, &self.logon)?;
        raw.extend_from_slice(&self.runtime_epoch.to_be_bytes());
        raw.extend_from_slice(&self.credential_generation);
        raw.extend_from_slice(&self.recorded_at_ms.to_be_bytes());
        raw.extend_from_slice(&self.request_id);
        raw.push(self.mode as u8);
        Ok(raw)
    }
}
#[derive(Clone, Debug)]
pub struct ApprovalRevocation {
    pub client_id: String,
    pub expected_sequence: u64,
    pub principal: String,
    pub logon: String,
    pub recorded_at_ms: u64,
    pub request_id: [u8; 16],
}
impl OperatorApproval {
    fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
        let ticket = self
            .ticket
            .encode()
            .map_err(|_| RecoveryError::InvalidIdentity)?;
        validate_review_actor(
            &self.principal,
            &self.logon,
            self.recorded_at_ms,
            self.request_id,
        )?;
        let mut raw = MAGIC.to_vec();
        raw.push(APPROVAL);
        add_name(&mut raw, &self.ticket.client_id)?;
        raw.extend_from_slice(&ticket);
        add_name(&mut raw, &self.principal)?;
        add_name(&mut raw, &self.logon)?;
        raw.extend_from_slice(&self.recorded_at_ms.to_be_bytes());
        raw.extend_from_slice(&self.request_id);
        raw.push(self.mode as u8);
        Ok(raw)
    }
}
impl ApprovalRevocation {
    fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
        validate_review_actor(
            &self.principal,
            &self.logon,
            self.recorded_at_ms,
            self.request_id,
        )?;
        if self.expected_sequence == 0 {
            return Err(RecoveryError::InvalidIdentity);
        }
        let mut raw = MAGIC.to_vec();
        raw.push(REVOKE_APPROVAL);
        add_name(&mut raw, &self.client_id)?;
        raw.extend_from_slice(&self.expected_sequence.to_be_bytes());
        add_name(&mut raw, &self.principal)?;
        add_name(&mut raw, &self.logon)?;
        raw.extend_from_slice(&self.recorded_at_ms.to_be_bytes());
        raw.extend_from_slice(&self.request_id);
        Ok(raw)
    }
}
fn validate_review_actor(
    principal: &str,
    logon: &str,
    at: u64,
    id: [u8; 16],
) -> Result<(), RecoveryError> {
    if !principal.starts_with("S-1-")
        || !logon.starts_with("S-1-5-5-")
        || !valid_name(principal)
        || !valid_name(logon)
        || !principal
            .split('-')
            .skip(1)
            .chain(logon.split('-').skip(1))
            .all(|v| !v.is_empty() && v.bytes().all(|b| b.is_ascii_digit()))
        || at == 0
        || id == [0; 16]
    {
        return Err(RecoveryError::InvalidIdentity);
    }
    Ok(())
}
fn check_approval(
    current: Option<&(u64, CeilingChange)>,
    approvals: &BTreeMap<String, ApprovalView>,
    requests: &BTreeSet<[u8; 16]>,
    value: &OperatorApproval,
) -> Result<(), RecoveryError> {
    value.encode()?;
    let (sequence, limit) = current.ok_or(RecoveryError::InvalidIdentity)?;
    let ticket = &value.ticket;
    if requests.contains(&value.request_id) || approvals.contains_key(&ticket.client_id) {
        return Err(RecoveryError::DuplicateIdentity);
    }
    check_review_context(
        *sequence,
        limit,
        ticket,
        &value.principal,
        value.recorded_at_ms,
        value.mode,
    )
}
fn check_review_context(
    sequence: u64,
    limit: &CeilingChange,
    ticket: &exec_ipc::review::Ticket,
    principal: &str,
    at: u64,
    mode: exec_ipc::StopMode,
) -> Result<(), RecoveryError> {
    if ticket.ceiling_sequence != sequence
        || ticket.quote != limit.ceiling.currency
        || ticket.quote_epoch != limit.ceiling.unit_epoch
        || ticket.quote_decimals != limit.ceiling.decimals
        || principal != limit.operator_user
        || at < limit.recorded_at_ms
        || ticket.expires_at_ms <= at
        || ticket.expires_at_ms
            > at.checked_add(30000)
                .ok_or(RecoveryError::InvalidIdentity)?
        || mode == exec_ipc::StopMode::Halted
        || (ticket.buy && mode != exec_ipc::StopMode::Disarmed)
        || ticket.max_quote_debit > limit.ceiling.capital_quanta
    {
        return Err(RecoveryError::InvalidIdentity);
    }
    Ok(())
}
fn check_preparation(
    current: Option<&(u64, CeilingChange)>,
    approvals: &BTreeMap<String, ApprovalView>,
    requests: &BTreeSet<[u8; 16]>,
    value: &IntentPreparation,
) -> Result<(), RecoveryError> {
    check_review_action(current, approvals, requests, value, false)
}
fn check_review_action(
    current: Option<&(u64, CeilingChange)>,
    approvals: &BTreeMap<String, ApprovalView>,
    requests: &BTreeSet<[u8; 16]>,
    value: &IntentPreparation,
    prepared: bool,
) -> Result<(), RecoveryError> {
    value.encode()?;
    let saved = approvals
        .get(&value.client_id)
        .ok_or(RecoveryError::UnknownIdentity)?;
    let ticket = &saved.approval.ticket;
    if requests.contains(&value.request_id) {
        return Err(RecoveryError::DuplicateIdentity);
    }
    if saved.sequence != value.expected_sequence
        || saved.revoked_at_ms.is_some()
        || saved.prepared_at_ms.is_some() != prepared
        || saved.approval.principal != value.principal
        || saved.approval.logon != value.logon
        || value.runtime_epoch != ticket.runtime_epoch
        || value.credential_generation != ticket.credential_generation
        || value.recorded_at_ms
            < saved
                .prepared_at_ms
                .unwrap_or(saved.approval.recorded_at_ms)
    {
        return Err(RecoveryError::InvalidIdentity);
    }
    let (sequence, limit) = current.ok_or(RecoveryError::InvalidIdentity)?;
    check_review_context(
        *sequence,
        limit,
        ticket,
        &value.principal,
        value.recorded_at_ms,
        value.mode,
    )
}
fn check_revocation(
    approvals: &BTreeMap<String, ApprovalView>,
    requests: &BTreeSet<[u8; 16]>,
    value: &ApprovalRevocation,
) -> Result<(), RecoveryError> {
    // Revocation must remain possible after wall-clock regression; journal sequence orders it.
    value.encode()?;
    let current = approvals
        .get(&value.client_id)
        .ok_or(RecoveryError::UnknownIdentity)?;
    if requests.contains(&value.request_id) {
        return Err(RecoveryError::DuplicateIdentity);
    }
    if current.sequence != value.expected_sequence
        || current.revoked_at_ms.is_some()
        || current.approval.principal != value.principal
    {
        return Err(RecoveryError::InvalidIdentity);
    }
    Ok(())
}

/// Durable metadata, not a money permit. The service must authenticate the writer.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CeilingChange {
    pub ceiling: exec_ipc::ceiling::Ceiling,
    pub principal: String,
    pub logon: String,
    pub operator_user: String,
    pub recorded_at_ms: u64,
    pub request_id: [u8; 16],
    pub expected_sequence: u64,
}
impl CeilingChange {
    fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
        self.ceiling
            .validate()
            .map_err(|_| RecoveryError::InvalidIdentity)?;
        let sid = |s: &str| {
            s.starts_with("S-1-")
                && s.split('-')
                    .skip(1)
                    .all(|v| !v.is_empty() && v.parse::<u64>().is_ok())
        };
        if !sid(&self.principal)
            || !sid(&self.operator_user)
            || !sid(&self.logon)
            || !self.logon.starts_with("S-1-5-5-")
            || self.recorded_at_ms == 0
            || self.request_id == [0; 16]
        {
            return Err(RecoveryError::InvalidIdentity);
        }
        let mut raw = MAGIC.to_vec();
        raw.push(CEILING);
        add_name(&mut raw, "installation")?;
        add_name(&mut raw, &self.ceiling.currency)?;
        raw.extend_from_slice(&self.ceiling.unit_epoch.to_be_bytes());
        raw.push(self.ceiling.decimals);
        raw.extend_from_slice(&self.ceiling.capital_quanta.to_be_bytes());
        add_name(&mut raw, &self.principal)?;
        add_name(&mut raw, &self.logon)?;
        add_name(&mut raw, &self.operator_user)?;
        raw.extend_from_slice(&self.recorded_at_ms.to_be_bytes());
        raw.extend_from_slice(&self.request_id);
        raw.extend_from_slice(&self.expected_sequence.to_be_bytes());
        Ok(raw)
    }
}

fn check_ceiling(
    current: Option<&(u64, CeilingChange)>,
    ids: &BTreeSet<[u8; 16]>,
    next: &CeilingChange,
) -> Result<(), RecoveryError> {
    next.encode()?;
    if ids.contains(&next.request_id) {
        return Err(RecoveryError::DuplicateIdentity);
    }
    if next.expected_sequence != current.map_or(0, |(seq, _)| *seq)
        || current.is_some_and(|(_, old)| {
            old.ceiling.currency != next.ceiling.currency
                || old.ceiling.unit_epoch != next.ceiling.unit_epoch
                || old.ceiling.decimals != next.ceiling.decimals
                || old.operator_user != next.operator_user
                || old.recorded_at_ms > next.recorded_at_ms
        })
        || (next.principal == next.operator_user
            && next.ceiling.capital_quanta
                > current.map_or(0, |(_, old)| old.ceiling.capital_quanta))
    {
        return Err(RecoveryError::InvalidIdentity);
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CredentialPermission {
    Unverified,
}

/// Ciphertext identity only. This record never confers executor authority.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CredentialMetadata {
    pub generation: [u8; 16],
    pub ciphertext_digest: [u8; 32],
    pub permission: CredentialPermission,
}
impl CredentialMetadata {
    fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
        if self.generation == [0; 16] || self.ciphertext_digest == [0; 32] {
            return Err(RecoveryError::InvalidIdentity);
        }
        let mut raw = MAGIC.to_vec();
        raw.push(CREDENTIAL);
        add_name(&mut raw, "venue")?;
        raw.extend_from_slice(&self.generation);
        raw.extend_from_slice(&self.ciphertext_digest);
        raw.push(0); // No trusted venue permission contract exists.
        Ok(raw)
    }
}

#[derive(Debug)]
pub enum RecoveryError {
    Ledger(LedgerError),
    InvalidIdentity,
    DuplicateIdentity,
    UnknownIdentity,
    MalformedEvent,
    Order(OrderError),
    Reservation(ReservationError),
}
impl PartialEq for RecoveryError {
    fn eq(&self, other: &Self) -> bool {
        use RecoveryError::*;
        match (self, other) {
            (InvalidIdentity, InvalidIdentity)
            | (DuplicateIdentity, DuplicateIdentity)
            | (UnknownIdentity, UnknownIdentity)
            | (MalformedEvent, MalformedEvent) => true,
            (Order(a), Order(b)) => a == b,
            (Reservation(a), Reservation(b)) => a == b,
            _ => false,
        }
    }
}
impl From<LedgerError> for RecoveryError {
    fn from(e: LedgerError) -> Self {
        Self::Ledger(e)
    }
}

#[derive(Clone, Debug)]
pub struct ObservedIntent {
    pub admission_index: usize,
    pub account: String,
    pub asset: String,
    pub attempt: Attempt,
    pub execution: Option<ExecutionIdentity>,
    pub execution_settlement: Option<ExecutionSettlement>,
    /// Exact reviewed units/envelope; never reinterpret as legacy limit_price units.
    pub review_ticket: Option<exec_ipc::review::Ticket>,
}

struct ReviewedReservation {
    context: IntentPreparation,
    ticket: exec_ipc::review::Ticket,
    snapshot: BalanceSnapshot,
}
impl ReviewedReservation {
    fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
        let mut raw = self.context.encode()?;
        raw[MAGIC.len()] = RESERVE_REVIEW;
        raw.extend_from_slice(
            &self
                .ticket
                .encode()
                .map_err(|_| RecoveryError::InvalidIdentity)?,
        );
        raw.extend_from_slice(&self.snapshot.available_quanta.to_be_bytes());
        raw.extend_from_slice(&self.snapshot.sequence.to_be_bytes());
        Ok(raw)
    }
}
fn apply_review_reservation(
    current: Option<&(u64, CeilingChange)>,
    approvals: &BTreeMap<String, ApprovalView>,
    requests: &BTreeSet<[u8; 16]>,
    intents: &mut BTreeMap<String, ObservedIntent>,
    reservations: &mut ReservationBook,
    value: &ReviewedReservation,
) -> Result<(), RecoveryError> {
    check_review_action(current, approvals, requests, &value.context, true)?;
    let ticket = &approvals
        .get(&value.context.client_id)
        .unwrap()
        .approval
        .ticket;
    if value.ticket != *ticket || intents.contains_key(&ticket.client_id) {
        return Err(RecoveryError::InvalidIdentity);
    }
    let asset = if ticket.buy {
        &ticket.quote
    } else {
        &ticket.base
    };
    let quanta = if ticket.buy {
        ticket.max_quote_debit
    } else {
        ticket.quantity_quanta
    };
    let units = |value: &exec_ipc::review::Ticket| {
        if value.base == *asset {
            (value.base_epoch, value.base_decimals)
        } else {
            (value.quote_epoch, value.quote_decimals)
        }
    };
    if intents.iter().any(|(id, order)| {
        order.asset == *asset
            && (ticket.buy || order.account == ticket.account)
            && reservations.is_reserved(id)
            && order
                .review_ticket
                .as_ref()
                .is_none_or(|previous| units(previous) != units(ticket))
    }) {
        return Err(RecoveryError::InvalidIdentity);
    }
    if ticket.buy
        && reservations
            .total_reserved(asset)
            .and_then(|total| total.checked_add(quanta))
            .is_none_or(|sum| sum > current.unwrap().1.ceiling.capital_quanta)
    {
        return Err(RecoveryError::Reservation(
            ReservationError::InsufficientAvailable,
        ));
    }
    let attempt = Attempt::new(ticket.quantity_quanta).map_err(RecoveryError::Order)?;
    reservations
        .reserve(
            &ticket.client_id,
            &ticket.account,
            asset,
            quanta,
            &value.snapshot,
            &attempt,
        )
        .map_err(RecoveryError::Reservation)?;
    intents.insert(
        ticket.client_id.clone(),
        ObservedIntent {
            admission_index: intents.len(),
            account: ticket.account.clone(),
            asset: asset.clone(),
            attempt,
            execution: None,
            execution_settlement: None,
            review_ticket: Some(ticket.clone()),
        },
    );
    Ok(())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Side {
    Buy,
    Sell,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Purpose {
    Entry,
    Conversion,
    ProtectiveExit,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionIdentity {
    pub instrument: String,
    pub base: String,
    pub quote: String,
    pub side: Side,
    pub purpose: Purpose,
    pub method: String,
    pub approval: String,
    pub rules_version: String,
    pub runtime_epoch: u64,
    pub expires_at_ms: u64,
    /// Quote quanta per base quantum; the fake venue uses the same exact scale.
    pub limit_price: u64,
    pub max_quote_quanta: u64,
}
impl ExecutionIdentity {
    fn validate(&self) -> Result<(), RecoveryError> {
        for name in [
            &self.instrument,
            &self.base,
            &self.quote,
            &self.method,
            &self.approval,
            &self.rules_version,
        ] {
            if !valid_name(name) {
                return Err(RecoveryError::InvalidIdentity);
            }
        }
        if self.base == self.quote
            || self.instrument != format!("{}{}", self.base, self.quote)
            || self.runtime_epoch == 0
            || self.expires_at_ms == 0
            || self.limit_price == 0
            || self.max_quote_quanta == 0
            || (self.purpose == Purpose::ProtectiveExit && self.side != Side::Sell)
            || (self.purpose == Purpose::Entry && self.side != Side::Buy)
        {
            return Err(RecoveryError::InvalidIdentity);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExecutionSettlement {
    pub filled_quanta: u64,
    pub gross_quote_quanta: u64,
    pub fee_asset: String,
    pub fee_quanta: u64,
    pub balance: SettlementEvidence,
}

pub struct DurableOrderJournal {
    ledger: Ledger,
    intents: BTreeMap<String, ObservedIntent>,
    reservations: ReservationBook,
    records: usize,
    /// A request already in flight when the journal was reopened cannot be
    /// certified as never sent by this newly started process.
    recovered_inflight: BTreeSet<String>,
    recovered_cancels: BTreeSet<String>,
    credential: Option<CredentialMetadata>,
    ceiling: Option<(u64, CeilingChange)>,
    ceiling_requests: BTreeSet<[u8; 16]>,
    approvals: BTreeMap<String, ApprovalView>,
    approval_requests: BTreeSet<[u8; 16]>,
}
enum Record {
    ReviewedReservation(ReviewedReservation),
    PrepareIntent(IntentPreparation),
    Approval(OperatorApproval),
    RevokeApproval(ApprovalRevocation),
    Ceiling(CeilingChange),
    Credential(CredentialMetadata),
    Execution {
        id: String,
        account: String,
        quantity: u64,
        identity: ExecutionIdentity,
        reserved: u64,
        available: u64,
        sequence: u64,
    },
    ExecutionSettled {
        id: String,
        settlement: ExecutionSettlement,
    },
    Open {
        id: String,
        account: String,
        asset: String,
        quantity: u64,
    },
    Observation {
        id: String,
        event: Event,
    },
    Hold {
        id: String,
        account: String,
        asset: String,
        quanta: u64,
        available: u64,
        sequence: u64,
    },
    ReleaseDenied {
        id: String,
    },
    ReleaseSettled {
        id: String,
        account: String,
        asset: String,
        sequence: u64,
        complete: bool,
        locked: u64,
        spent: u64,
        available: u64,
    },
}
fn valid_name(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 96
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_' | b':' | b'.'))
}
fn add_name(data: &mut Vec<u8>, name: &str) -> Result<(), RecoveryError> {
    if !valid_name(name) {
        return Err(RecoveryError::InvalidIdentity);
    }
    data.push(u8::try_from(name.len()).map_err(|_| RecoveryError::InvalidIdentity)?);
    data.extend_from_slice(name.as_bytes());
    Ok(())
}
fn record_intent(
    id: &str,
    account: &str,
    asset: &str,
    quantity: u64,
) -> Result<Vec<u8>, RecoveryError> {
    if quantity == 0 {
        return Err(RecoveryError::Order(OrderError::InvalidQuantity));
    }
    let mut data = MAGIC.to_vec();
    data.push(CREATE);
    add_name(&mut data, id)?;
    add_name(&mut data, account)?;
    add_name(&mut data, asset)?;
    data.extend_from_slice(&quantity.to_be_bytes());
    Ok(data)
}
fn record_event(id: &str, event: Event) -> Result<Vec<u8>, RecoveryError> {
    let mut data = MAGIC.to_vec();
    data.push(EVIDENCE);
    add_name(&mut data, id)?;
    use Event::*;
    let tag = match event {
        BeginSend => 1,
        TransportFailed(FailureStage::BeforeFirstByte) => 2,
        TransportFailed(FailureStage::AfterFirstByte) => 3,
        Acknowledged => 4,
        Working => 5,
        MissingFromList => 6,
        CumulativeFilled(_) => 7,
        TerminalReported => 8,
        SettlementVerified => 9,
        Denied => 10,
        VenueRejected => 11,
        SettlementAnomaly => 12,
        AnomalyReconciled { .. } => 13,
        BeginCancel => 14,
        CancelTransportFailed(FailureStage::BeforeFirstByte) => 15,
        CancelTransportFailed(FailureStage::AfterFirstByte) => 16,
        CancelAcknowledged => 17,
    };
    data.push(tag);
    match event {
        CumulativeFilled(n) => data.extend_from_slice(&n.to_be_bytes()),
        AnomalyReconciled {
            expected_available_quanta,
            observed_available_quanta,
        } => {
            data.extend_from_slice(&expected_available_quanta.to_be_bytes());
            data.extend_from_slice(&observed_available_quanta.to_be_bytes());
        }
        _ => {}
    }
    Ok(data)
}
// Every reservation change is part of the SAME durable ledger as the
// attempt, not a second database that could commit or fail independently.
fn record_hold(
    id: &str,
    snapshot: &BalanceSnapshot,
    quanta: u64,
) -> Result<Vec<u8>, RecoveryError> {
    let mut data = MAGIC.to_vec();
    data.push(HOLD);
    add_name(&mut data, id)?;
    add_name(&mut data, &snapshot.account)?;
    add_name(&mut data, &snapshot.asset)?;
    for value in [quanta, snapshot.available_quanta, snapshot.sequence] {
        data.extend_from_slice(&value.to_be_bytes());
    }
    Ok(data)
}
fn record_release_denied(id: &str) -> Result<Vec<u8>, RecoveryError> {
    let mut data = MAGIC.to_vec();
    data.push(RELEASE_DENIED);
    add_name(&mut data, id)?;
    Ok(data)
}
fn record_release_settled(
    id: &str,
    evidence: &SettlementEvidence,
) -> Result<Vec<u8>, RecoveryError> {
    let mut data = MAGIC.to_vec();
    data.push(RELEASE_SETTLED);
    add_name(&mut data, id)?;
    add_name(&mut data, &evidence.account)?;
    add_name(&mut data, &evidence.asset)?;
    data.extend_from_slice(&evidence.sequence.to_be_bytes());
    data.push(u8::from(evidence.complete));
    for value in [
        evidence.locked_quanta,
        evidence.spent_quanta,
        evidence.available_quanta,
    ] {
        data.extend_from_slice(&value.to_be_bytes());
    }
    Ok(data)
}

fn record_execution(
    id: &str,
    account: &str,
    quantity: u64,
    identity: &ExecutionIdentity,
    reserved: u64,
    snapshot: &BalanceSnapshot,
) -> Result<Vec<u8>, RecoveryError> {
    identity.validate()?;
    let asset = if identity.side == Side::Buy {
        &identity.quote
    } else {
        &identity.base
    };
    if quantity == 0 || reserved == 0 || snapshot.account != account || snapshot.asset != *asset {
        return Err(RecoveryError::InvalidIdentity);
    }
    let mut data = MAGIC.to_vec();
    data.push(EXECUTION);
    for name in [
        id,
        account,
        &identity.instrument,
        &identity.base,
        &identity.quote,
        &identity.method,
        &identity.approval,
        &identity.rules_version,
    ] {
        add_name(&mut data, name)?;
    }
    data.push(match identity.side {
        Side::Buy => 0,
        Side::Sell => 1,
    });
    data.push(match identity.purpose {
        Purpose::Entry => 0,
        Purpose::Conversion => 1,
        Purpose::ProtectiveExit => 2,
    });
    for value in [
        quantity,
        identity.runtime_epoch,
        identity.expires_at_ms,
        identity.limit_price,
        identity.max_quote_quanta,
        reserved,
        snapshot.available_quanta,
        snapshot.sequence,
    ] {
        data.extend_from_slice(&value.to_be_bytes());
    }
    Ok(data)
}
fn record_execution_settlement(
    id: &str,
    settlement: &ExecutionSettlement,
) -> Result<Vec<u8>, RecoveryError> {
    let mut data = MAGIC.to_vec();
    data.push(EXECUTION_SETTLED);
    for name in [
        id,
        &settlement.fee_asset,
        &settlement.balance.account,
        &settlement.balance.asset,
    ] {
        add_name(&mut data, name)?;
    }
    if !settlement.balance.complete {
        return Err(RecoveryError::Reservation(
            ReservationError::InvalidEvidence,
        ));
    }
    for value in [
        settlement.filled_quanta,
        settlement.gross_quote_quanta,
        settlement.fee_quanta,
        settlement.balance.sequence,
        settlement.balance.locked_quanta,
        settlement.balance.spent_quanta,
        settlement.balance.available_quanta,
    ] {
        data.extend_from_slice(&value.to_be_bytes());
    }
    Ok(data)
}

struct Reader<'a> {
    bytes: &'a [u8],
    pos: usize,
}
impl<'a> Reader<'a> {
    fn take(&mut self, len: usize) -> Result<&'a [u8], RecoveryError> {
        let end = self
            .pos
            .checked_add(len)
            .ok_or(RecoveryError::MalformedEvent)?;
        let part = self
            .bytes
            .get(self.pos..end)
            .ok_or(RecoveryError::MalformedEvent)?;
        self.pos = end;
        Ok(part)
    }
    fn one(&mut self) -> Result<u8, RecoveryError> {
        Ok(self.take(1)?[0])
    }
    fn num(&mut self) -> Result<u64, RecoveryError> {
        let bytes: [u8; 8] = self
            .take(8)?
            .try_into()
            .map_err(|_| RecoveryError::MalformedEvent)?;
        Ok(u64::from_be_bytes(bytes))
    }
    fn name(&mut self) -> Result<String, RecoveryError> {
        let len = self.one()? as usize;
        let bytes = self.take(len)?;
        let name = std::str::from_utf8(bytes).map_err(|_| RecoveryError::MalformedEvent)?;
        if !valid_name(name) {
            return Err(RecoveryError::MalformedEvent);
        }
        Ok(name.to_owned())
    }
}
fn decode(raw: &[u8]) -> Result<Record, RecoveryError> {
    let mut r = Reader { bytes: raw, pos: 0 };
    if r.take(MAGIC.len())? != MAGIC {
        return Err(RecoveryError::MalformedEvent);
    }
    let kind = r.one()?;
    let id = r.name()?;
    let rec = match kind {
        PREPARE_INTENT | RESERVE_REVIEW => {
            let value = IntentPreparation {
                client_id: id,
                expected_sequence: r.num()?,
                principal: r.name()?,
                logon: r.name()?,
                runtime_epoch: r.num()?,
                credential_generation: r.take(16)?.try_into().unwrap(),
                recorded_at_ms: r.num()?,
                request_id: r.take(16)?.try_into().unwrap(),
                mode: r
                    .one()?
                    .try_into()
                    .map_err(|_| RecoveryError::MalformedEvent)?,
            };
            value.encode()?;
            if kind == PREPARE_INTENT {
                Record::PrepareIntent(value)
            } else {
                let ticket =
                    exec_ipc::review::Ticket::decode(r.take(exec_ipc::review::TICKET_SIZE)?)
                        .map_err(|_| RecoveryError::MalformedEvent)?;
                let asset = if ticket.buy {
                    &ticket.quote
                } else {
                    &ticket.base
                };
                let snapshot = BalanceSnapshot::new(&ticket.account, asset, r.num()?, r.num()?)
                    .map_err(RecoveryError::Reservation)?;
                Record::ReviewedReservation(ReviewedReservation {
                    context: value,
                    ticket,
                    snapshot,
                })
            }
        }
        APPROVAL => {
            let ticket = exec_ipc::review::Ticket::decode(r.take(exec_ipc::review::TICKET_SIZE)?)
                .map_err(|_| RecoveryError::MalformedEvent)?;
            if ticket.client_id != id {
                return Err(RecoveryError::MalformedEvent);
            }
            let value = OperatorApproval {
                ticket,
                principal: r.name()?,
                logon: r.name()?,
                recorded_at_ms: r.num()?,
                request_id: r.take(16)?.try_into().unwrap(),
                mode: r
                    .one()?
                    .try_into()
                    .map_err(|_| RecoveryError::MalformedEvent)?,
            };
            value.encode()?;
            Record::Approval(value)
        }
        REVOKE_APPROVAL => {
            let value = ApprovalRevocation {
                client_id: id,
                expected_sequence: r.num()?,
                principal: r.name()?,
                logon: r.name()?,
                recorded_at_ms: r.num()?,
                request_id: r.take(16)?.try_into().unwrap(),
            };
            value.encode()?;
            Record::RevokeApproval(value)
        }
        CEILING => {
            if id != "installation" {
                return Err(RecoveryError::MalformedEvent);
            }
            let change = CeilingChange {
                ceiling: exec_ipc::ceiling::Ceiling {
                    currency: r.name()?,
                    unit_epoch: u32::from_be_bytes(r.take(4)?.try_into().unwrap()),
                    decimals: r.one()?,
                    capital_quanta: r.num()?,
                },
                principal: r.name()?,
                logon: r.name()?,
                operator_user: r.name()?,
                recorded_at_ms: r.num()?,
                request_id: r.take(16)?.try_into().unwrap(),
                expected_sequence: r.num()?,
            };
            change.encode()?;
            Record::Ceiling(change)
        }
        CREDENTIAL => {
            if id != "venue" {
                return Err(RecoveryError::MalformedEvent);
            }
            let generation = r
                .take(16)?
                .try_into()
                .map_err(|_| RecoveryError::MalformedEvent)?;
            let ciphertext_digest = r
                .take(32)?
                .try_into()
                .map_err(|_| RecoveryError::MalformedEvent)?;
            if r.one()? != 0 {
                return Err(RecoveryError::MalformedEvent);
            }
            let metadata = CredentialMetadata {
                generation,
                ciphertext_digest,
                permission: CredentialPermission::Unverified,
            };
            metadata.encode()?;
            Record::Credential(metadata)
        }
        EXECUTION => {
            let account = r.name()?;
            let (instrument, base, quote) = (r.name()?, r.name()?, r.name()?);
            let (method, approval, rules_version) = (r.name()?, r.name()?, r.name()?);
            let side = match r.one()? {
                0 => Side::Buy,
                1 => Side::Sell,
                _ => return Err(RecoveryError::MalformedEvent),
            };
            let purpose = match r.one()? {
                0 => Purpose::Entry,
                1 => Purpose::Conversion,
                2 => Purpose::ProtectiveExit,
                _ => return Err(RecoveryError::MalformedEvent),
            };
            let quantity = r.num()?;
            let identity = ExecutionIdentity {
                instrument,
                base,
                quote,
                side,
                purpose,
                method,
                approval,
                rules_version,
                runtime_epoch: r.num()?,
                expires_at_ms: r.num()?,
                limit_price: r.num()?,
                max_quote_quanta: r.num()?,
            };
            identity.validate()?;
            Record::Execution {
                id,
                account,
                quantity,
                identity,
                reserved: r.num()?,
                available: r.num()?,
                sequence: r.num()?,
            }
        }
        EXECUTION_SETTLED => {
            let (fee_asset, account, asset) = (r.name()?, r.name()?, r.name()?);
            let (filled_quanta, gross_quote_quanta, fee_quanta) = (r.num()?, r.num()?, r.num()?);
            let balance = SettlementEvidence::new(
                &account,
                &asset,
                r.num()?,
                true,
                r.num()?,
                r.num()?,
                r.num()?,
            )
            .map_err(RecoveryError::Reservation)?;
            Record::ExecutionSettled {
                id,
                settlement: ExecutionSettlement {
                    filled_quanta,
                    gross_quote_quanta,
                    fee_asset,
                    fee_quanta,
                    balance,
                },
            }
        }
        CREATE => {
            let account = r.name()?;
            let asset = r.name()?;
            let quantity = r.num()?;
            if quantity == 0 {
                return Err(RecoveryError::MalformedEvent);
            }
            Record::Open {
                id,
                account,
                asset,
                quantity,
            }
        }
        EVIDENCE => {
            use Event::*;
            let event = match r.one()? {
                1 => BeginSend,
                2 => TransportFailed(FailureStage::BeforeFirstByte),
                3 => TransportFailed(FailureStage::AfterFirstByte),
                4 => Acknowledged,
                5 => Working,
                6 => MissingFromList,
                7 => CumulativeFilled(r.num()?),
                8 => TerminalReported,
                9 => SettlementVerified,
                10 => Denied,
                11 => VenueRejected,
                12 => SettlementAnomaly,
                13 => AnomalyReconciled {
                    expected_available_quanta: r.num()?,
                    observed_available_quanta: r.num()?,
                },
                14 => BeginCancel,
                15 => CancelTransportFailed(FailureStage::BeforeFirstByte),
                16 => CancelTransportFailed(FailureStage::AfterFirstByte),
                17 => CancelAcknowledged,
                _ => return Err(RecoveryError::MalformedEvent),
            };
            Record::Observation { id, event }
        }
        HOLD => Record::Hold {
            id,
            account: r.name()?,
            asset: r.name()?,
            quanta: r.num()?,
            available: r.num()?,
            sequence: r.num()?,
        },
        RELEASE_DENIED => Record::ReleaseDenied { id },
        RELEASE_SETTLED => {
            let account = r.name()?;
            let asset = r.name()?;
            let sequence = r.num()?;
            let complete = match r.one()? {
                0 => false,
                1 => true,
                _ => return Err(RecoveryError::MalformedEvent),
            };
            Record::ReleaseSettled {
                id,
                account,
                asset,
                sequence,
                complete,
                locked: r.num()?,
                spent: r.num()?,
                available: r.num()?,
            }
        }
        _ => return Err(RecoveryError::MalformedEvent),
    };
    if r.pos != raw.len() {
        return Err(RecoveryError::MalformedEvent);
    }
    Ok(rec)
}
fn apply_record(
    intents: &mut BTreeMap<String, ObservedIntent>,
    reservations: &mut ReservationBook,
    record: Record,
) -> Result<(), RecoveryError> {
    match record {
        Record::Credential(_)
        | Record::ReviewedReservation(_)
        | Record::Ceiling(_)
        | Record::Approval(_)
        | Record::PrepareIntent(_)
        | Record::RevokeApproval(_) => return Err(RecoveryError::MalformedEvent),
        Record::Execution {
            id,
            account,
            quantity,
            identity,
            reserved,
            available,
            sequence,
        } => {
            if intents.contains_key(&id)
                || intents.values().any(|order| {
                    order
                        .execution
                        .as_ref()
                        .is_some_and(|saved| saved.approval == identity.approval)
                })
            {
                return Err(RecoveryError::DuplicateIdentity);
            }
            identity.validate()?;
            let asset = if identity.side == Side::Buy {
                &identity.quote
            } else {
                &identity.base
            };
            let snapshot = BalanceSnapshot::new(&account, asset, available, sequence)
                .map_err(RecoveryError::Reservation)?;
            let attempt = Attempt::new(quantity).map_err(RecoveryError::Order)?;
            if (identity.side == Side::Buy && reserved != identity.max_quote_quanta)
                || (identity.side == Side::Sell && reserved != quantity)
            {
                return Err(RecoveryError::InvalidIdentity);
            }
            reservations
                .reserve(&id, &account, asset, reserved, &snapshot, &attempt)
                .map_err(RecoveryError::Reservation)?;
            let admission_index = intents.len();
            intents.insert(
                id,
                ObservedIntent {
                    admission_index,
                    account,
                    asset: asset.clone(),
                    attempt,
                    execution: Some(identity),
                    execution_settlement: None,
                    review_ticket: None,
                },
            );
        }
        Record::ExecutionSettled { id, settlement } => {
            let current = intents.get(&id).ok_or(RecoveryError::UnknownIdentity)?;
            let credits = intents
                .values()
                .filter(|other| {
                    other.account == current.account
                        && other.admission_index > current.admission_index
                })
                .try_fold(0u64, |total, other| {
                    let (Some(identity), Some(saved)) =
                        (&other.execution, &other.execution_settlement)
                    else {
                        return Ok(total);
                    };
                    let (asset, gross) = if identity.side == Side::Buy {
                        (&identity.base, saved.filled_quanta)
                    } else {
                        (&identity.quote, saved.gross_quote_quanta)
                    };
                    if asset != &current.asset {
                        return Ok(total);
                    }
                    let net = gross
                        .checked_sub(if saved.fee_asset == *asset {
                            saved.fee_quanta
                        } else {
                            0
                        })
                        .ok_or(RecoveryError::InvalidIdentity)?;
                    total.checked_add(net).ok_or(RecoveryError::InvalidIdentity)
                })?;
            let order = intents.get_mut(&id).ok_or(RecoveryError::UnknownIdentity)?;
            let identity = order
                .execution
                .as_ref()
                .ok_or(RecoveryError::InvalidIdentity)?;
            if order.execution_settlement.is_some()
                || settlement.filled_quanta > order.attempt.requested_quanta()
                || (settlement.fee_asset != identity.base && settlement.fee_asset != identity.quote)
                || (settlement.filled_quanta == 0
                    && (settlement.gross_quote_quanta != 0 || settlement.fee_quanta != 0))
                || (settlement.filled_quanta > 0 && settlement.gross_quote_quanta == 0)
                || (identity.side == Side::Sell
                    && settlement.fee_asset == identity.quote
                    && settlement.fee_quanta > settlement.gross_quote_quanta)
                || (settlement.fee_asset == identity.base
                    && settlement.fee_quanta > settlement.filled_quanta)
            {
                return Err(RecoveryError::Reservation(
                    ReservationError::InvalidEvidence,
                ));
            }
            let spending_fee = if settlement.fee_asset == order.asset {
                settlement.fee_quanta
            } else {
                0
            };
            let spent = if identity.side == Side::Buy {
                settlement.gross_quote_quanta
            } else {
                settlement.filled_quanta
            };
            let spent = spent
                .checked_add(spending_fee)
                .ok_or(RecoveryError::InvalidIdentity)?;
            let cap = if identity.side == Side::Buy {
                identity.max_quote_quanta
            } else {
                order.attempt.requested_quanta()
            };
            if spent != settlement.balance.spent_quanta
                || spent > cap
                || (identity.side == Side::Buy
                    && settlement.gross_quote_quanta
                        > settlement
                            .filled_quanta
                            .checked_mul(identity.limit_price)
                            .ok_or(RecoveryError::InvalidIdentity)?)
                || (identity.side == Side::Sell
                    && settlement.gross_quote_quanta
                        < settlement
                            .filled_quanta
                            .checked_mul(identity.limit_price)
                            .ok_or(RecoveryError::InvalidIdentity)?)
            {
                return Err(RecoveryError::Reservation(
                    ReservationError::BalanceMismatch,
                ));
            }
            if matches!(
                order.attempt.lifecycle(),
                exec_core::orders::Lifecycle::Submitting | exec_core::orders::Lifecycle::Unknown
            ) {
                order
                    .attempt
                    .apply(Event::Acknowledged)
                    .map_err(RecoveryError::Order)?;
            }
            if order.attempt.lifecycle() != exec_core::orders::Lifecycle::TerminalReported {
                order
                    .attempt
                    .apply(Event::CumulativeFilled(settlement.filled_quanta))
                    .map_err(RecoveryError::Order)?;
                order
                    .attempt
                    .apply(Event::TerminalReported)
                    .map_err(RecoveryError::Order)?;
            } else if order.attempt.filled_quanta() != settlement.filled_quanta {
                return Err(RecoveryError::Order(OrderError::FillRegression));
            }
            order
                .attempt
                .apply(Event::SettlementVerified)
                .map_err(RecoveryError::Order)?;
            reservations
                .release_settled_with_credits(&id, &order.attempt, &settlement.balance, credits)
                .map_err(RecoveryError::Reservation)?;
            order.execution_settlement = Some(settlement);
        }
        Record::Open {
            id,
            account,
            asset,
            quantity,
        } => {
            if intents.contains_key(&id) {
                return Err(RecoveryError::DuplicateIdentity);
            }
            let admission_index = intents.len();
            intents.insert(
                id,
                ObservedIntent {
                    admission_index,
                    account,
                    asset,
                    attempt: Attempt::new(quantity).map_err(RecoveryError::Order)?,
                    execution: None,
                    execution_settlement: None,
                    review_ticket: None,
                },
            );
        }
        Record::Observation { id, event } => {
            let current = intents.get_mut(&id).ok_or(RecoveryError::UnknownIdentity)?;
            current.attempt.apply(event).map_err(RecoveryError::Order)?;
        }
        Record::Hold {
            id,
            account,
            asset,
            quanta,
            available,
            sequence,
        } => {
            let order = intents.get(&id).ok_or(RecoveryError::UnknownIdentity)?;
            if order.account != account || order.asset != asset {
                return Err(RecoveryError::Reservation(
                    ReservationError::InvalidEvidence,
                ));
            }
            let snapshot = BalanceSnapshot::new(&account, &asset, available, sequence)
                .map_err(RecoveryError::Reservation)?;
            reservations
                .reserve(&id, &account, &asset, quanta, &snapshot, &order.attempt)
                .map_err(RecoveryError::Reservation)?;
        }
        Record::ReleaseDenied { id } => {
            let order = intents.get(&id).ok_or(RecoveryError::UnknownIdentity)?;
            reservations
                .release_denied(&id, &order.attempt)
                .map_err(RecoveryError::Reservation)?;
        }
        Record::ReleaseSettled {
            id,
            account,
            asset,
            sequence,
            complete,
            locked,
            spent,
            available,
        } => {
            let order = intents.get(&id).ok_or(RecoveryError::UnknownIdentity)?;
            let evidence = SettlementEvidence::new(
                &account, &asset, sequence, complete, locked, spent, available,
            )
            .map_err(RecoveryError::Reservation)?;
            reservations
                .release_settled(&id, &order.attempt, &evidence)
                .map_err(RecoveryError::Reservation)?;
        }
    }
    Ok(())
}
impl DurableOrderJournal {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, RecoveryError> {
        let ledger = Ledger::open(path)?;
        let records = ledger.replay_from(0)?;
        let mut intents = BTreeMap::new();
        let mut reservations = ReservationBook::default();
        let mut credential = None;
        let mut generations = BTreeSet::new();
        let mut ceiling = None;
        let mut ceiling_requests = BTreeSet::new();
        let mut approvals = BTreeMap::new();
        let mut approval_requests = BTreeSet::new();
        for e in &records {
            let parsed = decode(&e.event_bytes)?;
            if let Record::ReviewedReservation(value) = parsed {
                apply_review_reservation(
                    ceiling.as_ref(),
                    &approvals,
                    &approval_requests,
                    &mut intents,
                    &mut reservations,
                    &value,
                )
                .map_err(|_| RecoveryError::MalformedEvent)?;
                approval_requests.insert(value.context.request_id);
                approvals
                    .get_mut(&value.context.client_id)
                    .unwrap()
                    .sequence = e.sequence;
                continue;
            }
            if let Record::PrepareIntent(value) = parsed {
                check_preparation(ceiling.as_ref(), &approvals, &approval_requests, &value)
                    .map_err(|_| RecoveryError::MalformedEvent)?;
                if intents.contains_key(&value.client_id) {
                    return Err(RecoveryError::MalformedEvent);
                }
                approval_requests.insert(value.request_id);
                let saved = approvals.get_mut(&value.client_id).unwrap();
                saved.prepared_at_ms = Some(value.recorded_at_ms);
                saved.sequence = e.sequence;
                continue;
            }
            if let Record::Approval(value) = parsed {
                check_approval(ceiling.as_ref(), &approvals, &approval_requests, &value)
                    .map_err(|_| RecoveryError::MalformedEvent)?;
                if intents.contains_key(&value.ticket.client_id) {
                    return Err(RecoveryError::MalformedEvent);
                }
                approval_requests.insert(value.request_id);
                approvals.insert(
                    value.ticket.client_id.clone(),
                    ApprovalView {
                        sequence: e.sequence,
                        approval: value,
                        revoked_at_ms: None,
                        prepared_at_ms: None,
                    },
                );
                continue;
            }
            if let Record::RevokeApproval(value) = parsed {
                check_revocation(&approvals, &approval_requests, &value)
                    .map_err(|_| RecoveryError::MalformedEvent)?;
                approval_requests.insert(value.request_id);
                let current = approvals.get_mut(&value.client_id).unwrap();
                current.sequence = e.sequence;
                current.revoked_at_ms = Some(value.recorded_at_ms);
                continue;
            }
            if let Record::Ceiling(change) = parsed {
                check_ceiling(ceiling.as_ref(), &ceiling_requests, &change)
                    .map_err(|_| RecoveryError::MalformedEvent)?;
                ceiling_requests.insert(change.request_id);
                ceiling = Some((e.sequence, change));
                continue;
            }
            if let Record::Credential(metadata) = parsed {
                if !generations.insert(metadata.generation) {
                    return Err(RecoveryError::MalformedEvent);
                }
                credential = Some(metadata);
                continue;
            }
            // Verified bytes that cannot form a legal state also fail closed.
            if matches!(&parsed, Record::Open { id, .. } | Record::Execution { id, .. } if approvals.contains_key(id))
            {
                return Err(RecoveryError::MalformedEvent);
            }
            apply_record(&mut intents, &mut reservations, parsed)
                .map_err(|_| RecoveryError::MalformedEvent)?;
        }
        let recovered_inflight = intents
            .iter()
            .filter(|(_, order)| {
                order.attempt.lifecycle() == exec_core::orders::Lifecycle::Submitting
            })
            .map(|(id, _)| id.clone())
            .collect();
        let recovered_cancels = intents
            .iter()
            .filter(|(_, order)| {
                order.attempt.cancellation() == exec_core::orders::Cancellation::Submitting
            })
            .map(|(id, _)| id.clone())
            .collect();
        Ok(Self {
            ledger,
            intents,
            reservations,
            records: records.len(),
            recovered_inflight,
            recovered_cancels,
            credential,
            ceiling,
            ceiling_requests,
            approvals,
            approval_requests,
        })
    }

    pub fn credential_metadata(&self) -> Option<&CredentialMetadata> {
        self.credential.as_ref()
    }

    pub fn installation_ceiling(&self) -> Option<&(u64, CeilingChange)> {
        self.ceiling.as_ref()
    }

    pub fn operator_approval(&self, client_id: &str) -> Option<&ApprovalView> {
        self.approvals.get(client_id)
    }
    pub fn record_approval(&mut self, value: OperatorApproval) -> Result<(), RecoveryError> {
        check_approval(
            self.ceiling.as_ref(),
            &self.approvals,
            &self.approval_requests,
            &value,
        )?;
        if self.intents.contains_key(&value.ticket.client_id) {
            return Err(RecoveryError::DuplicateIdentity);
        }
        let entry = self.ledger.append(&value.encode()?)?;
        self.approval_requests.insert(value.request_id);
        self.approvals.insert(
            value.ticket.client_id.clone(),
            ApprovalView {
                sequence: entry.sequence,
                approval: value,
                revoked_at_ms: None,
                prepared_at_ms: None,
            },
        );
        self.records += 1;
        Ok(())
    }
    pub fn revoke_approval(&mut self, value: ApprovalRevocation) -> Result<(), RecoveryError> {
        check_revocation(&self.approvals, &self.approval_requests, &value)?;
        let entry = self.ledger.append(&value.encode()?)?;
        self.approval_requests.insert(value.request_id);
        let current = self.approvals.get_mut(&value.client_id).unwrap();
        current.sequence = entry.sequence;
        current.revoked_at_ms = Some(value.recorded_at_ms);
        self.records += 1;
        Ok(())
    }
    pub fn prepare_intent(&mut self, value: IntentPreparation) -> Result<(), RecoveryError> {
        check_preparation(
            self.ceiling.as_ref(),
            &self.approvals,
            &self.approval_requests,
            &value,
        )?;
        if self.intents.contains_key(&value.client_id) {
            return Err(RecoveryError::DuplicateIdentity);
        }
        let entry = self.ledger.append(&value.encode()?)?;
        self.approval_requests.insert(value.request_id);
        let saved = self.approvals.get_mut(&value.client_id).unwrap();
        saved.prepared_at_ms = Some(value.recorded_at_ms);
        saved.sequence = entry.sequence;
        self.records += 1;
        Ok(())
    }

    /// Offline admission mechanics only. A supplied balance is not authenticated evidence;
    /// the live service exposes no reservation or transport command.
    pub fn reserve_prepared_intent(
        &mut self,
        context: IntentPreparation,
        snapshot: &BalanceSnapshot,
    ) -> Result<(), RecoveryError> {
        let ticket = self
            .approvals
            .get(&context.client_id)
            .ok_or(RecoveryError::UnknownIdentity)?
            .approval
            .ticket
            .clone();
        let value = ReviewedReservation {
            context,
            ticket,
            snapshot: snapshot.clone(),
        };
        let mut intents = self.intents.clone();
        let mut reservations = self.reservations.clone();
        apply_review_reservation(
            self.ceiling.as_ref(),
            &self.approvals,
            &self.approval_requests,
            &mut intents,
            &mut reservations,
            &value,
        )?;
        let entry = self.ledger.append(&value.encode()?)?;
        self.intents = intents;
        self.reservations = reservations;
        self.approval_requests.insert(value.context.request_id);
        self.approvals
            .get_mut(&value.context.client_id)
            .unwrap()
            .sequence = entry.sequence;
        self.records += 1;
        Ok(())
    }
    pub fn commit_ceiling(&mut self, change: CeilingChange) -> Result<(), RecoveryError> {
        check_ceiling(self.ceiling.as_ref(), &self.ceiling_requests, &change)?;
        let entry = self.ledger.append(&change.encode()?)?;
        self.ceiling_requests.insert(change.request_id);
        self.ceiling = Some((entry.sequence, change));
        self.records += 1;
        Ok(())
    }

    /// Call only after the immutable ciphertext generation has been durably published.
    pub fn commit_credential(&mut self, metadata: CredentialMetadata) -> Result<(), RecoveryError> {
        let raw = metadata.encode()?;
        for entry in self.ledger.replay_from(0)? {
            if let Record::Credential(old) = decode(&entry.event_bytes)? {
                if old.generation == metadata.generation {
                    return Err(RecoveryError::DuplicateIdentity);
                }
            }
        }
        self.ledger.append(&raw)?;
        self.credential = Some(metadata);
        self.records += 1;
        Ok(())
    }

    pub fn create_intent(
        &mut self,
        id: &str,
        account: &str,
        asset: &str,
        quantity: u64,
    ) -> Result<(), RecoveryError> {
        if self.intents.contains_key(id) || self.approvals.contains_key(id) {
            return Err(RecoveryError::DuplicateIdentity);
        }
        let raw = record_intent(id, account, asset, quantity)?;
        let parsed = decode(&raw)?;
        // Verify on a copy before persisting. No in-memory or venue effect before commit.
        let mut next = self.intents.clone();
        let mut next_holds = self.reservations.clone();
        apply_record(&mut next, &mut next_holds, parsed)?;
        self.ledger.append(&raw)?;
        self.intents = next;
        self.reservations = next_holds;
        self.records += 1;
        Ok(())
    }

    pub fn record_event(&mut self, id: &str, event: Event) -> Result<(), RecoveryError> {
        if (event == Event::TransportFailed(FailureStage::BeforeFirstByte)
            && self.recovered_inflight.contains(id))
            || (event == Event::CancelTransportFailed(FailureStage::BeforeFirstByte)
                && self.recovered_cancels.contains(id))
        {
            return Err(RecoveryError::Order(OrderError::IllegalTransition));
        }
        let raw = record_event(id, event)?;
        let parsed = decode(&raw)?;
        let mut next = self.intents.clone();
        let mut next_holds = self.reservations.clone();
        apply_record(&mut next, &mut next_holds, parsed)?;
        self.ledger.append(&raw)?;
        self.intents = next;
        self.reservations = next_holds;
        self.records += 1;
        Ok(())
    }
    /// Durable offline reservation admission. A snapshot is *not* trusted
    /// solely because this model accepts it: funded admission is disabled.
    pub fn reserve_intent(
        &mut self,
        id: &str,
        quanta: u64,
        snapshot: &BalanceSnapshot,
    ) -> Result<(), RecoveryError> {
        let raw = record_hold(id, snapshot, quanta)?;
        self.apply_durable(raw)
    }
    pub fn release_denied_reservation(&mut self, id: &str) -> Result<(), RecoveryError> {
        self.apply_durable(record_release_denied(id)?)
    }
    pub fn release_settled_reservation(
        &mut self,
        id: &str,
        evidence: &SettlementEvidence,
    ) -> Result<(), RecoveryError> {
        self.apply_durable(record_release_settled(id, evidence)?)
    }
    /// A failed transition is not appended and does not change any hold.
    fn apply_durable(&mut self, raw: Vec<u8>) -> Result<(), RecoveryError> {
        let parsed = decode(&raw)?;
        let mut next = self.intents.clone();
        let mut next_holds = self.reservations.clone();
        apply_record(&mut next, &mut next_holds, parsed)?;
        self.ledger.append(&raw)?;
        self.intents = next;
        self.reservations = next_holds;
        self.records += 1;
        Ok(())
    }
    /// Identity and reservation commit together; transport is a separate, later step.
    pub fn create_execution(
        &mut self,
        id: &str,
        account: &str,
        quantity: u64,
        identity: &ExecutionIdentity,
        snapshot: &BalanceSnapshot,
    ) -> Result<(), RecoveryError> {
        // Legacy simulation records cannot consume an authenticated operator review.
        if self.approvals.contains_key(id) {
            return Err(RecoveryError::DuplicateIdentity);
        }
        let reserved = if identity.side == Side::Buy {
            identity.max_quote_quanta
        } else {
            quantity
        };
        self.apply_durable(record_execution(
            id, account, quantity, identity, reserved, snapshot,
        )?)
    }
    pub fn settle_execution(
        &mut self,
        id: &str,
        settlement: &ExecutionSettlement,
    ) -> Result<(), RecoveryError> {
        if self
            .get(id)
            .and_then(|order| order.execution_settlement.as_ref())
            == Some(settlement)
        {
            return Ok(());
        }
        self.apply_durable(record_execution_settlement(id, settlement)?)
    }
    pub fn reserved(&self, account: &str, asset: &str) -> u64 {
        self.reservations.reserved(account, asset)
    }
    pub fn get(&self, id: &str) -> Option<&ObservedIntent> {
        self.intents.get(id)
    }
    pub fn pending_ids(&self) -> Vec<&str> {
        self.intents
            .iter()
            .filter(|(_, record)| record.attempt.holds_slot())
            .map(|(id, _)| id.as_str())
            .collect()
    }
    pub fn record_count(&self) -> usize {
        self.records
    }
}
