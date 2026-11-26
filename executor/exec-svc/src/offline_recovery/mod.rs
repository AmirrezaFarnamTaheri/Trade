//! Offline, durably logged order identity and evidence projection.
//! No transport or funded authority: restarting this journal never submits an order.
//! All records are appended to exec-store's FULL-synchronous hash-chained ledger
//! before an Attempt projection changes. Unknown bytes or illegal replay fail closed.
use crate::account_observation::{AccountKind, AccountObservation};
use exec_core::holds::ActiveHoldBook;
use exec_core::orders::{
    Attempt, BalanceSnapshot, Event, FailureStage, OrderError, ReservationBook, ReservationError,
    SettlementEvidence,
};
use exec_store::{Ledger, LedgerError};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::sync::{
    atomic::{AtomicU8, Ordering},
    Arc,
};
use std::thread::JoinHandle;

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
const ACCOUNT_OBSERVATION: u8 = 14;
const RESERVE_REVIEW_WITH_FEE: u8 = 15;
const REVIEW_SETTLED: u8 = 16;
const CHECKPOINT_MAGIC: &[u8; 8] = b"TGCKPT01";
const CHECKPOINT_MANIFEST_MAGIC: &[u8; 8] = b"TGCKPT02";
const CHECKPOINT_PAGE_MAGIC: &[u8; 8] = b"TGCKPG01";
const MAX_CHECKPOINT_BYTES: usize = 64 * 1024 * 1024;
const PAGE_HEADER: usize = 44;

#[derive(serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct CheckpointManifest {
    tip: (u64, [u8; 32]),
    chunks: u32,
    state_bytes: usize,
    digest: [u8; 32],
}

#[derive(Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Checkpoint {
    tip: (u64, [u8; 32]),
    intents: BTreeMap<String, ObservedIntent>,
    reservations: ActiveHoldBook,
    legacy_reservations: ReservationBook,
    credential: Option<CredentialMetadata>,
    generations: BTreeSet<[u8; 16]>,
    ceiling: Option<(u64, CeilingChange)>,
    ceiling_requests: BTreeSet<[u8; 16]>,
    approvals: BTreeMap<String, ApprovalView>,
    approval_requests: BTreeSet<[u8; 16]>,
    #[serde(with = "observation_map")]
    account_observations: BTreeMap<(AccountKind, String), AccountObservation>,
    account_requests: BTreeSet<[u8; 16]>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    history_through: Option<u64>,
}

mod observation_map {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        value: &BTreeMap<(AccountKind, String), AccountObservation>,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serde::Serialize::serialize(&value.iter().collect::<Vec<_>>(), serializer)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<BTreeMap<(AccountKind, String), AccountObservation>, D::Error> {
        let value: Vec<((AccountKind, String), AccountObservation)> =
            serde::Deserialize::deserialize(deserializer)?;
        Ok(value.into_iter().collect())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AuditStatus {
    Pending,
    Verified,
    Failed,
}

mod checkpoint;
mod replay;
mod review;
mod wire;

use checkpoint::*;
use replay::*;
use review::*;
pub use review::{
    ApprovalRevocation, ApprovalView, CeilingChange, CredentialMetadata, CredentialPermission,
    ExecutionIdentity, ExecutionSettlement, IntentPreparation, ObservedIntent, OperatorApproval,
    Purpose, Side,
};
use wire::*;

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

pub struct DurableOrderJournal {
    ledger: Ledger,
    audit: Option<JoinHandle<()>>,
    audit_state: Arc<AtomicU8>,
    intents: BTreeMap<String, ObservedIntent>,
    reservations: ActiveHoldBook,
    // Historical offline aggregate-settlement events retain their original projection.
    legacy_reservations: ReservationBook,
    records: usize,
    /// A request already in flight when the journal was reopened cannot be
    /// certified as never sent by this newly started process.
    recovered_inflight: BTreeSet<String>,
    recovered_cancels: BTreeSet<String>,
    credential: Option<CredentialMetadata>,
    generations: BTreeSet<[u8; 16]>,
    ceiling: Option<(u64, CeilingChange)>,
    ceiling_requests: BTreeSet<[u8; 16]>,
    approvals: BTreeMap<String, ApprovalView>,
    approval_requests: BTreeSet<[u8; 16]>,
    account_observations: BTreeMap<(AccountKind, String), AccountObservation>,
    account_requests: BTreeSet<[u8; 16]>,
}

impl Drop for DurableOrderJournal {
    fn drop(&mut self) {
        if let Some(audit) = self.audit.take() {
            let _ = audit.join();
        }
    }
}

impl DurableOrderJournal {
    pub fn audit_status(&self) -> AuditStatus {
        match self.audit_state.load(Ordering::Acquire) {
            0 => AuditStatus::Pending,
            1 => AuditStatus::Verified,
            _ => AuditStatus::Failed,
        }
    }

