# Requested skill coverage, 2026-11-11

Current execution ledger. Findings, verification and performance measurements are consolidated in [the audit](audit-2026-11-11.md). All 33 requested names are accounted for; prerequisite limits are explicit.

## Every requested skill


| Skill | Actual work | Execution limit |
| --- | --- | --- |
| onboard | Ran deep collector; read manifest, source entrypoints, CI, layout and generated orientation | Analyzer provenance verification failed (attestation 404); binary was refused. Basic collector completed; no repo-intel/map score |
| evolution-engine | Checked generation/evaluation isolation, held-out handling and local trial accounting | No arbitrary strategy, Binance job or model generation launched |
| heytraders-browser | Searched installed skill locations and available tool catalog | Instruction file and connector unavailable; no HeyTraders action claimed |
| backtesting-frameworks | Reviewed temporal/cost/causal valuation contracts and executed research regressions; found and repaired stale prospective comparisons | No live qualification or positive edge claim |
| risk-metrics-calculation | Reviewed performance/portfolio/FX/HRP and cutoff handling; ran focused tests | No claim that synthetic passing tests establish investment suitability |
| thefinancial-ai | Checked current skill/tool availability | Instruction file and connector unavailable; no ticker/portfolio task was supplied and no market query invented |
| architecture-analyst | Graph-led ownership/authority review, source/caller tracing | `epis` absent; no formal law/knowledge-graph score |
| antislop-code | Purpose-tested comments in money, concurrency, credential and process paths | Preserved meaningful constraints; no blanket deletion |
| cleaning-comments | Architecture-aware comment scan and dry review | No comment cleanup required |
| antislop-ui | Checked actual operator UI, geometry, themes, reading direction and state transitions | Gate not passed; numbered UI repairs await selection |
| antislop | User explicitly selected both modes; applied purpose/evidence rules to current audit and new guide | No claim of a passed whole-UI delivery gate |
| deslop | Deep scan across 528 explicitly listed tracked sources; 1,479 mechanical signals triaged by category/sample | Signals are not defects; no auto deletion; jscpd absent |
| ponytail-audit | Concrete whole-repository risk/bug/scale/test/speed/lean review in bounded high-risk paths | Not every source line read; reviewed limits disclosed |
| code-refactor | Traced shared owners and callers before assessing changes | No bulk rewrite or new abstraction |
| planning-backend-refactor | Checked stack and project-rules prerequisites | Missing PROJECT_RULES and unsupported Go/TypeScript backend; formal Ring plan inapplicable |
| planning-frontend-refactor | Checked rules and actual plain-JS UI | No React/Next.js conversion or invented framework plan |
| refactoring-and-tech-debt | Refreshed actual versus repaired debt and ownership/trigger decisions | Maintainer ownership remains unassigned; no invented delivery commitment |
| simplify-implementation | Existence/reuse review of bridge, worker, migration and kernel seams | Actual process/language/authority boundaries retained |
| planning-codebase-simplification | KEEP/REVIEW assessment with real consumers | Formal Go/TS-specific explorer workflow inapplicable and its atomic pool exceeds available slots |
| codebase-visualizer | Built a self-contained seven-view guide with EN/CN, two themes, searchable architecture and source-derived SQLite tables | Static/isolated interaction checks pass; browser rendering unverified |
| ai-integration-architect | Reviewed provider credentials, correlation, bounded output/time, isolated workers and advisory-only scope | No remote model call, scaffold, deployment or account mutation |
| searching-code | Queried fresh Graphify, followed with exact source/caller/test checks | Graph is navigation evidence, not proof of every dynamic call |
| typography-selector | Applied hierarchy/readability to current local Segoe/Tahoma/Cascadia roles | Existing product direction retained; no unnecessary downloaded font |
| color-curator | Confirmed actual light/dark semantic tokens in browser and audited purpose/roles | Full rendered contrast matrix unmeasured |
| trend-researcher | Inspected live Dribbble web/mobile examples and screenshots; recorded bounded observations | No redesign imposed and no market-wide popularity claim |
| checking-frontend-quality | Real-browser ten-route, three-width, EN/FA, two-theme checks; source UI tests | Formal Ring handoff absent; axe/cross-browser/Lighthouse/CWV not claimed |
| code-review-and-quality | Financial/authority/caller/contract/test review and post-fix check | No fictional project standards or blanket green status |
| review-agent | Automated defect-first review of actual Python fix and guide JavaScript | No introduced defect found in that bounded change scope |
| dev-review | Holistic design/caller/failure/rollback review | No configured devkit feature lifecycle, remote lint install or push |
| audit-project | Context collector, ten applicable perspectives, structured queue, high-priority repair, verification and automated rereview | Collector missed nested SQLite/plain-JS UI; actual source corrected scope; ordinary issues retained |
| systematic-debugging | Failure-before-fix regression and shared-root correction; separate source, host and browser limits | No speculative fix or paid reproduction |
| perf-baseline-manager | Used bundled storage/readback/comparison utilities for one versioned synthetic benchmark record | No prior same-version baseline; observational timing under concurrent workload, no speedup claim |
| codebase-documenter | Refreshed source-grounded ownership, startup/check commands and qualification limits in the reports/guide | Reused current docs; no competing documentation scaffold |

