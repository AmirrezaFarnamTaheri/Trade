# Research workspace

The Research page and `gymctl research` share `services/research_actions.py`.
All results are local research or paper calculations. None submits an order,
grants protected-executor permission or authenticates supplied holdings/fills.
Live and demo ledgers remain separate.

For object inputs, use `gymctl --data DATA research ACTION INPUT.json`.
`DATA/live` or `DATA/demo` contains the store; `--demo` selects the latter.
The browser calls token-protected `POST /api/research/action` with exactly
`{"action": ACTION, "value": INPUT}`. Duplicate JSON fields and nonfinite JSON
numbers are rejected. Object requests are bounded to 64 KiB. These actions use
the actual clock; they reject `--at` overrides.

## Expanding walk-forward selection

`walk-forward`: exactly `hypothesis`, `symbol`, `candidates` (strategy/params
objects), `windows` (train_from/train_to/test_from/test_to), `final_from`,
`resolution`, `cash`, `fee_rate`, `latency_ms`, `purge_bars`.
Use 2..8 distinct registered configurations, 1..5 windows and at most 32 total
training/test slots. Cash/fees are exact decimal strings. Windows must be
historical closed-bar boundaries, at most 31 days/5,000 decision periods each.
Training expands from one origin and can include earlier tests. Test windows
are disjoint; a purge of 1..100 decision bars separates training from its test.
The final cutoff cannot precede any test end and its market data is not read.

The existing experiment registry freezes the definition and all attempt slots
before market reads, then records every outcome and each selection before that
fold's test. Selection maximizes active, current-valued training net quote after
modeled costs, including negative winners. Missing/failed/stale/no-trade trials
remain visible. Replay uses one bounded read snapshot and the native paper engine;
saved runs are verified through the existing run reader. Each window has its own
flat cash account and warmup; test returns are not compounded into a portfolio.
The workflow is supervised through the CLI and private workbench. Results are
historical exploratory diagnostics, with no independent custody, future final
evaluation, measured fees or capital permission. Read the durable experiment ID
after uncertain delivery before deciding whether another search is appropriate.

## Coverage and recovery

`coverage`: exactly `symbol`, `from`, `to`, `resolution`. Times must be zoned;
`to` is exclusive and cannot be future. Maximum 31 days, 1,440 buckets and
100,000 combined quote/trade observations. Fixed native resolutions are `1min`,
`15min`, `1h`, `1day` (daily boundaries follow the venue calendar).

The timeline retains missing, degraded, stale and observed buckets, receipt-time
trade delay, age of the last known qualified quote, and indicator warmup. A
missing bucket resets readiness; it does not receive invented bars. An observed
bucket does not establish uninterrupted intrabucket coverage. A late historical
download does not become a quote known during the historical missing period.

`job-recover`: `job_id`, `expected_due`, `action` (`RETRY` or `SKIP`), `reason`.
Only the current failed, already-due window can be recovered. `expected_due`
prevents acting on a stale view. Retry clears its waiting deadline but does not
run the job. Skip advances exactly one window, retains the previous failure and
writes an actual-time audit event. A reason is required for both actions.

`job-catch-up`: `job_id`, `limit` (integer 1..10). Processes that job's eligible
windows only; it stops when no window is eligible. A failure retains the due
window and retry deadline. The GUI exposes these as separate explicit controls.
It does not silently skip the existing missing-data window.

An unavailable registered engine or strategy revision now produces
HYPOTHESIS_VERSION_UNAVAILABLE, retryable=false and no automatic retry time.
The job clock remains unchanged and its failed attempt survives restart. The
dashboard and recovery controls show the reason in English/Persian. An explicit
RETRY permits one more attempt after restoring the original revision; it does
not reinterpret an old hypothesis with current code. Alternatively pause that
job and register/schedule a separate current-engine hypothesis.

Live paper collection aborts on a backward wall clock and retains the observed
finish clock, first regressed reading and last processed time in its run identity.
Shutdown never moves the session cursor backward. If the wall clock has not
caught up, the aborted session closes at its last processed time and discloses
the earlier observed finish reading. This preserves the failed run rather than
losing it to finalization; it is not successful duration or coverage evidence.

## Decision replay

`replay`: `run_id`, `offset` (nonnegative integer), `limit` (1..200). The GUI
provides previous/next navigation. Artifact identity, output digest, store and
16 MiB size bound are checked before use. Fingerprints establish integrity
consistency, not independent source authentication.

