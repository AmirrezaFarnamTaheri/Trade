# Current system status

Updated 7 November 2026 (Asia/Tehran). Historical receipts remain in Git history
and the local evidence folders. This page describes the current delivery.

## Implemented and checked

- Public Wallex catalogue/feed collection, exact SQL observations, rule-aware bars,
  vintages, quality/readiness and transactional publication watermarks.
- Separated browser view owners preserve existing EN/FA contracts and hashed assets.
- Twelve registry strategies, saved paper runs, chronological comparisons,
  experiments, replay/debugging, screening, recovery, notes and robustness tools.
- Compound revision 3 keeps indicator history through wide spreads, records actual
  simulated positions and refuses fee-net holdings below known exit minimums.
- Portfolio revision 3 closes all markets before later quotes/fills, binds resolved
  assets/reference snapshots/depth/limit prints/rules/specifications to its ID,
  and rejects alias markets that would double-count one holding. TMN portfolios
  carry point-in-time USDT-equivalent curve marks and explicit FX freshness. It uses one
  independent read snapshot. Old saved study engines and records are retained.
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
D:/GitHub/Trade/data. Collector configuration explicitly selects --assets all;
no three-market watch override is used. The maintained launcher is
scripts/windows/Start-Workspace.ps1.

The actual HTTP server listens on 127.0.0.1:8765 and exposes all 12 strategies,
the portfolio replay capability and current content-hashed view assets. At 14:21
UTC on 7 November, both REST and WebSocket requests failed at the network
connection; all 373 selected pairs had MISSING current-process observations.
The collector recovered observation selection from 469 retained catalogue rows,
without changing their source clocks or claiming fresh catalogue confirmation.
An independent public HTTPS request also failed with a reset.

Windows tasks launch the installed Python module directly. A real isolated
scheduled-task test confirmed that stopping the task terminates its collector
child. The current collector and scheduler use that launch path; task state does
not establish market-feed health or useful paper results.

The private browser link is in the current user's
%LOCALAPPDATA%/TradingGYM/workspace-link.txt. The protected executor remains
Stopped/Disabled. No authenticated venue call, funded order or paid model call
was performed during this delivery.

## Current validation

- Python: 1,236 passed, four skipped and 39 subtests passed, including catalogue
  outage recovery, supervised workflow integration, robustness diagnostics and
  the separated UI contracts. Pinned default USDT run identities remain unchanged.
- Pure sampled-drawdown arithmetic lives in the domain layer; verified artifact
  loading does not import service orchestration. Architecture guards passed.
- Rust: all 152 workspace tests passed with normal parallel execution; the three
  shared-clock directory helpers now use atomic per-process suffixes.
- Python lint, Rust formatting and strict Clippy passed.
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

These are historical modeled observations, not evidence of sustained profitability,
measured venue execution costs or qualification of the new portfolio options.
Future prospective sessions require adequate per-market coverage; failed network
connections and missing current-process observations remain visible.

## Open work

The [implementation plan](implementation-plan.md) lists remaining implementation
and acceptance work. Operational journals and saved paper evidence retain their
existing owners.
See [acceptance gates](acceptance-status.md) for protected account/execution,
independent evaluation, cost calibration and physical-machine recovery requirements.
