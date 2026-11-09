# TradingGYM

A research and paper-trading observatory for the Wallex exchange (TMN and USDT spot markets).

## Current state

- **Observation and paper research only.** Funded execution is **DISARMED**: there is no order-submission,
  cancellation or protective-exit transport, and the funded-loss budget is zero.
- **No established edge.** Acceptance gates are open and no paper strategy has a positive result that survived
  the validation protocol. Paper results cannot authorize capital.
  See [acceptance status](gym-core/docs/acceptance-status.md) and [system status](gym-core/docs/system-status.md).
- **One venue.** Wallex is the only venue in scope; collection depends on reaching it from the host.

The product goal is an autonomous trading agent. That is a goal, not a capability; [PRODUCT.md](PRODUCT.md)
states the constraints.

## Layout

| Path | Runtime | Owns |
|------|---------|------|
| [`gym-core/`](gym-core/README.md) | Python, aiohttp, SQLite | Public observation, exact storage, simulator, paper research, EN/FA workspace |
| [`executor/`](executor/README.md) | Rust (Windows service) | Admission policy, credential vault, hash-chained ledger; DISARMED / NOT CERTIFIED |
| [`model-gateway/`](model-gateway/README.md) | Node 22 | Optional provider credentials and advisory AI calls; never on the order path |
| [`contracts/`](contracts/) | | Wire contracts and golden fixtures shared by Python and Rust |
| [`scripts/windows/`](scripts/windows/) | PowerShell | Install, service registration, workspace start, backups |

## Run

```powershell
cd gym-core
uv sync
uv run --no-sync gymctl --data ../data run --assets all
```

On Windows, `scripts/windows/Start-Workspace.ps1` starts the collector and the paper scheduler as limited-user
tasks (preview with `-WhatIf`). Details are in [gym-core/README.md](gym-core/README.md).

## Check

These are the commands CI runs ([validate.yml](.github/workflows/validate.yml)):

```powershell
cargo fmt --all --check
cargo test --locked --workspace --all-targets
cargo clippy --locked --workspace --all-targets -- -D warnings
cd gym-core; uv sync --locked --group dev; uvx ruff==0.16.9 check src tests; uv run pytest -q
cd ../model-gateway; npm ci --ignore-scripts; npm test
```

Further reading: [decisions](docs/adr/README.md), [disaster recovery](gym-core/docs/disaster-recovery.md), [architecture](gym-core/docs/architecture.md), [capabilities](gym-core/docs/capabilities.md),
[storage](gym-core/docs/storage.md), [design](DESIGN.md).