New `paper-session/8` artifacts record pre-decision balances, bar/context/reference
observations and deduplicated rule snapshots. Replay resolves the rule reference
and shows the decision, reasons and available feature values. Subsequent modeled
orders have a separate display; future outcome marks are excluded from the
decision-time view. Old runs retain unknown bar/rule details. Their reconstructed
balances use only postings strictly before the timestamp and explicitly flag
unknown equal-timestamp scan/settlement ordering.

## Recorded-market screening

`market-screen`: `symbols`, `reference`, `quote_currency`, `from`, `to`,
`resolution`, `metric`. Supply 1..20 distinct symbols with one USDT or TMN quote
currency and a reference within the universe. The same bounded market read
snapshot supplies every symbol. The universe is explicit, not a reconstructed
historical listing census.

Metrics: `momentum_percent`, `relative_momentum_percent`,
`sma_distance_20_percent`, `spread_bps`, `liquidity_quote`, `volatility_percent`.
Volatility is unannualized sample dispersion of bar returns; liquidity is the
smaller supplied top bid/ask notional, not full-book capacity. Relative momentum
is the difference from the reference's return. Stale, gapped, missing and warmup
markets retain exclusion reasons. These rankings are not intrinsic valuation,
aggregate confidence or trading permission.

## Target rebalance preview

`rebalance`: `quote_currency`, `cash`, `reserved_cash`, `fee_rate`, `positions`.
Each of 1..100 positions has exactly `symbol`, `held`, `reserved`,
`target_weight`, `bid`, `ask`, `quantity_step`, `minimum_quote`. Amounts and
weights are exact plain decimal strings; symbols must share the declared quote
currency. Weights sum to at most one. `minimum_quote: null` blocks that leg with
`UNKNOWN_MINIMUM`; it does not assume an exchange minimum of zero.

Equity and target quantities use supplied bid marks. Sales cannot use reserved quantities. Purchases
share cash after its reservation, round quantities downward and use ask prices.
The disclosed fee assumption charges the received asset. Sale proceeds remain
conditional: the output identifies purchases requiring sale settlement, reports
post-cost projected holdings/weights and remaining target shortfalls, and never
claims that those proceeds are available account cash. Turnover/concentration
are descriptive. Acquisition basis, ownership, price freshness, settlement and
actual fee schedules remain unverified supplied inputs.

## Experiments and robustness

`experiment-run`: exactly `hypothesis`, `symbol`, `strategy`, `trials`, `windows`,
`resolution`, `cash`, `scenarios`, `final_evaluation_id`. `trials` is a list of
native parameter objects. `windows` is a chronological, disjoint list of
`{from,to}` objects. `scenarios` contains `{fee_rate,latency_ms,outages}`, with
outages expressed as `{from,to}` inside one window. Use null for no final link.

Each list has 1..8 entries and the product is at most 32 attempted runs. Windows
are historical, at most 31 days and 5,000 bars each, with at most 100,000 source
quotes per window. The budget includes the requested instrument, consumed BTC
and USDT baselines, configured strategy references and their 120-second lookup,
and the one-day USDTTMN valuation lookback for TMN runs. Unrelated collected
markets do not consume this budget. Latency is 0..60,000ms;
each scenario has at most eight feed outages. Fee and latency assumptions use
the native paper order model; outage intervals remove quote receipts from the
strategy and matched baselines without altering the source database. There is
no independently adjustable extra-slippage parameter: native observed sides,
fee and latency drift remain the disclosed model.

The definition and every attempt are durably inserted before market reads.
One market read snapshot spans the comparisons. Results link saved run/output/
data digests and matched cash/asset baselines. Failures and no-data runs stay in
the journal. A crash or budget/read failure leaves `RESULT_PENDING` attempts,
which mean completion is unknown; they are never silently treated as zero-return
successes or automatically retried. This is exploratory comparison, not a
training/selection claim or automatic promotion.

`experiment-list` lists the latest 50 definitions with their events.
`experiment-status ID` reads a specific saved definition/packet/note and its
events. Definitions and events are append-only in `experiments.sqlite3`, using
WAL/FULL synchronization and retention triggers. This is local integrity, not
independent custody. A final link must match native parameters, symbol,
resolution, cash, engine digest and selection bounds; linking does not consume
the evaluation. Existing `final-register`/`final-run` retain consume-once rules.

## Evidence-linked AI notes

`research-packet`: `run_ids` (1..4 distinct saved runs). Produces an allowlisted
numeric performance/risk/cash-benchmark review, exact citation IDs and a bounded
prompt. Private notes, credentials, account journals, raw transcripts and order
tools are not included. Preparing a packet makes no provider request.

The GUI displays the prompt and saved packet ID. A separate explicit send button
uses a configured AI preset through the existing model gateway and may incur
charges. The gateway stays subject to its enabled/auth/preset policy. No paid
request or real authentication was performed during implementation checks.