    pub fn audit_failed(&self) -> bool {
        self.audit_status() == AuditStatus::Failed
    }

    /// Native custody chooses the local destination; a failed or pending audit cannot certify a copy.
    pub fn backup_to(
        &mut self,
        destination: impl AsRef<Path>,
    ) -> Result<(u64, [u8; 32]), RecoveryError> {
        self.wait_for_audit()?;
        Ok(self.ledger.backup_to(destination)?)
    }

    /// A writer never consumes a restored projection before independent replay has validated it.
    pub fn wait_for_audit(&mut self) -> Result<(), RecoveryError> {
        if let Some(audit) = self.audit.take() {
            if audit.join().is_err() {
                self.audit_state.store(2, Ordering::Release);
            }
        }
        if self.audit_status() != AuditStatus::Verified {
            return Err(RecoveryError::MalformedEvent);
        }
        Ok(())
    }

    fn append_record(&mut self, raw: &[u8]) -> Result<exec_store::LedgerEntry, RecoveryError> {
        self.wait_for_audit()?;
        let identities = if raw.starts_with(CHECKPOINT_MAGIC)
            || raw.starts_with(CHECKPOINT_MANIFEST_MAGIC)
            || raw.starts_with(CHECKPOINT_PAGE_MAGIC)
        {
            Vec::new()
        } else {
            record_identities(&decode(raw)?)
        };
        for (scope, key) in &identities {
            if self.ledger.identity_seen(scope, key)? {
                return Err(RecoveryError::DuplicateIdentity);
            }
        }
        let identities: Vec<_> = identities
            .iter()
            .map(|(scope, key)| (*scope, key.as_slice()))
            .collect();
        Ok(self.ledger.append_identified(raw, &identities)?)
    }
    fn maybe_checkpoint(&mut self) -> Result<(), RecoveryError> {
        if self.records.is_multiple_of(1024) && !self.checkpoint()? {
            eprintln!("executor checkpoint exceeds event bound; retaining verified replay");
        }
        if self.generations.len()
            + self.ceiling_requests.len()
            + self.approval_requests.len()
            + self.account_requests.len()
            > 1024
        {
            self.generations.clear();
            self.ceiling_requests.clear();
            self.approval_requests.clear();
            self.account_requests.clear();
        }
        Ok(())
    }

