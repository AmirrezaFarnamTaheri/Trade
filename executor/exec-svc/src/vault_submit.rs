use super::{now_ms, random_id, require_service_identity, AccountRead, Vault};
use exec_core::orders::{Event, Lifecycle};
use exec_ipc::{
    provision::{AccountResource, StartupMode},
    submit::{SubmitReply, SubmitRequest, SubmitState},
    StopMode,
};
use exec_svc::{
    account_observation::{AccountKind, AccountObservation},
    native_admission::{self, NativeInputs},
    native_effect::{self, SendOutcome},
    offline_recovery::{IntentPreparation, RecoveryError},
};
use std::io;

impl Vault {
    pub fn submit(
        &mut self,
        request: &SubmitRequest,
        user: &str,
        logon: &str,
        operator_user: &str,
        operator_logon: &str,
        gate: &exec_svc::StopGate,
    ) -> io::Result<SubmitReply> {
        require_service_identity()?;
        let mut reply = SubmitReply {
            state: SubmitState::Refused,
            mode: gate.mode(),
            runtime_epoch: gate.runtime_epoch(),
            correlation: request.correlation,
            sequence: 0,
            client_id: request.client_id.clone(),
        };
        if self.mode != StartupMode::Normal
            || user != operator_user
            || logon != operator_logon
            || request.runtime_epoch != gate.runtime_epoch()
        {
            return Ok(reply);
        }
        if !request.submit {
            reply.state = self
                .limits
                .as_ref()
                .and_then(|ledger| ledger.get(&request.client_id))
                .map_or(SubmitState::Missing, |order| {
                    match order.attempt.lifecycle() {
                        Lifecycle::Closed => SubmitState::Settled,
                        Lifecycle::Denied | Lifecycle::NotSent => SubmitState::NotSent,
                        Lifecycle::Acknowledged
                        | Lifecycle::Working
                        | Lifecycle::TerminalReported
                        | Lifecycle::Rejected => SubmitState::Observed,
                        _ => SubmitState::Pending,
                    }
                });
        } else {
            let outcome = self.submit_once(request, user, logon, gate);
            self.disarm();
            match outcome {
                Ok(Some(SendOutcome::Observed)) => reply.state = SubmitState::Observed,
                Ok(Some(SendOutcome::Pending)) => reply.state = SubmitState::Pending,
                Ok(Some(SendOutcome::NotSent)) => reply.state = SubmitState::NotSent,
                Ok(None) => {}
                Err(error) => return Err(error),
            }
        }
        reply.mode = gate.mode();
        reply.sequence = self
            .limits
            .as_ref()
            .and_then(|ledger| ledger.operator_approval(&request.client_id))
            .map_or(0, |saved| saved.sequence);
        Ok(reply)
    }

    fn submit_once(
        &mut self,
        request: &SubmitRequest,
        user: &str,
        logon: &str,
        gate: &exec_svc::StopGate,
    ) -> io::Result<Option<SendOutcome>> {
        if gate.mode() != StopMode::Armed || request.arm_revision != gate.revision() {
            return Ok(None);
        }
        let Some(policy) = self.arm_controller.policy().cloned() else {
            return Ok(None);
        };
        let at = now_ms()?;
        let Some(generation) = self.journal.credential_metadata().map(|key| key.generation) else {
            return Ok(None);
        };
        let Some(owner) = self.owner_review.as_ref() else {
            return Ok(None);
        };
        let Ok(_owner_lease) = owner.verify(&policy, generation, gate.runtime_epoch(), at) else {
            return Ok(None);
        };
        let evidence = self.arm_evidence(&policy, at, gate)?;
        let Some(risk) = self.measured_risk(&policy, generation, gate.runtime_epoch(), at) else {
            return Ok(None);
        };
        let Some(fees) = self
            .journal
            .account_observation(
                AccountKind::Fees,
                generation,
                gate.runtime_epoch(),
                at,
                30_000,
            )
            .cloned()
        else {
            return Ok(None);
        };
        let Some(ledger) = self.limits.as_ref() else {
            return Ok(None);
        };
        let Some(saved) = ledger.operator_approval(&request.client_id) else {
            return Ok(None);
        };
        let symbol = format!(
            "{}{}",
            saved.approval.ticket.base, saved.approval.ticket.quote
        );
        let Some(market) = self.native_markets.get(&symbol) else {
            return Ok(None);
        };
        let Some(key) = self.load_current_secret()? else {
            return Ok(None);
        };
        let context = IntentPreparation {
            client_id: request.client_id.clone(),
            expected_sequence: request.expected_sequence,
            principal: user.into(),
            logon: logon.into(),
            runtime_epoch: gate.runtime_epoch(),
            credential_generation: generation,
            recorded_at_ms: at,
            request_id: request.correlation,
            mode: gate.mode(),
        };
        let order = match native_admission::admit(
            &mut self.arm_controller,
            gate,
            self.limits.as_mut().unwrap(),
            context,
            NativeInputs {
                arm: &evidence,
                balances: &self.balances,
                fees: &fees,
                market,
                own_inventory: &risk.own_inventory,
                net_debits_quote: risk.net_debits_quote,
            },
        ) {
            Ok(order) => order,
            Err(RecoveryError::Ledger(_)) => {
                return Err(io::Error::other("native admission commit uncertain"))
            }
            Err(_) => return Ok(None),
        };
        // The vault lock excludes another admission while this activity invalidates the old pair.
        if self.balances.own_activity(now_ms()?).is_err() {
            let ledger = self.limits.as_mut().unwrap();
            ledger
                .record_event(&request.client_id, Event::Denied)
                .and_then(|_| ledger.release_denied_reservation(&request.client_id))
                .map_err(|_| io::Error::other("unsent hold release uncertain"))?;
            return Err(io::Error::other("native activity fence failed"));
        }
        let started = now_ms()?;
        let read_id = random_id()?;
        let owner = self.owner_review.as_ref().unwrap();
        let mut response = None;
        let outcome = native_effect::execute(
            self.limits.as_mut().unwrap(),
            &order,
            gate,
            || now_ms().ok(),
            |body, allowed| {
                let raw = crate::service_account::submit(&key, body, || {
                    allowed()
                        && now_ms().ok().is_some_and(|now| {
                            owner
                                .verify(&policy, generation, gate.runtime_epoch(), now)
                                .is_ok()
                        })
                })?;
                let matched = now_ms()
                    .ok()
                    .and_then(|received| {
                        AccountObservation::from_order_response(
                            &request.client_id,
                            &raw.0,
                            generation,
                            gate.runtime_epoch(),
                            read_id,
                            started,
                            received,
                        )
                        .ok()
                    })
                    .is_some_and(|observed| {
                        exec_svc::native_risk::matches_ticket(&order.ticket, &observed)
                    });
                response = Some(raw);
                Ok(matched)
            },
        )
        .map_err(|_| io::Error::other("native send journal commit uncertain"))?;
        if let Some(body) = response {
            let read = AccountRead {
                key,
                generation,
                started_at_ms: started,
                balance_read: None,
            };
            let _saved = self.finish_account_read(
                read,
                &AccountResource::KnownClientOrder(request.client_id.clone()),
                Ok(body),
                read_id,
                gate.runtime_epoch(),
            )?;
        }
        Ok(Some(outcome))
    }
}
