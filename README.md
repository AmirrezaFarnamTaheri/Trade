# TradingGYM

A research and paper-trading observatory for the Wallex exchange (TMN and USDT spot markets).

## Current state (2026-11-25)

- **Observation and paper research only.** Funded execution is **DISARMED** and the funded-loss budget is zero.
  A one-shot LIMIT order path exists in source behind an owner arm step; it is not installed, not qualified and
  not armed. There is no cancellation or protective-exit transport. Stages are defined in
  [capabilities](gym-core/docs/capabilities.md#stages).
- **Frozen prospective paper tracking active; no live funded edge claimed.** Historical seen-replay leaders are
  registered and tracking live untouched forward observations on Windows Task Scheduler (zero order authority):
  - **v1 Champion:** `70% BASE_13_S1_S5 (1d ADMM) + 30% 2h Frozen GRU-Ignition` ([v1 registration](evidence/2026-11-25-champion-ensemble-registration.json))
  - **v2 Champion (Parallel):** `70% 1d ACCEL_BLEND_20 + 11A Metals Reserve + Joint ADMM + 30% Twin-Phase 2h GRU11 Path-PnL (Conformal/DD)` ([v2 registration](evidence/2026-11-25-champion-v2-registration.json))
  - Standalone `BASE_13_S1_S5` ([leader registration](evidence/2026-11-24-s1-s5-prospective-registration.json)), `btc-daily-trend`, `breadth-trend-forward`, and `mix-journal-v2`.
  Paper results cannot authorize capital; see the [trial log](gym-core/docs/trial-log.md) and [evidence index](evidence/README.md).
- **Live multi-venue observation.** Primary collector streams 40 curated Wallex markets with 5-level depth (`core-40-wallex`);
  a read-only multi-venue recorder tracks 20 live Nobitex USDT pairs (`record_multi_venue_quotes.py`) for matched execution-cost
  and side-asymmetric routing audits ([smart execution report](evidence/2026-11-25-smart-execution-report.md)).
- **Offline research cockpit & health watchdog.** Interactive zero-CDN HTML5 dashboard at
  [2026-11-25-research-dashboard.html](evidence/2026-11-25-research-dashboard.html) and read-only operational watchdog at
  `gym-core/scripts/check_operational_health.py`.

The product goal is an autonomous trading agent. That is a goal, not a capability; [PRODUCT.md](PRODUCT.md)
states the constraints.

## Layout

| Path | Runtime | Owns |
|------|---------|------|
| [`gym-core/`](gym-core/README.md) | Python, aiohttp, SQLite | Public observation, exact storage, simulator, paper research, forward journals, EN/FA workspace |
| [`executor/`](executor/README.md) | Rust (Windows service) | Admission policy, credential vault, hash-chained ledger; DISARMED / NOT CERTIFIED |
| [`contracts/`](contracts/) | | Wire contracts and golden fixtures shared by Python and Rust |
| [`evidence/`](evidence/README.md) | Markdown, JSON, HTML | Dated study reports, frozen prospective registrations, interactive offline dashboard, SHA-256 index |
| [`scripts/windows/`](scripts/windows/) | PowerShell | Collector, multi-venue recorder, forward journals, service registration, workspace start, backups |

## Run

```powershell
cd gym-core
uv sync
uv run --no-sync gymctl --data ../data run --depth-levels 5 --assets 19 --add-symbols SLVONUSDT,COPXONUSDT
```

On Windows, `scripts/windows/Start-Workspace.ps1` starts the collector and the paper scheduler as limited-user
tasks (preview with `-WhatIf`). Details are in [gym-core/README.md](gym-core/README.md).

## Check

These are the commands CI runs ([validate.yml](.github/workflows/validate.yml)):

```powershell
cargo fmt --all --check
cargo test --locked --workspace --all-targets
cargo clippy --locked --workspace --all-targets -- -D warnings
./tasks.ps1 python
```

Further reading: [decisions](docs/adr/README.md), [disaster recovery](gym-core/docs/disaster-recovery.md), [architecture](gym-core/docs/architecture.md), [capabilities](gym-core/docs/capabilities.md),
[storage](gym-core/docs/storage.md), [design](DESIGN.md).