    /// Only this owner creates snapshots of committed state; request payloads never supply checkpoint state.
    pub fn checkpoint(&mut self) -> Result<bool, RecoveryError> {
        self.wait_for_audit()?;
        let mut saved = Checkpoint {
            tip: self.ledger.tip(),
            intents: self.intents.clone(),
            reservations: self.reservations.clone(),
            legacy_reservations: self.legacy_reservations.clone(),
            credential: self.credential.clone(),
            generations: self.generations.clone(),
            ceiling: self.ceiling.clone(),
            ceiling_requests: self.ceiling_requests.clone(),
            approvals: self.approvals.clone(),
            approval_requests: self.approval_requests.clone(),
            account_observations: self.account_observations.clone(),
            account_requests: self.account_requests.clone(),
            history_through: None,
        };
        saved.bounded_history(saved.tip.0);
        let state = serde_json::to_vec(&saved).map_err(|_| RecoveryError::MalformedEvent)?;
        let mut raw = CHECKPOINT_MAGIC.to_vec();
        raw.extend_from_slice(&exec_store::hash_event(&[0; 32], &state));
        raw.extend_from_slice(&state);
        // shortcut: state above 64 MiB uses full replay; qualify a larger memory budget before raising it.
        if state.len() > MAX_CHECKPOINT_BYTES {
            return Ok(false);
        }
        if raw.len() <= exec_store::MAX_EVENT_BYTES {
            self.append_record(&raw)?;
            self.records += 1;
        } else {
            let digest = exec_store::hash_event(&[0; 32], &state);
            let chunks = state.chunks(exec_store::MAX_EVENT_BYTES - PAGE_HEADER);
            let manifest = CheckpointManifest {
                tip: saved.tip,
                chunks: chunks.len() as u32,
                state_bytes: state.len(),
                digest,
            };
            for (index, chunk) in chunks.enumerate() {
                let mut page = CHECKPOINT_PAGE_MAGIC.to_vec();
                page.extend_from_slice(&(index as u32).to_be_bytes());
                page.extend_from_slice(&digest);
                page.extend_from_slice(chunk);
                self.append_record(&page)?;
                self.records += 1;
            }
            let mut commit = CHECKPOINT_MANIFEST_MAGIC.to_vec();
            commit.extend_from_slice(
                &serde_json::to_vec(&manifest).map_err(|_| RecoveryError::MalformedEvent)?,
            );
            self.append_record(&commit)?;
            self.records += 1;
        }
        self.ceiling_requests.clear();
        self.approval_requests.clear();
        self.account_requests.clear();
        self.generations.clear();
        Ok(true)
    }

    pub fn open(path: impl AsRef<Path>) -> Result<Self, RecoveryError> {
        let (ledger, records) =
            Ledger::open_after_checkpoints(path, &[CHECKPOINT_MAGIC, CHECKPOINT_MANIFEST_MAGIC])?;
        let mut state = Checkpoint::default();
        for e in &records {
            if e.event_bytes.starts_with(CHECKPOINT_PAGE_MAGIC) {
                if e.event_bytes.len() <= PAGE_HEADER {
                    return Err(RecoveryError::MalformedEvent);
                }
                continue;
            }
            if e.event_bytes.starts_with(CHECKPOINT_MANIFEST_MAGIC) {
                if e != &records[0] {
                    return Err(RecoveryError::MalformedEvent);
                }
                let manifest = checkpoint_manifest(e)?;
                let pages = ledger.checkpoint_pages(manifest.tip.0 + 1, e.sequence - 1)?;
                state = restore_checkpoint_pages(e, &pages)?;
                continue;
            }
            if e.event_bytes.starts_with(CHECKPOINT_MAGIC) {
                if e != &records[0] || e.event_bytes.len() < 40 {
                    return Err(RecoveryError::MalformedEvent);
                }
                state = decode_checkpoint(e)?;
                continue;
            }
            state.apply_event(e)?;
            state.bound_recent_ids();
        }
        let Checkpoint {
            intents,
            reservations,
            legacy_reservations,
            credential,
            generations,
            ceiling,
            ceiling_requests,
            approvals,
            approval_requests,
            account_observations,
            account_requests,
            ..
        } = state;
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
        let record_count = ledger
            .tip()
            .0
            .try_into()
            .map_err(|_| RecoveryError::MalformedEvent)?;
        let audit_state = Arc::new(AtomicU8::new(0));
        let audit_result = audit_state.clone();
        let audit_path = ledger.audit_path();
        let audit_tip = ledger.tip();
        let audit = std::thread::Builder::new()
            .name("executor-prefix-audit".into())
            .spawn(move || {
                let result = std::panic::catch_unwind(|| audit_prefix(&audit_path, audit_tip));
                audit_result.store(
                    if matches!(result, Ok(Ok(()))) { 1 } else { 2 },
                    Ordering::Release,
                );
            })
            .map_err(|_| RecoveryError::MalformedEvent)?;
        Ok(Self {
            ledger,
            audit: Some(audit),
            audit_state,
            intents,
            reservations,
            legacy_reservations,
            records: record_count,
            recovered_inflight,
            recovered_cancels,
            credential,
            generations,
            ceiling,
            ceiling_requests,
            approvals,
            approval_requests,
            account_observations,
            account_requests,
        })
    }

