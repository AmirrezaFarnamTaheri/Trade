# Implementation and acceptance plan

Updated 2026-11-05. The request to complete all archive-derived work remains open.
Implemented code, passing local tests and operational acceptance are separate.
Nothing in this plan enables funded orders or promotes a strategy.

## Current delivery scope

Decision updated 2026-11-04: predictive ML and reinforcement learning are outside
the current delivery scope. DQN/PPO agents, neural price forecasting, automated
model search and trained-model order execution are not deferred commitments or
release requirements. This is a scope change, not a claim that those capabilities
were implemented or qualified. Historical donor assessments retain their findings;
their ML candidates do not override this decision.

Keep indicators, explicit market screening, decision replay, experiment tracking,
robustness checks and supplied-forecast scoring. Keep optional Codex/Anthropic
connections for evidence-linked research and explanations, with explicit sending
and no trading authority. No working feature is removed by this plan change.

Prioritize data coverage/recovery, exact accounting/reservations, realistic paper
costs, protected execution/recovery and prospective evidence. Reconsider predictive
ML only as a separately approved research project after adequate data coverage
exists and a simple model demonstrates repeatable improvement over fixed-rule
baselines on untouched chronological future periods after modeled costs. Training
and selection must exclude future information; historical scores alone are not
an acceptance criterion.

## Eight-module research workspace implementation

The selected eight modules are implemented through existing native owners and
shared CLI/API dispatch. [Research workspace](research-workspace.md) documents
their exact inputs, bounds and authority limits.

| Module | Implemented behavior |
| --- | --- |
| Coverage and recovery | Bucket timeline, delayed receipts, stale carried quote ages, readiness resets; current-window retry/recorded skip and selected-job bounded catch-up with retained failure/audit. No silent recovery of missing quote history. |
| Replay debugger | Verified/paginated saved decisions, actual pre-decision balances, bar/context/reference/rule snapshots and separate later modeled outcomes. Old missing trace fields remain unknown. |
| Experiment registry | Immutable definitions, code/config lineage, every planned attempt recorded before calculation, retained failed/incomplete/pending states and checked frozen-final links. Local integrity does not establish independent custody. |
| Market screening | Explicit comparable universe, momentum/reference-relative return, SMA distance, spread, top notional and observed dispersion; exclusions remain visible. |
| Portfolio preview | Supplied current/target holdings, locks/reserved cash, bid/ask/fees/minimums/steps, conditional sale proceeds, turnover and post-cost projected concentration/shortfalls. Ownership/basis/settlement are not inferred. |
| Robustness laboratory | Native replay across chronological windows, parameter trials, bounded fees/latency and feed removal, with matched baselines and all attempt outcomes retained. No arbitrary extra-slippage model or automatic promotion. |
| AI research notes | Allowlisted evidence packets, explicit optional provider send, bounded roles/citations/numeric checks/disagreement and immutable notes. Prose and model provenance stay unverified. |
| Execution quality | Supplied partial-fill aggregation, fees/latency/VWAP/adverse-price comparisons, unmatched references, missing observations and modeled nonfills. Real account authenticity remains a separate acceptance gate. |

CLI and authenticated API tests cover the shared services. Browser checks use
actual recorded BTCUSDT data, not donor samples. The documented Downloads source
archives are already archived; `.pi/archive-verification.json` verifies 85 ZIPs,
including the platform batch, with none left in Downloads at the audit.
The eight-module implementation does not close the execution/acceptance work or
broader research extensions listed below.

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
| Measurement-aligned arithmetic | Optional numeric measurement clocks preserve old observation hashes. `research derived` resolves two known vintages in one snapshot, with explicit units/freshness/skew and unavailable results. No source authentication, sector model or forecast accuracy is inferred. |
| Point-in-time candle checks | Native crosscheck adds an optional exclusive receipt/fetch cutoff; the bounded local-only workbench action requires it. Current venue storage does not retain superseded candle vintages. |
| GUI report and ticket journal | Saved runs download the existing offline HTML report. Canonical previews can be saved and acknowledged/rejected from the GUI using the native journal and actual server review time. No Executor permission is issued. |
| Descriptive average distance and range oscillator | Shared indicator diagnostics include SMA200, close/SMA distance percentages for 20/50/200 observed bars and the 5/34 Awesome Oscillator from actual high/low ranges. Missing history stays warmup; no new strategy or intrinsic-value claim. |
| Decision-linked chart | Native bounded SVG replay displays up to 150 recorded points through the selected decision, explicit gaps, escaped exact-price labels and keyboard navigation. No chart framework or donor data imported. |
| Causality and warm-up audit | Shared `strategy-audit` action compares full versus truncated native decision traces at selected endpoints and separately varies prehistory. Missing comparisons stay unavailable; matching selected endpoints does not prove all branches unbiased. |
| Saved-return uncertainty | Shared `return-bootstrap` action verifies saved artifacts and computes seeded stationary-block centered-return diagnostics. Real timestamp gaps break block adjacency. Declared assumptions, interval counts, modeled costs and uncorrected strategy selection remain visible; no promotion verdict. |
| Durable paper attempt ownership | Scheduler records an attempt before calculation and releases the write lock during replay. Exact-claim interruption fences late publication; crash claims remain visible until explicit recovery. CLI/API/GUI expose claim, start, progress and unknown liveness separately. This does not terminate processes or cancel orders. |
| Windows ciphertext publication | Reproduced child-file rename failure under strict ancestor sharing (OS error 32). Directory pins now permit write sharing while denying delete sharing; ciphertext/secret-file pins remain stricter. Regression checks publication, directory rename denial and ciphertext write denial. New binary is built locally; protected installation is not qualified. |

