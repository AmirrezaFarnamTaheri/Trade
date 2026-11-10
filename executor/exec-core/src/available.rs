//! Verified available balance for admission (owner decision OD-5): fail closed.
//!
//! The vault keeps two journals (`credentials.sqlite` and `exec_ledger.db`), and admission takes a "verified
//! available" amount as an input. This is the one rule that produces it: the newest observation for the account and
//! asset by venue sequence, across every journal, refused when it is older than the freshness bound, and refused
//! (and the arm record disarmed) when two journals report different amounts for the same sequence. Ages use
//! the receiving host's clock only as an annotation of staleness; ordering is by venue sequence (finding E-6).

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Journal {
    Credentials,
    Ledger,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObservedBalance {
    pub journal: Journal,
    pub account: String,
    pub asset: String,
    pub available_quanta: u64,
    pub sequence: u64,
    pub received_at_ms: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Available {
    pub available_quanta: u64,
    pub sequence: u64,
    pub age_ms: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AvailableError {
    /// No observation for this account and asset: block.
    Missing,
    /// The newest observation is older than the bound: block until a fresh read.
    Stale { age_ms: u64 },
    /// Two journals disagree about the same venue sequence: block and disarm.
    Disagreement { sequence: u64 },
}

impl AvailableError {
    /// Whether the arm record must disarm (not just refuse this order).
    pub fn disarms(self) -> bool {
        matches!(self, AvailableError::Disagreement { .. })
    }
}

pub fn verified_available(
    observations: &[ObservedBalance],
    account: &str,
    asset: &str,
    now_ms: u64,
    max_age_ms: u64,
) -> Result<Available, AvailableError> {
    let relevant: Vec<&ObservedBalance> = observations
        .iter()
        .filter(|o| o.account == account && o.asset == asset)
        .collect();
    // Any disagreement anywhere in history is a custody fault, not only at the newest sequence.
    for (i, a) in relevant.iter().enumerate() {
        for b in &relevant[i + 1..] {
            if a.sequence == b.sequence && a.available_quanta != b.available_quanta {
                return Err(AvailableError::Disagreement {
                    sequence: a.sequence,
                });
            }
        }
    }
    let newest = relevant
        .iter()
        .max_by_key(|o| (o.sequence, o.received_at_ms))
        .ok_or(AvailableError::Missing)?;
    let age_ms = now_ms.saturating_sub(newest.received_at_ms);
    if age_ms > max_age_ms {
        return Err(AvailableError::Stale { age_ms });
    }
    Ok(Available {
        available_quanta: newest.available_quanta,
        sequence: newest.sequence,
        age_ms,
    })
}
