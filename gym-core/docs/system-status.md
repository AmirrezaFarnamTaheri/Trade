# Current system status

Updated 8 November 2026 (Asia/Tehran). Historical receipts remain in Git history
and the local evidence folders. This page describes the current delivery.

## Implemented and checked

- Public Wallex catalogue/feed collection, exact SQL observations, rule-aware bars,
  vintages, quality/readiness and transactional publication watermarks.
- Separated browser view owners preserve existing EN/FA contracts and hashed assets.
- Sixteen registry strategies, saved paper runs, chronological comparisons,
  experiments, replay/debugging, screening, recovery, notes and robustness tools.
- Compound revision 3 keeps indicator history through wide spreads, records actual
  simulated positions and refuses fee-net holdings below known exit minimums.
- Portfolio revision 5 closes all markets before later quotes/fills, binds resolved
  assets/reference snapshots/depth/limit prints/rules/specifications to its ID,
  and rejects alias markets that would double-count one holding. TMN portfolios
  carry point-in-time USDT-equivalent curve marks and explicit FX freshness. It uses one
  independent read snapshot. Old saved study engines and records are retained.
  Within that snapshot, rule evidence is fingerprinted per recorded knowledge
  vintage, not per quote. Valuation and staleness scan held markets; the next
  close is cached instead of scanning the full universe on every update.
- Equal/inverse-volatility/risk-parity targets, correlation caps, target clocks,
  optional rebalancing, cash floors and drawdown/Tehran daily-loss latches use the
  native shared cash book. Sell signals take precedence over rebalance buys;
  reservations and limits are checked again at actual partial settlement.
- Shared default-off regime and fixed/profit/ATR/time exits preserve default
  strategy identities. Actual fill cost/time, dust and maker/taker fee assumptions
  remain explicit. Rebuilt single-market and portfolio checkpoints verify saved
  history, pending orders, reservations, targets and latches without deserializing
  mutable state. This is replay reconstruction, not runtime restoration.
- Default-off `entry_risk_bps` reuses native exact portfolio sizing against an
  explicit fixed stop. Shared held exposure and pending reservations reduce the
  remaining budget; market and maker partials recheck capacity and current venue
  minimum/precision before filling. Unknown limits abstain. This is a modeled
  closed-bar stop budget, not a guaranteed loss ceiling or venue protection.
- Capped fractional Kelly diagnostics require an evaluated preregistered native
  run, at least 30 closed simple non-overlapping positions, current valuation and
  observed losses. Seeded moving-block uncertainty precedes the supplied fraction
  multiplier and cap. Scaled/recycled/partial cashflow structures are explicitly
  unsupported; no allocation is changed automatically.
- Regular strategy-trial experiments have verified scorecards, parameter/cost
  heatmaps and user-selected saved historical/prospective path overlays. Every
  registered attempt remains visible, including failures, missing artifacts and
  unready or stale results. Walk-forward folds retain their separate native report.
- Store-scoped campaign counts and a bounded verified readiness/trade sample are
  visible in Schedules. Instrumented schedulers and campaign launchers hold an OS
  ownership lock and recent heartbeat. Abrupt termination releases the lock even
  when a saved receipt says RUNNING. Frozen/uninstrumented campaign processes stay
  UNKNOWN; process presence does not establish progress or fresh data.
  Native workers use private temporary directories for Windows
  SQL sorting without inheriting user secrets.
- Shared-cash replay is available in the private research API and EN/FA Workbench.
  Native quote/trade counts, worker time, saved-file size and response size are bounded.
  Saved reads verify fingerprints and recompute aggregate performance.
- Resting limits now cap fills to observed capacity after queue depletion, charge
  maker fees per partial fill and retain exact working remainders until expiry.
  New limit identities carry queue-capacity/2; old artifacts remain unchanged.
- RSI/MACD/TRIX/Keltner periods and thresholds have validated registry schemas.
  Nondefault configurations use version 2; default identities remain version 1.
- Expanding walk-forward selection freezes candidates and chronology in the
  existing experiment registry. Every training/test slot, failure and selection
  is retained; the final cutoff is not read. Historical diagnostics do not grant
  independent final-evaluation status.
  Test windows that never warm up or never trade are retained as NOT_ACTIVE,
  with separate WARMUP_NOT_COMPLETED/NO_TRADES reasons; they cannot make the
  overall report EVALUATED. Robustness groups accept recorded entry_regime
  from regime-gated strategies as well as the original compound regime field.