| Work | Implementation | Verification |
| --- | --- | --- |
| Joint ranked paper allocation | `domain/portfolio.py`, existing `paper-research` command, model `portfolio-sizing` | Shared cash reserve, individual position caps, combined modeled stop-loss cap, aggregate allocation cap, fees/slippage and downward step rounding; 11 cases. It models new entries only, not verified existing holdings or an executable portfolio. |
| Typed numeric claim verification | `services/research_grounding.py`, `research claim-check` | 16 cases for saved-run identity/output digests, allowlisted fields, matched-input arithmetic, explicit rounding, invented profit, private fields, malformed artifacts and selected store. The actual recorded run `385bcd9aa23442dd` matched its −12.53677481 USDT result. Prose, causal claims, forecasts, malicious artifact replacement and feed authenticity are not verified. |
| Portable offline research reports | `services/portable_report.py`, `summary --format json|html --output FILE` | Nine cases, including private-data omission, escaping, malformed inputs and no-overwrite output. Actual recorded-data HTML opened in the browser, with working provenance disclosure, no scripts and no overflow at 390px. It is an English paper summary, not a full replay bundle or localized cockpit replacement. |
| Closed-bar technical diagnostics | domain/indicators.py, services/technical_analysis.py, `technicals` CLI | 15 cases and real recorded-data report `fbf96b7fde2b7681`; null warmup, invalid-quote/gap handling, bounded read snapshot and no-overwrite output. Descriptive only; no new strategy or authority. |
| Multiple technical timeframes | Existing `technical_analysis.py`, repeated `technicals --res` | Ten further cases: one observation snapshot/digest, per-view closed bars and warmup, combined work bounds, invalid selections, unchanged single-view output and real writer between calculations. Recorded-data report `f3f90d2996f1b1f8`. No consensus/confidence or trading rule. |
| Useful custody failure diagnostics | `gym-provision` retains the existing fixed client failure/OS error instead of discarding it | One Rust regression distinguishes request failure, timeout and disconnected client. The diagnostic retains uncertain-commit wording and grants no authority. It has not been installed over the protected binary. |
| Installed custody diagnosis | Stage-specific SCM codes; retained zero-event ledger and synthetic-only continuation | Instrumented service reached RUNNING_DISARMED, then stopped/disabled. Later synthetic provision failed at ciphertext publication (1011), without acknowledgement or funded authority. Empty inspection-created WAL/SHM sidecar ownership was repaired to LocalService, preserving ledger/history and ACLs. Subsequent administrator prompt was canceled; the local rename fix remains uninstalled/unqualified. |

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

## Open archive-derived implementation and acceptance

The latest request makes the useful documented integration candidates active work;
the historical assessments' wording that they were only candidates is not a
completion claim. The additions above close only their stated local contracts.
Remaining implementation includes correction-aware indicator/replay fixtures,
resumable snapshot-bound projections, saved annotations and linked chart panes,
sequence-checked depth, aligned-return correlation, bounded result bytes/pages,
persisted entry locks and remaining GUI journal/conversion/probe inputs. Protected
runtime, real venue, portfolio settlement, vendor feeds and independent-custody
contracts below also remain open. Excluded predictive ML and unrelated donor
applications are not silently reinstated. No unavailable operational acceptance
is replaced with a mock or marked complete.

