# B1 Executor foundation — read-only

`exec-core` is a pure stop-state reducer. `exec-store` is the draft
single-writer SQLite event ledger with WAL, FULL synchronous commits,
immutable-event guards and byte-level hash verification.

`exec-ipc` adds a fixed-size, versioned T0 stop-only codec, and `exec-svc`
adds the atomic, monotone stop gate and a **Windows-only named-pipe listener
library** with explicit DACL creation and remote-client rejection. The listener
must be hosted on its own thread, with verified service and logon SIDs.

**Not yet implemented:** a registered restricted Windows service or installer;
service-identity/ACL self-tests; T2 pipe and privileged credential provisioning;
full versioned event envelopes; account read adapters; tray; journal replication;
funded order create/cancel; position protection. This code does **not** arm or
submit orders. It is not B1-complete and is not trading-ready.

## Verification

- `cargo test --workspace --all-targets` on Linux and Windows; also compile
  Windows-only modules on a real Windows runner.
- `cd gym-core && uv run pytest -q` for Python contract and existing behavior
  tests. `test_stop_wire_contract.py` uses independent golden vectors.
- Windows acceptance must verify the actual pipe DACL under service identity,
  inaccessible T2/ledger/secret paths, rejected network clients, stop behavior
  with Python/API dead, and stop responsiveness under loop starvation.

Do not merge without green CI. A stored-byte hash chain is tamper-evident but
not a substitute for OS isolation or a restorable off-machine backup.

## Next implementation slice

Register the restricted service with the Windows SCM, provision service SID
and operator logon SID through trusted installer state, add security self-tests,
and exercise stop-only pipes on the target OS. Then proceed with read-only
Wallex account views and external exposure. No execution transport is allowed
until the B2 money-path gates and later C venue probes.
