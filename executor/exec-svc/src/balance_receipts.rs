//! Native, single-flight balance receipts. Restart discards the pair and requires two new reads.
use crate::account_observation::{AccountKind, AccountObservation};
use crate::offline_recovery::DurableOrderJournal;
use exec_core::available::{
    verified_available, Available, AvailableError, Journal, ObservedBalance, ReceiptFence,
};
use exec_ipc::account::ObservationReceipt;
use std::collections::VecDeque;

#[derive(Debug)]
pub struct BalanceRead {
    fence: ReceiptFence,
    request_id: [u8; 16],
    started_at_ms: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReceiptError {
    InvalidRead,
    ActivityChanged,
    CommitUncertain,
}

pub struct BalanceCommit {
    pub receipt: ObservationReceipt,
    pub paired: bool,
    pub disagreed: bool,
}

#[derive(Default)]
pub struct BalanceReceipts {
    fence: Option<ReceiptFence>,
    in_flight: Option<[u8; 16]>,
    last_received_at_ms: u64,
    reads: VecDeque<(AccountObservation, u64)>,
    poisoned: bool,
}

fn amount_parts(text: &str) -> (&str, &str) {
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    (
        whole.trim_start_matches('0'),
        fraction.trim_end_matches('0'),
    )
}

fn same_balances(a: &AccountObservation, b: &AccountObservation) -> bool {
    let a = a.data()["result"]["balances"].as_object().unwrap();
    let b = b.data()["result"]["balances"].as_object().unwrap();
    a.len() == b.len()
        && a.iter().all(|(asset, row)| {
            b.get(asset).is_some_and(|other| {
                ["value", "locked"].iter().all(|field| {
                    amount_parts(row[field].as_str().unwrap())
                        == amount_parts(other[field].as_str().unwrap())
                })
            })
        })
}

fn quanta(text: &str, decimals: u8, round_up: bool) -> Result<u64, AvailableError> {
    if decimals > 18 {
        return Err(AvailableError::InvalidReceipt);
    }
    let (whole, fraction) = text.split_once('.').unwrap_or((text, ""));
    let precision = usize::from(decimals);
    let mut digits =
        whole
            .bytes()
            .chain(fraction.bytes().take(precision))
            .chain(std::iter::repeat_n(
                b'0',
                precision.saturating_sub(fraction.len()),
            ));
    let mut value = digits
        .try_fold(0u64, |sum, digit| {
            sum.checked_mul(10)?
                .checked_add(u64::from(digit.checked_sub(b'0')?))
        })
        .ok_or(AvailableError::InvalidReceipt)?;
    if round_up && fraction.bytes().skip(precision).any(|digit| digit != b'0') {
        value = value.checked_add(1).ok_or(AvailableError::InvalidReceipt)?;
    }
    Ok(value)
}

impl BalanceReceipts {
    pub fn matches_context(&self, generation: [u8; 16], runtime_epoch: u64) -> bool {
        !self.poisoned
            && self.fence.is_some_and(|fence| {
                fence.credential_generation == generation && fence.runtime_epoch == runtime_epoch
            })
    }
    /// Context comes from the native vault and runtime, never from an IPC balance body.
    pub fn begin(
        &mut self,
        generation: [u8; 16],
        runtime_epoch: u64,
        request_id: [u8; 16],
        now_ms: u64,
    ) -> Result<BalanceRead, ReceiptError> {
        if self.poisoned
            || generation == [0; 16]
            || runtime_epoch == 0
            || request_id == [0; 16]
            || now_ms == 0
            || self.in_flight.is_some()
            || now_ms < self.last_received_at_ms
            || self
                .reads
                .iter()
                .any(|(value, _)| value.request_id() == request_id)
        {
            return Err(ReceiptError::InvalidRead);
        }
        if self.fence.is_none_or(|f| {
            f.credential_generation != generation || f.runtime_epoch != runtime_epoch
        }) {
            self.reads.clear();
            self.fence = Some(ReceiptFence {
                credential_generation: generation,
                runtime_epoch,
                activity_seq: 0,
                not_before_ms: now_ms,
            });
        }
        let fence = self.fence.unwrap();
        if now_ms < fence.not_before_ms {
            return Err(ReceiptError::InvalidRead);
        }
        self.in_flight = Some(request_id);
        Ok(BalanceRead {
            fence,
            request_id,
            started_at_ms: now_ms,
        })
    }

    pub fn abort(&mut self, read: BalanceRead) {
        if self.in_flight == Some(read.request_id) {
            self.in_flight = None;
        }
        self.reads.clear();
    }

    /// Call before an own venue effect, and when a new own order/fill is observed.
    pub fn own_activity(&mut self, now_ms: u64) -> Result<(), ReceiptError> {
        self.reads.clear();
        if self.poisoned || now_ms == 0 || now_ms < self.last_received_at_ms {
            self.poisoned = true;
            return Err(ReceiptError::InvalidRead);
        }
        if let Some(fence) = self.fence.as_mut() {
            fence.activity_seq = fence.activity_seq.checked_add(1).ok_or_else(|| {
                self.poisoned = true;
                ReceiptError::InvalidRead
            })?;
            fence.not_before_ms = now_ms.max(fence.not_before_ms);
        }
        Ok(())
    }

