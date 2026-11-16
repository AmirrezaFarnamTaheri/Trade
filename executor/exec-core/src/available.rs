//! Conservative balance policy under ADR 0008. Receipt order is local, never exchange snapshot order.
//!
//! The native producer must supply its last two single-flight reads, matching durable copies in both journals,
//! and the current credential/runtime/activity fence. This pure rule cannot authenticate GETs or grant authority.
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Journal {
    Credentials,
    Ledger,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ReceiptFence {
    pub credential_generation: [u8; 16],
    pub runtime_epoch: u64,
    pub activity_seq: u64,
    pub not_before_ms: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObservedBalance {
    pub journal: Journal,
    pub account: String,
    pub asset: String,
    pub available_quanta: u64,
    pub locked_quanta: u64,
    pub receipt_seq: u64,
    pub fence: ReceiptFence,
    pub request_id: [u8; 16],
    pub response_digest: [u8; 32],
    pub started_at_ms: u64,
    pub received_at_ms: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Available {
    pub available_quanta: u64,
    pub receipt_seq: u64,
    pub age_ms: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AvailableError {
    /// Two eligible receipts with both durable journal copies are required.
    Missing,
    /// Both reads must satisfy the bound: block until a fresh pair exists.
    Stale {
        age_ms: u64,
    },
    /// Journal copies or consecutive reads at the same activity fence disagree.
    Disagreement {
        receipt_seq: u64,
    },
    InvalidReceipt,
}

impl AvailableError {
    /// Whether the arm record must disarm (not just refuse this order).
    pub fn disarms(self) -> bool {
        matches!(self, Self::Disagreement { .. } | Self::InvalidReceipt)
    }
}

fn paired<'a>(
    copies: &[Option<&'a ObservedBalance>; 2],
    receipt_seq: u64,
) -> Result<&'a ObservedBalance, AvailableError> {
    let (Some(a), Some(b)) = (copies[0], copies[1]) else {
        return Err(AvailableError::Missing);
    };
    if a.available_quanta != b.available_quanta
        || a.locked_quanta != b.locked_quanta
        || a.request_id != b.request_id
        || a.response_digest != b.response_digest
        || a.started_at_ms != b.started_at_ms
        || a.received_at_ms != b.received_at_ms
    {
        return Err(AvailableError::Disagreement { receipt_seq });
    }
    Ok(a)
}

pub fn verified_available(
    observations: &[ObservedBalance],
    account: &str,
    asset: &str,
    fence: ReceiptFence,
    now_ms: u64,
    max_age_ms: u64,
    open_holds_quanta: u64,
) -> Result<Available, AvailableError> {
    if account.is_empty()
        || asset.is_empty()
        || fence.runtime_epoch == 0
        || fence.credential_generation == [0; 16]
        || fence.not_before_ms > now_ms
    {
        return Err(AvailableError::InvalidReceipt);
    }
    let mut receipts: BTreeMap<u64, [Option<&ObservedBalance>; 2]> = BTreeMap::new();
    for o in observations
        .iter()
        .filter(|o| o.account == account && o.asset == asset && o.fence == fence)
    {
        if o.receipt_seq == 0
            || o.request_id == [0; 16]
            || o.response_digest == [0; 32]
            || o.started_at_ms < fence.not_before_ms
            || o.started_at_ms > o.received_at_ms
            || o.received_at_ms > now_ms
            || o.available_quanta.checked_add(o.locked_quanta).is_none()
        {
            return Err(AvailableError::InvalidReceipt);
        }
        let index = match o.journal {
            Journal::Credentials => 0,
            Journal::Ledger => 1,
        };
        let copies = receipts.entry(o.receipt_seq).or_default();
        if copies[index].is_some_and(|previous| previous != o) {
            return Err(AvailableError::Disagreement {
                receipt_seq: o.receipt_seq,
            });
        }
        copies[index] = Some(o);
    }
    let mut latest = receipts.iter().rev();
    let (new_seq, new_copies) = latest.next().ok_or(AvailableError::Missing)?;
    let (old_seq, old_copies) = latest.next().ok_or(AvailableError::Missing)?;
    let newest = paired(new_copies, *new_seq)?;
    let previous = paired(old_copies, *old_seq)?;
    if previous.request_id == newest.request_id || previous.received_at_ms > newest.started_at_ms {
        return Err(AvailableError::InvalidReceipt);
    }
    if previous.available_quanta != newest.available_quanta
        || previous.locked_quanta != newest.locked_quanta
    {
        return Err(AvailableError::Disagreement {
            receipt_seq: *new_seq,
        });
    }
    let age_ms = now_ms - previous.received_at_ms;
    if age_ms > max_age_ms.min(120_000) {
        return Err(AvailableError::Stale { age_ms });
    }
    Ok(Available {
        available_quanta: previous
            .available_quanta
            .min(newest.available_quanta)
            .saturating_sub(open_holds_quanta),
        receipt_seq: *new_seq,
        age_ms,
    })
}
