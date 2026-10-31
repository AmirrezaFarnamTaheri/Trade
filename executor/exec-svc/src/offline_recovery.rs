//! B2 offline, durably logged order identity and evidence projection.
//! No transport or funded authority: restarting this journal never submits an order.
//! All records are appended to exec-store's FULL-synchronous hash-chained ledger
//! before an Attempt projection changes. Unknown bytes or illegal replay fail closed.
use exec_core::orders::{Attempt, Event, FailureStage, OrderError};
use exec_store::{Ledger, LedgerError};
use std::collections::BTreeMap;
use std::path::Path;

const MAGIC: &[u8; 5] = b"TGOR1";
const CREATE: u8 = 1;
const EVIDENCE: u8 = 2;

#[derive(Debug)]
pub enum RecoveryError {
    Ledger(LedgerError),
    InvalidIdentity,
    DuplicateIdentity,
    UnknownIdentity,
    MalformedEvent,
    Order(OrderError),
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
    records: usize,
}
enum Record {
    Open { id: String, account: String, asset: String, quantity: u64 },
    Observation { id: String, event: Event },
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
        _ => return Err(RecoveryError::MalformedEvent),
    };
    if r.pos != raw.len() { return Err(RecoveryError::MalformedEvent); }
    Ok(rec)
}
fn apply_record(intents: &mut BTreeMap<String, ObservedIntent>, record: Record)
    -> Result<(), RecoveryError>
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
    }
    Ok(())
}
impl DurableOrderJournal {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, RecoveryError> {
        let ledger = Ledger::open(path)?;
        let records = ledger.replay_from(0)?;
        let mut intents = BTreeMap::new();
        for e in &records {
            let parsed = decode(&e.event_bytes)?;
            // Verified bytes that cannot form a legal state also fail closed.
            apply_record(&mut intents, parsed).map_err(|_| RecoveryError::MalformedEvent)?;
        }
        Ok(Self { ledger, intents, records: records.len() })
    }

    pub fn create_intent(&mut self, id: &str, account: &str, asset: &str, quantity: u64)
        -> Result<(), RecoveryError>
    {
        if self.intents.contains_key(id) { return Err(RecoveryError::DuplicateIdentity); }
        let raw = record_intent(id, account, asset, quantity)?;
        let parsed = decode(&raw)?;
        // Verify on a copy before persisting. No in-memory or venue effect before commit.
        let mut next = self.intents.clone();
        apply_record(&mut next, parsed)?;
        self.ledger.append(&raw)?;
        self.intents = next;
        self.records += 1;
        Ok(())
    }

    pub fn record_event(&mut self, id: &str, event: Event) -> Result<(), RecoveryError> {
        let raw = record_event(id, event)?;
        let parsed = decode(&raw)?;
        let mut next = self.intents.clone();
        apply_record(&mut next, parsed)?;
        self.ledger.append(&raw)?;
        self.intents = next;
        self.records += 1;
        Ok(())
    }
    pub fn get(&self, id: &str) -> Option<&ObservedIntent> { self.intents.get(id) }
    pub fn pending_ids(&self) -> Vec<&str> {
        self.intents.iter().filter(|(_, record)| record.attempt.holds_slot())
            .map(|(id, _)| id.as_str()).collect()
    }
    pub fn record_count(&self) -> usize { self.records }
}
