# Phase A — honest measurement (items 8–18)

Phase A builds on the Phase 0 PR branch and keeps funded execution **DISARMED**. The
market receipt and historical paper-run formats remain unchanged unless an explicit
new analytical input requires a separately versioned run identity. No live orders,
authenticated venue writes, new runtime dependencies, or capital permissions are added.

## Changelog and acceptance evidence

| Item | Change | Verification / limits |
|---|---|---|
| 8 | Append-only research-question trial ledger counts one-off paper/portfolio runs, compare/validate, experiment slots, expanding walk-forward, and prospective candidates. | Five one-off runs report N=5; trial IDs reject conflicting reuse; CLI and API portfolio entry paths covered. Duplicate replays count as distinct selection attempts, without changing frozen run identities. |
| 9 | Add Lo autocorrelation-adjusted Sharpe with disclosed finite lag cap, probabilistic Sharpe and minimum track-record eligibility. | Analytic examples and short-record abstentions; historical market artifacts are not rewritten. A 20-lag capped estimate is **not** the full q−1 lag estimator for minute data. |
| 10 | Compare realized holding durations/trade count against 200 seeded random entry timings on observed quote marks. | Fixed-seed tests, explicit NO_EXACT_HOLDING_WINDOW abstention; simulated friction and order timing cannot certify live fills. |
| 11 | Show matched after-cost, buy-and-hold-relative stationary-bootstrap familywise SPA-style p-values on experiment scorecards. | Seeded null family false-positive test and common-window requirements; Monte Carlo p-values and conservative finite-simulation upper uncertainty are descriptive, **not** independently certified Hansen SPA or prospective edge. |
| 12 | Rank numeric heatmap configurations by their own and orthogonally adjacent parameter scores after USDT-equivalent costs. | Isolated peak versus plateau and diagonal-neighbor tests; no grid or incomplete evidence means no selection claim. |
| 13 | Warm indicators from pretest bars with **no pretest simulated orders** and display hypothetical chained out-of-sample returns, drawdown and losing-trade streak. | Boundary and chained-curve regressions; folds still start with flat cash and hypothetical chaining is not an executable portfolio. |
| 14 | Attribute TMN return to USDT return, TMN-per-USDT rate move, and exact interaction residual. | Exact Decimal identity test, FX absence abstention; figures are valuation-only. |
| 15 | Keep dated read-only account GET maker/taker rates separate; persist immutable feed calibration receipts; automatically apply eligible observed cost defaults only when explicit overrides are absent. | Synthetic/stale data rejection and recorded provenance. Feed delay is a **lower bound**, not measured order RTT. Paper fill slippage is not an independent measurement, so no slippage estimate is auto-promoted; historical replays must not import future receipts. |
| 16 | Select optional top-N historical quote-volume universes using receipts available strictly before the research start; flag later collection gaps without inferring delisting. | Future-receipt mutation test, market-screen and versioned portfolio identity tests. Does not reconstruct a complete venue historical listing census. |
| 17 | Estimate annual periods from recorded open-market time, excluding verified closed spans but **never** treating missing receipts as a closure. | Half-day closure example and overlap-union test. Causal observed closure history may be incomplete. |
| 18 | Gate opt-in CLI replay, portfolio and market-screen results on explicit missing + stale/unqualified fixed-bar coverage. | 10-of-30 missing-bar refusal test, screen/portfolio refusal tests. Default remains off. A sampled bucket with an observed quote is not proof of continuous trading availability. |

## Evidence and risk limitations

These are **paper-only research diagnostics**, not an assertion of trade profitability.
All stored historical feeds are subject to exchange-reporting and collector gaps;
the presence of a bar does not authenticate its price, spread or execution capacity.
The absence of source venue trade IDs remains disclosed for limit models.
USDT is the primary comparable scorecard numeraire, when current causal FX valuation
exists; unverified FX causes abstention rather than a fabricated conversion.

The optimizer correction includes exploratory candidates and counted trial attempts,
but no local append-only ledger can prove that an operator has never explored another
worktree, parameter sweep or external account. SPA is a statistical screening aid
and not a licensed order signal. Short samples and missing matched candidate paths
must not be promoted. The historical market census cannot prove all now-delisted
symbols were collected. For actual execution fees, latency and slippage, operator
account receipts and independent funded fill evidence are required; those are not
authorized or generated by this phase.

## Review gate

- Run the complete Python suite with line coverage, Ruff lint and Chrome/Edge
  real-browser UI smoke. Verify Rust/Linux and Windows jobs, dependency audits,
  independent ledger restore and Windows service identity/ACL checks.
- Verify unchanged golden market replay identities when no new option/evidence
  is applied and versioned identities for explicit historical universes.
- Inspect the GitHub review threads and fixes on the Phase A PR.
- Require an explicit review and merge of Phase 0 before a subsequent Phase A
  merge to master; do not rewrite master or delete remote branches here.
- Do not classify fee/latency proxies as independent funded execution quality.
