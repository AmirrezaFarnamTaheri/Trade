# Implementation and acceptance plan

Updated 7 November 2026 (Asia/Tehran). This is the unified backlog for the
31-item cleanup/finance proposal and the repository audit. The user authorized
unifying and starting execution. Items stay visible until their acceptance checks
pass; a proposed idea is not an implemented feature or a proven trading edge.

## Scope and order

1. Correctness and reproducibility before cleanup or new strategies.
2. Reliable collection, one data root, and visible coverage before new paper claims.
3. Documentation and structural cleanup without breaking active consumers.
4. Research measurement, execution realism and shared risk controls.
5. New strategy hypotheses and portfolio extensions, evaluated on new data.
6. Read-only account contracts, protected execution and operational acceptance.

Use existing native owners, purpose-based filenames and exact money arithmetic.
Preserve saved runs, frozen engines, raw data, failed attempts and provenance.
Moving an ignored folder is not automatically safe: .pi contains live launchers,
study definitions and qualification receipts. Do not move it wholesale.
Local phase commits follow passing relevant checks. No push, paid provider request,
credential replacement or funded order is implied. The funded loss budget stays zero.

## Current evidence

- The frozen revision-3 compound study completed all 373 eligible spot market batches:
  1,492 cases defined, 1,380 completed and 112 NO_QUALIFIED_DATA cases; 44 fills,
  17 negative cases, zero positive cases, 208 stale end marks and 364 completed
  cases without readiness. This is one five-hour, one-minute-bar historical study.
- Its saved outcomes are in .pi/compound-study/20261106T205324Z/outcomes.json.
  The separate 149,573-case ten-strategy campaign is not complete. Neither is
  qualification of the new portfolio/limit features.
- The audit baseline at ef5da64 passed 1,148 Python tests/four skips/39 subtests,
  29 gateway tests/one skip and serial Rust tests. Parallel Rust exposed a test
  directory collision. Those counts do not describe changes made after that audit.
- At audit time the collector was offline and the executor stopped/disabled.
  The 85 documented donor ZIPs were present in Downloads/archive, with no matching
  names in Downloads' root. ZIP contents were not freshly rehashed in that audit.

## Phase 1 — Correctness and reproducibility

| ID | Work | Acceptance | State |
| --- | --- | --- | --- |
| C1 | Remove future information from shared-cash portfolio marks and sizing | Changing later quotes cannot change earlier marks or allocations; close all markets in event order | Implemented; regressions passed |
| C2 | Bind portfolio identity to consumed depth, trade prints, rules and metadata | Relevant input changes produce distinct IDs; identical snapshot reruns match; version corrected portfolios | Implemented; regressions passed |
| C3 | Stop silently converting compound limit requests into market orders | Unsupported combinations fail clearly through CLI/API; compound spread/capacity/position safeguards remain enforced | Implemented; regressions passed |
| C4 | Retain all allowlisted execution assumptions in JSON/HTML exports | Maker fees, depth, participation, remainder and sizing options survive export; private fields do not | Implemented; regressions passed |
| C5 | Isolate concurrent Rust test directories | Default parallel workspace suite passes without clock-based directory collisions | Implemented; regressions passed |

Keep old native artifacts and legacy strategy identities intact. Run regression,
UI contracts, lint and Rust checks appropriate to touched paths. Do not relabel old
results as produced by the corrected portfolio implementation.

## Phase 2 — Operations and visibility

| ID | Work | Acceptance | State |
| --- | --- | --- | --- |
| O1 | Diagnose collector shutdown and unify startup/data-root selection | One collector on loopback; all eligible pairs by default; explicit exclusions; current native assets served | Startup verified; fresh venue coverage blocked by connectivity |
| O2 | Supervise collection and paper scheduling | No duplicate processes; clear failures/retries; no hidden narrowing to BTC/ETH/USDT; recovery preserves history | Limited-user task supervision verified; sustained observation still open |
| O3 | Publish one current campaign/results view | Show defined/attempted/completed/ready/traded counts, exclusions, dated progress and process liveness separately | Queued |
| O4 | Add shared-cash portfolio replay to GUI/API | Same validated native owner as CLI, bounded jobs, readable errors and verified saved records | Implemented; native worker/API and EN/FA DOM regressions passed; real-browser visual check remains unverified |