    pub fn credential_metadata(&self) -> Option<&CredentialMetadata> {
        self.credential.as_ref()
    }

    /// Receipts are not balance/fee/permission authority. Freshness never survives a new runtime/key.
    pub fn account_observation(
        &self,
        kind: AccountKind,
        generation: [u8; 16],
        epoch: u64,
        now: u64,
        max_age: u64,
    ) -> Option<&AccountObservation> {
        if self.credential.as_ref()?.generation != generation {
            return None;
        }
        self.account_observations
            .get(&(kind, String::new()))
            .filter(|value| value.is_fresh(generation, epoch, now, max_age))
    }

    pub fn known_order_observation(
        &self,
        client_id: &str,
        generation: [u8; 16],
        epoch: u64,
        now: u64,
        max_age: u64,
    ) -> Option<&AccountObservation> {
        if self.credential.as_ref()?.generation != generation {
            return None;
        }
        self.account_observations
            .get(&(AccountKind::KnownClientOrder, client_id.into()))
            .filter(|value| value.is_fresh(generation, epoch, now, max_age))
    }
    pub fn latest_known_order(&self, client_id: &str) -> Option<&AccountObservation> {
        self.account_observations
            .get(&(AccountKind::KnownClientOrder, client_id.into()))
    }

    pub fn order_page_observation(
        &self,
        resource: &exec_ipc::provision::AccountResource,
        generation: [u8; 16],
        epoch: u64,
        now: u64,
        max_age: u64,
    ) -> Option<&AccountObservation> {
        use exec_ipc::provision::AccountResource;
        resource.path().ok()?;
        let (kind, page, per_page) = match resource {
            AccountResource::OpenOrders { page, per_page } => {
                (AccountKind::OpenOrders, page, per_page)
            }
            AccountResource::OrderHistory { page, per_page } => {
                (AccountKind::OrderHistory, page, per_page)
            }
            _ => return None,
        };
        if self.credential.as_ref()?.generation != generation {
            return None;
        }
        self.account_observations
            .get(&(kind, format!("{page}/{per_page}")))
            .filter(|value| value.is_fresh(generation, epoch, now, max_age))
    }

    pub fn record_account_observation(
        &mut self,
        value: AccountObservation,
    ) -> Result<exec_ipc::account::ObservationReceipt, RecoveryError> {
        check_account_observation(
            self.credential.as_ref(),
            &self.account_observations,
            &self.account_requests,
            &value,
        )?;
        let mut raw = MAGIC.to_vec();
        raw.push(ACCOUNT_OBSERVATION);
        add_name(&mut raw, "main")?;
        raw.extend_from_slice(&value.encode().map_err(|_| RecoveryError::InvalidIdentity)?);
        let entry = self.append_record(&raw)?;
        let receipt = value.receipt(entry.sequence, entry.event_hash);
        self.account_requests.insert(value.request_id());
        self.account_observations.insert(value.key(), value);
        self.records += 1;
        self.maybe_checkpoint()?;
        Ok(receipt)
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
        let entry = self.append_record(&value.encode()?)?;
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
        self.maybe_checkpoint()?;
        Ok(())
    }
    pub fn revoke_approval(&mut self, value: ApprovalRevocation) -> Result<(), RecoveryError> {
        check_revocation(&self.approvals, &self.approval_requests, &value)?;
        let entry = self.append_record(&value.encode()?)?;
        self.approval_requests.insert(value.request_id);
        let current = self.approvals.get_mut(&value.client_id).unwrap();
        current.sequence = entry.sequence;
        current.revoked_at_ms = Some(value.recorded_at_ms);
        self.records += 1;
        self.maybe_checkpoint()?;
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
        let entry = self.append_record(&value.encode()?)?;
        self.approval_requests.insert(value.request_id);
        let saved = self.approvals.get_mut(&value.client_id).unwrap();
        saved.prepared_at_ms = Some(value.recorded_at_ms);
        saved.sequence = entry.sequence;
        self.records += 1;
        self.maybe_checkpoint()?;
        Ok(())
    }

