# Research workspace

The Research page and `gymctl research` share
[`research_actions.py`](../src/gym/services/research_actions.py). Its action registry
and handlers own the exact request schemas. This page explains the workflows and
their evidence boundaries; [capabilities](capabilities.md) records supported scope.

## Common request contract

Use `gymctl --data DATA research ACTION INPUT.json` for object inputs. The browser
uses token-protected `POST /api/research/action` with exactly
`{"action": ACTION, "value": INPUT}`. Live/demo stores remain separate; `live`
means recorded feed data. Research actions grant paper authority only.

Amounts are exact decimal strings and times have zones; end bounds are exclusive.
Duplicate/nonfinite JSON is rejected. Object input is at most 64 KiB, delivered
JSON at most 2 MiB. Per-action read, time and work limits apply independently.
Actions use the actual clock and reject `--at` overrides.

## Paper premium, lag, TWAP and future comparison

| Action | Purpose |
| --- | --- |
| `premium-research` | Align BTCTMN, BTCUSDT and USDTTMN quotes strictly before closed-bar cutoffs; retain missing/stale/skew exclusions and hypothetical three-leg costs. |
| `lead-lag-research` | Pair the leader's preceding adjacent return with the follower's next return; retain insufficient overlap and zero variance. |
| `twap-preview` | Attempt fixed-time slices at the first eligible received quote, bounded by displayed size, funds and market minimums; expire residuals. |
| `prospective-register` | Freeze two to four configurations, costs, cash, engine and a future disjoint window. |
| `prospective-status` | Inspect the returned 64-character ID without consuming it. |
| `prospective-evaluate` | Consume that ID once, after its window ends, including failed attempts. |

Use the guided frozen-comparison form for common registrations or the advanced
JSON workbench for the full schema. After uncertain delivery, inspect the saved ID
before another mutation. A completed calculation does not establish transferability,
settlement, real fills, independent evaluation custody or prospective profitability.

The guided prospective form freezes a one-line hypothesis and minimum net uplift in bps against the same quote-cash position. A completed comparison reports whether each candidate met that modeled threshold only if its terminal valuation is current. Earlier registrations without a threshold keep their original report format.

### Offline factor diagnostics

Run `gymctl research factor-ic-lab packet.json`. The packet has a `seed` and an `observations` array. Each row supplies `at` and `label_end` as ISO timestamps, with symbol-keyed numeric `factors` and `forward_returns`. The command rejects unfinished labels, retains disjoint intervals in snapshot order, and reports the retained intervals and seeded shuffle result. The result does not register a trial.

## Compare a saved run with holding USDT

Open a saved run to see its net result next to holding USDT over the same window.
The bars share a zero line. Runs quoted in another currency use the saved USDT
conversion for both values. If either value is missing, no bars appear. Open
**All comparisons and exchange rates** for the other benchmarks and any saved
conversion details.

## Paper-run sizing estimate

The Runs page reports a simple Kelly estimate from average gains and losses in
quote currency. Break-even closes count in the displayed win rate, but not in
this estimate. The estimate needs at least 20 closes with a gain or loss and at
least one of each. Older reports without the sample count do not show it. This
statistic does not set order size or replace the fractional-sizing diagnostic.

## Entry risk and fractional sizing

`entry_risk_bps` is 0..200 and requires a positive `exit_stop_bps` when enabled.
Exact fees, precision, minimums, existing exposure and working reservations consume
the modeled stop budget. Cash floors and loss latches still apply. Gaps and
slippage can exceed it. `exit_venue_stop=1` uses received trade ticks to trigger a
paper market exit; waiting stops do not reserve inventory. See
[paper costs and stops](paper-costs-and-stops.md).

`fractional-sizing` takes a verified EVALUATED protocol ID, fraction, cap, seed,
simulation count and block length. It needs 30..500 closed non-overlapping positions,
current end valuation and an observed loss. Partial/recycled/open-position samples
remain unavailable. Moving blocks report sample percentiles; the positive
multiplier is at most one half and the hard cap one quarter. These are declared
diagnostic bounds, with the lower percentile used before multiplier/cap.

## Experiment scorecards and process ownership

`experiment-scorecard` reads a regular strategy-trial experiment and up to four
verified shadow sessions. Matching configuration, cash, resolution and costs are
required. Missing, failed, stale, unready and no-trade outcomes remain visible.
Overlays use recorded clocks and bounded display samples; full artifacts retain
all marks. A heatmap neither selects a winner nor corrects for searched trials.

`campaign-status` reports instrumented process owners. ALIVE requires a held OS
lock and heartbeat within 20 seconds; PID text alone proves nothing. Presence
does not establish strategy progress or feed health.

