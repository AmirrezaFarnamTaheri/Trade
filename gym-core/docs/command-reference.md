# gym-core — market observatory and paper research

Public Wallex collector, venue-rule service and a bilingual (EN/FA) operator workspace for an autonomous trading agent.
The current app is **DISARMED**: observation, paper research and offline preparation do not authorize funded execution.
Nothing here can place, cancel or sign venue orders.

The **AI connections** page provides provider setup, protected API-key storage,
supported browser sign-in, model presets and explicit advisory prompts. It uses
the optional [model gateway](../../model-gateway/README.md); requests start disabled.
Paper research also includes an advanced workbench for hypotheses, observations,
numeric reviews, outcome memory, future evaluation and native diagnostics.
See [structure and GUI coverage](architecture.md) for module owners and the
remaining terminal-only or protected-console workflows.
The [documentation index](README.md), [current status](system-status.md)
and [unified implementation plan](implementation-plan.md) separate delivered work from open goals.

```powershell
cd gym-core
uv sync
uv run gymctl --data ../data run --assets all  # canonical repo data/live; all eligible spot pairs
uv run gymctl --data ../data run --assets 100 # explicitly choose a ranked subset
uv run gymctl --data ../data run --demo       # separate synthetic repo data/demo
uv run gymctl --data ../data rules list       # also: add|edit|import|export|disable|rollback|preset|check
uv run gymctl --data ../data spreads --output spreads.json  # all observed pairs, grouped by Tehran hour
uv run gymctl --data ../data trade-flow BTCUSDT --output flow.json  # recorded VWAP, volume and aggressor flow
uv run gymctl --data ../data candles BTCUSDT --fetch         # internal bars vs venue 1min candles
uv run gymctl --data ../data paper USDTTMN --res session --subscribe 1h
uv run gymctl --data ../data demo-seed         # 72 h synthetic DEMO history
uv run gymctl --data ../data paper BTCTMN --demo   # saved synthetic replay under repo data/demo
uv run pytest -q               # behavior and architecture checks
uv run python scripts/check.py # lint + tests + real-browser smoke (also: lint|test|ui|smoke)
```

Use the same absolute `--data` root for every command below. If running from
`gym-core`, use `--data ../data` to access the repository's existing observations;
omitting it selects `gym-core/data`, a separate store. Do not overwrite one store
with another when resolving an older installation.

On Windows, `scripts/windows/Start-Workspace.ps1` (from the repository root)
starts the collector and paper scheduler as limited-user scheduled tasks, using
the repository data root and all eligible spot markets. Preview with `-WhatIf`;
use `-DataDirectory` for an existing custom root. The private browser link is in
`%LOCALAPPDATA%\TradingGYM\workspace-link.txt`. This does not start the executor.

`run` and `serve` print a private link (`http://127.0.0.1:<port>/#t=<session key>`) and open it in the
default browser; pass `--no-browser` to only print it. The key stays in the link's fragment and the tab's
session storage, never in the served page. Market and saved-run reads work without it; every write and
private read needs it, so open the printed link rather than typing the address.

Collection stops with a clear error when the raw-archive volume has less than 5 GiB free. Move older hourly
day folders to another drive with `uv run gymctl raw-move --before 20261101 --to E:\archive` (see
[storage](storage.md)); the manifest is updated so replays still find them.

Long-running collection: `run --archive-to E:\cold --keep-days 7` moves finished day folders once a day,
and every day the collector re-hashes recent raw segments against the manifest. System health shows free
space, growth per hour and hours until the floor, each live connection's reconnects and last frame, the last
archive and integrity sweep, and can raise desktop alerts. `gymctl verify-segments`, `gymctl compact
--before <time> --bucket 1s` (keeps one quote per market and second; the raw archive keeps everything) and
`gymctl candles SYMBOL --fill-gaps` (venue 1-minute candles for quote gaps over 120 s, logged as
GAP_BACKFILLED) are the manual tools. Events are written as JSON lines to `<store>/events.jsonl`, rotated at
50 MB. `scripts/windows/Install-Collector.ps1` starts the collector at logon and restarts it after a
failure; it writes the private link to `%LOCALAPPDATA%\TradingGYM\workspace-link.txt`.
`scripts/windows/Install-BackupSchedule.ps1` runs a daily encrypted ledger backup and a restore drill
(`gymctl restore-drill`) with a passphrase sealed once by `gymctl key set-backup`.

