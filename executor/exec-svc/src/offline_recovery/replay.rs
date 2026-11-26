use super::*;

pub(super) fn apply_record(
    intents: &mut BTreeMap<String, ObservedIntent>,
    reservations: &mut ActiveHoldBook,
    legacy: &mut ReservationBook,
    record: Record,
) -> Result<(), RecoveryError> {
    match record {
        Record::AccountObservation(_)
        | Record::Credential(_)
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
                .reserve_order(&id, &account, asset, reserved, &snapshot, &attempt)
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
                .release_settled(&id, &order.attempt, &settlement.balance)
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
        Record::ReviewSettled {
            id,
            filled,
            balance,
        } => {
            use exec_core::orders::Lifecycle;
            let order = intents.get_mut(&id).ok_or(RecoveryError::UnknownIdentity)?;
            if order.review_ticket.is_none() {
                return Err(RecoveryError::InvalidIdentity);
            }
            let mut next = order.attempt;
            if matches!(next.lifecycle(), Lifecycle::Submitting | Lifecycle::Unknown) {
                next.apply(Event::Acknowledged)
                    .map_err(RecoveryError::Order)?;
            }
            next.apply(Event::CumulativeFilled(filled))
                .map_err(RecoveryError::Order)?;
            if next.lifecycle() != Lifecycle::TerminalReported {
                next.apply(Event::TerminalReported)
                    .map_err(RecoveryError::Order)?;
            }
            next.apply(Event::SettlementVerified)
                .map_err(RecoveryError::Order)?;
            reservations
                .release_settled(&id, &next, &balance)
                .map_err(RecoveryError::Reservation)?;
            order.attempt = next;
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
            legacy
                .reserve(&id, &account, &asset, quanta, &snapshot, &order.attempt)
                .map_err(RecoveryError::Reservation)?;
        }
        Record::ReleaseDenied { id } => {
            let order = intents.get(&id).ok_or(RecoveryError::UnknownIdentity)?;
            if legacy.is_reserved(&id) {
                legacy.release_denied(&id, &order.attempt)
            } else {
                reservations.release_denied(&id, &order.attempt)
            }
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
            legacy
                .release_settled(&id, &order.attempt, &evidence)
                .map_err(RecoveryError::Reservation)?;
        }
    }
    Ok(())
}
