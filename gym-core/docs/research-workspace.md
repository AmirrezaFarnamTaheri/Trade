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
are historical, at most 31 days and 5,000 bars each, with at most 100,000 quotes
in the full-market window and its one-day FX lookback. Latency is 0..60,000ms;
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