Live `run` stores every current catalog row and defaults to `--assets all`: observe
all listed spot assets with TMN/USDT quotes, including venue-risk-flagged listings.
This does not grant paper eligibility or order authority. Automatic collection has
a 500-asset resource ceiling; exceeding it fails explicitly instead of truncating.
`--assets 1..500` selects a ranked non-risk-flagged subset by combined 24-hour quote
volume (TMN volumes are normalized through USDTTMN). `--add-symbols BTCUSDT,XRPTMN`
and `--remove-symbols PEPETMN` overlay the set; `--watch` replaces it with an explicit
market list. Custom additions are observation-only and bypass ranking filters.
Each WebSocket observes at most 21 markets (63 of the adapter's 64-channel ceiling). Public REST is globally
paced at four requests/second, backs off again on HTTP 429, reseeds stale books in batches of five, and rotates ten candle
checks per minute. The local `/api/markets` response exposes the full catalogue,
collection reasons and capabilities; `/api/capabilities` reports the same runtime
policy. The EN/FA Markets page displays it. Its search and quote filter apply to
both observed quotes and the catalogue; uncollected listings have no invented quotes.

Spot paper buying/selling remains **long/flat at 1×**: SELL exits owned assets.
The separate **Paper research → Wallex margin** workflow now supports LONG/SHORT
paper positions using current venue credit-ratio grids, collateral checks,
public previews, currency-aware fees and recorded-quote replay. The GUI and
`gymctl research margin-markets|margin-preview|margin-replay` use the same bounded
services and immutable receipts. See [margin rules and endpoint review](wallex-margin.md)
for inputs, fee/closure assumptions, authenticated endpoints and qualification
limits. No real borrowing, margin position, order or transfer is submitted.
Generic supplied-debt diagnostics remain available through `gymctl paper-research`.

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

`paper` takes `--from/--to` (zoned ISO), `--res` and comma-separated `--subscribe`.
Shared fixed timeframes are `1min`, `3min`, `5min`, `15min`, `30min`, `1h`, `2h`,
`4h`, `6h`, `12h`, `1day`; rule-based `session` is also available in CLI replay.
Comparison, coverage, technical reports and confirmation schemas use the same
fixed-timeframe catalogue. These bars derive from received observations; they do
not backfill missing history. Direct venue candle fetching remains `1min`/`1h`.
Daily bars align to Tehran midnight; intraday bars align to UTC.
Other paper options include
`--params`, `--fee`, `--latency-ms` and `--rules point-in-time|today`. Legacy EMA
`--fast/--slow` remain supported; maintained examples use registry parameters. Subscribed closed bars are merged by
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
See [acceptance status](acceptance-status.md) for the remaining release blockers.

## Offline external-order observation (B1 development only)

`uv run gymctl --data data external-observe /path/to/manual-observation.json`
accepts a local JSON object with `account_id`, a zoned `observed_at` and
`orders` entries containing `client_id`, `status`, `filled` as exact decimal
text and optionally `symbol`. The importer stores only sanitized,
**unverified external observations** in `data/live/external_journal.db`. The
Account journal (`#account`) displays this sequence read-only; its endpoint requires the
per-run local token. Never include API keys in the import file.
Recorded account reads also retain sanitized order/fill details: exact requested
and executed quantity, reported fill prices, fees and fee assets. The EN/FA
account page expands these observations alongside native known-order receipt
references when supplied by the reviewed service helper. Missing details and
settlement remain unknown; old snapshots are not backfilled.

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

`gymctl models` exposes Pi-backed provider/OAuth connections, explicit environment-key pools and portable preset import/export/catalog sync. It is off by default, runs outside R0, and has no trading tools or funded authority. See the [setup, schema and tested limits](../../model-gateway/README.md). Existing collector/paper commands do not require Node.

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
Research, operator journals, Executor state and model credential/rotation state
also use SQLite. See [storage ownership and verification](storage.md) for
why the compressed raw audit archive remains separate from queryable SQL records.

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

The UI remains native HTML/CSS/JavaScript. [Decision records](decisions.md) explain the session key, display rounding and run-identity rules. [Design system](../../DESIGN.md) and
[surface contract](../../.impeccable/surfaces/operator-workspace.md) describe its shared visual and capability boundaries.

## Paper sessions, Journal and economic evidence

Run these from `gym-core` (use the same `--data` root in both terminals):

```powershell
uv run gymctl run --demo
# Second terminal: synthetic streaming paper, duration begins after two closed 1-minute bars
uv run gymctl session BTCUSDT --demo --res 1min --params '{"fast":1,"slow":2}' --seconds 60
# Session and replay share the strategy registry and validated parameters:
uv run gymctl session BTCUSDT --demo --res 1min --strategy sma-reversion --params '{"lookback":5,"entry_bps":50}' --seconds 60
# Replay stored history for matched baselines, then use its printed run ID:
uv run gymctl paper BTCTMN --demo
uv run gymctl evidence <run-id> --demo --diagnostics --decide NONE --cap 0 --note "Synthetic data: no capital"
```

Shadow mode is a live `session` on the live store: decisions and paper fills against real quotes, no orders.
`gymctl calibrate` then reports feed latency (venue trade time to local receipt, a lower bound for order
round-trips, with a suggested `--latency-ms`) and, across saved runs, decision-to-fill delay, latency drift and
spread cost in basis points plus nonfill reasons.

Sessions record CONFIGURED → WARMING_UP → RUNNING → FINISHING → ENDED; Ctrl+C preserves ABORTED,
reason and replay cursor. There is no warmup timeout: stop an idle session with Ctrl+C. Pending requests settle
only on later qualified observations; ending never sells a holding. Live duration stops new decisions at the
post-warmup deadline and drains pending orders until their fill or timeout. Replay ends at its explicit data cut,
recording any unsettled request as a nonfill. Missing intervals are recorded, not filled with invented HOLDs.

Open **Paper research** (`#research`) in the local UI. Its tabs hold saved runs, the matched comparison form,
schedules, Wallex margin and the advanced workbench. Each run shows risk and return (total and, for windows of
30+ days, annualized return; per-period Sharpe with the probabilistic Sharpe ratio; Sortino, Calmar, drawdown;
win rate, profit factor, expectancy, exposure and turnover) and a first-in-first-out closed-trade ledger. Comparisons
add a selection check: the deflated Sharpe ratio of the best candidate given how many were tried. `paper`,
`compare` and `validate` accept `--participation 0.25` (also on the compare form) to cap each fill at that share
of the displayed best-level size; larger orders are resized down, and runs without the cap keep their old IDs.
Charts show exact values on hover or with the arrow keys, buy and sell markers, and an underwater
(drawdown) strip; comparisons overlay the equity paths. Tick up to four saved runs to view them side by side,
download trades or decisions as CSV, and link straight to a run with `#research/runs/<run id>`. All figures are
explained in [metrics](metrics.md). `gymctl assistant SYMBOL --preset <model preset> --budget 3` lets a
connected model propose configurations, which are validated, tested on paper and saved (so they count as trials);
AI connections shows tokens and cost per model.
The page also lists equity, gross-to-net costs, the active-trading
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

The shared registry contains twelve strategies: `ema-trend`, `sma-cross`,
`sma-reversion`, `bollinger-reversion`, `ema-confirmed`, `relative-momentum`,
`rsi-rebound`, `macd-cross`, `trix-cross`, `keltner-breakout`, `trend-pullback` and
`adaptive-channel`. The [composite strategies](compound-strategies.md) combine
regime/entry filters, scenario costs, displayed-depth sizing and actual-fill
stop/target/drawdown state. They remain paper-only and unqualified. Closed-bar `sma-cross`
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

The [research design](research-design.md) records what was
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

The [capability map](capabilities.md) records the Jev,
AI-Trader and Vibe-Trading adaptations and deferred modules. The
[system status](system-status.md) records module boundaries,
current checks and remaining release work.

Still not certified: independent parity, depth/queue-position stress, installed-worker isolation, trusted funded execution/protection and automatic promotion. See [acceptance status](acceptance-status.md). No monitoring stack was added.

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
[implementation plan](implementation-plan.md).

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
source-family decisions are in [source assessment](source-assessment.md).

## Measurement-aligned research and offline review

Observation imports optionally accept `measured_at` for numeric series. It must
precede publication; actual receipt still determines when a supplied vintage
becomes known. Older records retain their identities and missing measurement
times remain unknown. The observation store does not authenticate supplied data.

`gymctl research derived ratio.json` and the advanced workbench accept exactly
`left`, `right`, `operation`, `as_of`, `max_age_seconds`, `max_skew_seconds`.
Each side identifies `source_id`, `series`, `subject`, `kind`, `unit`.
`RATIO` returns an explicit unit ratio (dimensionless for matching units);
`DIFFERENCE` requires identical units. Both sides use one read snapshot and the
latest measurement known at the cutoff. Stale, misaligned, missing-clock and
zero-denominator results remain unavailable. Arithmetic uses 160 significant
digits with half-even rounding. No external feed or prediction is generated.

`gymctl candles BTCUSDT --from 2026-11-03T17:13:00Z --to 2026-11-03T17:18:00Z --as-of 2026-11-03T17:20:00Z`
excludes trade receipts and candle fetches at or after the cutoff. Omitting
`--as-of` preserves the retrospective CLI report. The advanced workbench action
requires `symbol`, `from`, `to`, `as_of`, `tolerance_bps` and only reads recorded
one-minute candles. It neither fetches replacements nor reconstructs superseded
venue candle vintages.

Saved runs now offer **Download offline HTML report**. The offline ticket form
can save its canonical preview; **Account journal** provides one-time offline
acknowledgment/rejection within the preview's validity window. Web review times
come from the server. These records never grant Executor approval or submit an
order. Other GUI and execution gaps remain in the [implementation plan](implementation-plan.md).
The three subsequent sources and remaining ideas are recorded in the
[research source assessment](research-source-assessment.md).

Technical reports also expose `sma_200`, `sma_distance_20_percent`,
`sma_distance_50_percent`, `sma_distance_200_percent` and `awesome_5_34`.
Distance is `100 * (last_close / SMA - 1)`, a descriptive price comparison;
it does not measure intrinsic value. Awesome Oscillator uses five- and 34-bar
averages of observed high/low midpoints. Periods are contiguous observed bars,
not necessarily days. The existing 31-day read bound cannot provide a 200-day
average; missing history remains WARMUP. No new strategy is enabled.
See the [six-source trading assessment](trading-source-assessment.md)
for complete file accounting, module decisions and all 61 strategy references.
## Research workspace follow-up

The Research page now exposes recorded-data coverage/recovery and stepwise saved
decision replay. Its advanced workbench also provides comparable market ranking,
offline target rebalance previews, immutable experiment/robustness runs,
evidence-linked AI notes and supplied execution-quality comparisons. The CLI
uses the same services. See [workflow contracts](research-workspace.md) and
[implementation/acceptance state](implementation-plan.md).

These are bounded paper/research capabilities. Paid AI sending requires an
explicit action; supplied holdings/fills are unauthenticated and no workflow
grants funded trading authority.

Predictive ML/RL training, neural price forecasting, automated model search and
trained-model order execution are outside current delivery scope. Indicators,
replay, screening, experiment/robustness tools, supplied-forecast scoring and
optional evidence-linked AI connections remain supported.
