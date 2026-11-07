# Current capability boundaries

The [architecture](architecture.md) identifies implementation owners and browser
locations. [System status](system-status.md) records dated checks; the
[implementation plan](implementation-plan.md) owns open work. This page describes
the supported product boundary.

| Capability | Current scope | Evidence limit |
| --- | --- | --- |
| Market collection | Catalogue-wide public spot observations, recorded depth/trades/candles, SQL publication and raw archive | Selection is not freshness; per-market gaps and stale quotes remain visible |
| Paper strategies | Twelve native long/flat rules, configurable indicators and compound policies | Modeled fills; no established profitable edge |
| Comparison and validation | Matched independent accounts, expanding walk-forward selection and held-out diagnostics | Historical selection is not independent final evaluation |
| Shared-cash portfolios | One native cash book, bounded replay, verified records and causal FX marks | Dynamic weighting and portfolio risk extensions remain in the plan |
| Coverage and recovery | Recorded bucket/readiness timeline and explicit retry, catch-up, skip and interrupted-claim controls | Missing periods stay missing; claim interruption does not kill a process |
| Replay and experiments | Verified decisions, annotations, registry pages, retained trials/failures and local consume-once evaluations | Local hashes and ledgers are not independent custody |
| Screening and diagnostics | Comparable recorded markets, exact supplied-data models and return/cost diagnostics | Supplied holdings/fills/forecasts are unauthenticated; scoring is not prediction |
| AI research | Scoped provider connections, explicit advisory requests, evidence packets and checked numeric citations | No order tools or automatic paid requests; interpretation remains unverified |
| Margin paper | Public rules/previews and recorded LONG/SHORT positions using venue credit grids | No real loan, position or protective order is submitted |
| Account observations | Sanitized journal and separately protected read-only transport contracts | Observation is not completeness, spendability or settlement |
| Protected executor | Native custody, operator intent, preparation, journals and emergency-stop foundations | Installed evidence is dated; funded admission and transport remain open |
| Backups | Encrypted native backup/restore and append-only receipt history | Receipt presence does not prove current archives or second-host recovery |

Predictive ML/RL training, unrelated donor runtimes and automatic paid requests are outside accepted scope.