| Capability | Required work before claiming completion |
| --- | --- |
| Semantic analyst/debate roles | Bounded cited role notes, disagreement and exact numeric checks are implemented. Independently authenticated observations and verified prose semantics remain unestablished; numeric matching never certifies them. |
| Outcome reflection | Resolution-time numeric memory and immutable evidence-linked narrative notes are implemented. A model's narrative lesson remains unverified judgment and is never persisted as economic truth. |
| Independent final evaluation | Local consume-once enforcement is implemented. Independent custody/access control, a real prospective future window and external qualification remain open. Repeated historical windows are diagnostics. |
| Indicator-based strategy qualification | ATR/ADX/Keltner/TRIX, EMA slopes and four closed-bar strategy rules are implemented and tested. Real prospective cost/coverage evidence and independent selection accounting remain required before any promotion. No TA-Lib numerical parity is claimed. |
| Portfolio execution and partial exits | Exact supplied-mark return arithmetic, reservation-aware target preview and supplied partial-fill comparison are implemented. Actual holdings/basis, authenticated fee reconciliation and partial settlement remain required for executable targets and tiered exits. |
| Additional clocks/component forms/unit-epoch derived views | Measurement clocks and two-input aligned arithmetic are implemented. Component forms, confirmation clocks and cross-epoch derived views still need explicit consumer contracts; no historical raw rows may be silently relabeled. |
| New news/fundamental/social/vendor feeds | The user-supplied vintage store and screener are implemented. Actual adapters, source authentication, feed availability/rights and release/revision verification remain open. Live search cannot replace historical vintages. |
| Macro/whale/funding/open-interest diagnostics | Source-specific screening, supplied-forecast scoring and aligned two-series ratios/differences are implemented. Breadth/sector diagnostics and transfer context still require explicit input/consumer contracts. Predictive training and forecast generation are outside current scope; vendor scores or Prophet intervals are not measured confidence. |
| Maker orders, trade credit, relay and multi-leg execution | Implement their distinct custody, idempotency, ownership, settlement, protection and outage contracts after the core executor gates. No derivative, loan, cloud or relay authority is implied. |

Unrelated monetization, social/community infrastructure, Pixel Office, a second
desktop stack, donor deployment scripts, fallback prices and unfinished donor
order handlers remain explicit exclusions in [capabilities](capabilities.md).
They are not silently installed as a consequence of completing useful deferred work.
The latest eight sources have complete file accounting and 52 family decisions
in [source assessment](source-assessment.md); all 570 files have a disposition.
The subsequent OpenAlice/Zipline/AITD inventory covers 4,353 regular files, with
selected implementation reads and explicit module-family decisions in the
[research source assessment](research-source-assessment.md). Its useful remaining
ideas are not all implemented. These three ZIPs are now in Downloads/archive, and the
source snapshots remain review references; local changes are now authorized for commit.
The next six unique Downloads ZIPs have 454 entries assigned to 30 module-family
decisions, plus an individual catalogue of all 61 supplied strategy examples in
the [trading source assessment](trading-source-assessment.md). Their native
additions and remaining research candidates are listed separately. Neither the
resource catalogues nor historical backtests qualify a live strategy.

The subsequent six market-infrastructure sources have 432 hashed entries, 32
module-family decisions and 187 indicator declarations catalogued in the
[market source assessment](market-source-assessment.md). Their ZIPs were archived
with matching hashes. Useful candidates are mapped to the eight-module
[research workspace plan](research-workspace-plan.md); this review does not mark
those modules complete.

Further source reviews are recorded in the [four-source interface assessment](interface-source-assessment.md)
(3,085 entries, 31 family decisions), the [eleven-source analytics assessment](analytics-source-assessment.md)
(8,394 entries, 40 family decisions), and the [fourteen-source library assessment](trading-library-assessment.md)
(9,257 entries, 64 family decisions). Their strongest candidates concern indicator
contracts and cache corrections, event-linked charting, fill/balance reconciliation
and cancellation under failed entry constraints. These are assessed candidates,
not newly implemented features or expanded ML commitments. Each assessment maps
its findings to existing native owners and records verification limits.

The [Freqtrade/OctoBot/Jesse platform assessment](platform-source-assessment.md)
adds 8,207 hashed entries and 45 family decisions, including OctoBot's sixteen
functional package directories. Its strongest additional candidates are
future-data invariance and recursive warm-up checks, timestamp/fast-full replay
parity, worker claim fencing with separate progress/liveness, and pending-cancel
reconciliation. Optional statistical diagnostics require declared assumptions
and all attempted trials; they do not reopen predictive ML or authorize trading.
The causality/prehistory audit, saved-return block diagnostic and durable native
paper claim fencing now implement specific parts of these findings. Timestamp
parity, hard process deadlines, bounded result publication and the other
contracts retain their separate acceptance requirements.

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
