//! Stored-byte hash chain for Executor event records.

// RED: replace with SHA-256(previous_hash || u64_be(len) || exact_event_bytes).
pub fn hash_event(_previous_hash: &[u8; 32], _event_bytes: &[u8]) -> [u8; 32] {
    [0; 32]
}
