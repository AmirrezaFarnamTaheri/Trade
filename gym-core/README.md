# gym-core — observatory and paper research

TradingGYM collects public Wallex observations, runs reproducible paper research
and provides an English/Persian operator workspace. The product goal is an
autonomous agent; funded execution remains DISARMED and unavailable.

## Install and run

From the repository's gym-core directory:

```powershell
uv sync
uv run gymctl --data ../data run --assets all
```

Use the same explicit data root for every command. Here, `../data/live` is the
canonical observed store; DEMO uses `../data/demo`. Omitting `--data` selects a
separate `./data` store. Do not overwrite either store to resolve a mismatch.

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
uv run gymctl --data ../data paper BTCUSDT --res 1min --params '{"fast":8,"slow":21}'
uv run gymctl --data ../data portfolio BTCUSDT,ETHUSDT --res 1min
uv run gymctl --data ../data rules list
uv run gymctl --data ../data spreads --output spreads.json
uv run gymctl --data ../data research list
```

Paper research exposes comparisons, validation, saved runs, shared-cash
portfolios, margin previews/replays and research workflows. AI connections use
the optional [model gateway](../model-gateway/README.md); paid requests are
explicit and initially disabled. Spot paper is long/flat; selling exits owned
assets. Margin paper has separate venue credit/collateral contracts.

These example markets demonstrate syntax. The collector defaults to every
eligible spot market; it does not restrict the universe to those examples.
Missing history stays missing. Synthetic DEMO observations and modeled fills
are labeled and cannot authorize capital.

## Documentation and checks

- [Current system status](docs/system-status.md) and [acceptance gates](docs/acceptance-status.md)
- [Implementation plan](docs/implementation-plan.md) and [documentation index](docs/README.md)
- [Architecture and GUI coverage](docs/architecture.md)
- [Full command reference](docs/command-reference.md)
- [Portfolio replay](docs/portfolio-replay.md), [research contracts](docs/research-workspace.md),
  [margin rules](docs/wallex-margin.md) and [metrics](docs/metrics.md)
- [Storage, archive movement and backup receipts](docs/storage.md)

```powershell
uv run --no-sync python scripts/check.py  # lint, tests and real-browser smoke
uv run --no-sync python scripts/check.py test  # focused mode when browser checks are unavailable
```

Real-browser checks depend on an installed supported browser and are not implied
by API or DOM contract tests. Installed-host security drills, funded-cost
measurement, future evaluation windows and physical-host recovery have separate
acceptance evidence.

## Existing section links

Detailed instructions remain available under their original section headings:

## Observed spread report

[Read the retained section](docs/command-reference.md#observed-spread-report).

## Offline external-order observation (B1 development only)

[Read the retained section](docs/command-reference.md#offline-external-order-observation-b1-development-only).

## Optional advisory model connections

[Read the retained section](docs/command-reference.md#optional-advisory-model-connections).

## Code organization

[Read the retained section](docs/command-reference.md#code-organization).

## Local operator workspace

[Read the retained section](docs/command-reference.md#local-operator-workspace).

## Paper sessions, Journal and economic evidence

[Read the retained section](docs/command-reference.md#paper-sessions-journal-and-economic-evidence).

## Persistent paper research and read-only MCP

[Read the retained section](docs/command-reference.md#persistent-paper-research-and-read-only-mcp).

## Joint paper sizing, claim checks and portable reports

[Read the retained section](docs/command-reference.md#joint-paper-sizing-claim-checks-and-portable-reports).

## Closed-bar technical diagnostics

[Read the retained section](docs/command-reference.md#closed-bar-technical-diagnostics).

## Measurement-aligned research and offline review

[Read the retained section](docs/command-reference.md#measurement-aligned-research-and-offline-review).

## Research workspace follow-up

[Read the retained section](docs/command-reference.md#research-workspace-follow-up).
