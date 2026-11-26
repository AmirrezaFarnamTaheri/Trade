use super::*;

impl Checkpoint {
    pub(super) fn apply_event(&mut self, e: &exec_store::LedgerEntry) -> Result<(), RecoveryError> {
        let Self {
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
        } = self;
        let parsed = decode(&e.event_bytes)?;
        if let Record::AccountObservation(value) = parsed {
            check_account_observation(
                credential.as_ref(),
                account_observations,
                account_requests,
                &value,
            )
            .map_err(|_| RecoveryError::MalformedEvent)?;
            account_requests.insert(value.request_id());
            account_observations.insert(value.key(), value);
            return Ok(());
        }
        if let Record::ReviewedReservation(value) = parsed {
            apply_review_reservation(
                ceiling.as_ref(),
                approvals,
                approval_requests,
                intents,
                reservations,
                &value,
            )
            .map_err(|_| RecoveryError::MalformedEvent)?;
            approval_requests.insert(value.context.request_id);
            approvals
                .get_mut(&value.context.client_id)
                .unwrap()
                .sequence = e.sequence;
            return Ok(());
        }
        if let Record::PrepareIntent(value) = parsed {
            check_preparation(ceiling.as_ref(), approvals, approval_requests, &value)
                .map_err(|_| RecoveryError::MalformedEvent)?;
            if intents.contains_key(&value.client_id) {
                return Err(RecoveryError::MalformedEvent);
            }
            approval_requests.insert(value.request_id);
            let saved = approvals.get_mut(&value.client_id).unwrap();
            saved.prepared_at_ms = Some(value.recorded_at_ms);
            saved.sequence = e.sequence;
            return Ok(());
        }
        if let Record::Approval(value) = parsed {
            check_approval(ceiling.as_ref(), approvals, approval_requests, &value)
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
            return Ok(());
        }
        if let Record::RevokeApproval(value) = parsed {
            check_revocation(approvals, approval_requests, &value)
                .map_err(|_| RecoveryError::MalformedEvent)?;
            approval_requests.insert(value.request_id);
            let current = approvals.get_mut(&value.client_id).unwrap();
            current.sequence = e.sequence;
            current.revoked_at_ms = Some(value.recorded_at_ms);
            return Ok(());
        }
        if let Record::Ceiling(change) = parsed {
            check_ceiling(ceiling.as_ref(), ceiling_requests, &change)
                .map_err(|_| RecoveryError::MalformedEvent)?;
            ceiling_requests.insert(change.request_id);
            *ceiling = Some((e.sequence, change));
            return Ok(());
        }
        if let Record::Credential(metadata) = parsed {
            if !generations.insert(metadata.generation) {
                return Err(RecoveryError::MalformedEvent);
            }
            *credential = Some(metadata);
            return Ok(());
        }
        // Verified bytes that cannot form a legal state also fail closed.
        if matches!(&parsed, Record::Open { id, .. } | Record::Execution { id, .. } if approvals.contains_key(id))
        {
            return Err(RecoveryError::MalformedEvent);
        }
        apply_record(intents, reservations, legacy_reservations, parsed)
            .map_err(|_| RecoveryError::MalformedEvent)?;
        Ok(())
    }

    pub(super) fn bounded_history(&mut self, through: u64) {
        self.generations.clear();
        self.ceiling_requests.clear();
        self.approval_requests.clear();
        self.account_requests.clear();
        self.history_through = Some(through);
    }

    pub(super) fn bound_recent_ids(&mut self) {
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
    }
}

pub(super) fn decode_checkpoint(e: &exec_store::LedgerEntry) -> Result<Checkpoint, RecoveryError> {
    if e.event_bytes.len() < 40 {
        return Err(RecoveryError::MalformedEvent);
    }
    let raw = &e.event_bytes[40..];
    if exec_store::hash_event(&[0; 32], raw).as_slice() != &e.event_bytes[8..40] {
        return Err(RecoveryError::MalformedEvent);
    }
    let saved: Checkpoint =
        serde_json::from_slice(raw).map_err(|_| RecoveryError::MalformedEvent)?;
    if saved.tip != (e.sequence - 1, e.previous_hash)
        || saved
            .history_through
            .is_some_and(|through| through != saved.tip.0)
        || serde_json::to_vec(&saved).map_err(|_| RecoveryError::MalformedEvent)? != raw
    {
        return Err(RecoveryError::MalformedEvent);
    }
    Ok(saved)
}

pub(super) fn record_identities(record: &Record) -> Vec<(&'static str, Vec<u8>)> {
    let (scope, key) = match record {
        Record::AccountObservation(value) => ("account_request", value.request_id().to_vec()),
        Record::ReviewedReservation(value) => {
            ("approval_request", value.context.request_id.to_vec())
        }
        Record::PrepareIntent(value) => ("approval_request", value.request_id.to_vec()),
        Record::Approval(value) => {
            return vec![
                ("approval_request", value.request_id.to_vec()),
                ("client", value.ticket.client_id.as_bytes().to_vec()),
            ]
        }
        Record::RevokeApproval(value) => ("approval_request", value.request_id.to_vec()),
        Record::Ceiling(value) => ("ceiling_request", value.request_id.to_vec()),
        Record::Credential(value) => ("generation", value.generation.to_vec()),
        Record::Open { id, .. } | Record::Execution { id, .. } => {
            ("client", id.as_bytes().to_vec())
        }
        _ => return Vec::new(),
    };
    vec![(scope, key)]
}

