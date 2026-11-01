//! B2 offline, durably logged order identity and evidence projection.
//! No transport or funded authority: restarting this journal never submits an order.
//! All records are appended to exec-store's FULL-synchronous hash-chained ledger
//! before an Attempt projection changes. Unknown bytes or illegal replay fail closed.
use exec_core::orders::{
    Attempt, BalanceSnapshot, Event, FailureStage, OrderError,
    ReservationBook, ReservationError, SettlementEvidence,
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
    fn from(e: LedgerError) -> Self { Self::Ledger(e) }
}

#[derive(Clone, Debug)]
pub struct ObservedIntent {
    pub account: String,
    pub asset: String,
    pub attempt: Attempt,
}
pub struct DurableOrderJournal {
    ledger: Ledger,
    intents: BTreeMap<String, ObservedIntent>,
    reservations: ReservationBook,
    records: usize,
    /// A request already in flight when the journal was reopened cannot be
    /// certified as never sent by this newly started process.
    recovered_inflight: BTreeSet<String>,
}
enum Record {
    Open { id: String, account: String, asset: String, quantity: u64 },
    Observation { id: String, event: Event },
    Hold { id: String, account: String, asset: String, quanta: u64, available: u64, sequence: u64 },
    ReleaseDenied { id: String },
    ReleaseSettled { id: String, account: String, asset: String,
        sequence: u64, complete: bool, locked: u64, spent: u64, available: u64 },
}
fn valid_name(s: &str) -> bool {
    !s.is_empty() && s.len() <= 96 &&
        s.bytes().all(|c| c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_' | b':' | b'.'))
}
fn add_name(data: &mut Vec<u8>, name: &str) -> Result<(), RecoveryError> {
    if !valid_name(name) { return Err(RecoveryError::InvalidIdentity); }
    data.push(u8::try_from(name.len()).map_err(|_| RecoveryError::InvalidIdentity)?);
    data.extend_from_slice(name.as_bytes());
    Ok(())
}
fn record_intent(id: &str, account: &str, asset: &str, quantity: u64) -> Result<Vec<u8>, RecoveryError> {
    if quantity == 0 { return Err(RecoveryError::Order(OrderError::InvalidQuantity)); }
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
        BeginSend => 1, TransportFailed(FailureStage::BeforeFirstByte) => 2,
        TransportFailed(FailureStage::AfterFirstByte) => 3, Acknowledged => 4,
        Working => 5, MissingFromList => 6, CumulativeFilled(_) => 7,
        TerminalReported => 8, SettlementVerified => 9, Denied => 10,
        VenueRejected => 11, SettlementAnomaly => 12, AnomalyReconciled { .. } => 13,
    };
    data.push(tag);
    match event {
        CumulativeFilled(n) => data.extend_from_slice(&n.to_be_bytes()),
        AnomalyReconciled { expected_available_quanta, observed_available_quanta } => {
            data.extend_from_slice(&expected_available_quanta.to_be_bytes());
            data.extend_from_slice(&observed_available_quanta.to_be_bytes());
        }
        _ => {}
    }
    Ok(data)
}
// Every reservation change is part of the SAME durable ledger as the
// attempt, not a second database that could commit or fail independently.
fn record_hold(id: &str, snapshot: &BalanceSnapshot, quanta: u64)
    -> Result<Vec<u8>, RecoveryError>
{
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
fn record_release_settled(id: &str, evidence: &SettlementEvidence)
    -> Result<Vec<u8>, RecoveryError>
{
    let mut data = MAGIC.to_vec();
    data.push(RELEASE_SETTLED);
    add_name(&mut data, id)?;
    add_name(&mut data, &evidence.account)?;
    add_name(&mut data, &evidence.asset)?;
    data.extend_from_slice(&evidence.sequence.to_be_bytes());
    data.push(u8::from(evidence.complete));
    for value in [evidence.locked_quanta, evidence.spent_quanta, evidence.available_quanta] {
        data.extend_from_slice(&value.to_be_bytes());
    }
    Ok(data)
}

struct Reader<'a> { bytes: &'a [u8], pos: usize }
impl<'a> Reader<'a> {
    fn take(&mut self, len: usize) -> Result<&'a [u8], RecoveryError> {
        let end = self.pos.checked_add(len).ok_or(RecoveryError::MalformedEvent)?;
        let part = self.bytes.get(self.pos..end).ok_or(RecoveryError::MalformedEvent)?;
        self.pos = end;
        Ok(part)
    }
    fn one(&mut self) -> Result<u8, RecoveryError> { Ok(self.take(1)?[0]) }
    fn num(&mut self) -> Result<u64, RecoveryError> {
        let bytes: [u8; 8] = self.take(8)?.try_into().map_err(|_| RecoveryError::MalformedEvent)?;
        Ok(u64::from_be_bytes(bytes))
    }
    fn name(&mut self) -> Result<String, RecoveryError> {
        let len = self.one()? as usize;
        let bytes = self.take(len)?;
        let name = std::str::from_utf8(bytes).map_err(|_| RecoveryError::MalformedEvent)?;
        if !valid_name(name) { return Err(RecoveryError::MalformedEvent); }
        Ok(name.to_owned())
    }
}
fn decode(raw: &[u8]) -> Result<Record, RecoveryError> {
    let mut r = Reader { bytes: raw, pos: 0 };
    if r.take(MAGIC.len())? != MAGIC { return Err(RecoveryError::MalformedEvent); }
    let kind = r.one()?;
    let id = r.name()?;
    let rec = match kind {
        CREATE => {
            let account = r.name()?;
            let asset = r.name()?;
            let quantity = r.num()?;
            if quantity == 0 { return Err(RecoveryError::MalformedEvent); }
            Record::Open { id, account, asset, quantity }
        }
        EVIDENCE => {
            use Event::*;
            let event = match r.one()? {
                1 => BeginSend, 2 => TransportFailed(FailureStage::BeforeFirstByte),
                3 => TransportFailed(FailureStage::AfterFirstByte),
                4 => Acknowledged, 5 => Working, 6 => MissingFromList,
                7 => CumulativeFilled(r.num()?), 8 => TerminalReported,
                9 => SettlementVerified, 10 => Denied, 11 => VenueRejected,
                12 => SettlementAnomaly, 13 => AnomalyReconciled {
                    expected_available_quanta: r.num()?,
                    observed_available_quanta: r.num()?,
                },
                _ => return Err(RecoveryError::MalformedEvent),
            };
            Record::Observation { id, event }
        }
        HOLD => Record::Hold {
            id, account: r.name()?, asset: r.name()?,
            quanta: r.num()?, available: r.num()?, sequence: r.num()?,
        },
        RELEASE_DENIED => Record::ReleaseDenied { id },
        RELEASE_SETTLED => {
            let account = r.name()?;
            let asset = r.name()?;
            let sequence = r.num()?;
            let complete = match r.one()? {
                0 => false, 1 => true,
                _ => return Err(RecoveryError::MalformedEvent),
            };
            Record::ReleaseSettled {
                id, account, asset, sequence, complete,
                locked: r.num()?, spent: r.num()?, available: r.num()?,
            }
        }
        _ => return Err(RecoveryError::MalformedEvent),
    };
    if r.pos != raw.len() { return Err(RecoveryError::MalformedEvent); }
    Ok(rec)
}
fn apply_record(intents: &mut BTreeMap<String, ObservedIntent>,
    reservations: &mut ReservationBook, record: Record) -> Result<(), RecoveryError>
{
    match record {
        Record::Open { id, account, asset, quantity } => {
            if intents.contains_key(&id) { return Err(RecoveryError::DuplicateIdentity); }
            intents.insert(id, ObservedIntent {
                account, asset, attempt: Attempt::new(quantity).map_err(RecoveryError::Order)?,
            });
        }
        Record::Observation { id, event } => {
            let current = intents.get_mut(&id).ok_or(RecoveryError::UnknownIdentity)?;
            current.attempt.apply(event).map_err(RecoveryError::Order)?;
        }
        Record::Hold { id, account, asset, quanta, available, sequence } => {
            let order = intents.get(&id).ok_or(RecoveryError::UnknownIdentity)?;
            if order.account != account || order.asset != asset {
                return Err(RecoveryError::Reservation(ReservationError::InvalidEvidence));
            }
            let snapshot = BalanceSnapshot::new(&account, &asset, available, sequence)
                .map_err(RecoveryError::Reservation)?;
            reservations.reserve(&id, &account, &asset, quanta, &snapshot, &order.attempt)
                .map_err(RecoveryError::Reservation)?;
        }
        Record::ReleaseDenied { id } => {
            let order = intents.get(&id).ok_or(RecoveryError::UnknownIdentity)?;
            reservations.release_denied(&id, &order.attempt)
                .map_err(RecoveryError::Reservation)?;
        }
        Record::ReleaseSettled {
            id, account, asset, sequence, complete, locked, spent, available,
        } => {
            let order = intents.get(&id).ok_or(RecoveryError::UnknownIdentity)?;
            let evidence = SettlementEvidence::new(
                &account, &asset, sequence, complete, locked, spent, available,
            ).map_err(RecoveryError::Reservation)?;
            reservations.release_settled(&id, &order.attempt, &evidence)
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
        for e in &records {
            let parsed = decode(&e.event_bytes)?;
            // Verified bytes that cannot form a legal state also fail closed.
            apply_record(&mut intents, &mut reservations, parsed)
                .map_err(|_| RecoveryError::MalformedEvent)?;
        }
        let recovered_inflight = intents.iter()
            .filter(|(_, order)| order.attempt.lifecycle() == exec_core::orders::Lifecycle::Submitting)
            .map(|(id, _)| id.clone()).collect();
        Ok(Self { ledger, intents, reservations, records: records.len(), recovered_inflight })
    }

    pub fn create_intent(&mut self, id: &str, account: &str, asset: &str, quantity: u64)
        -> Result<(), RecoveryError>
    {
        if self.intents.contains_key(id) { return Err(RecoveryError::DuplicateIdentity); }
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
        if event == Event::TransportFailed(FailureStage::BeforeFirstByte)
            && self.recovered_inflight.contains(id)
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
    pub fn reserve_intent(&mut self, id: &str, quanta: u64,
        snapshot: &BalanceSnapshot) -> Result<(), RecoveryError>
    {
        let raw = record_hold(id, snapshot, quanta)?;
        self.apply_durable(raw)
    }
    pub fn release_denied_reservation(&mut self, id: &str)
        -> Result<(), RecoveryError>
    {
        self.apply_durable(record_release_denied(id)?)
    }
    pub fn release_settled_reservation(&mut self, id: &str,
        evidence: &SettlementEvidence) -> Result<(), RecoveryError>
    {
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
    pub fn reserved(&self, account: &str, asset: &str) -> u64 {
        self.reservations.reserved(account, asset)
    }
    pub fn get(&self, id: &str) -> Option<&ObservedIntent> { self.intents.get(id) }
    pub fn pending_ids(&self) -> Vec<&str> {
        self.intents.iter().filter(|(_, record)| record.attempt.holds_slot())
            .map(|(id, _)| id.as_str()).collect()
    }
    pub fn record_count(&self) -> usize { self.records }
}