## Expanding walk-forward selection

`walk-forward` freezes 2..8 configurations, 1..5 expanding training/disjoint test
folds, a 1..100-bar purge and a later final cutoff. At most 32 train/test slots;
each window is at most 31 days/5,000 periods. Training maximizes current-valued
net quote, including negative winners. Selection commits before its test. The
final window is not read. Each fold starts flat; zero fills or unfinished warmup
leave the report INCOMPLETE. This remains historical exploratory selection.

## Execution assumption evidence

`execution-calibration` summarizes bounded public event-to-receipt delays. A
candidate needs 20 nonnegative observations, no clock disagreement and a fresh
receipt. DEMO, stale or mixed-market samples do not propose latency. Public timing
is a lower-bound proxy for authenticated execution and is never applied automatically.

## Selection and path robustness

`robustness` compares 2..8 matching native runs with common clocks, cash, costs and
inputs. CSCV uses contiguous equal partitions and mean interval return; reports
trimming, selection/median ties and both rank conventions. Gaps, indistinguishable
configurations and insufficient intervals remain unavailable. Stationary return
blocks and fixed FIFO P/L permutations have different assumptions; neither
generates new fills or independently validates the searched sample.

## Coverage and recovery

`coverage` retains missing/degraded/stale buckets and warmup, with 31-day,
1,440-bucket and 100,000-observation bounds. Missing buckets reset readiness;
late downloads do not rewrite historical knowledge.

`job-recover` requires the exact `job_id`, `expected_due`, RETRY/SKIP and reason.
Retry clears the deadline; skip advances one window and retains its failure.
`job-catch-up` processes at most ten eligible windows. An unavailable frozen
engine remains HYPOTHESIS_VERSION_UNAVAILABLE; restore that revision or register
a separate hypothesis. Clock regression aborts a live session and preserves its
last processed time and observed finish clock.

## Decision replay

`replay` pages a verified saved run by offset/limit (1..200). Version 8 and later
retain decision-time balances, bars and rules; older missing details stay unknown.
Later order outcomes are separate. The chart selects actual decision indexes by
mouse or keyboard, breaks continuity gaps and preserves exact textual values.

## Recorded-market screening

`market-screen` compares 1..20 explicit same-quote symbols, using momentum,
relative momentum, SMA distance, spread, top liquidity or unannualized volatility.
`market-breadth` counts advances/declines among supplied disjoint groups.
Both retain exclusions; a supplied universe/group is not a historical listing census.

## Target rebalance preview

`rebalance` accepts exact supplied cash/reservations/fees and 1..100 same-quote
positions. Sales exclude reserved quantities; buys share remaining cash, use asks
and round down. Unknown minimums block the leg. Purchases funded by modeled sales
remain conditional on settlement. Inputs do not authenticate holdings or prices.

## Experiments and robustness

`experiment-run` freezes hypothesis/configuration, chronological windows and
fee/latency/outage scenarios before reading markets; at most 32 attempted runs.
`experiment-list` and `experiment-status ID` read the append-only journal.
Failures and RESULT_PENDING survive crashes. Matched baselines share the native
cost model; final links require matching frozen inputs and do not consume a final
evaluation. `final-register`/`final-run` retain their separate consume-once rules.

## Execution-quality comparison

`execution-quality` compares a verified run with at most 500 supplied fills.
It retains unmatched references/nonfills and aggregates partial quantities,
VWAP, price/fee differences and first-fill latency. Fees keep their currency;
base fees get a disclosed quote-equivalent calculation. Missing observations
remain unknown, and supplied fills remain unauthenticated.

## Causality and prehistory diagnostics

`strategy-audit` independently truncates native replays to compare decision prefixes
and recorded features, excluding later outcomes. Different legitimate holdings
are not convergence errors. `return-bootstrap` resamples stationary blocks of
strictly chronological positive-equity returns, breaks gaps and reports its
finite-sample null fraction. Neither diagnostic corrects for selecting trials.

## Durable scheduled attempt ownership

The scheduler commits RUNNING plus a unique claim before replay and releases its
write lock during calculation. Publication and clock advance recheck the claim
inside one transaction. Unexpected failures leave RUNNING/UNKNOWN.
`job-interrupt` requires the exact due time, claim and reason; it fences publication,
but does not kill the process. Elapsed time never silently expires a claim.

## Aligned market returns and response bounds

`return-correlations` aligns exact adjacent return intervals for 2..8 same-quote
markets. Missing/gapped clocks, stale quotes, zero variance and insufficient
overlap remain explicit. Pairwise samples need not form a covariance matrix.
Oversized responses fail with HTTP 413, retaining the possible-commit warning;
delivery limits do not imply that a mutation was rolled back.

