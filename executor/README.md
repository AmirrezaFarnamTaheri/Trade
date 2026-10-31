# B1 Executor foundation (read-only)

This workspace implements **pure, unauthorised** primitives only:
- `exec-core`: runtime-epoch-fenced and monotone T0 stop-state reducer; boot defaults to DISARMED.
- `exec-store`: stored-byte SHA-256 event-chain hashing and verification. **No SQLite ledger yet.**
- `contracts/v1/fixtures`: golden event bytes.

There is no Windows service, IPC transport, credential provisioning, venue read client,
order-submission code, arming, or trade key here. The test fixture is not an
authorization or a funded ledger. No B1 acceptance or real-trading readiness is claimed.

## Verify

Run `cargo test --workspace --all-targets` on a machine with Rust available.
The repository CI separately runs Rust tests on Linux/Windows and existing Python tests.

## Next implementation slice

Add a single-writer SQLite ledger with durable intent/event append, replay and
tamper verification; define versioned control envelopes. Then create the Windows
service and independent stop-only named pipe with explicit DACL and fault tests,
followed by restricted identity, T2 provisioning and read-only Wallex account views.
Do not introduce venue writes before the B2 gates in the master plan.
