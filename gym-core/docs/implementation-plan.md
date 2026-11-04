# Implementation and acceptance plan

Updated 2026-11-04. The request to complete all deferred work remains open.
Implemented code, passing local tests and operational acceptance are separate.
Nothing in this plan enables funded orders or promotes a strategy.

## Completed in the current implementation pass

The subsequent implementation/refactoring slice adds these native capabilities:

| Work | Implementation and present boundary |
| --- | --- |
| Indicators and strategy rules | Shared bounded streaming EMA20/50/200 slopes, Wilder ATR/ADX, Keltner and TRIX; four registered long/flat strategies add fresh RSI/MACD/TRIX crosses and an ADX-filtered Keltner breakout. Ten strategies total. Closed/available bars, gap resets and known holdings are required. No numerical-parity or profit claim. |
| Fixed numeric analyst roles | `research review` uses performance, risk and cash-benchmark roles with allowlisted artifact tools. Missing/stale metrics remain explicit. Semantic grounding, autonomous debate and model judgment are not implemented by these deterministic roles. |
| Resolution-time outcome memory | Immutable actual run/output references and numeric cash-benchmark lessons, visible only after their first recorded resolution. Pending/stale outcomes do not become earlier knowledge. |
| Consume-once future evaluation | Frozen native engine/configuration, disjoint future periods, actual clock, one-period purge and consumption committed before data reads. Errors/crashes retain consumption. This local ledger cannot independently seal data or prevent another ledger/raw-data reader. |
| Observation vintages and screener | Immutable user-supplied news/fundamental/macro/social/whale/funding/OI records, actual receipt-derived knowledge times, source/series/unit-specific ranking and stale/future exclusions. No vendor feed/authenticity or rights claim. |
| Return and forecast arithmetic | Cash-flow-adjusted TWR/Modified Dietz with reconciled supplied marks; point forecast errors, empirical interval coverage and optional Brier scoring. Inputs are unverified and scoring does not establish independent predictive calibration. |
| AI connections | Dedicated GUI/API and private gateway control process for supported SDK OAuth, DPAPI-stored API keys, connection status, preset sync/import/export and explicit advisory prompts. No real sign-in, key replacement or paid provider completion was performed. |
| Shared CLI/browser workflows | `research_actions.py` owns fixed dispatch. Separate `api/models.py`, `api/research.py`, `ui/models.js` and `ui/research.js` avoid adding these workflows to the observatory monolith. See [architecture and interface gaps](architecture.md). |

| Work | Implementation | Verification |
| --- | --- | --- |
| Joint ranked paper allocation | `domain/portfolio.py`, existing `paper-research` command, model `portfolio-sizing` | Shared cash reserve, individual position caps, combined modeled stop-loss cap, aggregate allocation cap, fees/slippage and downward step rounding; 11 cases. It models new entries only, not verified existing holdings or an executable portfolio. |
| Typed numeric claim verification | `services/research_grounding.py`, `research claim-check` | 16 cases for saved-run identity/output digests, allowlisted fields, matched-input arithmetic, explicit rounding, invented profit, private fields, malformed artifacts and selected store. The actual recorded run `385bcd9aa23442dd` matched its −12.53677481 USDT result. Prose, causal claims, forecasts, malicious artifact replacement and feed authenticity are not verified. |
| Portable offline research reports | `services/portable_report.py`, `summary --format json|html --output FILE` | Nine cases, including private-data omission, escaping, malformed inputs and no-overwrite output. Actual recorded-data HTML opened in the browser, with working provenance disclosure, no scripts and no overflow at 390px. It is an English paper summary, not a full replay bundle or localized cockpit replacement. |
| Closed-bar technical diagnostics | domain/indicators.py, services/technical_analysis.py, `technicals` CLI | 15 cases and real recorded-data report `fbf96b7fde2b7681`; null warmup, invalid-quote/gap handling, bounded read snapshot and no-overwrite output. Descriptive only; no new strategy or authority. |
| Multiple technical timeframes | Existing `technical_analysis.py`, repeated `technicals --res` | Ten further cases: one observation snapshot/digest, per-view closed bars and warmup, combined work bounds, invalid selections, unchanged single-view output and real writer between calculations. Recorded-data report `f3f90d2996f1b1f8`. No consensus/confidence or trading rule. |
| Useful custody failure diagnostics | `gym-provision` retains the existing fixed client failure/OS error instead of discarding it | One Rust regression distinguishes request failure, timeout and disconnected client. The diagnostic retains uncertain-commit wording and grants no authority. It has not been installed over the protected binary. |
| Read-only custody-state diagnosis | Existing ledger integrity checker, administrator-only inspection | Current service is stopped/disabled with exit code 5. The retained ledger has schema 1, zero events, zero chain head and file SHA-256 `33ee21f91bcaef3fa7c99361658a19a63305e8e2a3f047e35aae4bdc9d641580`. No ciphertext generation was present. No custody data, ACL, binding or service configuration was changed; no secret content was read. This narrows the old failed attempt but does not prove its cause. |

The new commands use existing dependencies. The original three-tool MCP surface
and research ledger schema are retained; outcome/vintage/final-window records use
a separately versioned protocol database. The protected worker/runtime and
funded boundary were not expanded by these research features.

