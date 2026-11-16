//! One durable attempt. Before-byte failure abandons the identity; uncertain sends retain every hold.
use crate::{
    native_admission::AdmittedOrder,
    offline_recovery::{DurableOrderJournal, RecoveryError},
    StopGate,
};
use exec_core::orders::{Event, FailureStage, Lifecycle};
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SendOutcome {
    NotSent,
    Pending,
    Observed,
}

pub fn execute(
    ledger: &mut DurableOrderJournal,
    order: &AdmittedOrder,
    gate: &StopGate,
    clock: impl Fn() -> Option<u64>,
    transport: impl FnOnce(&[u8], &mut dyn FnMut() -> bool) -> Result<bool, FailureStage>,
) -> Result<SendOutcome, RecoveryError> {
    let id = &order.ticket.client_id;
    if ledger
        .get(id)
        .is_none_or(|intent| intent.attempt.lifecycle() != Lifecycle::IntentLogged)
    {
        return Err(RecoveryError::InvalidIdentity);
    }
    let mut allowed = || clock().is_some_and(|now| order.allows_effect_at(gate, now));
    if !allowed() {
        ledger.record_event(id, Event::Denied)?;
        ledger.release_denied_reservation(id)?;
        return Ok(SendOutcome::NotSent);
    }
    ledger.record_event(id, Event::BeginSend)?;
    match transport(&order.body, &mut allowed) {
        Ok(true) => {
            ledger.record_event(id, Event::Acknowledged)?;
            Ok(SendOutcome::Observed)
        }
        Ok(false) | Err(FailureStage::AfterFirstByte) => {
            ledger.record_event(id, Event::TransportFailed(FailureStage::AfterFirstByte))?;
            Ok(SendOutcome::Pending)
        }
        Err(FailureStage::BeforeFirstByte) => {
            ledger.record_event(id, Event::TransportFailed(FailureStage::BeforeFirstByte))?;
            ledger.record_event(id, Event::AbandonUnsent)?;
            ledger.release_denied_reservation(id)?;
            Ok(SendOutcome::NotSent)
        }
    }
}
