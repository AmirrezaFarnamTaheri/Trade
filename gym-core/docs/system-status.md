# System status — 2026-11-04

The review spans production modules, callers, tests, workflow, UI and local
operational state. Current membership/hash/symbol/direct-test-import inventory:
`.pi/donor-integration/module-inventory.json`, 113 production files: 66 Python,
25 Rust, four gateway modules, 14 Windows scripts, browser JS/HTML/CSS and CI.
Inventory membership is not a line-by-line correctness certificate.

## Coverage and boundaries

| Area | Reviewed connections and outcome |
| --- | --- |
| Public adapters, collector, raw segments and market DB | Fixed-origin public reads, body limits, independent housekeeping/reseed, per-side clocks, quality flags, point-in-time metadata and separate demo store retained. Outages remain visible; no missing observation is synthesized. |
| Instruments, decimals, units, bars, sessions and rules | Exact amounts, Tehran closure/vintage logic, availability clocks and unit-discontinuity entry freeze retained. Session bars have no fictitious fixed purge period. |
| Strategy registry and paper market/accounting/session | Six bounded/versioned strategies, independent paper accounts, modeled costs, received-asset fees, nonfills, warmup, reference availability and immutable identities retained. Closed-price population-deviation bands add `bollinger-reversion`; no leverage, shorts or protected stops were added. No profitability claim is inferred. |
| Comparisons, temporal validation, diagnostics and reports | Matched read snapshots/saved reports reach the UI. Temporal validation is repeated historical diagnostics, not sealed independent evidence. Drawdown includes initial cash/end estimate and its sampling limitation. Offline sizing bounds risk, position value and reserved cash with fees/slippage/downward step rounding. `trade-economics` discloses two-outcome reward/risk and break-even assumptions; unknown inference costs stay unavailable and cost-dominated targets have no feasible probability. Neither diagnostic verifies a stop or authorizes orders. |
| Research ledger, scheduler, MCP and worker | Publication precedes clock advancement; retries retain failure evidence. Pause/resume preserves due times. MCP retains three fixed read-only tools; result metadata binds input and exact output fingerprints, without asserting source authenticity or analyst grounding. Installed AppContainer isolation remains unqualified after custody-stage failure. |
| Account parsers, service bridge, external/offline journals | Bounded helper output, exact normalization and private-read token checks retained. Account observations are not spendable executor cash; terminal/imported order status is not settlement. No real account query was performed here. |
| Venue facts, tickets, conversion, probe ladder, shadow and exit/reopening | Evidence-only/advisory outputs remain explicit. Caller assertions cannot grant runtime authority. Synthetic offline examples stay labeled. Real funded transport/protection remains missing integration. |
| Rust authority, lifecycle, permits and reservations | Tier policy is not an authenticated capability. Durable first-byte/unknown-order/settlement rules retained; seeded fake-venue and recovery tests pass. Fake execution was not wired into the service as real execution. |
| Rust event store and IPC | FULL-synchronous economic journal, single writer, hash chain, bounded/correlated frames and separate authentication retained. A chain hash alone does not prove external origin. |
| Windows SCM, identity, custody, pipes and helpers | Installed image-path quoting and PowerShell alias collision corrected. Actual audit confirms disabled/stopped service, code/data ACLs and restricted service SID. Synthetic provisioning was not acknowledged; further stages were not passed. |
| Model gateway/config/state/credential helper | Disabled advisory mode, fixed protocols, key/cooldown behavior, SDK failures, Windows DPAPI and refresh serialization tested. Unknown prices stay unknown. Live entitlements/paid completions and financial grounding are unqualified. |
| API and UI | Loopback Host and per-run write/private-read tokens retained. All nine destinations load; exact values/EN/FA have regression checks. Script/style URLs use content hashes so updates cannot retain stale cached assets. Real summary download matches its digest and original saved output. Browser checks at 1440px and 390px, including Persian RTL, show no page overflow; tables retain their own scrolling. |
| Backup/manifest/restore/update | Authenticated encryption, no-overwrite restore, ledger verification and recovery-only semantics retained. Admission policies are advisory. Same-host WSL portability does not prove hardware-loss recovery. |
| Packaging/dependencies/tests/CI | Python lock matches manifest; 22 installed packages are compatible. Locked/offline Rust and gateway checks run. npm audit reports zero known vulnerabilities. No new dependency, push, deployment or credential mutation. Hosted CI was not rerun. |

## Verification

- **752 Python passed, five skipped, 39 subtests passed** in the full suite
  (50.02 seconds), including 15 technical-report cases, ten multi-window validation/CLI cases and ten
  follow-up API/error-path cases, plus the earlier 12 trade-flow, 18 band/economics
  and 25 sizing/provenance cases.
  Ruff also passed. In an earlier pass, actual stdio calls verified
  all three local research tools.
  Five skips require Windows symlink privilege. Focused UI/Windows contract
  checks also pass after final UI error-path changes.
- The earlier end-to-end pass refreshed the full Python/Rust/gateway suites,
  all nine browser routes, desktop/mobile RTL layout, public health/private-read
  boundaries, the new comparison/export flow and actual service state.
- Locked/offline Rust all-target workspace tests passed (104 tests, 31 suites),
  strict Clippy/formatting passed; all 14 Windows scripts parsed.
- Gateway: **23 passed, one symlink-privilege skip** as ordinary ACER, including
  Windows DPAPI/ACL checks against local test servers. Sandbox ACL writes were
  refused; protections were not relaxed to make tests pass.
