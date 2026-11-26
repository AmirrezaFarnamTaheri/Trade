use super::*;

pub(super) enum Record {
    AccountObservation(AccountObservation),
    ReviewedReservation(ReviewedReservation),
    ReviewSettled {
        id: String,
        filled: u64,
        balance: SettlementEvidence,
    },
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
pub(super) fn valid_name(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 96
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_' | b':' | b'.'))
}
pub(super) fn add_name(data: &mut Vec<u8>, name: &str) -> Result<(), RecoveryError> {
    if !valid_name(name) {
        return Err(RecoveryError::InvalidIdentity);
    }
    data.push(u8::try_from(name.len()).map_err(|_| RecoveryError::InvalidIdentity)?);
    data.extend_from_slice(name.as_bytes());
    Ok(())
}
pub(super) fn record_intent(
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
pub(super) fn record_event(id: &str, event: Event) -> Result<Vec<u8>, RecoveryError> {
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
        AbandonUnsent => 18,
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
pub(super) fn record_hold(
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
pub(super) fn record_release_denied(id: &str) -> Result<Vec<u8>, RecoveryError> {
    let mut data = MAGIC.to_vec();
    data.push(RELEASE_DENIED);
    add_name(&mut data, id)?;
    Ok(data)
}
pub(super) fn record_release_settled(
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

pub(super) fn record_execution(
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
pub(super) fn record_execution_settlement(
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

pub(super) struct Reader<'a> {
    bytes: &'a [u8],
    pos: usize,
}
impl<'a> Reader<'a> {
    pub(super) fn take(&mut self, len: usize) -> Result<&'a [u8], RecoveryError> {
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
    pub(super) fn one(&mut self) -> Result<u8, RecoveryError> {
        Ok(self.take(1)?[0])
    }
    pub(super) fn num(&mut self) -> Result<u64, RecoveryError> {
        let bytes: [u8; 8] = self
            .take(8)?
            .try_into()
            .map_err(|_| RecoveryError::MalformedEvent)?;
        Ok(u64::from_be_bytes(bytes))
    }
    pub(super) fn name(&mut self) -> Result<String, RecoveryError> {
        let len = self.one()? as usize;
        let bytes = self.take(len)?;
        let name = std::str::from_utf8(bytes).map_err(|_| RecoveryError::MalformedEvent)?;
        if !valid_name(name) {
            return Err(RecoveryError::MalformedEvent);
        }
        Ok(name.to_owned())
    }
}
pub(super) fn decode(raw: &[u8]) -> Result<Record, RecoveryError> {
    let mut r = Reader { bytes: raw, pos: 0 };
    if r.take(MAGIC.len())? != MAGIC {
        return Err(RecoveryError::MalformedEvent);
    }
    let kind = r.one()?;
    let id = r.name()?;
    let rec = match kind {
        ACCOUNT_OBSERVATION => {
            if id != "main" {
                return Err(RecoveryError::MalformedEvent);
            }
            Record::AccountObservation(
                AccountObservation::decode(r.take(raw.len() - r.pos)?)
                    .map_err(|_| RecoveryError::MalformedEvent)?,
            )
        }
        PREPARE_INTENT | RESERVE_REVIEW | RESERVE_REVIEW_WITH_FEE => {
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
                    held_quanta: if kind == RESERVE_REVIEW_WITH_FEE {
                        Some(r.num()?)
                    } else {
                        None
                    },
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
                18 => AbandonUnsent,
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
        RELEASE_SETTLED | REVIEW_SETTLED => {
            let account = r.name()?;
            let asset = r.name()?;
            let sequence = r.num()?;
            let complete = match r.one()? {
                0 => false,
                1 => true,
                _ => return Err(RecoveryError::MalformedEvent),
            };
            let locked = r.num()?;
            let spent = r.num()?;
            let available = r.num()?;
            if kind == REVIEW_SETTLED {
                Record::ReviewSettled {
                    id,
                    filled: r.num()?,
                    balance: SettlementEvidence {
                        account,
                        asset,
                        sequence,
                        complete,
                        locked_quanta: locked,
                        spent_quanta: spent,
                        available_quanta: available,
                    },
                }
            } else {
                Record::ReleaseSettled {
                    id,
                    account,
                    asset,
                    sequence,
                    complete,
                    locked,
                    spent,
                    available,
                }
            }
        }
        _ => return Err(RecoveryError::MalformedEvent),
    };
    if r.pos != raw.len() {
        return Err(RecoveryError::MalformedEvent);
    }
    Ok(rec)
}