Prospective evidence is collected with actual clocks; elapsed downtime is a gap,
not fabricated history. Multi-day paper sessions cannot be declared complete at launch.

## Phase 3 — Cleanup proposal, original items 1–15

| Original item | Consolidated work | Acceptance / decision | State |
| --- | --- | --- | --- |
| 1 | Classify .pi, tool-state folders and target/tmp | Trace callers/processes first; retain active study/runtime evidence; archive only verified inactive files outside repo with a manifest and no overwrite | Consumer audit |
| 2 | Consolidate the three root specification documents | Preserve live requirements in PRODUCT and this plan; check links/external consumers before moving originals | Queued |
| 3 | Resolve duplicate backup-status databases | Establish canonical data root; inspect both histories, back up and merge through existing journal semantics; never overwrite either database | Canonical runtime root verified; both journals snapshotted; two missing receipts merged idempotently; original source retained |
| 4 | Replace the system-status diary with a current status page | One dated current summary, links to evidence; historical receipts remain in Git/artifacts | Current page delivered |
| 5 | Reduce acceptance-status to current gates | Distinguish implemented, verified, unverified and physically blocked; preserve original evidence | Current gates delivered |
| 6 | Reduce capabilities/research-design repetition | Keep actual capability contracts and reuse decisions; archive historical source comparisons without losing attribution | Queued |
| 7 | Shorten gym-core README | Install/run/common commands plus links; no arbitrary line-count target that removes necessary instructions | Queued |
| 8 | Index docs and remove architecture/workspace duplication | Trace section links; one owner per contract and a docs index | Docs index delivered; architecture merge queued |
| 9 | Align CHANGELOG, PRODUCT and DESIGN | State current behavior and remaining work; preserve intentional historical release notes | Queued |
| 10 | Migrate legacy --fast/--slow usage | Find scripts/tests/users first; keep compatibility until consumers use --params; no gratuitous CLI break | Maintained example migrated; active-script audit found no further callers; frozen engines untouched; legacy/native-parameter equivalence test passed |
| 11 | Split CLI by established command groups | One entry point; preserve invocation, defaults, return codes, errors and protected-boundary behavior | Queued |
| 12 | Continue browser view separation | Preserve EN/FA, theme, focus, mobile layout, hashed assets and existing UI contracts | Queued |
| 13 | Review research service consolidation | Merge only actual redundant forwarding; preserve worker import/module identities used by protected launchers | Queued |
| 14 | Consolidate duplicate tests/document invocation | Preserve behavioral coverage and independent boundary tests; test count reduction is not a goal | Queued |
| 15 | Establish line-ending policy | Inspect tracked EOLs first; add gitattributes if needed; isolate normalization from behavior changes | Audited index: all 407 newline-bearing text blobs already LF; explicit LF policy added separately, wire fixtures/binaries excluded; no bulk rewrite required |

## Phase 4 — Measurement and realistic mechanics

| Original item | Consolidated work | Acceptance / dependency | State |
| --- | --- | --- | --- |
| 27 | Consistent TMN and USDT-equivalent valuation | Reuse existing point-in-time FX owner; add missing portfolio/curve surfaces; preserve STALE/STALE_CLOSED/UNAVAILABLE and never use later FX | Portfolio revision 3, CLI and GUI conversion delivered; existing single-market boundary valuation shares the owner; historical single-market curve surfaces still open |
| 28 | Walk-forward parameter search | Freeze training/test chronology, purge overlaps, record every trial/failure and selection count; never tune the final window | Queued |
| 29 | Overfitting and regime diagnostics | Declare CSCV/block/dependence assumptions; distinguish trade-path reshuffling from new market samples; no confidence from insufficient data | Queued |
| 16 | Shared optional exit policy | Fixed, ATR trailing, profit and time exits; actual holdings/fills, partials, dust, costs and closures; defaults preserve existing run identities | Queued |
| 17 | Parameterize RSI/MACD/TRIX/Keltner rules | Validate ranges and readiness; version/hash changed behavior; keep prior defaults reproducible | Implemented; bounded schemas, custom readiness/gap tests and unchanged default hashes passed |
| 19 | Optional reusable regime gate | Verify the actual detector owner first; causal inputs, explicit regime transitions, default-off identity compatibility | Queued |
| 20 | Stop-risk sizing in replay | Reuse portfolio_sizing with exact quantities, stop distance, shared cash, reservations, venue minimums and explicit unknowns | Queued |
| 24 | Partial resting-limit fills | Queue depletion limits filled quantity; maker fees and remaining order state reconcile; no whole-order fill from a tiny print | Implemented; buy/sell/expiry/capacity and malformed-queue regressions passed; public queue remains modeled |
| 26 | Calibrated execution assumptions | Reuse calibrate evidence with source/freshness/sample limits; unauthenticated or absent measurements cannot silently become trusted defaults | Queued |

