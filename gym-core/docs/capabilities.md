# Current capability boundaries

The [architecture](architecture.md) identifies implementation owners and browser
locations. [System status](system-status.md) records dated checks; the
[implementation plan](implementation-plan.md) owns open work. This page describes
the product boundary rather than repeating historical donor reviews.

| Capability | Current scope | Evidence limit |
| --- | --- | --- |
| Market collection | Catalogue-wide public spot observations, recorded depth/trades/candles, SQL publication and raw archive | Selection is not freshness; per-market gaps and stale quotes remain visible |
| Paper strategies | Twelve native long/flat rules, configurable indicators and compound policies | Modeled fills; no established profitable edge |
| Comparison and validation | Matched independent accounts, chronological blocked selection and held-out diagnostics | Historical selection is not independent final evaluation |
| Shared-cash portfolios | One native cash book, bounded replay, verified records and causal FX marks | Dynamic weighting and portfolio risk extensions remain in the plan |
| Coverage and recovery | Recorded bucket/readiness timeline and explicit retry, catch-up, skip and interrupted-claim controls | Missing periods stay missing; claim interruption does not kill a process |
| Replay and experiments | Verified decisions, annotations, registry pages, retained trials/failures and local consume-once evaluations | Local hashes and ledgers are not independent custody |
| Screening and diagnostics | Comparable recorded markets, exact supplied-data models and return/cost diagnostics | Supplied holdings/fills/forecasts are unauthenticated; scoring is not prediction |
| AI research | Scoped provider connections, explicit advisory requests, evidence packets and checked numeric citations | No order tools or automatic paid requests; interpretation remains unverified |
| Margin paper | Public rules/previews and recorded LONG/SHORT positions using venue credit grids | No real loan, position or protective order is submitted |
| Account observations | Sanitized journal and separately protected read-only transport contracts | Observation is not completeness, spendability or settlement |
| Protected executor | Native custody, operator intent, preparation, journals and emergency-stop foundations | Installed evidence is dated; funded admission and transport remain open |
| Backups | Encrypted native backup/restore and append-only receipt history | Receipt presence does not prove current archives or second-host recovery |

Historical source inventories, hashes, attribution, defects, exclusions and review
receipts are preserved in [source capability decisions](archive/source-capability-decisions.md)
and the [research source rationale](archive/research-source-rationale.md). Their
dated words such as deferred do not override the current plan or authorize
importing an unrelated runtime. Predictive ML/RL remains outside accepted scope.
Specific implementation candidates remain visible in the plan.

The [documentation index](README.md#source-assessments) links the other retained
source assessments. Relocation did not delete an integration requirement or
declare a candidate implemented.

## Historical section links

## Reuse decisions across the modules

See the [retained section](archive/source-capability-decisions.md#reuse-decisions-across-the-modules).

## Verification and limits

See the [retained section](archive/source-capability-decisions.md#verification-and-limits).

## Deferred-work implementation follow-up

See the [retained section](archive/source-capability-decisions.md#deferred-work-implementation-follow-up).

## OpenTrade, Pamela, Stock-Market, AutoHedge and OpenProphet

See the [retained section](archive/source-capability-decisions.md#opentrade-pamela-stock-market-autohedge-and-openprophet).

## Latest eight-source follow-up

See the [retained section](archive/source-capability-decisions.md#latest-eight-source-follow-up).

