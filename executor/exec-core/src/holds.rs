//! Active reservation model used by the durable order journal (ADR 0003).
//!
//! Per account and asset it keeps the newest verified venue observation, the active holds of orders that are
//! not yet settled, and settled spends the newest observation does not yet reflect. Admission requires
//!
//! `active holds + unobserved settled spends + request <= newest observed available`
//!
//! There is no shared snapshot anchor, so overlapping orders admitted against different observations are fine,
//! and no exact-equality release, so a venue credit (dust, rebate) can never wedge a hold. A settled spend above
//! its hold by more than the asset's tolerance puts the asset into RECONCILE, which blocks new entries until a
//! strictly newer observation arrives.
use crate::orders::{
    Attempt, BalanceSnapshot, Lifecycle, ReservationError, Settlement, SettlementEvidence,
};
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HoldError {
    InvalidEvidence,
    StaleObservation,
    DuplicateIntent,
    UnknownIntent,
    InsufficientAvailable,
    Reconciling,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct AssetState {
    observed_available: u64,
    observed_seq: u64,
    holds: BTreeMap<String, (u64, u64)>, // quanta and the observation sequence at admission
    /// (observation sequence the spend settled after, quanta); dropped once a newer observation covers it.
    unobserved_spends: Vec<(u64, u64)>,
    /// Allowed overspend of one settlement above its hold, in quanta (venue rounding or dust rules).
    tolerance: u64,
    reconcile_after: Option<u64>,
}

impl AssetState {
    fn committed(&self) -> Option<u64> {
        let holds = self
            .holds
            .values()
            .try_fold(0u64, |t, (q, _)| t.checked_add(*q))?;
        self.unobserved_spends
            .iter()
            .try_fold(holds, |t, (_, q)| t.checked_add(*q))
    }
}

#[derive(Clone, Debug, Default)]
pub struct ActiveHoldBook {
    assets: BTreeMap<(String, String), AssetState>,
}

fn valid(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 96
        && name
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'-' | b'_' | b':' | b'.'))
}

impl ActiveHoldBook {
    pub fn is_reserved(&self, intent: &str) -> bool {
        self.assets
            .values()
            .any(|state| state.holds.contains_key(intent))
    }

    pub fn reserved(&self, account: &str, asset: &str) -> u64 {
        self.assets
            .get(&(account.into(), asset.into()))
            .map_or(0, |s| s.committed().unwrap_or(u64::MAX))
    }

    pub fn total_reserved(&self, asset: &str) -> Option<u64> {
        self.assets
            .iter()
            .filter(|((_, name), _)| name == asset)
            .try_fold(0u64, |total, (_, state)| {
                total.checked_add(state.committed()?)
            })
    }

    /// The journal supplies authenticated snapshots; repeated sequence numbers must agree exactly.
    pub fn reserve_order(
        &mut self,
        intent: &str,
        account: &str,
        asset: &str,
        quanta: u64,
        snapshot: &BalanceSnapshot,
        order: &Attempt,
    ) -> Result<(), ReservationError> {
        if snapshot.account != account || snapshot.asset != asset || snapshot.sequence == 0 {
            return Err(ReservationError::InvalidEvidence);
        }
        if order.lifecycle() != Lifecycle::IntentLogged {
            return Err(ReservationError::OrderNotFresh);
        }
        if let Some(state) = self.assets.get(&(account.into(), asset.into())) {
            if snapshot.sequence < state.observed_seq {
                return Err(ReservationError::StaleBalance);
            }
            if snapshot.sequence == state.observed_seq
                && snapshot.available_quanta != state.observed_available
            {
                return Err(ReservationError::InvalidEvidence);
            }
        }
        if self
            .assets
            .get(&(account.into(), asset.into()))
            .is_none_or(|s| snapshot.sequence > s.observed_seq)
        {
            self.observe(account, asset, snapshot.available_quanta, snapshot.sequence)
                .map_err(reservation_error)?;
        }
        self.reserve(intent, account, asset, quanta)
            .map_err(reservation_error)
    }

    pub fn release_denied(
        &mut self,
        intent: &str,
        order: &Attempt,
    ) -> Result<(), ReservationError> {
        if order.lifecycle() != Lifecycle::Denied {
            return Err(ReservationError::OrderNotSettled);
        }
        self.release_unsent(intent).map_err(reservation_error)
    }