`research-notes`: `packet_id`, `preset`, `notes`. Paste the returned structured
notes and the original packet/preset references. Each of at most three notes has
`role` (`performance`, `risk`, `benchmark`), `observation` (1..2,000 characters),
`citations`, `claims`, `disagrees_with`. Roles are distinct. Citations must match
the packet; numeric claims use the existing exact `claim-check` schema and must
match cited native metrics. Disagreement references must identify included roles.
Empty claim lists are allowed. Interpretations and model provenance remain
unverified; numeric checks never certify prose or causality. Saved notes are
immutable journal events, not execution recommendations or verified lessons.

## Execution-quality comparison

`execution-quality`: `run_id`, `observations` (0..500). Each observed fill has
`fill_id`, `order_ref`, `side`, `quantity`, `price`, `fee`, `fee_currency`,
`filled_at`, `observed_at`. Amounts are decimal strings, IDs are unique and
bounded, and fee currency must be the run's base or quote. Receipt cannot precede
fill time; matched fills cannot precede the decision or disagree on side.

The comparison retains unmatched order references, modeled nonfills and orders
with no observed fill. It aggregates partial observations without assuming that
they constitute complete settlement, computes VWAP/quantity differences, adverse
price bps, fee differences and first-fill latency. Base fees are converted at
their individual fill prices for a disclosed quote-equivalent diagnostic.
These supplied observations are unauthenticated; no real fill is fabricated
from a paper order, and missing observations never become measured zero cost.

## Causality and prehistory diagnostics

`strategy-audit`: `symbol`, `strategy`, `params`, `from`, `to`, `resolution`,
`cash`, `fee_rate`, `latency_ms`, `checkpoints`, `history_starts`. Amounts are
decimal strings; time bounds are zoned past timestamps. A single read snapshot
and fresh native strategy instance per replay compare the full decision prefix
with each independently truncated replay. Later outcome marks are omitted.
Prehistory variants compare only recorded feature values at the same final
decision time; legitimate different holdings/actions are not convergence errors.
Absent features are NOT_COMPARABLE. Bounds: 31 days, 1,440 bars, 1..8 endpoints,
0..4 prehistory starts and 500,000 quote-read units across repeats. No arbitrary
strategy code or missing market observation is generated. Selected matches do
not prove absence of bias or future profitability.

`return-bootstrap`: `run_id`, `seed`, `simulations`, `mean_block_length`,
`max_gap_seconds`. Verifies the saved run/output identity and selected store.
Uses simple equity returns including the saved modeled costs; marks must be
strictly chronological, finite and positive. At least 20 intervals are required.
Intervals exceeding the declared gap bound are excluded and break blocks;
endpoints also restart blocks. Reports segments, gaps, the centered null mean
distribution and a finite-sample upper-tail fraction. Limits: 10,000 marks,
100..2,000 simulations, 1..1,000 mean block length, one million sampled returns.
This is per-interval, not annualized; selection across trials is uncorrected.
It does not produce a signal, confidence score, promotion or funded permission.

Both actions are available through the existing `research ACTION INPUT.json`
CLI, authenticated `/api/research/action` and advanced browser workbench.

## Durable scheduled attempt ownership

A scheduler commits RUNNING and its unique claim before calculation, without
holding the ledger write lock during market replay. The final claim check,
immutable artifact publication and clock advance share a write transaction.
Started/failure/interruption/completion audit records are retained. Unexpected
exceptions or publication failures leave RUNNING with liveness UNKNOWN; elapsed
time or a readable database does not certify a live worker. No automatic lease
expiry or silent retry of these claims is performed.

`job-interrupt`: `job_id`, `expected_due`, `expected_claim`, `reason` (1..256
characters). An exact current claim becomes FAILED and eligible for retry;
stale requests fail. Old calculations cannot publish over the replacement.
This fences publication only: it does not terminate a process, cancel an order
or imply that an interrupted calculation has stopped consuming CPU. GUI recovery
shows the claim and an explicit release control. Authenticated inspection and
interruption remain available while a workbench catch-up action is running.
Existing RETRY/SKIP controls retain their failed-window audit and due-time checks.

The replay chart displays at most 150 points through the selected decision.
Missing bar continuity is not connected, older unavailable trace fields stay
unknown, and geometry floats do not replace stored exact decimal labels. Mouse,
Enter/Space and left/right keys select actual saved decision indexes. It is a
linked price/equity/indicator view. Equity uses recorded pre-decision balances
and the recorded bid; absent balances remain unknown. Indicator panes use saved
numeric features, including negative values, without recomputing old decisions.
Annotations are separate immutable operator notes. Drawings and silent rewriting
of historical decisions are not implemented by this chart.