pub(super) fn checkpoint_manifest(
    entry: &exec_store::LedgerEntry,
) -> Result<CheckpointManifest, RecoveryError> {
    let raw = entry
        .event_bytes
        .get(8..)
        .ok_or(RecoveryError::MalformedEvent)?;
    let manifest: CheckpointManifest =
        serde_json::from_slice(raw).map_err(|_| RecoveryError::MalformedEvent)?;
    if manifest.chunks < 2
        || manifest.state_bytes > MAX_CHECKPOINT_BYTES
        || manifest.state_bytes <= exec_store::MAX_EVENT_BYTES - 40
        || manifest.tip.0.checked_add(u64::from(manifest.chunks) + 1) != Some(entry.sequence)
        || serde_json::to_vec(&manifest).map_err(|_| RecoveryError::MalformedEvent)? != raw
    {
        return Err(RecoveryError::MalformedEvent);
    }
    Ok(manifest)
}

pub(super) fn restore_checkpoint_pages(
    entry: &exec_store::LedgerEntry,
    pages: &[exec_store::LedgerEntry],
) -> Result<Checkpoint, RecoveryError> {
    let manifest = checkpoint_manifest(entry)?;
    if pages.len() != manifest.chunks as usize {
        return Err(RecoveryError::MalformedEvent);
    }
    let mut raw = CHECKPOINT_MAGIC.to_vec();
    raw.extend_from_slice(&manifest.digest);
    let mut previous = manifest.tip.1;
    for (index, page) in pages.iter().enumerate() {
        if !page.event_bytes.starts_with(CHECKPOINT_PAGE_MAGIC)
            || page.event_bytes.len() <= PAGE_HEADER
            || page.sequence != manifest.tip.0 + index as u64 + 1
            || page.previous_hash != previous
            || page.event_bytes[8..12] != (index as u32).to_be_bytes()
            || page.event_bytes[12..44] != manifest.digest
            || (index + 1 < pages.len() && page.event_bytes.len() != exec_store::MAX_EVENT_BYTES)
        {
            return Err(RecoveryError::MalformedEvent);
        }
        raw.extend_from_slice(&page.event_bytes[PAGE_HEADER..]);
        if raw.len() > manifest.state_bytes + 40 {
            return Err(RecoveryError::MalformedEvent);
        }
        previous = page.event_hash;
    }
    if raw.len() != manifest.state_bytes + 40 || previous != entry.previous_hash {
        return Err(RecoveryError::MalformedEvent);
    }
    decode_checkpoint(&exec_store::LedgerEntry {
        sequence: manifest.tip.0 + 1,
        previous_hash: manifest.tip.1,
        event_bytes: raw,
        event_hash: [0; 32],
    })
}

pub(super) fn retain_checkpoint_page(
    pages: &mut Vec<exec_store::LedgerEntry>,
    entry: &exec_store::LedgerEntry,
) -> Result<(), RecoveryError> {
    if entry.event_bytes.len() <= PAGE_HEADER {
        return Err(RecoveryError::MalformedEvent);
    }
    let index = u32::from_be_bytes(entry.event_bytes[8..12].try_into().unwrap()) as usize;
    if index == 0 {
        pages.clear();
    }
    if index != pages.len()
        || (index + 1) * (exec_store::MAX_EVENT_BYTES - PAGE_HEADER)
            > MAX_CHECKPOINT_BYTES + exec_store::MAX_EVENT_BYTES
    {
        return Err(RecoveryError::MalformedEvent);
    }
    pages.push(entry.clone());
    Ok(())
}

pub(super) fn audit_prefix(path: &Path, tip: (u64, [u8; 32])) -> Result<(), LedgerError> {
    let mut state = Checkpoint::default();
    let mut pages = Vec::new();
    Ledger::audit_prefix(path, tip, |entry, index| {
        let malformed = || LedgerError::Integrity {
            sequence: entry.sequence,
            reason: "independent journal replay disagrees with checkpoint",
        };
        if entry.event_bytes.starts_with(CHECKPOINT_PAGE_MAGIC) {
            retain_checkpoint_page(&mut pages, entry).map_err(|_| malformed())?;
            state.tip = (entry.sequence, entry.event_hash);
            return Ok(());
        }
        if entry.event_bytes.starts_with(CHECKPOINT_MAGIC)
            || entry.event_bytes.starts_with(CHECKPOINT_MANIFEST_MAGIC)
        {
            let saved = if entry.event_bytes.starts_with(CHECKPOINT_MAGIC) {
                decode_checkpoint(entry)
            } else {
                restore_checkpoint_pages(entry, &pages)
            }
            .map_err(|_| malformed())?;
            let mut expected = state.clone();
            expected.tip = saved.tip;
            if saved.history_through.is_some() {
                expected.bounded_history(saved.tip.0);
            } else {
                expected.history_through = None;
                let keys = |scope| -> Result<BTreeSet<[u8; 16]>, LedgerError> {
                    index
                        .keys(scope)?
                        .into_iter()
                        .map(|key| key.try_into().map_err(|_| malformed()))
                        .collect()
                };
                expected.generations = keys("generation")?;
                expected.ceiling_requests = keys("ceiling_request")?;
                expected.approval_requests = keys("approval_request")?;
                expected.account_requests = keys("account_request")?;
            }
            if serde_json::to_vec(&expected).map_err(|_| malformed())?
                != serde_json::to_vec(&saved).map_err(|_| malformed())?
            {
                return Err(malformed());
            }
            state = expected;
        } else {
            let record = decode(&entry.event_bytes).map_err(|_| malformed())?;
            let identities = record_identities(&record);
            for (scope, key) in &identities {
                if index.contains(scope, key)? {
                    return Err(malformed());
                }
            }
            state.apply_event(entry).map_err(|_| malformed())?;
            for (scope, key) in identities {
                index.remember(scope, &key, entry.sequence)?;
            }
            state.bound_recent_ids();
        }
        pages.clear();
        state.tip = (entry.sequence, entry.event_hash);
        Ok(())
    })
}
