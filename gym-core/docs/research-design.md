# Research design and source rationale — 2026-11-03

Source: `D:\GitHub\TradingGym`, clean checkout at
`f352caaccd10c7179a5e5c67e771988120aabda5`.
Target: `D:\GitHub\Trade`. The source checkout was not modified. No credentials,
account databases, checkpoints, example balances or synthetic market fixtures were
copied into the target's live store. The integrations adapt designs to the
existing native modules rather than introducing a runtime dependency on the old
project. No new package was required.

## Highest-value pieces

| Priority | Source capability / main files | Decision for this project |
| --- | --- | --- |
| 1 | Reason-coded operational readiness — `api/readiness.py`, `tests/api/test_operational_readiness.py` | **Adapted.** Current two-sided book ages, missing/future/stale/invalid quotes, stream faults and per-market degradation are exposed by `/api/ready` and System Health. `/api/health` remains available when readiness is blocked. Neither endpoint attests to a privileged Executor. |
| 2 | Chronological selection and final-window separation — `agent/campaigns/splits.py`, `rl/pipelines/research_protocol.py`, `agent/strategy_lab/overfitting.py` | **Adapted a bounded diagnostic.** First 70% selects one registered candidate by nominal net after modeled costs; one decision period is purged; a separate flat paper account evaluates the fixed choice on later data. One SQLite read snapshot spans both phases. CLI `validate` and the Research button publish immutable run references and a validation manifest. This does not implement the source's consume-once final evaluator, ML training or statistical promotion. |
| 3 | Campaign workbench and persisted research progress — `frontend/src/components/lab/CampaignWorkbench.jsx`, `agent/campaigns/execution.py` | **Adapted to the existing research ledger.** The cockpit shows actual schedules, due times, latest result, retries and alerts, with pause/resume and one bounded due-job batch. Successful jobs publish immutable runs before advancing their clock; results open in the existing inspector. Foreground continuous scheduling remains explicit. |
| 4 | Durable intent/outbox and unknown-delivery handling — `execution/production/mutation_retry.py`, `execution/live/cockpit_orders.py`, `core/audit_outbox.py` | **Keep the target's native implementation.** Rust already has FULL-synchronous intent/reservation history, first-byte retry rules and unresolved holds. Reuse the source's failure cases during real Wallex transport integration; do not duplicate its Python journal or treat broker-specific idempotency as a Wallex fact. |
| 5 | Exact accounting, fee currencies, unmatched fills and reconciliation — `execution/accounting/{ledger,order_fill_parity,pnl_decomposition}.py` | **Reuse contracts and test cases selectively.** Target received-asset fees, exact-decimal parsers, external snapshot journal and reservation model already cover substantial overlap. Do not replace these with source diagnostics that use floats, assume a different fee model or infer settlement. |
| 6 | Paper divergence attribution — `agent/campaigns/divergence.py` | **Next useful refinement.** Match decision identity, instrument, source period and clocks before reporting price/cost/timing deltas; mismatched or missing periods need reasons and no invented numeric delta. Current engine parity remains a shared-engine check, not independent calibration. |
| 7 | Sealed candidate budgets, bounded campaigns and retention — `agent/campaigns/{contracts,execution,retention}.py` | **Later, when a real search workload needs it.** Current comparisons already cap candidates at four and a window at 31 days. Add trial accounting and consume-once final claims before calling an optimization result independent; avoid importing a generic campaign runtime now. |
| 8 | Provider rosters, cooldown and recorded model routes — `agent/gateway.py`, `intelligence/llm_key_pool.py` | **Retain the existing gateway.** It already has explicit connection/preset identity, unique-key rotation, persisted cooldown and bounded actual SDK calls. Native System One and OpenAI-compatible chat are different protocols; no automatic fallback or copied entitlement claim. |
| 9 | Linked inspectors, watchlists and decision history — `frontend/src/{views,components}` | **Selective UI follow-up.** Keep the current dependency-free EN/FA interface and exact monetary strings. Linked selections and saved views are useful; a wholesale React frontend replacement would not close the execution or data-quality gaps. |
| 10 | PPO/RL, HPO, leverage and multi-venue planners — `rl/`, `execution/portfolio/`, retained institutional modules | **Deferred.** Their dependencies, market conventions and authority contracts differ. Source breadth or passing local tests do not qualify them for funded Wallex use. Many institutional modules produce advisory/evidence artifacts rather than executable economic actions. |

## Additional defects corrected during integration

The target's housekeeping loop awaited public REST refreshes. Slow refreshes could
delay both stale-book marking and stored observation heartbeats. Tick maintenance
and REST refresh now run separately, with structured cancellation before shutdown.
Missing/stale books can be reseeded even when the WebSocket is disconnected.
Markets and FX status also recalculate freshness from both actual book-side
timestamps at request time; a fresh ping cannot make an old quote current.
Future book-side timestamps are disqualified.

Research jobs previously kept their reports only inside SQLite. They now publish
the actual immutable run before committing completion and advancing the clock.
A publication failure leaves the clock and completion history unchanged.

## Verification and actual observation exercise

- **Source:** 18 focused readiness/overfitting/divergence tests passed with real
  installed dependencies, bytecode/cache writes disabled, and all test/application
  state redirected to new directories under the target's `.pi/`. This is not a
  full source-project qualification.
- **Target:** regression and UI contracts cover authorization, durable job
  pause/resume, retries, inspectable saved reports, missing/stale/future books,
  blocked REST maintenance, worker cancellation and later-data selection
  invariance. Current integrated counts are in [acceptance status](acceptance-status.md).
- **Actual data:** validation `a7db6a5da359cb5e` used the three-hour BTCUSDT
  observation window ending `2026-11-03T20:13:00.008408Z`. EMA 2/5 was selected
  among active candidates; SMA abstained. EMA selection net was **−26.86004777
  USDT** and later-window net was **−31.02680259 USDT**, each on a separate
  1,000-virtual-USDT account. End marks were current at their respective run
  cutoffs. These are historical paper replays, not a new three-hour prospective
  session or a profitability qualification.
- One hourly EMA 2/5 paper job was initialized from that same paper profile and
  its first due run completed on actual observations. No real account/model call
  or order was made. Machine summary: `.pi/donor-integration/live-validation.json`.

The source API constructs its default application/data home at import. The first
source test attempt hit the private-home permission boundary; the successful run
used an explicit isolated home. The target does not import that API or start its
connectors. No default-home data was copied or used as evidence.

## Remaining release work

Installed Windows custody/isolation/STOP/containment, actual account permissions
and lifecycle qualification, real trusted Wallex submit/cancel/reconcile transport,
certified exits/Autopilot, another-machine recovery and sustained prospective
paper evidence remain open. The source's Abantether adapter cannot stand in for
those capabilities. All transferred functionality retains zero funded authority.
