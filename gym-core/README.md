# gym-core — market observatory and paper research

Public Wallex collector, venue-rule service and a bilingual (EN/FA) operator workspace for an autonomous trading agent.
The current app is **DISARMED**: observation, paper research and offline preparation do not authorize funded execution.
Nothing here can place, cancel or sign venue orders.

The **AI connections** page provides provider setup, protected API-key storage,
supported browser sign-in, model presets and explicit advisory prompts. It uses
the optional [model gateway](../model-gateway/README.md); requests start disabled.
Paper research also includes an advanced workbench for hypotheses, observations,
numeric reviews, outcome memory, future evaluation and native diagnostics.
See [structure and GUI coverage](docs/architecture.md) for module owners and the
remaining terminal-only or protected-console workflows.

```powershell
cd gym-core
uv sync
uv run gymctl run              # full catalog + top 50 non-risky spot assets -> data\live
uv run gymctl run --assets 100 # choose 25..500 assets; both TMN/USDT markets are observed when listed
uv run gymctl run --demo       # synthetic DEMO feed -> data\demo (never mixed with live)
uv run gymctl rules list       # also: add|edit|import|export|disable|rollback|preset|check
uv run gymctl spreads --output spreads.json  # all observed pairs, grouped by Tehran hour; creates a new file
uv run gymctl trade-flow BTCUSDT --output flow.json  # recorded VWAP, volume and aggressor flow; creates a new file
uv run gymctl candles BTCUSDT --fetch         # internal trade bars vs venue 1min candles, last two hours
uv run gymctl paper USDTTMN --res session --subscribe 1h  # primary session decisions plus 1h close events
uv run gymctl demo-seed         # 72 h synthetic DEMO history (USDTTMN goes silent in its closures)
uv run gymctl paper BTCTMN --demo   # EMA replay + baselines + gross-to-net waterfall -> data\demo\runs\<id>.json
uv run pytest -q               # behavior and architecture checks
```