- Historical TMN runs fingerprint causal FX curves through causal-fx-curve/1.
  Saved-run details show conversion/freshness without bridging missing factors;
  native USDT default identities remain unchanged.
- Execution calibration exposes bounded, dated public-feed samples and exact
  negative-clock counts. Stale, insufficient, mixed-market, DEMO and clock-
  disagreement inputs cannot silently become execution defaults. Real fee,
  slippage and order-latency measurements remain unverified.
- Robustness diagnostics verify comparable saved records before CSCV rank
  recombination, recorded-regime grouping, stationary return blocks or additive
  FIFO P/L reshuffling. Gaps, insufficient samples, identical candidates and ties
  remain explicit; no method grants a promotion verdict.
- Unsupported compound limit orders and working remainders now fail explicitly;
  the simulator does not silently reinterpret the requested execution model.
- Portable JSON/HTML cards retain allowlisted optional execution/sizing assumptions.
- AI connections support scoped Windows-protected keys/OAuth and explicit advisory
  requests. Advisory output grants no order authority.
- Margin rules/previews and LONG/SHORT paper replay are implemented; funded
  borrowing, margin orders and real protection are not.
- Native custody, operator review/preparation, journal and STOP foundations have
  dated installed-host synthetic evidence. Real execution remains unavailable.

## Current runtime

Collector and research scheduler are installed/running as separate limited-user
Windows tasks, with restart-on-failure and IgnoreNew instance policy. Both use
D:/GitHub/Trade/data. Their windowless installed Python entry points avoid
console-close interruption. Collector configuration explicitly selects --assets all;
no three-market watch override is used. The maintained launcher is
scripts/windows/Start-Workspace.ps1.

The actual HTTP server listens on 127.0.0.1:8765 and exposes all 14 strategies,
the portfolio replay capability, default-off shared exit/regime controls and current
content-hashed view assets. At 19:07 UTC on 7 November, REST and WebSocket
connections still failed. Freshness remained BLOCKED; retained observations were
not relabeled as new current-process receipts.
The collector recovered observation selection from 469 retained catalogue rows,
without changing their source clocks or claiming fresh catalogue confirmation.
An independent public HTTPS request also failed with a reset.

Windows tasks launch the installed Python module directly. A real isolated
scheduled-task test confirmed that stopping the task terminates its collector
child. A second isolated synthetic probe on 7 November confirmed the windowless
collector has no visible window and that task stop removes its listener and child
(.pi/qualification/workspace-20261107T184509Z/receipt.json). The current collector
and scheduler use that launch path; task state does not establish market-feed
health or useful paper results.

The private browser link is in the current user's
%LOCALAPPDATA%/TradingGYM/workspace-link.txt. The protected executor remains
Stopped/Disabled. No authenticated venue call, funded order or paid model call
was performed during this delivery.

## Current validation

- Python: 1,318 passed, four skipped and 39 subtests passed, including catalogue
  outage recovery, supervised workflow integration, robustness diagnostics and
  the separated UI contracts. Pinned default USDT run identities remain unchanged.
- A paired synthetic 500-market/60,000-observation replay took 67.51 seconds with
  the prior implementation and 13.06 seconds with revision 5. Cash balances,
  equity marks and per-market orders matched exactly. A separate native worker
  replay at 500 markets/200,000 observations completed and saved a verified DEMO
  artifact in 79.80 seconds, inside the unchanged 120-second deadline.
  Measurements are hardware/data-specific capacity evidence, not profit evidence
  or a promise that every strategy/window fits the deadline. Local receipts are
  retained under .pi/benchmarks/portfolio-throughput.
- The restarted live workspace exposed all 14 strategies. Its private API returned
  an ALIVE scheduler owner with a current heartbeat and served an actual saved
  experiment scorecard retaining eight attempts: two completed, four incomplete,
  two pending. Those pending receipts were not relabeled as completed. At this
  check all 373 selected markets lacked a current qualified quote; process
  presence did not change market readiness.
- Pure sampled-drawdown arithmetic lives in the domain layer; verified artifact
  loading does not import service orchestration. Architecture guards passed.
- Retained native baseline: all 152 Rust workspace tests passed with normal
  parallel execution. Native binaries were not changed or requalified in this batch.