## Phase 5 — Strategy and portfolio hypotheses

| Original item | Consolidated work | Acceptance / dependency | State |
| --- | --- | --- | --- |
| 18 | Toman premium, Donchian/turtle, compression and lead-lag hypotheses | Separate preregistered rules, causal aligned inputs, FX/closure costs and held-out comparisons; none is an established edge | Queued |
| 21 | Inverse-volatility/risk-parity weights, correlation caps, rebalance clocks | Shared-cash accounting, lookback readiness, causal covariance and turnover/cost controls; test allocation conservation | Queued |
| 22 | Portfolio drawdown and daily loss limits | Latched state, correct Tehran/UTC clock policy, actual simulated exposure and restart/replay parity | Queued |
| 23 | Capped fractional Kelly sizing | Require sufficient out-of-sample evidence; disclose estimation uncertainty; a supplied fraction is not an inferred optimal fraction | Queued |
| 25 | TWAP and spread-aware execution choice | Recorded child orders, displayed capacity, partials, cancellation, timing and total reservation conservation; paper only | Queued |
| 30 | Prospective shadow comparison | Freeze configurations before future data; matched costs/baselines; daily drift, gaps and no-trade cases visible | Queued |
| 31 | Scorecards, parameter heatmaps and backtest/shadow overlays | Read native verified records; show USDT/FX status, trial counts, failure/readiness and statistical limitations | Queued |

Predictive ML/RL training remains outside delivery scope. These statistical and
rule-based features do not reinstate it. New data feeds require a specific provider,
clock/revision/rights contract and explicit credentials/paid-call authorization.

## Phase 6 — Protected account, execution and acceptance

These pre-existing goals from the audit remain separate from research UI completion.

| Work | Completion requirement | State |
| --- | --- | --- |
| Service-owned account readiness | Instrument/rule/unit identity, actual key permission semantics, complete exposure/reservations, pagination and fee provenance | Open |
| Authenticated observation/settlement | Verify actual venue responses; absence of orders is not completeness, spendability or settlement | Unverified |
| T1 admission and arming | Consume exact operator review, account/rule/cost evidence and installation/session/loss caps atomically | Open |
| Real submit/cancel/reconciliation | Fixed origin, durable first-byte outcomes, no blind retry, partial fills and unknown-order holds across restart | Open |
| Protective exits and capped automation | Qualified venue protection, disjoint quantities, restart/reopening and hard installation/loss ceilings | Open |
| Maker/trade-credit/relay/multi-leg execution | Distinct custody/idempotency/settlement/protection/outage contracts after core execution | Open |
| Installed custody/isolation/STOP | Repeat current-build drills after relevant deployment/policy changes; earlier synthetic receipts remain dated evidence | Existing host evidence; requalification scoped to changes |
| Actual-versus-modeled costs | Independently reconcile measured quantities, fees, depth and latency; separately authorized probe and loss budget before funded testing | Open; funded budget zero |
| Independent final evaluation | Consume-once local registry plus independent custody and a real future evaluation window | Open |
| Physical-host recovery | Restore on a second physical host, explicitly reprovision credentials and retain DISARMED | Blocked: user has no second machine |

No code-only substitute can finish a future observation window or a second-machine
drill. Implementable contracts continue; those acceptance conditions remain explicit.

## Delivery evidence

Record each completed batch, exact validation, compatibility changes and operational
limits in CHANGELOG and the current system status. This plan replaces duplicated
cleanup/finance and audit to-do lists; it does not erase historical source assessments.
