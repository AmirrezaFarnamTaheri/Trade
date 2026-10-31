# B1 Executor foundation (no funded capabilities)

`exec-core` is a pure runtime-epoch-fenced, monotone stop-state reducer.
`exec-store` is the initial on-disk event ledger: SQLite WAL and
`synchronous=FULL`, one advisory-locked writer, serial `BEGIN IMMEDIATE`
appends, forward-only schema v1, append-only triggers, exact stored-byte
SHA-256 chaining, verified replay, fail-closed startup and bounded event size.

**This is not a finished B1 or a funded Executor.** No Windows service,
credential handling, named pipes, authorized event-envelope validation,
API account reader, order creation/cancellation, or strategy arming exists.
The store accepts opaque bytes that must be validated by the future contract
boundary. A hash chain is tamper-evident, not a substitute for restricted
Windows ACLs and recoverable off-machine backups. Advisory locks do not stop
an attacker who already has file-write permissions.

## Tests

- `cargo test --workspace --all-targets`: Rust states, hash chain and
  durable ledger integration tests (run on Linux and Windows).
- `cd gym-core && uv run pytest -q`: existing Python tests plus an independent
  stored-byte SHA-256 and SQLite-schema check.

The Rust tests require a Rust toolchain. CI must pass before merging; this
change does not enable live or dry-run funded activity.

## Next B1 work

Versioned event envelopes and IPC, service identity/ACL/DACL self-tests,
separate T2 control, stop-only named pipe, then read-only Wallex balances,
fees, manual order status and external exposure. The real crash/restore
fault-injection gate remains unsatisfied, and off-machine restore is B3.
