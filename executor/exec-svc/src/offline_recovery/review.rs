use super::*;

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct OperatorApproval {
    pub ticket: exec_ipc::review::Ticket,
    pub principal: String,
    pub logon: String,
    pub recorded_at_ms: u64,
    pub request_id: [u8; 16],
    pub mode: exec_ipc::StopMode,
}
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
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
    pub(super) fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
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
    pub(super) fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
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
    pub(super) fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
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
pub(super) fn validate_review_actor(
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
pub(super) fn check_approval(
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
        false,
    )
}
pub(super) fn check_review_context(
    sequence: u64,
    limit: &CeilingChange,
    ticket: &exec_ipc::review::Ticket,
    principal: &str,
    at: u64,
    mode: exec_ipc::StopMode,
    prepared: bool,
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
        || (ticket.buy
            && mode != exec_ipc::StopMode::Disarmed
            && !(prepared && mode == exec_ipc::StopMode::Armed))
        || ticket.max_quote_debit > limit.ceiling.capital_quanta
    {
        return Err(RecoveryError::InvalidIdentity);
    }
    Ok(())
}
pub(super) fn check_preparation(
    current: Option<&(u64, CeilingChange)>,
    approvals: &BTreeMap<String, ApprovalView>,
    requests: &BTreeSet<[u8; 16]>,
    value: &IntentPreparation,
) -> Result<(), RecoveryError> {
    check_review_action(current, approvals, requests, value, false)
}
pub(super) fn check_review_action(
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
        prepared,
    )
}
pub(super) fn check_revocation(
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
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
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
    pub(super) fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
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

pub(super) fn check_ceiling(
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

#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum CredentialPermission {
    Unverified,
}

/// Ciphertext identity only. This record never confers executor authority.
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CredentialMetadata {
    pub generation: [u8; 16],
    pub ciphertext_digest: [u8; 32],
    pub permission: CredentialPermission,
}
impl CredentialMetadata {
    pub(super) fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
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

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
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

pub(super) struct ReviewedReservation {
    pub(super) context: IntentPreparation,
    pub(super) ticket: exec_ipc::review::Ticket,
    pub(super) snapshot: BalanceSnapshot,
    pub(super) held_quanta: Option<u64>,
}
impl ReviewedReservation {
    pub(super) fn encode(&self) -> Result<Vec<u8>, RecoveryError> {
        let mut raw = self.context.encode()?;
        raw[MAGIC.len()] = if self.held_quanta.is_some() {
            RESERVE_REVIEW_WITH_FEE
        } else {
            RESERVE_REVIEW
        };
        raw.extend_from_slice(
            &self
                .ticket
                .encode()
                .map_err(|_| RecoveryError::InvalidIdentity)?,
        );
        raw.extend_from_slice(&self.snapshot.available_quanta.to_be_bytes());
        raw.extend_from_slice(&self.snapshot.sequence.to_be_bytes());
        if let Some(held) = self.held_quanta {
            raw.extend_from_slice(&held.to_be_bytes());
        }
        Ok(raw)
    }
}
pub(super) fn apply_review_reservation(
    current: Option<&(u64, CeilingChange)>,
    approvals: &BTreeMap<String, ApprovalView>,
    requests: &BTreeSet<[u8; 16]>,
    intents: &mut BTreeMap<String, ObservedIntent>,
    reservations: &mut ActiveHoldBook,
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
    let ordinary_hold = if ticket.buy {
        ticket.max_quote_debit
    } else {
        ticket.quantity_quanta
    };
    let quanta = value.held_quanta.unwrap_or(ordinary_hold);
    if (ticket.buy && quanta != ordinary_hold)
        || quanta < ordinary_hold
        || (!ticket.buy && quanta > ordinary_hold.saturating_mul(2))
    {
        return Err(RecoveryError::InvalidIdentity);
    }
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
        .reserve_order(
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

#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum Side {
    Buy,
    Sell,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum Purpose {
    Entry,
    Conversion,
    ProtectiveExit,
}

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
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
    pub(super) fn validate(&self) -> Result<(), RecoveryError> {
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

#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ExecutionSettlement {
    pub filled_quanta: u64,
    pub gross_quote_quanta: u64,
    pub fee_asset: String,
    pub fee_quanta: u64,
    pub balance: SettlementEvidence,
}

pub(super) fn check_account_observation(
    credential: Option<&CredentialMetadata>,
    observations: &BTreeMap<(AccountKind, String), AccountObservation>,
    requests: &BTreeSet<[u8; 16]>,
    value: &AccountObservation,
) -> Result<(), RecoveryError> {
    // Freshness is per resource: a read that started before the newest read of the same resource
    // finished cannot replace it. Unrelated resources (balances versus fees, other pages) do not
    // block each other. Every ledger written under the older all-resources rule also passes this.
    if credential.is_none_or(|key| key.generation != value.generation())
        || requests.contains(&value.request_id())
        || observations
            .get(&value.key())
            .is_some_and(|old| value.started_at_ms() < old.received_at_ms())
    {
        return Err(RecoveryError::InvalidIdentity);
    }
    Ok(())
}