    pub fn complete(
        &mut self,
        read: BalanceRead,
        value: AccountObservation,
        credentials: &mut DurableOrderJournal,
        execution: Option<&mut DurableOrderJournal>,
    ) -> Result<BalanceCommit, ReceiptError> {
        if self.poisoned
            || self.in_flight.take() != Some(read.request_id)
            || value.kind() != AccountKind::Balances
            || value.generation() != read.fence.credential_generation
            || value.runtime_epoch() != read.fence.runtime_epoch
            || value.request_id() != read.request_id
            || value.started_at_ms() != read.started_at_ms
            || value
                .encode()
                .and_then(|raw| AccountObservation::decode(&raw))
                .is_err()
        {
            self.reads.clear();
            return Err(ReceiptError::InvalidRead);
        }
        if self.fence != Some(read.fence) {
            self.reads.clear();
            return Err(ReceiptError::ActivityChanged);
        }
        let Some(metadata) = credentials
            .credential_metadata()
            .filter(|key| key.generation == value.generation())
            .cloned()
        else {
            self.reads.clear();
            return Err(ReceiptError::ActivityChanged);
        };
        let result = (|| {
            if let Some(ledger) = execution.as_ref() {
                if ledger
                    .credential_metadata()
                    .is_some_and(|key| key.generation == metadata.generation && key != &metadata)
                {
                    return Err(ReceiptError::CommitUncertain);
                }
            }
            let receipt = credentials
                .record_account_observation(value.clone())
                .map_err(|_| ReceiptError::CommitUncertain)?;
            let paired = if let Some(ledger) = execution {
                if ledger.credential_metadata() != Some(&metadata) {
                    ledger
                        .commit_credential(metadata)
                        .map_err(|_| ReceiptError::CommitUncertain)?;
                }
                let copy = ledger
                    .record_account_observation(value.clone())
                    .map_err(|_| ReceiptError::CommitUncertain)?;
                if receipt.kind != copy.kind
                    || receipt.runtime_epoch != copy.runtime_epoch
                    || receipt.credential_generation != copy.credential_generation
                    || receipt.response_digest != copy.response_digest
                    || receipt.started_at_ms != copy.started_at_ms
                    || receipt.received_at_ms != copy.received_at_ms
                    || receipt.event_hash == [0; 32]
                    || copy.event_hash == [0; 32]
                {
                    return Err(ReceiptError::CommitUncertain);
                }
                true
            } else {
                false
            };
            self.last_received_at_ms = value.received_at_ms();
            let disagreed = paired
                && self
                    .reads
                    .back()
                    .is_some_and(|(previous, _)| !same_balances(previous, &value));
            if !paired || disagreed {
                self.reads.clear();
            }
            if paired {
                // The service issues its receipt at the credentials commit position; the second ledger has
                // its own row number. Request/generation/epoch/digest bind the two copies, never venue order.
                self.reads.push_back((value, receipt.sequence));
                while self.reads.len() > 2 {
                    self.reads.pop_front();
                }
            }
            Ok(BalanceCommit {
                receipt,
                paired,
                disagreed,
            })
        })();
        if result.is_err() {
            self.poisoned = true;
            self.reads.clear();
        }
        result
    }

    pub fn available(
        &self,
        asset: &str,
        decimals: u8,
        open_holds: u64,
        now_ms: u64,
        max_age_ms: u64,
    ) -> Result<Available, AvailableError> {
        if self.poisoned || decimals > 18 {
            return Err(AvailableError::InvalidReceipt);
        }
        let fence = self.fence.ok_or(AvailableError::Missing)?;
        let mut copies = Vec::with_capacity(4);
        for (value, receipt_seq) in &self.reads {
            let row = value.data()["result"]["balances"]
                .get(asset)
                .ok_or(AvailableError::Missing)?;
            let total = quanta(
                row["value"]
                    .as_str()
                    .ok_or(AvailableError::InvalidReceipt)?,
                decimals,
                false,
            )?;
            let locked = quanta(
                row["locked"]
                    .as_str()
                    .ok_or(AvailableError::InvalidReceipt)?,
                decimals,
                true,
            )?;
            for journal in [Journal::Credentials, Journal::Ledger] {
                copies.push(ObservedBalance {
                    journal,
                    account: "main".into(),
                    asset: asset.into(),
                    available_quanta: total.saturating_sub(locked),
                    locked_quanta: locked,
                    receipt_seq: *receipt_seq,
                    fence,
                    request_id: value.request_id(),
                    response_digest: value.response_digest(),
                    started_at_ms: value.started_at_ms(),
                    received_at_ms: value.received_at_ms(),
                });
            }
        }
        verified_available(
            &copies, "main", asset, fence, now_ms, max_age_ms, open_holds,
        )
    }

    /// Settlement needs a complete pair whose requests both followed the terminal native receipt.
    pub fn settlement_evidence(
        &self,
        asset: &str,
        decimals: u8,
        spent: u64,
        after_ms: u64,
        now_ms: u64,
    ) -> Result<exec_core::orders::SettlementEvidence, AvailableError> {
        let available = self.available(asset, decimals, 0, now_ms, 120_000)?;
        if after_ms == 0
            || self
                .reads
                .front()
                .is_none_or(|(read, _)| read.started_at_ms() < after_ms)
        {
            return Err(AvailableError::Missing);
        }
        let locked = self
            .reads
            .back()
            .and_then(|(read, _)| read.data()["result"]["balances"][asset]["locked"].as_str())
            .ok_or(AvailableError::Missing)?;
        Ok(exec_core::orders::SettlementEvidence {
            account: "main".into(),
            asset: asset.into(),
            sequence: available.receipt_seq,
            complete: true,
            locked_quanta: quanta(locked, decimals, true)?,
            spent_quanta: spent,
            available_quanta: available.available_quanta,
        })
    }
}