Live `run` stores every current catalog row, then ranks active non-risky spot assets by combined 24-hour quote volume
(TMNs are normalized through USDTTMN). The default is 50 assets; `--assets 25..500` changes the target. `--add-symbols BTCUSDT,XRPTMN` and `--remove-symbols PEPETMN` overlay
the ranked set; `--watch` replaces it with an explicit market list. Custom additions are observation-only and bypass ranking filters. Each WebSocket observes at most 21 markets (63 of Wallex's 64 channels). Public REST is globally
paced at four requests/second, backs off again on HTTP 429, reseeds stale books in batches of five, and rotates ten candle
checks per minute. The local `/api/markets` response exposes the selection and pacing policy.

`trade-flow [SYMBOL]` reads the existing store without changing it. Optional
`--from` and `--to` are zoned ISO bounds, with an exclusive upper cut. A trade
must have occurred in the window and been received before that cut. Defaults
span the stored events through the last receipt, including legacy timestamps
without fractional seconds. Reports group by pair and Tehran hour across the
selected dates, retaining exact base volume/quote notional, VWAP, average trade
size and buy/sell/unknown base volume. Unknown direction makes imbalance null;
empty data is unavailable. `--demo` explicitly labels synthetic observations.
The digest identifies the included raw rows; gaps, repeats, complete venue tape
and executable prices are not certified. No model call, signal or order occurs.

`paper` takes `--from/--to` (zoned ISO), `--res 1min|15min|1h|1day|session`, `--subscribe 1min,15min,1h,1day,session`,
`--fast/--slow`, `--fee`, `--latency-ms` and `--rules point-in-time|today`. Subscribed closed bars are merged by
availability time and resolution rank; only the primary `--res` drives the current EMA strategy. The same inputs give the same `run_id` and `outputs` digest. Fills use the first qualified
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

## Offline external-order observation (B1 development only)

`uv run gymctl --data data external-observe /path/to/manual-observation.json`
accepts a local JSON object with `account_id`, a zoned `observed_at` and
`orders` entries containing `client_id`, `status`, `filled` as exact decimal
text and optionally `symbol`. The importer stores only sanitized,
**unverified external observations** in `data/live/external_journal.db`. The
Account journal (`#account`) displays this sequence read-only; its endpoint requires the
per-run local token. Never include API keys in the import file.

A missing row does not prove a trade was canceled/absent. A terminal status
is not settlement. Imported balances are never spendable Executor cash. The
GET-only Wallex adapter has **no order-write methods**. `gymctl account --source user`
uses the interactive user's stored read key. From a separate elevated console,
`gymctl account --source service --record` invokes only the protected installed
Executor helper; Python receives no service credential. Both paths normalize
balances, fees and explicitly identified manual orders. `--record` atomically saves
an immutable account snapshot and order changes; the token-protected account view
reads the latest saved snapshot. Version-1 order journals migrate without erasing
history. Transport provenance and venue key permissions remain UNVERIFIED;
balances are never inferred to be spendable. No funded capability is enabled.

## Optional advisory model connections

`gymctl models` exposes Pi-backed provider/OAuth connections, explicit environment-key pools and portable preset import/export/catalog sync. It is off by default, runs outside R0, and has no trading tools or funded authority. See the [setup, schema and tested limits](../model-gateway/README.md). Existing collector/paper commands do not require Node.

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
Venue rules (`#rules`).

## Local operator workspace

The default Overview (`#overview`) combines observed markets, saved paper evidence, mission shortcuts, safety and
known constraints. The shared shell has ten destinations: Overview, Markets (`#markets`), Paper research
(`#research`), Account journal (`#account`), Offline ticket (`#operate`), Venue rules (`#rules`), System health
(`#health`), Safety (`#safety`), Backups (`#backups`) and AI connections (`#models`). English/Persian and light/dark controls are in the navigation;
tables scroll within their own region on small screens.

Offline ticket offers structured fields and a JSON editor for the same bounded cost preview. Use exact decimal
strings for amounts; the synthetic example remains labelled. Editing a ticket invalidates its previous result.
The preview submits no venue order and grants no capital authority. Safety exposes missing execution gates.
Backups documents the existing protected-console backup/restore commands; the web API has no archive inventory or
last-recovery status, so the screen explicitly reports **Status not connected**. Keep credentials and recovery
passphrases out of browser fields. System health displays only existing collector, venue-evidence and saved
simulation records; missing evidence is not a successful check.

The UI remains native HTML/CSS/JavaScript. [Design system](../DESIGN.md) and
[surface contract](../.impeccable/surfaces/operator-workspace.md) describe its shared visual and capability boundaries.

## Paper sessions, Journal and economic evidence

Run these from `gym-core` (use the same `--data` root in both terminals):

```powershell
uv run gymctl run --demo
# Second terminal: synthetic streaming paper, duration begins after two closed 1-minute bars
uv run gymctl session BTCUSDT --demo --res 1min --fast 1 --slow 2 --seconds 60
# Session and replay share the strategy registry and validated parameters:
uv run gymctl session BTCUSDT --demo --res 1min --strategy sma-reversion --params '{"lookback":5,"entry_bps":50}' --seconds 60
# Replay stored history for matched baselines, then use its printed run ID:
uv run gymctl paper BTCTMN --demo
uv run gymctl evidence <run-id> --demo --diagnostics --decide NONE --cap 0 --note "Synthetic data: no capital"
```

Sessions record CONFIGURED → WARMING_UP → RUNNING → FINISHING → ENDED; Ctrl+C preserves ABORTED,
reason and replay cursor. There is no warmup timeout: stop an idle session with Ctrl+C. Pending requests settle
only on later qualified observations; ending never sells a holding. Live duration stops new decisions at the
post-warmup deadline and drains pending orders until their fill or timeout. Replay ends at its explicit data cut,
recording any unsettled request as a nonfill. Missing intervals are recorded, not filled with invented HOLDs.

Open **Paper research** (`#research`) in the local UI for saved runs, equity, gross-to-net costs, the active-trading
USDT-equivalent ranking, matched replay baselines, reports and expandable decisions (snapshot, feature hash, request,
order/veto, +15m/+1h/+4h outcome marks). Zero-trade results remain visible as abstainers and are excluded from the
active rank. Public Wallex instrument metadata is stored as complete, point-in-time vintages with source, availability
interval, version and raw digest; missing historical fields remain UNKNOWN rather than borrowing today's catalog.
Marks are PENDING before their horizon, MISSING without a later qualified quote, or OBSERVED_AFTER_GAP with delay.
The UI lists the latest 50 runs and last 100 decisions; full records remain in `data/<store>/runs`.

`evidence` writes `<id>.evidence.md` and `.evidence.json`. Diagnostics check repeatability, midpoint future-truncation
and streaming/replay decision parity. Warmup compares EMA direction against twice-slow-length prehistory when
available, otherwise explicitly NOT_RUN. Matched-filled-path cost stress scales observed spread, fees and latency drift
by 0/1/1.25/2/3; it does not change fills, depth or decisions. Parity shares an engine, not an independent simulator. The horizon estimate uses completed round trips
and an explicitly IID approximation, not a power guarantee for dependent trades. No report currently supports a
validated/promising claim or gate promotion. DEMO permits only NONE/zero capital.

`--decide NONE|EXPERIMENTAL --cap <amount> --ccy USDT|TMN --note <text>` adds an immutable `*.decision.json`,
never trading permission. Existing decisions are never edited. Live sessions disclose that baselines and USDT
attribution need a separate matched replay; live-session diagnostics are explicitly NOT_RUN.
Evidence reports explicitly disclose the final qualified mark's age at the run
cutoff; marks older than the existing 120-second quote limit are STALE. A recorded
last-mark result is not a current end-of-window valuation.

## Persistent paper research and read-only MCP

Hypotheses pin the built-in strategy, parameters, code/engine identity and symbol. For example, save this as `hypothesis.json`:

```json
{"symbol":"BTCUSDT","strategy":"ema-trend","params":{"fast":8,"slow":21}}
```

```powershell
uv run gymctl --data ../data research register hypothesis.json
uv run gymctl --data ../data research list
uv run gymctl --data ../data research shadow-open shadow.json
uv run gymctl --data ../data research shadow-close close.json
uv run gymctl --data ../data research schedule schedule.json
uv run gymctl --data ../data research tick --at 2026-11-03T12:00:00Z
uv run gymctl --data ../data research pause <job-id>
uv run gymctl --data ../data research resume <job-id>
uv run gymctl --data ../data research start --poll-seconds 5
uv run gymctl --data ../data research mcp
uv run gymctl paper-research input.json --output report.json
```

Registration returns the `hypothesis_id`. A shadow-open input has exactly `position_id`, `hypothesis_id`, `quote`, `gross_quantity`, `fee_rate`; close has `position_id`, `quote`. Quote fields are `at`, `bid`, `ask`, `state` (`OPEN`/`CLOSED`), `qualified` (`true`). Quantity, price and fee values are plain finite decimal strings. Fees reduce the asset received on each side. A closed-market close remains `PENDING_REOPEN`; it never fabricates an executable fill.

A schedule has exactly `hypothesis_id`, `every_seconds` (60–86400), `lookback_seconds` (60–2678400), `first_at` (zoned ISO timestamp), `resolution`, `cash`, `fee_rate`. `tick` runs one bounded batch of ten due jobs. `start` supervises repeated batches in the foreground using read-only market connections; polling is 1–60 seconds. Ctrl+C stops after the current synchronous batch. Restart retains committed clocks/retries; `pause` and `resume` control individual jobs without deleting history. No daemon or automatic system startup is installed. Failed windows persist a retry time instead of starving healthy jobs. Report, alert and successful clock advance commit together. Research alerts are not execution Proposals. Add `--demo` to each research command for an isolated synthetic store.

The stdio MCP server exposes only `strategy_catalog`, `research_state`, `market_coverage`, with fixed arguments and read-only SQLite access. Discovery annotations and its capability snapshot describe this fixed local read-only surface; they do not attest installed runtime isolation. No credential/account tool, arbitrary file path, dynamic tool or execution capability is exposed. The market/expiry report also remains PAPER_ONLY; product terms/liquidity calibration need real venue evidence.

Successful tool responses include `_meta["tradinggym/provenance"]`: the tool name,
the arguments' native sorted-key JSON digest and the SHA-256 of the exact UTF-8 text in
`content[0].text`. Verify that text directly, without parsing/reserializing it.
The text payload remains unchanged for existing clients. Metadata follows the
[project's MCP 2024-11-05 result schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2024-11-05/schema.json).
These checksums detect mismatches; they do not authenticate the venue or prove
that an analyst's conclusions follow from the data.

`paper-research` also accepts `position-sizing`, a long-only spot calculation.
For a **hypothetical arithmetic example**, save the following as `sizing.json`
and run `uv run gymctl paper-research sizing.json --output sizing-report.json`:

```json
{"model":"position-sizing","parameters":{
  "quote_currency":"USDT","equity":"1000","cash":"500",
  "entry_price":"100","stop_price":"90","risk_fraction":"0.02",
  "max_position_fraction":"0.3","cash_buffer_fraction":"0.1",
  "quantity_step":"0.01","fee_rate":"0.001","slippage_rate":"0.005"
}}
```

Every input is explicit; amounts and fractions are plain decimal strings.
Risk/position fractions must be positive and below one; reserve/fee/slippage
fractions must be nonnegative and below one. Cash cannot exceed equity, and the
stop must be positive and below entry. The example sizes **1.79 gross base units**,
binding on its 20-USDT modeled-loss budget. Quantity rounds down to the supplied
step; insufficient cash or a step too large produces `NO_CAPACITY`.
The model includes adverse slippage and fees in the received asset on both legs.
It neither verifies these assumptions nor supplies a stop order, venue minimums,
portfolio allocation, account permissions or funded authority.

The shared registry contains ten strategies: `ema-trend`, `sma-cross`,
`sma-reversion`, `bollinger-reversion`, `ema-confirmed`, `relative-momentum`,
`rsi-rebound`, `macd-cross`, `trix-cross` and `keltner-breakout`. Closed-bar `sma-cross`
requires `slow + 1` observations to compare previous/current averages. Its
crossovers use actual holding state; an unfilled entry does not create a position.
Replay, live paper, schedules, comparisons, validation and the UI use the same
validated parameters and versioned strategy identity.

`bollinger-reversion` uses the rolling mean and population standard deviation of
closed prices: enter below `mean - deviations × standard_deviation`, then exit
at or above the rolling mean. Defaults are 20 bars and two deviations; lookback
is bounded to 2..10,000 and deviations to integer 1..5. This is a long-only band
experiment, not the source's leveraged squeeze/ADX breakout or a protected order.

The offline `trade-economics` model makes trading and inference costs explicit.
For example, save this **hypothetical calculation** as `economics.json`, then
run `uv run gymctl paper-research economics.json --output economics-report.json`:

```json
{"model":"trade-economics","parameters":{
  "quote_currency":"USDT","entry_price":"100","stop_price":"90",
  "target_price":"120","gross_base_quantity":"2","fee_rate":"0.001",
  "slippage_rate":"0.005","inference_cost_quote":null
}}
```

It reports modeled gain, loss, reward/risk and the break-even win fraction under
an explicit two-outcome assumption, including received-asset fees and adverse
slippage. A missing inference cost keeps the after-inference result `UNAVAILABLE`;
an explicit decimal string `"0"` means known zero for this supplied scenario.
Inference cost is allocated once per round trip in the stated quote currency.
If costs erase even the target outcome, status is `COST_DOMINATED` with no feasible
break-even probability. These are supplied assumptions, not measured billing,
a win-probability forecast, a stop-fill guarantee or approval to trade.

The Paper Research screen reads recorded schedules, due times, last results,
retry deadlines and alerts. Pause/resume retain the committed clock. **Run due
jobs now** executes one batch of at most ten jobs; it does not silently start a
background scheduler. Successful jobs publish immutable, inspectable run files
before their completion/clock transaction commits. A publication failure cannot
report a completed run or advance the clock.

**Run chronological validation** uses the comparison inputs: select an active
candidate on the first 70%, skip one decision period, and evaluate that fixed
candidate on the later data in a separate paper account. Both phases share one
SQLite read snapshot. The CLI equivalent is `gymctl validate` with the same
`--candidate` inputs as `compare`. Fixed-duration bars are required; each phase
needs at least three decision periods and still has its own strategy warmup.
Zero-trade or stale selection results abstain. Runs and a validation manifest are
saved separately; repeated historical diagnostics are **not** independent final
evidence or capital permission.

The CLI accepts `validate --folds 1..5` (default `1`). Research exposes the same
choice as **Validation windows**; `/api/validate` accepts an optional integer
`folds` with the same bounds and default. It partitions
the requested range into successive, disjoint windows and repeats that same
70/30 diagnostic inside each, with a separate one-period purge and fresh paper
cash/strategy state. All windows share one SQLite read snapshot. Each window
retains its selection, status, referenced runs and holdout result; missing
selection data rejects the request, while stale/abstaining windows make the
overall result `INCOMPLETE`. Failed outcomes never become zero returns, and
the report does not compound independent accounts into a portfolio curve.
This is repeated historical evaluation, not expanding ML training. A single
window preserves the existing result format. For example:

```powershell
uv run gymctl validate BTCUSDT --res 1min --folds 3 `
  --from 2026-11-03T17:13:00Z --to 2026-11-03T20:13:00Z `
  --candidate '{"strategy":"ema-trend","params":{"fast":3,"slow":8}}' `
  --candidate '{"strategy":"sma-reversion","params":{"lookback":3,"entry_bps":0}}'
```

Each sub-window needs enough recorded data for the chosen decision resolution
and warmup. More windows do not create more independent market evidence.

`GET /api/ready` returns reason-coded public-data readiness (503 when blocked).
System Health shows current bid/ask ages per pair. A healthy pair can remain
usable when another pair is degraded; no public readiness response grants funded
authority. The health endpoint remains available while readiness is blocked.
Freshness ticks do not wait for REST refreshes, and shutdown cancels the collector
workers together before storage cleanup.

The [research design](docs/research-design.md) records what was
adapted from the older project and which overlapping or broker-specific modules
were deliberately retained there.

Expanded Markets rows show observed depth within 10/25/50 bps of mid and
base-quantity imbalance. They use only actual received levels; stale, future or
invalid books publish no aggregate. This is not executable depth or queue proof.

Paper reports include sampled drawdown from initial cash and the end estimate.
The Research inspector downloads an authenticated, allowlisted JSON summary with
run/data/config fingerprints, exact values, valuation age and modeled costs.
Private notes and account records are excluded; the original run is still needed
for replay. Gaps can hide larger losses between recorded marks.

The [capability map](docs/capabilities.md) records the Jev,
AI-Trader and Vibe-Trading adaptations and deferred modules. The
[system status](docs/system-status.md) records module boundaries,
current checks and remaining release work.

Still not certified: independent parity, depth/queue-position stress, installed-worker isolation, trusted funded execution/protection and automatic promotion. See [acceptance status](docs/acceptance-status.md). No monitoring stack was added.

## Joint paper sizing, claim checks and portable reports

`gymctl paper-research FILE` also accepts `"model":"portfolio-sizing"`.
Parameters are `quote_currency`, `equity`, `cash`, `total_risk_fraction`,
`cash_buffer_fraction`, `max_allocation_fraction`, `fee_rate`, `slippage_rate`
and `candidates`. All numeric inputs are plain decimal strings. Each of 1..100
ordered candidates has `symbol`, `entry_price`, `stop_price`, `risk_fraction`,
`max_position_fraction` and `quantity_step`. Symbols must be unique and use the
declared quote currency. Candidates share one reserve, loss budget and allocation
cap; this sizes hypothetical new entries, not actual holdings or venue orders.

`gymctl research claim-check FILE` checks 1..32 typed numeric claims against
saved artifacts in the selected store. Each claim has `id`, `operation`
(`VALUE`, `DIFFERENCE`, `RATIO`), `sources`, `value` and `decimal_places` (0..12,
half-even rounding). Each source is `{ "run_id": "...", "metric": "..." }`.
Metrics are `net_quote`, `equity_quote`, `starting_cash_quote`,
`hold_cash_net_quote`, `fills`, `qualified_observations` and
`sampled_drawdown_percent`. Arithmetic requires matching inputs and units;
unknown fields, missing data and zero-denominator ratios reject. Exit status
is 0 for all matched, 3 for a numeric mismatch, and 2 for invalid input. This
does not validate free-text claims, predictions or feed authenticity and cannot
authorize an order. `--demo` selects the isolated demo store explicitly.

`gymctl summary RUN_ID --format html --output paper.html` creates a portable,
script-free English report with escaped text, exact values, limitations and the
allowlisted source summary. JSON is the default format. Output files are created
exclusively; existing files are never overwritten. Private notes, account data,
model transcripts and arbitrary evidence are excluded in both formats.

The complete remaining work and acceptance requirements are tracked in
[implementation plan](docs/implementation-plan.md).

## Closed-bar technical diagnostics

`gymctl technicals BTCUSDT --from 2026-11-03T17:13:00Z --to 2026-11-03T20:13:00Z --res 1min --output technicals.json`
reads the existing market store and creates a JSON report without overwriting
an existing file. `--demo` explicitly selects the separate demo store. Bounds
must include time zones, span at most 31 days and contain at most 10,000 fixed
bar periods; session bars are excluded. Reads are bounded to 100,000 observations.

The report describes observed midpoint quotes using SMA20/50, Wilder RSI14 and
MACD12/26/9. Only complete closed bars qualify. Invalid-quote intervals are
excluded, missing buckets restart warmup, and insufficient history returns null.
RSI needs 15 closes and genuinely flat prices return 50. MACD uses the existing
first-close-seeded EMA; its signal averages available MACD history and needs 34
closes. This convention does not promise numerical parity with other libraries.
Quote volume is unavailable. These are descriptive observations, without a
buy/sell signal, calibrated probability, new strategy or order authority.

Repeat `--res` to compare up to four distinct fixed resolutions from one read:
`gymctl technicals BTCUSDT --from 2026-11-03T17:13:00Z --to 2026-11-03T20:13:00Z --res 1min --res 15min --res 1h --output timeframes.json`.
Multiple resolutions produce `technical-timeframes/1`, with a shared observation
digest and cutoff and independent closed bars, quality exclusions and warmup per
view. The 10,000-period budget applies across all requested views. One resolution
keeps the original report format; omitting `--res` still uses `15min`. Agreement
between views is not a probability or order instruction. The complete latest
source-family decisions are in [source assessment](docs/source-assessment.md).