- Browser: all nine routes without a connection-error banner; real band
  comparison `6446637092710b27`, translated parameter controls, and downloaded
  `paper-b5c48a637ca78c85.json` matched the saved output/checksum. At 390px
  Persian RTL and 1440px English there was no page overflow.
- Dependency locks did not change. The preceding npm, RustSec and PyPI/pip-audit
  receipts each reported zero known vulnerabilities; those network audits were
  not repeated in this pass. They are database snapshots, not proof that no
  vulnerability exists.
- Static inventory covers preceding source groups (581 and 330 files), the
  preceding four archives' 620 files, latest five archives' 659 files and native
  113 production files.
  Latest standalone Python parsing passed for all 22 files; the preceding
  four-archive group had 83 passing files. The tutorial has
  28 notebook code cells; one f-string cell is incompatible with Python 3.11.
  The older TradzQAI DQNN indentation issue remains recorded. No source runtime
  or weights were loaded. Native scan hits for fake execution are explicit
  DEMO/offline/test facilities; no source fallback was wired into observed
  markets or funded execution. Inventory and tests are not a line-by-line or
  installed-host qualification certificate.
- Earlier `trade-flow` reports read the existing market store without migrations,
  use event and receipt cutoffs, preserve exact units and disclose unknown
  direction/empty data. The real CLI processed 89 recorded BTCUSDT trades in
  the 2026-11-03 17:13–20:13 UTC window. The preceding follow-up changed Python/API/UI,
  but no Rust, gateway, Windows, dependency or authority configuration; their
  runtime checks were not rerun.
- New CLI `validate --folds 1..5` repeats the existing 70/30 diagnostic across
  disjoint windows in one read snapshot, resetting cash/state per account.
  Stale/abstaining outcomes remain incomplete, and missing selection data
  rejects the request. The actual recorded-data run `94ff958194e89855` saved
  nine referenced runs; later windows lost 1.66016392, 6.10882287 and 12.53677481
  virtual USDT on separate 1,000-USDT starts. Research and `/api/validate` now
  expose the same 1..5 window choice. The actual browser reproduced that exact
  validation identity and all three rows in English and Persian. Three UI
  runtime tests passed, including incomplete-state rendering and input-change
  invalidation. Unexpected replay errors propagate; only typed missing market
  data becomes `UNAVAILABLE`. Screenshot: `.pi/ui-verification/validation-windows.png`.

The foreground collector and scheduler stopped when the tool session changed,
without an application traceback. They were restarted as ordinary ACER processes
outside the temporary tool process tree; no autostart/service was installed for
them. This interruption remains a gap in prospective collection, not continuous
paper evidence.

## Remaining material work

1. Diagnose the synthetic provisioning failure without replacing uncertain
   custody history. Finish custody/recovery, actual worker denial, independent
   STOP and hung-process containment. Service remains disabled/stopped.
2. Implement/qualify trusted Wallex approval, submit, cancel, unknown-order
   reconciliation and protective execution. Actual account permissions,
   pagination/lifecycle evidence, budget and exact approved probe precede orders.
3. Collect sustained prospective paper sessions with gaps disclosed; calibrate
   modeled depth/latency/fees through separately authorized real observations.
   Existing short negative windows do not establish profitability.
4. Demonstrate another-physical-machine recovery with credential reprovisioning.
5. Extend typed analyst grounding, independent final evaluation, portfolios or
   RL only with their required data/authority/evaluation contracts.

See [capabilities and design sources](capabilities.md) and
[acceptance status](acceptance-status.md). No statement here grants capital or
asserts all original master-plan jobs are complete.

## Deferred-work implementation follow-up

Joint ranked paper-entry sizing, typed numeric run-claim checks and script-free
portable HTML summaries are now available through the existing CLI. Thirty-six
new Python cases cover their limits, exact arithmetic, privacy and malformed
artifact paths. The complete suite above includes those cases; Ruff passed.
The recorded run `385bcd9aa23442dd` passed the real CLI claim check for
−12.53677481 USDT and produced the browser-checked portable report. At 390px,
the expanded provenance view had no horizontal page overflow and zero scripts.
No API, UI, MCP tool, research schema or live process was changed in this pass.

The provisioning helper now reports the fixed client/OS failure, deadline or
disconnection while retaining uncertain-commit semantics. Independent Rust
review ran check, strict Clippy and tests (105 passed, 35 suites); formatting
passed. This diagnostic is source/build evidence, not an installed custody fix.

Administrator-only read inspection confirmed the service stopped/disabled,
an intact zero-event ledger and no ciphertext generation. It did not start the
service, read secret contents, alter ACLs or replace custody history. The user
confirmed that no second physical machine is available. The overall request
remains open; exact implemented/open/blocked work is in
[implementation plan](implementation-plan.md).

## Latest five-source review

OpenTrade, Pamela, Stock-Market, AutoHedge and OpenProphet were statically
inventoried and selected implementation families reviewed. Their applications,
models, wallets and broker calls were not run. Native closed-bar SMA/RSI/MACD
diagnostics now reach the read-only `technicals` CLI, with explicit warmup,
invalid-quote exclusions and gap resets. No strategy, API, UI or authority
surface changed. Recorded BTCUSDT report `fbf96b7fde2b7681` contains 178 closed
bars and 43 final contiguous bars; SMA50 correctly remains unavailable.
The 15 new cases and full Python suite passed; Ruff passed. Rust, gateway,
Windows, browser and network-audit checks were not repeated for this addition;
no collector or scheduler restart was performed. See [capabilities](capabilities.md).