- Current Python lint passed. Retained Rust formatting and strict Clippy checks
  remain dated native evidence.
- Existing gateway audit baseline: 29 passed and one platform-related skip.
- Python/Node dependency audits found no known vulnerabilities in audited
  dependencies; the editable application is outside the advisory database.
- Real-browser visual/accessibility checks and installed protected-service drills
  were not repeated for these Python/startup/fixture changes.

## Paper evidence

The frozen compound study completed all 373 eligible market batches: 1,492 cases
registered, 1,380 completed, 112 no-data cases, 44 fills, 17 negative cases and no
positive cases. It retains 208 stale ending marks and 364 completed cases that
never reached readiness. Source: .pi/compound-study/20261106T205324Z/outcomes.json.
The separate 149,573-case historical campaign is still incomplete.

The native full-universe portfolio study 4a68967cf68deb77 used both quote books:
187 TMN pairs and 186 USDT pairs, with 204 fills across 148 traded markets.
TMN net was -2,759,177.6444 TMN (derived -10.1641 USDT equivalent); the separate
USDT net was -6.589184499 USDT. Both ended with STALE_VALUATION. They are distinct
cash books and are not summed. Each definition/result and its exact engine remain
in data/live/studies; native portfolios remain in data/live/runs/portfolios.

The expanded study 1621a5c99fd63eb8 covered fourteen strategies, both quote books,
and defaults versus shared controls over the same 30-minute recorded window:
56 cases, 54 completed, two explicit relative-reference identity failures,
1,130 fills, 16 negative trading cases and no positive cases. Thirty-five completed
cases never reached readiness; shared regime variants need more than this window
for warmup. Three endings were stale. This is a diagnostic, not held-out selection,
matched prospective qualification or evidence that strict gates improve returns.
Its failed attempts and frozen engine are retained.

The matched two-hour Donchian study f47f6b73062be1c7 completed four cases over
all 373 observed markets, keeping TMN and USDT cash separate. Default TMN net was
-2,538,310.7513 TMN with 118 fills; shared-control TMN net was -1,745,746.0825 TMN
with 92 fills and 134 ready markets. Default USDT net was -7.463499955 USDT with
87 fills and a stale ending; shared-control USDT net was -2.078938386 USDT with
51 fills and 88 ready markets. Other endings were current. All four cases lost
value. One historical comparison cannot establish a reliable improvement or
profitability, and observation gaps still prevented readiness in many markets.

A separate disposable-process rebuild of the 187-market Donchian portfolio
34d52bf013d84b33 verified a 500-observation prefix and returned EXACT_MATCH against
the saved full result. This does not establish runtime recovery.

At the 19:07 UTC API check, all 373 observed product rows had UNKNOWN margin
availability without a newly selected public receipt. The saved journal had
10,131 definitions, 82,589 registered attempts, 51,997 completed and 211 unreported
attempts. Its newest 25-result verified sample contained 14 ready and 13 traded
runs. These counts retain repeated attempts and do not certify completion of the
separate 149,573-case campaign or a living campaign process.

These are historical modeled observations, not evidence of sustained profitability,
measured venue execution costs or qualification of the new portfolio options.
Future prospective sessions require adequate per-market coverage; failed network
connections and missing current-process observations remain visible.

## Open work

The [implementation plan](implementation-plan.md) lists remaining implementation
and acceptance work. Operational journals and saved paper evidence retain their
existing owners.
See [acceptance gates](acceptance-status.md) for protected account/execution,
evaluation, cost calibration and recovery requirements.

## November 11 follow-up verification

Allocation input windows now reject invalid bounds before journal writes; repeated
symbols are deduplicated, and both fill directions apply recorded venue sizing
rules. The focused allocation/specification checks passed 85 tests.

Model drafts and responses survive language changes without retaining credential
fields or allowing duplicate in-flight submissions. Portfolio and margin receipts
refresh selected-zone timestamps without repeating replay. The UI checks passed
28 Node tests and 11 Python wrappers. Edge headless smoke passed 80 mobile
route/language/theme/width combinations, including market-selection targets and
visible keyboard focus. This is bounded synthetic browser evidence, not a complete
accessibility or provider qualification.

The fresh locked Python and production Node dependency audits reported no known
vulnerabilities. Native/service and hosted checks remain separately dated evidence.
