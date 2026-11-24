# gym-core — observatory and paper research

TradingGYM collects public Wallex observations, runs reproducible paper research
and provides an English/Persian operator workspace. The product goal is an
autonomous agent; funded execution remains DISARMED and unavailable.

## Install and run

From the repository's gym-core directory:

```powershell
uv sync
uv run --no-sync gymctl --data ../data run --depth-levels 5 --assets 19 --add-symbols SLVONUSDT,COPXONUSDT
```

Use the same data root for every command. Here, `../data/live` is the
canonical observed store; DEMO uses `../data/demo`. In a source checkout,
omitting `--data` now resolves to the repository's `data/` directory whether
you launch from the repository root or `gym-core/`. An explicit `--data` always
wins. Installed wheels without a checkout must use an explicit data root.

If an earlier launch wrote `gym-core/data/live/backup_status.sqlite3` or other
data, **do not delete or overwrite it**. Stop all writers, inspect both roots,
and follow the conservative migration notes in `docs/storage.md` before
switching to the canonical root.

Open the private link printed by the process. It carries the local session key
in its fragment; the page itself contains no key. Market reads are public on
loopback. Private reads and writes require the key. `--no-browser` suppresses
opening the browser.

On Windows, run `scripts/windows/Start-Workspace.ps1` from the repository root.
It supervises collection and paper scheduling as separate limited-user tasks
with the canonical data root and all eligible pairs. Preview with `-WhatIf`.
The private link is saved under `%LOCALAPPDATA%/TradingGYM/workspace-link.txt`.
Protected executor installation and custody remain separate.

## Common workflows

```powershell
uv run --no-sync gymctl --data ../data paper BTCUSDT --res 1min --params '{"fast":8,"slow":21}'
uv run --no-sync gymctl --data ../data portfolio BTCUSDT,ETHUSDT --res 1min
uv run --no-sync gymctl --data ../data rules list
uv run --no-sync gymctl --data ../data spreads --output spreads.json
uv run --no-sync gymctl --data ../data research list
uv run --no-sync gymctl --data ../data doctor   # read-only integrity check; exit 1 on failure
```

Paper research exposes comparisons, validation, saved runs, shared-cash
portfolios, margin previews/replays and research workflows. Spot paper is long/flat; selling exits owned
assets. Margin paper has separate venue credit/collateral contracts.

These example markets demonstrate syntax. The collector defaults to every
eligible spot market; it does not restrict the universe to those examples.
Missing history stays missing. Synthetic DEMO observations and modeled fills
are labeled and cannot authorize capital.

## Long-history research and the daily allocation journal

Studies on Binance public data (checksum-verified monthly files) with Wallex costs, each split into
train (ranking only), validation (a gate against buy-and-hold) and test (scored once):

```bash
uv run --no-sync python scripts/long_history_study.py fetch BTCUSDT ETHUSDT --interval 1d
uv run --no-sync python scripts/long_history_study.py study BTCUSDT ETHUSDT --margin BTCUSDT,ETHUSDT
uv run --no-sync python scripts/long_history_study.py fetch BTCUSDT ETHUSDT --interval 1m --from 2025-11
uv run --no-sync python scripts/horizon_study.py BTCUSDT ETHUSDT --margin BTCUSDT,ETHUSDT
```

The only rule that held up out of sample is the daily trend allocation (close above its 50-day
average, sized to 40% annual volatility, 0.2 rebalance band). Run it forward on Wallex prices once a
day after the UTC close, with the collector running; it appends to `data/live/allocation/journal.jsonl`:

```bash
uv run --no-sync gymctl history BTCUSDT ETHUSDT --resolution 1d --from 2025-01-01T00:00:00Z
uv run --no-sync gymctl allocate BTCUSDT ETHUSDT
```

Paper only: decisions use completed daily candles fetched before the run, fills use the freshest
qualified quote and the venue rules in force, and a missing quote records NO_QUOTE instead of a fill.

## Prospective forward journals, multi-venue observation & dashboard

In addition to `gymctl`, the research stack includes read-only forward paper journals, multi-venue quote recording, operational health checks, and an offline HTML5 dashboard (all `DISARMED`, zero order authority):

```powershell
# Daily S1+S5 standing leader journal & 2-hourly Champion Ensemble (70% Core + 30% Frozen GRU-Ignition)
uv run --no-sync python scripts/record_leader_journal.py
uv run --no-sync python scripts/record_champion_journal.py --gold-symbol XAUTUSDT

# Read-only 20-symbol Nobitex + Wallex live spread recorder & side-asymmetric execution audit
uv run --no-sync python scripts/record_multi_venue_quotes.py --once
uv run --no-sync python scripts/evaluate_smart_execution.py

# Operational health watchdog & offline interactive HTML5 dashboard
uv run --no-sync python scripts/check_operational_health.py
uv run --no-sync python scripts/build_research_dashboard.py
```

On Windows, `scripts/windows/Install-ChampionJournals.ps1` and `scripts/windows/Install-MultiVenueRecorder.ps1` register these as limited-user scheduled tasks.

## Documentation and checks

- [Capabilities](docs/capabilities.md), [trial log](docs/trial-log.md) and [roadmap](docs/roadmap.md)
- [Documentation index](docs/README.md)
- [Architecture and GUI coverage](docs/architecture.md)
- Full command and option reference: gymctl --help and gymctl COMMAND --help
- [Portfolio replay](docs/portfolio-replay.md), [research contracts](docs/research-workspace.md),
  [margin rules](docs/wallex-margin.md) and [metrics](docs/metrics.md)
- [Storage, archive movement and backup receipts](docs/storage.md)

```powershell
uv run --no-sync python scripts/check.py  # lint, tests and real-browser smoke
uv run --no-sync python scripts/check.py test  # focused mode when browser checks are unavailable
```

Real-browser checks depend on an installed supported browser and are not implied
by API or DOM contract tests. Installed-host security drills, funded-cost
measurement, future evaluation windows and runtime recovery have separate
acceptance evidence.

## Optional Rust money kernel

The simulator can run its sizing, depth-walk and price-guard rules in the executor's Rust kernel (ADR 0005):

```powershell
uvx --from "maturin>=1.7,<2" maturin build --release -m ../executor/exec-kernel-py/Cargo.toml -o dist
uv pip install --no-deps dist\exec_kernel-*.whl
$env:GYM_RUST_KERNEL = "1"; uv run --no-sync gymctl ...
```

`uv run` without `--no-sync` removes the wheel again, because it is deliberately not a locked dependency.