## Aligned market returns and response bounds

`return-correlations`: `symbols` (2..8 distinct), `quote_currency` (`USDT` or
`TMN`), `from`, `to`, `resolution`, `min_overlap` (2..1,440). Uses the existing
31-day/1,440-bucket/100,000-observation bounds and one read snapshot. Every
market must have the declared quote currency. Computes simple MID returns only
between adjacent eligible closed bars, then aligns the exact interval start and
end for each pair. No carried price or gap return is manufactured. The upper
triangle includes self comparisons; constant inputs return ZERO_VARIANCE,
insufficient pairs return INSUFFICIENT_OVERLAP. Last-quote degradation/staleness
excludes a market while preserving its coverage details. Per-pair overlap and
one-sided missing intervals are explicit; pairwise matrices need not share one
sample and are not a covariance model or diversification advice. No inference,
significance, annualization or trading confidence is attached.

Research workbench responses additionally cap delivery at 2 MiB of UTF-8 JSON.
Serialization stops when the bound is exceeded, without returning partial
economic fields. HTTP 413 indicates that output was not delivered, a mutation
may have committed, and automatic retry is prohibited. Inspect saved state or
request a smaller supported page/window. The bound limits delivered bytes, not
all service memory allocation; existing per-action read/work bounds still apply.

## Replay, registry and paper controls

`registry-page`: `kind` (null or an allowed event kind), `parent` (null or exact
parent), `after` (initially 0), `through` (initially null), `limit` (1..100).
Reuse the returned `through` and `next_after` for later pages. One read snapshot
fixes the initial sequence ceiling; later appends cannot enter that page set.
Each event is hash/store checked, and pages have a 262,144-byte event bound.
An oversized first event fails explicitly rather than being truncated.

`annotation-add`: `run_id`, `outputs_digest`, `decision_index`, `request_id`
(32 lowercase hex characters), `text` (1..2,000 characters). The decision time,
symbol, resolution and close come from verified saved evidence. A request ID is
idempotent for identical content; different content with the same ID is rejected.
`annotation-list`: `run_id`, `outputs_digest`, `after`, `through`, `limit`.
Notes never become decision or economic evidence. The dedicated replay form
retains its request identity after uncertain delivery.

`replay-checkpoint`: `run_id`, `quote_count` (1..100,000).
`replay-resume`: `checkpoint_id`. Current native point-in-time fixed-bar runs
only, at most 31 days/5,000 bars/100,000 observed quotes. A checkpoint stores
hashes of the engine, source prefix, saved artifacts, pending order and native
state. Resume reconstructs that prefix from a new read snapshot, then continues;
both saved-output and independent full-replay comparisons must match. Any gym
Python source change invalidates the engine hash. Changed input/rules/metadata
fail rather than reusing stale state. No executable objects are deserialized,
and no new order or run result is fabricated.

`entry-lock-add`: `run_id`, `scope` (PAIR/GLOBAL), `reason`
(COOLDOWN/DRAWDOWN), `duration_seconds` (60..604800), `threshold_percent`
(null for cooldown; positive and at most 100 for drawdown). Verified past-run
fills or sampled drawdown trigger a persistent native BLOCK_ENTRY rule with
actual creation/expiry times and evidence references. Repeating the same request
does not extend expiry. `entry-locks` reads these rules, including expired ones.
Exit and cancellation remain unrestricted by these paper locks.

## Observation and supplied-market extensions

Optional observation `confirmed_at` must follow publication/revision; knowledge
time also includes actual receipt. Optional `components` are 1..32 unique
`{label,value}` numeric entries whose exact sum must match the parent; news does
not accept numeric components. Optional `unit_epoch` identifies a revision's
scale. Omitted fields preserve old hashes. Derived arithmetic rejects mixed
epochs. `unit-convert` takes `value`, `factor` (observation references),
`from_epoch`, `to_epoch`, `target_unit`, `as_of`, `max_age_seconds`, and
`max_skew_seconds`; the positive factor must have exact target/source
units. Source references and clocks remain visible; raw rows are unchanged.

`market-breadth` takes `groups` (1..8 named groups with disjoint `symbols`, at
most 20 total), `quote_currency`, `from`, `to`, `resolution`. One native market
screen snapshot counts advances/declines/flats only among eligible comparable
markets. Missing/excluded members remain visible. Group classification is supplied,
not an authenticated sector taxonomy.

