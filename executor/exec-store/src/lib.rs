//! Stored-byte hash chain primitives for Executor event records.
//! Future append-only SQLite implementation must hash persisted bytes, not parsed JSON.

use sha2::{Digest, Sha256};

/// SHA-256(previous_hash || u64_be(length) || exact_event_bytes).
/// Returns the digest only; storage, transactions and replay are not implemented.
pub fn hash_event(previous_hash: &[u8; 32], event_bytes: &[u8]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(previous_hash);
    hasher.update((event_bytes.len() as u64).to_be_bytes());
    hasher.update(event_bytes);
    hasher.finalize().into()
}

/// Verify an ordered sequence against the genesis hash and its expected head.
/// This is not a substitute for a durable single-writer transaction.
pub fn verify_chain<'a>(
    genesis_hash: [u8; 32],
    events: impl IntoIterator<Item = &'a [u8]>,
    expected_head: [u8; 32],
) -> bool {
    let mut current = genesis_hash;
    for event in events {
        current = hash_event(&current, event);
    }
    current == expected_head
}
