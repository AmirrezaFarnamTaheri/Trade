# Rust Executor

The Windows service remains **DISARMED / NOT CERTIFIED**. There is no funded
submission, cancellation or protective-exit transport.

- `exec-core`: authority/stop policies, exact order/reservation state and seeded Fake Venue scenarios.
- `exec-store`: single-writer SQLite WAL ledger with FULL-synchronous commits and stored-byte hash verification.
- `exec-ipc`: bounded stop, credential provisioning and read-only account contracts.
- `exec-svc`: restricted LocalService host, independent authenticated STOP listener,
  elevated provisioning/account-read pipe, service-context DPAPI custody and explicit recovery startup.
- `gym-research-worker`: constrained AppContainer launcher for the fixed public-data-only Python entrypoint.

The protected account helper makes only fixed-origin GET requests. Its output is
an unparsed observation; key permissions, settlement and spendable balances are
not established by a successful read. Python can normalize those observations
with `gymctl account --source service --record`, from a separate elevated console.
The operator and research worker cannot read the service credential.

From the repository root:

```powershell
cargo fmt --all --check
cargo test --locked --workspace --all-targets
cargo clippy --locked --workspace --all-targets -- -D warnings
```

Earlier B1/B2/B3 and C preparation PRs have merged. The current combined work is
in PR #18; merging code does not certify a money path. See
[service security status](docs/service-security-status.md) for implemented
boundaries and installed-host/venue gates, and
[Windows setup](docs/windows-service-bootstrap.md) for protected installation.
