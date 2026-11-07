# Composite paper strategies

The registry adds `trend-pullback` and `adaptive-channel` alongside the ten
existing strategies. Both combine complementary conditions, explicit execution
costs and actual-fill risk state. They are deterministic research rules, not
predictive models or demonstrated profitable strategies. All eligible spot
symbols and supported closed-bar resolutions use the same implementation.

## Signals

Both require 50 continuous valid closed bars. Features come from the existing
streaming indicator engine: EMA20/50, EMA20 slope over five bars, ADX14 and its
directional components, RSI14, ATR14, MACD12/26/9 and Keltner20/14/2. No forming
bar or future quote is accepted. Missing periods or a price jump above 5%
restart indicator history; existing position exits remain usable. From strategy
version 2, wide spreads block new entries while valid closed bars continue
updating indicators. Wide spreads do not suppress trend-based exits. The original
version reset history on each spread violation and rarely reached readiness;
its frozen study and results remain retained separately.

| Strategy | Eligible condition | Entry | Additional exit |
| --- | --- | --- | --- |
| Trend pullback | ADX at least 25, EMA20 above EMA50, rising EMA20 and positive directional dominance | Closed price recovers above EMA20 after being at/below it; RSI 40–70 | Downtrend |
| Adaptive channel | Same uptrend definition | Fresh close above the upper Keltner band and positive MACD histogram | Downtrend |
| Adaptive channel | ADX at most 18 and EMA separation no greater than ATR | Fresh recovery above the lower Keltner band; RSI 30–55 | Return to EMA20 or downtrend |

Downtrends and transitional conditions generate no new long position. ATR must
be positive and no more than 2% of close. The range rule's target room is the
distance to EMA20; the trend rule uses the configured initial reward/risk
distance. This is a geometric filter, not a forecast of achievable profit.

## Costs, sizing and actual fills

Compound strategies currently support market orders. Selecting resting limit
orders or carried working remainders is rejected explicitly by the shared native
session validator in CLI/API workflows; these options are never silently ignored
or reinterpreted. Ordinary strategy limit simulations retain their existing model.

The decision must have fresh two-sided quotes, displayed quantities, actual
cash/equity/holdings and the selected scenario's fees. Target room must exceed
twice `spread + two fees + 10 bps`. The additional 10 bps is a disclosed modeling
allowance, not measured latency. Initial stop distance is the larger of 50 bps
and two ATR by default.

Entry size is the smallest of the cash allocation cap, the risk budget divided
by stop-plus-cost distance, and participation in the smaller displayed quote
side. The native simulator applies the fraction to available quote cash. It
checks venue precision/minimums and rechecks spread/depth at the actual eligible
fill quote. A changed or unavailable book records a nonfill without changing
balances. An entry whose fee-adjusted total holding is already below the known
sellable lot/minimum records `NET_HOLDING_BELOW_EXIT_MINIMUM` before any posting;
existing residual balances count toward that total and are never erased.
Baseline runs retain their existing unconstrained execution model;
their headline returns are therefore not an execution-policy-controlled comparison.

Only actual modeled fills establish a position. Cost basis includes the modeled
received-asset fee; initial stop, opening time and order identity are retained.
A full executable-lot exit preserves any rounding residual in balances and cost
basis. Recorded dust can enter cooldown and later reentry without being erased.
If the residual becomes executable again, it is managed as a position.

| Control | Default | Allowed range |
| --- | --- | --- |
| Entry risk budget | 50 bps (0.5%) | 1–200 bps |
| Cash allocation cap | 2,500 bps (25%) | 1–10,000 bps |
| Maximum entry spread | 25 bps | 1–1,000 bps |
| Participation in displayed quantity | 1,000 bps (10%) | 1–10,000 bps |
| Stop ATR multiple | 2 | 1–5 |
| Initial target reward/risk | 2 | 1–5 |
| Cooldown after observed exit | 3 bars | 0–100 bars |
| Maximum holding time | 60 bars | 1–1,000 bars |
| Session drawdown lock | 300 bps (3%) | 50–2,000 bps |

Stops ratchet with peak observed bid minus the ATR distance, move to a
fee-adjusted break-even level after one initial risk unit, and never loosen.
Targets and maximum holding time also request exits. Drawdown is measured from
the session's highest valid decision-time equity; once reached, its lock stays
latched for that session and requests liquidation of an active position.

**These are closed-bar paper decisions, not venue stop orders or guaranteed
loss limits.** Gaps, latency, closures, minimums and insufficient displayed depth
can prevent an exit or exceed the budget. No full order-book/queue model or
funded margin/short execution was added.

## Interfaces and evidence

Replay, prospective paper sessions, hypotheses/schedules, comparisons,
validation and the EN/FA Paper research controls use the native registry.
Decision inspection includes indicator values, reasons, account/risk context
and a separate execution fingerprint. Shared market snapshot hashes remain
comparable between independent accounts; prior strategy identities and frozen
campaign engines are preserved.

```powershell
uv run gymctl paper BTCUSDT --strategy trend-pullback --res 1min
uv run gymctl paper BTCUSDT --strategy adaptive-channel --res 1min
```

Tests exercise native trend and range triggers, costs, capacity rechecks,
actual fills, precision dust, cooldown, ratcheting stops, targets, drawdown,
prefix stability, scheduled persistence and verified decision replay. Synthetic
fixtures are test inputs only and are not profitability evidence.

An exploratory study was registered before execution at
`.pi/compound-study/20261106T184523Z/plan.json`: all 373 eligible spot pairs,
both strategies with defaults, 1-minute decisions over 00:00–05:00 UTC on
6 November 2026, and two fee/latency scenarios (0.1%/500 ms, 0.2%/2,000 ms):
1,492 cases. Its source and previously recorded public-data snapshot are frozen;
the native experiment registry and verified run artifacts retain every outcome.
This is one recorded window, not an untouched holdout or prospective qualification.
The earlier 149,573-case campaign retains its original ten-strategy definition.

A separate version-2 rerun is registered at
`.pi/compound-study/20261106T203309Z/plan.json` with the same 373 markets,
windows, defaults and two scenarios (1,492 cases). Its frozen source includes
the spread/history separation, wide-spread regime exits and fee-net sellability
check. Major pairs are processed first; all other eligible pairs remain in the
registered scope. Version-1 results and definitions are unchanged. The prepared
intermediate folder `20261106T202521Z` was explicitly superseded before execution.
Strategy revision and configuration hashes distinguish revised runs; existing
version-1 compound hypotheses were rejected as unavailable by that revision
rather than silently changed.

Revision 3 is the current implementation. The revision-2 recorded-data rerun
produced a SOLUSDT buy and exit, then exposed the legitimate zero balance
`0E-9` being rejected as an external-style decimal string. Native execution
context now normalizes all Decimal fields to plain strings through the existing
finite/exponent/length validator before serialization. This covers tiny prices,
depth, quantities, fee rates and post-exit zeros. Invalid/unbounded depth becomes
unknown; the simulator validates it again before capacity arithmetic. External
decimal input validation remains strict.

The separately frozen current rerun is
`.pi/compound-study/20261106T205324Z/plan.json` (1,492 cases, all 373 pairs, the
same defaults/window/scenarios). Revision-1/2 receipts remain unchanged. Earlier
unexecuted preparation folders explicitly record `SUPERSEDED_BEFORE_EXECUTION`.
Previous revision-1/2 hypotheses require fresh registration for revision 3.