    /// Journal mechanics alone grant no authority; native admission supplies authenticated receipts.
    pub fn reserve_prepared_intent(
        &mut self,
        context: IntentPreparation,
        snapshot: &BalanceSnapshot,
    ) -> Result<(), RecoveryError> {
        self.reserve_review(context, snapshot, None)
    }

    /// Native admission includes a conservative outgoing-base fee in a sell hold.
    pub fn reserve_prepared_with_hold(
        &mut self,
        context: IntentPreparation,
        snapshot: &BalanceSnapshot,
        held_quanta: u64,
    ) -> Result<(), RecoveryError> {
        self.reserve_review(context, snapshot, Some(held_quanta))
    }

    fn reserve_review(
        &mut self,
        context: IntentPreparation,
        snapshot: &BalanceSnapshot,
        held_quanta: Option<u64>,
    ) -> Result<(), RecoveryError> {
        if self
            .intents
            .keys()
            .any(|id| self.legacy_reservations.is_reserved(id))
        {
            return Err(RecoveryError::Reservation(
                ReservationError::InvalidEvidence,
            ));
        }
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
            held_quanta,
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
        let entry = self.append_record(&value.encode()?)?;
        self.intents = intents;
        self.reservations = reservations;
        self.approval_requests.insert(value.context.request_id);
        self.approvals
            .get_mut(&value.context.client_id)
            .unwrap()
            .sequence = entry.sequence;
        self.records += 1;
        self.maybe_checkpoint()?;
        Ok(())
    }
    pub fn commit_ceiling(&mut self, change: CeilingChange) -> Result<(), RecoveryError> {
        check_ceiling(self.ceiling.as_ref(), &self.ceiling_requests, &change)?;
        let entry = self.append_record(&change.encode()?)?;
        self.ceiling_requests.insert(change.request_id);
        self.ceiling = Some((entry.sequence, change));
        self.records += 1;
        self.maybe_checkpoint()?;
        Ok(())
    }

