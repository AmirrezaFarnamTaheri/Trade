# Executor contracts v1 (preliminary)

The event byte sequence is defined in Master Specification sections 5.2
and 13.1: SHA-256(previous_hash || u64_be(len(event_bytes)) || exact_event_bytes).
`genesis-event.json` intentionally has no trailing newline, to make its exact
bytes portable across Rust and Python. The SQLite schema is implemented in
`executor/exec-store/schema.sql`.

**This is a byte-level compatibility fixture, not yet a complete semantic
ledger envelope.** Before enabling IPC or funded activity, add versioned
schemas for the full event envelope, auth, order intent/recovery and proposals;
ensure numerical money values are exact decimal strings; verify Rust/Python
contracts using golden vectors. Never reserialize stored events when checking
hashes. Only the Rust Executor may author the authoritative funded ledger.
