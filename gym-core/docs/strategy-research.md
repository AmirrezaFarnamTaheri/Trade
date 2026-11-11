# Strategy research contracts (improvement plan items 25–30)

These contracts cover the **strategy research** section of the November 2026
46-item TradingGYM improvement plan. It is distinct from the controlled
integration engineering runbook ("Workstream C", private venue/Executor
acceptance). These contracts grant no money authority, permission to
borrow, exchange API access, a live strategy recommendation, or a funded
order path. The funded loss budget remains zero.

## 25 — TMN discount z-score and half-life exit

Existing `toman-premium` defaults and configuration IDs remain unchanged.
An explicit `z_entry: 1..8` selects version 2, optionally with
`z_exit: 0..8` and `half_life_multiple: 0..20`.
The current observed TMN cross-market discount is scored against **previous**
EWMA moments (alpha 0.08), with 20 historical observations and nonzero
historical variance required. The latest score is never used to fit itself.
The half-life is `-ln(2)/ln(phi)`, where phi is estimated by exact-Decimal
AR(1) with intercept from the *previous* 12..129 discounts. Phi outside
(0,1) is explicitly unidentifiable; there is no synthetic expiry. Missing,
closed, skewed or gapped conversion quotes cannot be backfilled.
An identified half-life optionally bounds modeled paper holding time. A gap
resets the score estimator without resetting the age of a held position; while
z-score statistics warm up, a held position may exit on the original fixed
`exit_bps` reversion rule, but new entries remain disabled. The existing
fixed-discount costs and no-conversion-transport limitations remain.

## 26 — Lag selection on earlier observations

`lead-lag-research` accepts optional `max_delay_bars: 1..12`. One
is the unchanged legacy report. Larger scans compute leader return in the
previous interval and follower return after the requested number of
closed intervals; missing intermediate returns break the match.
For each delay, a chronological 70% training segment selects using
training correlation only. The remaining 30% is *diagnostic*; the reported
`best_training_delay` never uses its score. No independence or predictive
validity is claimed. The paper strategy accepts optional
`delay_bars: 1..12`, with version 2 and unchanged default version 1.
Available fixed intervals start at one minute; sub-minute Hayashi–Yoshida
alignment is outside supported data/resolutions.

## 27 — Same-quote long/short margin paper pairs

`margin-pairs-replay` takes separate, locally verified historical public
margin preview IDs, `from`, `to`, `exit_fee_rate`,
`holding_seconds`, and `max_skew_seconds`. It requires one long and
one short, on distinct pairs with the same quote asset, where both previews
precede the period. A single read-only snapshot supplies up to 5000
qualified quote observations per leg. The existing margin engine models
borrowed base on short sells, fee currencies, periodic extension, call
levels, liquidation triggers, unfillable gaps and debt. This **is not**
one shared live cross-margin account. Only two fully closed paper legs
produce `net_quote`; `net_usdt` is null for TMN without eligible FX.
Aligned log-mid-price-spread dispersion and a training-only (first 70%) AR(1)
half-life are descriptive and cannot certify cointegration or executable
arbitrage. The `half_life_observations` field counts aligned long-leg quote
updates, which are irregular events rather than fixed-duration bars.

## 28 — Causal out-of-sample paper weighting

`combine-oos` accepts 2..4 locally verified, matched native prospective
USDT run IDs, bounded `lookback`, and explicit
`rebalance_cost_bps` or null. Equal timestamps, starting cash,
instrument/cost assumptions and frozen strategy identities are required.
Weights are proportional to inverse rolling *past squared net return
versus a zero-return cash benchmark*; this is an error/risk **proxy**, not
trained predictive error, and it excludes the contemporaneous return from
the signal. A model-level USDT gross and cost-adjusted path and each
component net result are shown. Missing modeled switching costs yield
`COST_UNAVAILABLE`, never a fictitious net win. There is no real shared
cash, matched filled orders, or independent custody in this aggregation.

## 29 — Only evidence-backed retirement

`strategy-retirement-screen` reads 3..100 locally verified, matched
prospective paper runs with a declared market universe. It applies the
existing **200-seed random-entry timing benchmark**, requires at least
30 completed positions per tested market and current valuation, and
shows incomplete, missing or stale evidence rather than classifying it
as a failed strategy. Even if every supplied market falls below the
50th percentile, the outcome is `REVIEW_REQUIRED`: caller-selected
history and locally checked receipts do **not** certify an independently
frozen universe or an untouched final evaluation. The catalog is **not
automatically hidden or mutated**. Actual retirement needs future
independent evidence and explicit code review; no such evidence exists here.

## 30 — Meta-labeling remains deferred

`meta-label-eligibility` reports `DEFERRED` below 300 closed trades.
At or above 300, `RESEARCH_ELIGIBLE_NOT_TRAINED` is still not permission
to train or select an ML model without verified labels, out-of-sample
calibration, and suitable custody. No logistic classifier, RL agent, paid
model, or automated strategy selection has been added.

## Acceptance and limits

These are implementable **paper research mechanics**, not proof of a
repeatable after-cost edge or of funded trading safety. The execution
model, broker permissions, independently authenticated actual fees,
cash reservations, protection/reopening behavior and venue settlement
remain in their existing distinct ownership, with no new order path.
The live-session collection failure and absence of independent final
evaluation prevent empirical strategy qualification. The status must remain
open until genuine future prospective, accessible market and account
evidence can be collected.

Run `cd gym-core && uvx ruff==0.16.9 check src tests`, then
`uv run --with coverage==7.6.10 coverage run --source=src/gym -m pytest -q`.
The repository Windows, Rust, browser smoke and security jobs also gate
merging. New actions are available through the EN/FA Research Workbench
and executed with the existing supervised research worker.
