# gym-core — market observatory and paper research

Public Wallex collector, venue-rule service and a bilingual (EN/FA) Markets screen with a pair-scoped
"When can I act?" bar, paper sessions and an economic evidence report. No live order code exists; nothing here can place, cancel or sign venue orders.

```powershell
cd gym-core
uv sync
uv run gymctl run              # live public data -> data\live, UI on http://127.0.0.1:8765/
uv run gymctl run --demo       # synthetic DEMO feed -> data\demo (never mixed with live)
uv run gymctl rules list       # also: add|edit|import|export|disable|rollback|preset|check
uv run gymctl spreads --output spreads.json  # all observed pairs, grouped by Tehran hour; creates a new file
uv run gymctl candles BTCUSDT --fetch         # internal trade bars vs venue 1min candles, last two hours
uv run gymctl paper USDTTMN --res session    # session bars bounded by the venue-rule closures
uv run gymctl demo-seed         # 72 h synthetic DEMO history (USDTTMN goes silent in its closures)
uv run gymctl paper BTCTMN --demo   # EMA replay + baselines + gross-to-net waterfall -> data\demo\runs\<id>.json
uv run pytest -q               # behavior and architecture checks
```

`paper` takes `--from/--to` (zoned ISO), `--res 1min|15min|1h|1day`, `--fast/--slow`, `--fee`, `--latency-ms` and
`--rules point-in-time|today`. The same inputs give the same `run_id` and `outputs` digest. Fills use the first qualified
ask (buy) or bid (sell) at or after decision + latency. Rule closures, quota and minimums cause nonfills. Holdings are
never auto-sold at the end. USDT-equivalent uses a disclosed USDTTMN mid valuation rate only when qualified
quotes were already available at both valuation boundaries. Otherwise results remain in the quote currency;
a later FX quote is never borrowed to value starting cash.

## Observed spread report

`gymctl spreads [SYMBOL] [--demo] [--from <zoned-ISO>] [--to <zoned-ISO>] [--output <new-file>]`
reports sample counts, minimum, median, nearest-rank p95 and maximum spread in basis points for each pair/Tehran hour.
Ranges are start-inclusive and end-exclusive; defaults include the last stored quote. Reports retain a source-data digest.
Without `--output`, JSON goes to stdout. File output never overwrites an existing file, including the source database.

These are **observation-weighted** distributions of change-only snapshots and heartbeats, not time-weighted estimates.
Unobserved hours are absent, not zero. Invalid/stale observations are excluded; windows are not filtered, so a stored
quote is not proof of executability. DEMO is explicitly synthetic. This does not measure fees, depth slippage or latency.
See [acceptance status](docs/acceptance-status.md) for the remaining release blockers.

## Code organization

- `src/gym/domain/`: pure market types, bars, rules, strategies and simulation/accounting.
- `src/gym/adapters/`: Wallex transport, SQLite/raw segments and validated run-artifact storage.
- `src/gym/services/data_portal.py`: point-in-time market-data queries.
- `src/gym/services/session.py`: paper-session state and pending-order settlement.
- `src/gym/services/paper.py` and `live_paper.py`: replay and streaming orchestration.
- `src/gym/services/diagnostics.py`: reproducibility, causality and stress checks.
- `src/gym/services/reports.py`: economic evidence and human-readable reporting.
- `src/gym/services/market_statistics.py`: observed spreads by pair and venue-local hour.
- `src/gym/services/feed_crosscheck.py`: internal LAST bars against venue candles.
- `src/gym/domain/units.py`: IRT unit-discontinuity detection and the entry-freeze rule it produces.
- `src/gym/api/server.py`: loopback HTTP endpoints; `src/gym/ui/`: HTML, JavaScript and CSS.
- `tests/`: behavior-focused suites with deterministic fixtures in `tests/support.py`.

Architecture tests enforce inward dependencies: domain → no I/O, adapters → no services/API,
services → no API. There are no milestone-named production modules or tests.

Storage: raw WS/REST frames go to hourly `raw/YYYYMMDD/*.jsonl.zst` with a SHA-256 manifest in `segments`. `market.db` holds
change-only `book_top`, `trades`, `quality_events` and the immutable `regime_events` rule ledger.

The first run preloads the preset `usdt-irt-october-2026`: USDTTMN closed 21:00-09:00 Tehran from 30 Sep, then 23:30-11:30
from 18 Oct, plus a 2,000 USDT purchase cap per Tehran day. Status is REPORTED, from an announcement. Edit it in
Settings -> Venue rules.

## Paper sessions, Journal and economic evidence

Run these from `gym-core` (use the same `--data` root in both terminals):

```powershell
uv run gymctl run --demo
# Second terminal: synthetic streaming paper, duration begins after two closed 1-minute bars
uv run gymctl session BTCUSDT --demo --res 1min --fast 1 --slow 2 --seconds 60
# Replay stored history for matched baselines, then use its printed run ID:
uv run gymctl paper BTCTMN --demo
uv run gymctl evidence <run-id> --demo --diagnostics --decide NONE --cap 0 --note "Synthetic data: no capital"
```

Sessions record CONFIGURED → WARMING_UP → RUNNING → FINISHING → ENDED; Ctrl+C preserves ABORTED,
reason and replay cursor. There is no warmup timeout: stop an idle session with Ctrl+C. Pending requests settle
only on later qualified observations; ending never sells a holding. Live duration stops new decisions at the
post-warmup deadline and drains pending orders until their fill or timeout. Replay ends at its explicit data cut,
recording any unsettled request as a nonfill. Missing intervals are recorded, not filled with invented HOLDs.

Open **Research / Journal** in the local UI for saved runs, equity, gross-to-net costs, matched replay baselines,
reports and expandable decisions (snapshot, feature hash, request, order/veto, +15m/+1h/+4h outcome marks).
Marks are PENDING before their horizon, MISSING without a later qualified quote, or OBSERVED_AFTER_GAP with delay.
The UI lists the latest 50 runs and last 100 decisions; full records remain in `data/<store>/runs`.

`evidence` writes `<id>.evidence.md` and `.evidence.json`. Diagnostics check repeatability, midpoint future-truncation
and streaming/replay decision parity. Warmup compares EMA direction against twice-slow-length prehistory when
available, otherwise explicitly NOT_RUN. Cost stress scales **fees only** by 0/1/1.25/2/3; 0 is fee-free, not
frictionless. Parity shares an engine, not an independent simulator. The horizon estimate uses completed round trips
and an explicitly IID approximation, not a power guarantee for dependent trades. No report currently supports a
validated/promising claim or gate promotion. DEMO permits only NONE/zero capital.

`--decide NONE|EXPERIMENTAL --cap <amount> --ccy USDT|TMN --note <text>` adds an immutable `*.decision.json`,
never trading permission. Existing decisions are never edited. Live sessions disclose that baselines and USDT
attribution need a separate matched replay; live-session diagnostics are explicitly NOT_RUN.

Deferred: independent parity oracle, full spread/depth/latency stress, session/volume bars, venue-candle cross-check,
limit orders, automatic promotion, tray and Rust Executor. No monitoring stack or new dependency was added.
