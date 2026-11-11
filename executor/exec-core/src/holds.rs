//! Proposed reservation model for funded orders (ADR 0003). NOT wired into the service: `ReservationBook`
//! stays authoritative until the money-path review swaps this in deliberately.
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
    holds: BTreeMap<String, u64>,
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
            .try_fold(0u64, |t, q| t.checked_add(*q))?;
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
        state.holds.insert(intent.into(), quanta);
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
        let hold = state.holds.remove(intent).unwrap_or(0);
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