## Onboarding and operating boundaries

### Requested repository-wide simplification follow-up

The six explicitly requested skills were read and applied together: AI DevKit
`simplify-implementation`, Fable `fable-simplify`, both engineering-suite
`code-simplification` variants, `ponytail`, and `ponytail-audit`. Their common
contract is to trace real consumers, preserve behavior, and verify each small
transformation after an affected green baseline. The audit skill supplied findings;
implementation followed the separate simplification workflows.

The static inventory covered all 660 tracked paths, including 526 code files,
with graph-led targeted source, registry and dynamic-consumer inspection. It did
not independently review every source line. The concrete candidates were an
unreachable dispatcher fallback, an unused internal helper, and duplicated batch
indicator calculations. Real process, authority, transaction, frozen-engine and
language-binding boundaries were retained.

Indicator consolidation was rejected after exact output comparison and timing:
for 10,000 deterministic Decimal closes, three-run medians were 0.086299 seconds
for the batch implementation and 0.764286 seconds for a streaming projection
(8.86 times slower). These are local synthetic measurements; preserving the
faster batch path is preferable to removing its small numerical implementation.

The reviewed dispatcher/helper cleanup removed 42 net lines while preserving all
83 actions in 38 registered handlers. Its focused suite passed 62 tests; automated
review separately passed 24 registry/bias tests and found no behavior drift.
No dependency was removed or added.

A bounded exact SQLite read benchmark populated an isolated store whose main
database file was 43,986,944 bytes (WAL sidecars excluded)
with 373 symbols and 600 quote rows per symbol (223,800 rows). Reading every
symbol through DataPortal.tops took 1.692 seconds median over three runs;
EXPLAIN used book_top_avail with no temporary sort. Longer histories, concurrent
writes and storage contention remain unqualified. Retain the existing store
until a representative workload demonstrates a deadline failure that warrants
another storage tier. Gateway import/dependency measurements and the decision
to retain the active SDK are recorded in its README.

What this repo does: TradingGYM collects Wallex spot observations and runs local paper research. Python owns collection, exact SQLite storage, the simulator and EN/FA workspace. Rust owns a separately protected executor boundary; Node offers optional advisory model calls. Assumed load is one local operator with concurrent collector/research/browser activity.

The numerical vectorization pass replaced SPA's interpreted per-element resampling
with a native vector gather, reusing each simulation's time indices across candidate
return columns. Candidate ordering, seeded block sampling and exact `fmean`
reductions remain unchanged. Complete result dictionaries matched the original.
Five alternating local CPython 3.11.9 measurements gave these medians:

| Periods × candidates × simulations | Original | Vector gather | Speedup |
|---|---:|---:|---:|
| 100 × 4 × 199 | 13.686 ms | 7.350 ms | 1.86× |
| 2,000 × 8 × 199 | 396.685 ms | 141.911 ms | 2.80× |
| 10,000 × 8 × 100 | 2,078.590 ms | 772.451 ms | 2.69× |

An evaluated NumPy matrix gather retaining the exact reduction was slower than
the native gather. Array mean was faster but changed floating-point rounding,
which can change bootstrap threshold ties; it was not adopted. No dependency or
backend option was added. Expanded validation passed 113 tests covering SPA,
scorecards, indicators, portfolio policy, covariance shrinkage and risk parity.
At the largest tested workload, traced peak allocation rose from 1,113,692 to
1,580,796 bytes (about 456 KiB); sampled vectors remain bounded by 10,000 periods.

Price/return covariance owners already use aligned Decimal columns and symmetric
dot products. Keep exact money, causal timestamps, validity masks and market IDs
at their existing boundaries. Descriptive metadata remains keyed by identity;
turning mixed records into object tensors would add conversion without a numeric
operation. Historical indicator batching retains intermediate Decimal validation
and trap behavior. This pass does not claim SIMD arithmetic or a whole-repository
tensor migration.

Entry paths are `gym-core/src/gym/cli.py` to command modules, `commands/daemon.py` to collector/API composition, `model-gateway/host.mjs` to the correlated advisory runtime, and Rust service/helper binaries under `executor/exec-svc`. Shared wire contracts/golden fixtures live in `contracts/`. The Node result has no funded order authority.

Use the existing README setup/check commands. Local verification used the existing locked Python environment and installed Rust/Node toolchains. No commit, push, hosted CI dispatch, provider/account mutation or funded execution was performed. Local success does not certify hosted deployment, real settlement, venue stops or strategy edge.