    /// A reconciled terminal observation covers the spend; unrelated credits never require exact equality.
    pub fn release_settled(
        &mut self,
        intent: &str,
        order: &Attempt,
        evidence: &SettlementEvidence,
    ) -> Result<(), ReservationError> {
        if order.lifecycle() != Lifecycle::Closed
            || !matches!(
                order.settlement(),
                Settlement::Settled | Settlement::Verified
            )
        {
            return Err(ReservationError::OrderNotSettled);
        }
        let ((account, asset), state) = self
            .assets
            .iter()
            .find(|(_, s)| s.holds.contains_key(intent))
            .ok_or(ReservationError::UnknownIntent)?;
        if evidence.account != *account || evidence.asset != *asset || !evidence.complete {
            return Err(ReservationError::InvalidEvidence);
        }
        if evidence.sequence <= state.holds[intent].1 || evidence.sequence < state.observed_seq {
            return Err(ReservationError::StaleBalance);
        }
        if evidence.sequence == state.observed_seq
            && evidence.available_quanta != state.observed_available
        {
            return Err(ReservationError::InvalidEvidence);
        }
        if evidence.locked_quanta != 0 {
            return Err(ReservationError::StillLocked);
        }
        if evidence.spent_quanta > state.holds[intent].0 {
            return Err(ReservationError::BalanceMismatch);
        }
        let (account, asset) = (account.clone(), asset.clone());
        let newer = evidence.sequence > state.observed_seq;
        self.release_unsent(intent).map_err(reservation_error)?;
        if newer {
            self.observe(
                &account,
                &asset,
                evidence.available_quanta,
                evidence.sequence,
            )
            .map_err(reservation_error)?;
        }
        Ok(())
    }
    /// Declare the per-settlement tolerance for an asset (default zero: any overspend reconciles).
    pub fn set_tolerance(
        &mut self,
        account: &str,
        asset: &str,
        quanta: u64,
    ) -> Result<(), HoldError> {
        if !valid(account) || !valid(asset) {
            return Err(HoldError::InvalidEvidence);
        }
        self.assets
            .entry((account.into(), asset.into()))
            .or_default()
            .tolerance = quanta;
        Ok(())
    }

    /// Record a verified venue observation; sequences must strictly increase per account and asset.
    pub fn observe(
        &mut self,
        account: &str,
        asset: &str,
        available: u64,
        sequence: u64,
    ) -> Result<(), HoldError> {
        if !valid(account) || !valid(asset) || sequence == 0 {
            return Err(HoldError::InvalidEvidence);
        }
        let state = self
            .assets
            .entry((account.into(), asset.into()))
            .or_default();
        if sequence <= state.observed_seq {
            return Err(HoldError::StaleObservation);
        }
        state.observed_available = available;
        state.observed_seq = sequence;
        state
            .unobserved_spends
            .retain(|(after, _)| *after >= sequence);
        if state.reconcile_after.is_some_and(|seq| sequence > seq) {
            state.reconcile_after = None;
        }
        Ok(())
    }

    pub fn reserve(
        &mut self,
        intent: &str,
        account: &str,
        asset: &str,
        quanta: u64,
    ) -> Result<(), HoldError> {
        if !valid(intent) || quanta == 0 {
            return Err(HoldError::InvalidEvidence);
        }
        if self.assets.values().any(|s| s.holds.contains_key(intent)) {
            return Err(HoldError::DuplicateIntent);
        }
        let state = self
            .assets
            .get_mut(&(account.into(), asset.into()))
            .filter(|s| s.observed_seq > 0)
            .ok_or(HoldError::InvalidEvidence)?;
        if state.reconcile_after.is_some() {
            return Err(HoldError::Reconciling);
        }
        let after = state
            .committed()
            .and_then(|c| c.checked_add(quanta))
            .ok_or(HoldError::InsufficientAvailable)?;
        if after > state.observed_available {
            return Err(HoldError::InsufficientAvailable);
        }
        state
            .holds
            .insert(intent.into(), (quanta, state.observed_seq));
        Ok(())
    }

    /// The order never reached the venue: drop its hold, nothing was spent.
    pub fn release_unsent(&mut self, intent: &str) -> Result<(), HoldError> {
        let state = self
            .assets
            .values_mut()
            .find(|s| s.holds.contains_key(intent))
            .ok_or(HoldError::UnknownIntent)?;
        state.holds.remove(intent);
        Ok(())
    }

    /// The order is terminal and its fills reconciled: replace the hold by the actual spend until a newer
    /// observation covers it. An overspend beyond tolerance is still recorded, and the asset reconciles.
    pub fn settle(&mut self, intent: &str, spent: u64) -> Result<(), HoldError> {
        let state = self
            .assets
            .values_mut()
            .find(|s| s.holds.contains_key(intent))
            .ok_or(HoldError::UnknownIntent)?;
        let hold = state.holds.remove(intent).map_or(0, |(q, _)| q);
        if spent > 0 {
            state.unobserved_spends.push((state.observed_seq, spent));
        }
        if spent > hold.saturating_add(state.tolerance) {
            state.reconcile_after = Some(state.observed_seq);
        }
        Ok(())
    }

    pub fn active(&self, account: &str, asset: &str) -> u64 {
        self.assets
            .get(&(account.into(), asset.into()))
            .and_then(AssetState::committed)
            .unwrap_or(u64::MAX)
    }

    pub fn reconciling(&self, account: &str, asset: &str) -> bool {
        self.assets
            .get(&(account.into(), asset.into()))
            .is_some_and(|s| s.reconcile_after.is_some())
    }
}

fn reservation_error(error: HoldError) -> ReservationError {
    match error {
        HoldError::DuplicateIntent => ReservationError::DuplicateIntent,
        HoldError::UnknownIntent => ReservationError::UnknownIntent,
        HoldError::StaleObservation => ReservationError::StaleBalance,
        HoldError::InsufficientAvailable => ReservationError::InsufficientAvailable,
        HoldError::InvalidEvidence | HoldError::Reconciling => ReservationError::InvalidEvidence,
    }
}