`depth-audit`: `source_id`, `as_of`, `max_age_seconds` (1..3600), `max_levels`
(1..200), `frames` (1..500). Supplied SNAPSHOT/DELTA frames carry explicit sequence,
previous sequence, event/receipt times and bid/ask price/quantity arrays. Limits:
400 updates per side/frame and 50,000 total. Gaps, conflicting duplicates,
crossed/empty books and overflow require a strictly newer snapshot; levels are
never silently discarded. Exact duplicate last frames are idempotent. Stale or
future books expose no usable quote. Inputs are unauthenticated. Current Wallex
unsequenced side snapshots are not relabeled as this sequenced feed.

Market schema 3 retains immutable candle vintages on the actual collector path.
Latest projections never regress on an older fetch. Exclusive point-in-time
checks select a retained eligible vintage; pre-migration discarded revisions
remain unrecoverable.

## Shared local journal actions

The advanced GUI and generic research CLI/API expose `conversion-report`,
`probe-stage`, `external-import`, `venue-fact-import`, `evidence-report`, and
`evidence-decision` through `operator_actions.py`. Existing conversion, budget,
account/venue journals and saved-evidence owners perform validation and writes.
Conversion fills are explicitly modeled; imported facts remain unauthenticated;
probe budgets and evidence decisions are records with no execution permission.
No arbitrary filesystem path, command, provider call or account request is
accepted. The original dedicated terminal commands reuse the same service.

## Supervised calculation and recovery

Heavy workbench actions, comparisons/chronological validation and scheduled
ticks run in disposable fixed-entry Python processes. The CLI and foreground
scheduler use the same supervisor. The deadline is 120 seconds; the exact child
is killed and reaped before the caller releases its work lock. Browser paper
requests allow 130 seconds for deadline/cleanup delivery. No arbitrary command,
callable, executable path or caller environment is accepted.

HTTP 504 means the calculation timed out; HTTP 413 means its result exceeded the
2 MiB bound. Worker failures and validation errors also retain
`operation_may_have_committed=true`, `automatic_retry_allowed=false` and actual
termination evidence. Inspect the registry/run/job first. A committed RUNNING
claim stays visible after a killed/crashed worker until explicit interruption;
neither elapsed time nor a canceled client silently advances its clock. These
ordinary operator processes are not the separately qualified R0 AppContainer.

## Explicit public news retrieval

`news-fetch`: `source` must be `FED_PRESS`, `max_items` must be 1..20; live store
only. Explicitly fetches the official fixed Federal Reserve RSS URL over normal
validated HTTPS. No proxy, redirect, cookie, API key, arbitrary URL, linked-page
fetch or provider completion is used. Bodies are at most 512 KiB; XML declarations,
entities, duplicate/ambiguous items, unsupported links and invalid dates fail
closed. Future items are excluded. Stored title/link observations have origin
PUBLIC_FEED_HTTP and actual immutable first-receipt knowledge times. Repeat
identical items retain their first receipt. Older publication dates do not become
earlier knowledge. This is an attributed feed receipt, not independently signed
content, verified interpretation, historical backfill or a trading signal.

## Explicit paged account observations

The protected native helper accepts `open-orders PAGE PER_PAGE` and
`order-history PAGE PER_PAGE` only for pages 1..1000 and sizes 1..100. These map
to the fixed service GET origin, never arbitrary URLs or writes. Normal Python
account readers share the same strict documented map-of-order-arrays parser;
missing/changed pagination echoes are unverified or rejected. Partial fills and
fees remain observations, and duplicate or inconsistent identities fail closed.
`gymctl account --open-orders-page N --history-page N --per-page N` opts in to
these separate reads. No automatic walk, complete-account snapshot, absence or
settlement is inferred. New native builds require protected installation before
using these new page requests; no real authenticated read was performed.

`order-page-import`: `account_id`, `observed_at`, `kind` (OPEN/HISTORY), `page`,
`per_page`, `payload`. The workbench validates and sanitizes a supplied page into
the existing external journal. It neither invokes the protected helper nor
authenticates imported content. Missing orders do not become canceled or absent.

## Recorded backup/restore status

Successful protected-console `backup-once` and `restore-backup` operations append
sanitized receipts under the selected `--data` workspace. The authenticated
read-only `/api/backup-status` supplies the EN/FA Backups page. An empty read
creates no receipt database. Receipts omit paths, passphrases and credentials,
retain concurrent operations and include exact ledger/file hashes. They report
past operations only: current archive availability, independent origin/custody
and separate-machine recovery remain unverified. A receipt failure after a
successful operation reports `status_recorded=false` without implying rollback
or recommending an automatic repeat.