## Remaining execution and acceptance work

| Work | Current state | Concrete completion requirement |
| --- | --- | --- |
| Installed custody/recovery | Open; prior attempt failed | Diagnose the actual service-side rejection, securely update reviewed binaries, preserve retained history and pass synthetic provision/restart/corruption/recovery. The fresh-install drill refuses an existing vault; deleting its ledger to retry is not acceptable. |
| Actual worker isolation | Open, dependent on installed custody | Update and hash the protected package, run the selected ACER AppContainer and prove denial of custody files, STOP/T2 pipes, profile canary and SCM changes. Source tests do not prove actual process isolation. |
| Independent STOP and hung containment | Open | Measure the selected operator's four stop commands under the parked loop (≤1s), retained-process containment (≤10s), and DISARMED restart. |
| Service-owned venue permissions/exposure | Open | Establish the actual key permission contract, current balances/locked/external exposure, pagination, manual-order lifecycle and freshness. A successful GET alone cannot certify read-only permissions or settlement. |
| Trusted T1 and real submit/cancel/reconcile | Missing integration | Implement principal-bound, payload-bound approvals, fixed-origin transport, durable first-byte outcomes, unknown-order reconciliation and real account/instrument identity. Exercise offline failures before any separately approved venue probe. |
| Protective stops, Exit Guard and capped Autopilot | Missing integration | Qualify native venue protection, disjoint quantities, restart/reopening and loss/installation caps through the real money path. Existing offline policy outputs remain advisory. |
| Sustained prospective paper evidence | Open | Retain actual availability clocks, feed gaps and stale valuations across supervised future sessions. No backfill or short historical replay can establish uninterrupted collection or profitability. |
| Actual-versus-modeled costs | Open | Independently reconcile measured fills, fees, depth and latency with modeled assumptions. Real orders require a specific approved probe and loss budget; neither is supplied by this broad implementation request. |
| Physical-machine recovery | Blocked: user confirmed no second machine is available | Restore and verify on a separate physical host, explicitly reprovision credentials, retain DISARMED state. Same-machine WSL does not satisfy this gate. |

## Deferred research expansion still requiring implementation

| Capability | Required work before claiming completion |
| --- | --- |
| Semantic analyst/debate roles | Fixed numeric role dispatch is implemented above. Prose grounding, independently authenticated observations and bounded model debate remain open; numeric matching does not complete them. |
| Outcome reflection | Resolution-time numeric memory is implemented. A model's narrative lesson remains unverified judgment and is not automatically persisted as economic truth. |
| Independent final evaluation | Local consume-once enforcement is implemented. Independent custody/access control, a real prospective future window and external qualification remain open. Repeated historical windows are diagnostics. |
| Indicator-based strategy qualification | ATR/ADX/Keltner/TRIX, EMA slopes and four closed-bar strategy rules are implemented and tested. Real prospective cost/coverage evidence and independent selection accounting remain required before any promotion. No TA-Lib numerical parity is claimed. |
| Portfolio execution and partial exits | Cash-flow return arithmetic is implemented for supplied exact marks. Actual holdings/basis, cash-flow/fee-currency reconciliation, shared reservations and partial settlement remain required for executable targets and tiered exits. |
| DQN/PPO/RL training and artifact evaluation | Build a separate local research path with leak-free train/validation/final periods, exact account rewards, reproducible seeds/artifact identity and hardware/runtime checks. Existing short, gapped observations are not validated training or profitability evidence. No paid service or model runtime was activated. |
| Additional clocks/component forms/unit-epoch derived views | Define consumers and preserve availability ordering, confirmation time and explicit units; no historical raw rows may be silently relabeled. |
| New news/fundamental/social/vendor feeds | The user-supplied vintage store and screener are implemented. Actual adapters, source authentication, feed availability/rights and release/revision verification remain open. Live search cannot replace historical vintages. |
| Macro/whale/funding/open-interest models and forecasts | Source-specific numeric screening and supplied-forecast scoring are implemented. Timestamp-aligned breadth/credit/yield/sector ratios, transfer context, actual forecast generation and independent predictive calibration remain open. Vendor scores or Prophet intervals are not measured confidence. |
| Maker orders, trade credit, relay and multi-leg execution | Implement their distinct custody, idempotency, ownership, settlement, protection and outage contracts after the core executor gates. No derivative, loan, cloud or relay authority is implied. |

Unrelated monetization, social/community infrastructure, Pixel Office, a second
desktop stack, donor deployment scripts, fallback prices and unfinished donor
order handlers remain explicit exclusions in [capabilities](capabilities.md).
They are not silently installed as a consequence of completing useful deferred work.
The latest eight sources have complete file accounting and 52 family decisions
in [source assessment](source-assessment.md); all 570 files have a disposition.

## Evidence and authority

Current target verification and the older Rust/gateway evidence are recorded in
[system status](system-status.md). Read-only host receipts are
`.pi/paper-qualification/host-inspection.json` and
`.pi/paper-qualification/custody-ledger-inspection.json`; the old failure receipt
is retained. The actual exported example is
`.pi/reports/paper-385bcd9aa23442dd.html`.

No real account call, model completion, paid job, credential replacement, funded
order, push or deployment was performed. Missing implementation above is still
missing code; operational blockers do not convert it into completed work.