## Replay, registry and paper controls

`registry-page` freezes a sequence ceiling; reuse `through` and `next_after`.
`annotation-add/list` bind notes to run/output/decision identity and an idempotent
request ID. Notes never become economic evidence. `replay-checkpoint/resume`
reconstruct a verified prefix before continuing; changed source/data/rules fail.
`entry-lock-add/entry-locks` maintain expiring paper entry rules from verified
past fills/drawdown; exits and cancellation remain unrestricted.

## Observation and supplied-market extensions

Knowledge includes actual receipt, publication, revision and optional confirmation.
Components must sum exactly; unit conversions require matching explicit epochs and
units. `depth-audit` validates supplied sequenced snapshots/deltas, rejects gaps,
conflicting duplicates and crossed books, and requires a newer recovery snapshot.
Wallex's unsequenced snapshots are not relabeled as sequenced data. Market schema 3
retains immutable candle vintages for point-in-time reads.

## Shared local journal actions

`conversion-report`, `probe-stage`, `external-import`, `venue-fact-import`,
`evidence-report` and `evidence-decision` reuse `operator_actions.py`. Imported
facts remain supplied observations. These actions accept neither arbitrary
commands/paths nor provider completions or execution permission.

## Supervised calculation and recovery

Heavy calculations and scheduled ticks use fixed-entry disposable Python processes,
with a 120-second deadline and kill/reap before releasing the work lock. Browser
timeouts allow cleanup. HTTP 504, worker failures and validation failures retain
possible-commit, no-automatic-retry and actual termination evidence. Inspect saved
state first. These ordinary processes do not provide a security sandbox. The
retired MCP server and native AppContainer launcher are removed.

## Explicit public news retrieval

`news-fetch` accepts FED_PRESS and at most 20 items from the fixed official RSS
origin. Validated HTTPS has no redirects/proxy/credentials; XML, date and size
bounds apply. Immutable first receipt controls knowledge time. A feed receipt
does not authenticate interpretation or create a trading signal.

## Explicit paged account observations

The native helper maps explicit open/history pages (1..1000, size 1..100) to fixed
service GETs. `gymctl account` opts in; it does not infer complete account state,
absence or settlement. `order-page-import` validates/sanitizes a supplied page
without invoking the helper or authenticating the content. Native source changes
require a reviewed matching protected installation before use.

## Recorded backup/restore status

Protected-console backup/restore commands append sanitized local receipts for the
Backups page. They omit paths, passphrases and credentials, retain hashes and
report past operations only. A failed receipt after a successful operation reports
`status_recorded=false`; it does not imply rollback or justify repeating it.
Off-machine backup scheduling and second-machine restore were canceled by the owner.

### Daily spot trend replay

Run `gymctl research trend-replay packet.json` to compare a long-only paper account with holding the same initial quote cash at zero interest. Supply `symbol`, `quote_currency` (USDT or TMN), `cash`, `quantity_step`, `minimum_quote`, `fee_rate`, `band`, and `observations`. Use plain decimal strings for amounts, rates and prices. Each observation contains a zoned `at`, `bid` and `ask`. Supply 258–4096 consecutive daily observations. The first 256 are warmup.

The three equally weighted 16/64, 32/128 and 64/256 forecasts use a fixed scalar of ten and a cap of twenty. Sizing uses 36 daily returns ending before the signal day, a 15% annual volatility target and a 100% spot allocation cap. The cost gate assumes six round trips per year and a budget of 10% of target volatility. The following day's supplied quote sets modeled fill prices. A zero target requests exit down to the executable lot. Buy fees reduce base received. Sell fees reduce quote proceeds. Terminal inventory is marked to bid. The output assumes sufficient displayed liquidity for planned lots. It includes modeled fees, turnover, daily decisions and excess terminal quote value. The command consumes no registration slot.

### Verify a replay input window

Run `gymctl --data DATA research raw-replay-audit packet.json` with fields `symbol`, `from` and `to` (zoned ISO timestamps). The read-only verifier examines every stored trade and book top received in the half-open interval. It refuses windows over 10,000 rows per source. Split larger intervals at receipt timestamps. It reads closed segments from the store's raw directory and checks the archive digest, frame sequence and raw payload hash before comparing the normalized trade or each side of the published book. Separate bid and ask frames are supported. The process returns nonzero for unsupported legacy references, modified rows, empty windows or missing archives.

Schema 7 records both side references on newly published book tops. Schema 6 remains readable and its historical rows retain unknown side references. A successful result establishes correspondence for stored rows in the named window. Feed completeness, market rules, fee vintages, forward outcomes and venue execution require their own evidence.