    /// Call only after the immutable ciphertext generation has been durably published.
    pub fn commit_credential(&mut self, metadata: CredentialMetadata) -> Result<(), RecoveryError> {
        let raw = metadata.encode()?;
        if self.generations.contains(&metadata.generation) {
            return Err(RecoveryError::DuplicateIdentity);
        }
        self.append_record(&raw)?;
        self.generations.insert(metadata.generation);
        self.credential = Some(metadata);
        self.records += 1;
        self.maybe_checkpoint()?;
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
        let mut next_legacy = self.legacy_reservations.clone();
        apply_record(&mut next, &mut next_holds, &mut next_legacy, parsed)?;
        self.append_record(&raw)?;
        self.intents = next;
        self.reservations = next_holds;
        self.legacy_reservations = next_legacy;
        self.records += 1;
        self.maybe_checkpoint()?;
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
        let mut next_legacy = self.legacy_reservations.clone();
        apply_record(&mut next, &mut next_holds, &mut next_legacy, parsed)?;
        self.append_record(&raw)?;
        self.intents = next;
        self.reservations = next_holds;
        self.legacy_reservations = next_legacy;
        self.records += 1;
        self.maybe_checkpoint()?;
        Ok(())
    }
    /// Legacy model admission. A snapshot alone is never authenticated evidence.
    pub fn reserve_intent(
        &mut self,
        id: &str,
        quanta: u64,
        snapshot: &BalanceSnapshot,
    ) -> Result<(), RecoveryError> {
        if self
            .intents
            .keys()
            .any(|id| self.reservations.is_reserved(id))
        {
            return Err(RecoveryError::Reservation(
                ReservationError::InvalidEvidence,
            ));
        }
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
    /// Closing and releasing a reviewed hold are one commit, so a crash cannot strand a closed hold.
    pub fn settle_reviewed(
        &mut self,
        id: &str,
        filled: u64,
        balance: &SettlementEvidence,
    ) -> Result<(), RecoveryError> {
        let mut raw = record_release_settled(id, balance)?;
        raw[MAGIC.len()] = REVIEW_SETTLED;
        raw.extend_from_slice(&filled.to_be_bytes());
        self.apply_durable(raw)
    }
    pub fn reviewed_pending_ids(&self) -> Vec<String> {
        self.intents
            .iter()
            .filter(|(id, order)| {
                order.review_ticket.is_some()
                    && (order.attempt.holds_slot() || self.reservations.is_reserved(id))
            })
            .map(|(id, _)| id.clone())
            .collect()
    }
    pub fn reconciliation_ready(&self) -> bool {
        use exec_core::orders::Lifecycle;
        self.intents
            .iter()
            .all(|(id, order)| match order.attempt.lifecycle() {
                Lifecycle::Acknowledged | Lifecycle::Working => order.review_ticket.is_some(),
                Lifecycle::Closed | Lifecycle::Denied => {
                    !self.reservations.is_reserved(id) && !self.legacy_reservations.is_reserved(id)
                }
                _ => false,
            })
    }
    /// A failed transition is not appended and does not change any hold.
    fn apply_durable(&mut self, raw: Vec<u8>) -> Result<(), RecoveryError> {
        let parsed = decode(&raw)?;
        let mut next = self.intents.clone();
        let mut next_holds = self.reservations.clone();
        let mut next_legacy = self.legacy_reservations.clone();
        apply_record(&mut next, &mut next_holds, &mut next_legacy, parsed)?;
        self.append_record(&raw)?;
        self.intents = next;
        self.reservations = next_holds;
        self.legacy_reservations = next_legacy;
        self.records += 1;
        self.maybe_checkpoint()?;
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
        if self
            .intents
            .keys()
            .any(|id| self.legacy_reservations.is_reserved(id))
        {
            return Err(RecoveryError::Reservation(
                ReservationError::InvalidEvidence,
            ));
        }
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
        self.reservations
            .reserved(account, asset)
            .saturating_add(self.legacy_reservations.reserved(account, asset))
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
    /// History is protected native receipt data; active orders also require a current read.
    pub fn reviewed_risk_orders(
        &self,
        generation: [u8; 16],
        epoch: u64,
        now: u64,
    ) -> Option<Vec<crate::native_risk::OwnOrder<'_>>> {
        self.intents
            .iter()
            .filter(|(_, order)| order.attempt.lifecycle() != exec_core::orders::Lifecycle::Denied)
            .map(|(id, order)| {
                let ticket = order.review_ticket.as_ref()?;
                let observation = self
                    .account_observations
                    .get(&(AccountKind::KnownClientOrder, id.clone()))?;
                if order.attempt.holds_slot()
                    && !observation.is_fresh(generation, epoch, now, 30_000)
                {
                    return None;
                }
                let submitted_at_ms = self.approvals.get(id)?.prepared_at_ms?;
                Some(crate::native_risk::OwnOrder {
                    ticket,
                    observation,
                    submitted_at_ms,
                })
            })
            .collect()
    }
    pub fn record_count(&self) -> usize {
        self.records
    }
}

#[cfg(test)]
#[path = "../checkpoint_tests.rs"]
mod checkpoint_tests;
