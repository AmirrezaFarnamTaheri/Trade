# Current capability boundaries

The [architecture](architecture.md) identifies implementation owners and browser
locations. [System status](system-status.md) records dated checks; the
[implementation plan](implementation-plan.md) owns open work. This page describes
the supported product boundary.

| Capability | Current scope | Evidence limit |
| --- | --- | --- |
| Market collection | Catalogue-wide public spot observations, recorded depth/trades/candles, SQL publication and raw archive | Selection is not freshness; per-market gaps and stale quotes remain visible |
| Paper strategies | Sixteen native long/flat rules, configurable indicators, compound policies, default-off regime gates and fixed/profit/ATR/time exits | Closed-bar paper exits can miss or exceed thresholds; no venue protection or established edge |
| Comparison and validation | Matched independent accounts, expanding walk-forward selection and held-out diagnostics | Historical selection is not independent final evaluation |
| Shared-cash portfolios | Up to 500 distinct-base markets per quote book, exact reservations, equal/inverse-volatility/risk-parity targets, correlation caps, conditional rebalancing, cash buffers, loss latches, causal FX and verified checkpoint reconstruction | Covariance/observation/worker budgets apply; stale held marks block entries; no authenticated portfolio execution or runtime recovery qualification |
| Product capabilities | All observed markets joined to an explicitly selected public margin receipt, credit grid and LONG/SHORT availability | Observation is not current listing, credit eligibility, permission or collateral qualification |
| Coverage and recovery | Recorded bucket/readiness timeline and explicit retry, catch-up, skip and interrupted-claim controls | Missing periods stay missing; claim interruption does not kill a process |
| Replay and experiments | Verified decisions, annotations, registry pages, retained trials/failures, scorecards/heatmaps/path overlays, store-scoped counts, instrumented process ownership and local consume-once evaluations | Ready/traded counts are a bounded verified sample; old progress is not liveness; local ledgers are not independent custody |
| Paper sizing | Exact stop-risk entries against held exposure/pending cash, plus capped fractional Kelly diagnostics from completed preregistered evaluations | Unknown venue limits abstain; hypothetical stops can fail; fractional diagnostics require simple closed positions and do not change allocation automatically |
| Screening and diagnostics | Comparable recorded markets, exact supplied-data models and return/cost diagnostics | Supplied holdings/fills/forecasts are unauthenticated; scoring is not prediction |
| AI research | Scoped provider connections, explicit advisory requests, evidence packets and checked numeric citations | No order tools or automatic paid requests; interpretation remains unverified |
| Margin paper | Public rules/previews and recorded LONG/SHORT positions using venue credit grids | No real loan, position or protective order is submitted |
| Account observations | Sanitized journal and separately protected read-only transport contracts | Observation is not completeness, spendability or settlement |
| Protected executor | Native custody, operator intent, preparation, journals and emergency-stop foundations | Installed evidence is dated; funded admission and transport remain open |
| Backups | Encrypted native backup/restore and append-only receipt history | Receipt presence does not prove current archives or runtime readiness |

Predictive ML/RL training is paper-only and gated (300 verified closed trades, every fit counted as a trial; see PRODUCT.md). Unrelated donor runtimes and automatic paid requests are outside accepted scope.
