# System status — 2026-11-05

## Reviewed reservations and paper recovery

Native offline admission now commits the exact prepared ticket, attempt and
reservation together in journal tag 13. Replay rechecks the same identities,
current limit, expiry, mode, units and cash constraints. Quote holds share an
installation-wide checked total across accounts. Legacy untyped active holds,
changed base precision/epochs and inconsistent/stale balance anchors are refused.
Revocation cannot erase a hold; unknown outcomes retain it after restart. This
method is not exposed by the service or browser: supplied balances are not
authenticated venue evidence. Real admission, arming, session/loss/exposure caps,
transport/reconciliation and protective exits remain unfinished.

The actual research job had retried an empty historical window 32 times and
targeted unavailable paper engine 6. Four verified empty windows were explicitly
recorded as skipped, with prior failures retained. Catch-up then encountered the
version mismatch; it did not relabel those inputs or silently reuse engine 8.
The scheduler now exposes HYPOTHESIS_VERSION_UNAVAILABLE, stops automatic
retries across restart and requires explicit recovery. EN/FA dashboard and
recovery views show the reason. The old schedule is paused, and a separate
current-engine hypothesis/schedule preserves the strategy parameters with a
new future first window. Receipts:
.pi/paper-qualification/schedule-recovery-20261105T153103760785.json and
.pi/paper-qualification/schedule-renewal-20261105T153646417464.json.
A research database snapshot was retained before recovery.

The public collector was not listening when checked; it was restarted with
50 observed assets on loopback port 8765. A no-data aborted session remains
recorded; another attempt failed during finalization and is not qualification.
Backward-clock regression now produces an explicit saved ABORTED run with
original clock readings rather than losing the report. No earlier missing
prices, elapsed duration or fills were fabricated.

A subsequent real paper run **283fdcf2e906ce0a** ended normally. It observed
56 qualified BTCUSDT quotes from 15:44:03 to 15:48:00 UTC, including two running
minutes after warm-up, zero fills and unchanged virtual 1,000 USDT. Receipt:
.pi/paper-qualification/prospective-20261105T154403968416.json.
It is a short operational check, not sustained coverage, measured execution
costs or profitability. The collector remains running; the native service
remains stopped/disabled.

Full regression: **944 Python passed, five skipped, 39 subtests passed;
140 native tests passed across 37 result groups**. Strict Clippy, Windows release
build, changed-file lint and JavaScript syntax checks passed. Both dependency
audits reported no known vulnerabilities; the editable local Python project
was omitted by pip-audit. The new native journal build was not installed;
the last installed ordinary-operator qualification below covers its own bundle.
Current browser rendering and second-machine recovery were not checked.

## Existing-install publication and operator qualification

Added a guarded complete-bundle updater that requires the existing service
stopped/disabled, checks exact source/staged hashes, preserves prior code and
records rollback outcomes without touching custody or journals. A flushed
publication marker precedes file replacement. The new executor refuses startup
with code 1019 if that marker is present, before creating listeners. Failure
attempts reverse-order code rollback and never starts the service. Parent ACL
mutation checks were added to the installation audit; migration preflight labels
its relaxed treatment of absent new helpers explicitly.

Operator rebinding now includes the review helper, invalidates the old logon
before helper changes and removes the previous operator's explicit grants. The
new ordinary-operator qualification script exercises an exact synthetic review,
consume-once preparation, inspection/revocation, all seven worker-denial targets
and four STOP acknowledgements, using a recent protected runtime manifest and
an exact zero capital budget. It has no exchange/account API call.

Local self-tests pass strict manifest validation, pinned file access, actual
temporary-file replacement/rollback, exact u64 frames and correlation refusal.
Native workspace regression passes 132 tests; strict Clippy and Windows release
build pass. The new test scripts are syntax checked. Full Python regression
passed 939 tests, five skips and 39 subtests. Both dependency audits reported no
known vulnerabilities; pip-audit omitted the local editable project. No
dependency was added.

Installed publication and the actual ordinary ACER operator test passed at
15:05 UTC. The retained receipt directory is
`.pi/qualification/20261105T1505191135205`. Review/prepare/duplicate refusal/
inspection/revocation passed; the actual R0 worker was denied all seven private
targets; four STOP acknowledgements took 84/12/11/11 ms. The administrator
stopped and disabled the service and the strict installation audit passed. The
helper's unnecessary process-object access was removed after the ordinary-token
failure: fixed SCM identity and connected pipe server identity are checked on
both sides of the exchange. Administrator hard containment still pins the process.
Custody was preserved, existing journal history was retained, and the test added
only zero-budget metadata and clearly synthetic review events. It made no account
API or order call. Earlier canceled/failed attempts remain recorded.
Admission/reservations, arming, real order transport/reconciliation, protective
exits and independent-machine recovery retain their separate implementation or
acceptance requirements. Current browser rendering was not checked.
See [publication and qualification](../../executor/docs/service-publication.md).

## Consume-once preparation and qualification follow-up

The protected review workflow now supports `prepare`: the service rechecks the
actual principal/logon, runtime, key generation, current installation limit,
expiry and mode, then commits the consumed marker and immutable reviewed-ticket
reference in one event. Restart, duplicate requests and lost receipts cannot
prepare it twice. It remains revocable at the returned sequence. The legacy
simulation intent APIs cannot reuse its identity. No executable order or money
reservation is created, and no account/venue request occurs.

The same operation reaches the fixed helper, CLI, token/origin-protected API and
EN/FA Operate panel. Worker publication and host preflight now require seven
negative targets, including the operator pipe. Isolation-drill startup keeps
that listener available for denial probes but refuses all review operations;
credential recovery does not create it. The new publication has not been
installed, so old six-target host results do not qualify this change.

Full local regression: **935 Python passed, five skipped, 39 subtests passed**;
**131 native tests passed**. Strict Clippy, formatting, Windows release build,
new-code style checks and repository-wide Python correctness lint pass. All three
changed PowerShell scripts parse; the host-evidence and manifest-policy self-tests
pass. Fresh Python and offline npm dependency audits report no known advisories.
No dependency was added. The observatory was reloaded with the new API; the
protected service remains stopped/disabled and is not updated. Live browser
rendering remains unverified. The section below retains the preceding receipt.

A new actual public-data BTCUSDT paper session `d263cdeb46eecd2f` ran from
12:50:01 to 12:54:00 UTC on 2026-11-05, including warmup and two running minutes.
It ended normally with 66 qualified observations, zero fills and unchanged
virtual 1,000 USDT. It used declared example fees and has no matched baseline.
Receipt: `.pi/paper-qualification/prospective-20261105T125001396769.json`.
This adds operational evidence, not sustained collection or strategy qualification.

Still open: executable admission and atomic money reservations, authenticated
account/rule/cost facts, arming, real transport/reconciliation, protective exits,
new installed-host tests, sustained paper qualification and independent-host
recovery. These are not silently marked complete by the preparation feature.

## Protected operator intent

The native service now has a separate OS-user/logon-authenticated operator pipe
for exact intent recording, inspection and revocation. A fixed SCM-pinned helper,
bounded Python/Rust frames and the existing protected execution journal retain
payloads, principal/logon, runtime/limit/key-generation bindings and actual clocks.
Stale limits, wrong units, duplicate identities, invalid spending envelopes and
expiry outside the next 30 seconds are refused. STOP remains independent.

The shared CLI adapter and explicit EN/FA Operate panel require no credential
entry. The API requires the local token, exact POST origin, bounded input and a
single active request; DEMO disables it. No research or MCP dispatch exposes this
workflow. Lost receipts remain uncertain and never trigger automatic retry.
No order is submitted and no trading capability is issued. Historical records
can be expired or invalidated; their presence does not authorize execution.

Validation: 934 Python tests passed, five platform skips and 39 subtests; 129
native tests passed across 37 result groups. Strict workspace Clippy, formatting,
Windows release build, new-module style checks and repository-wide Python
correctness lint passed. All three changed PowerShell files parse. The npm
offline audit and fresh installed-Python dependency audit found no known
vulnerabilities; the editable local package is outside the advisory database.
No dependency changed.

The observatory was not listening when reload was attempted. It was started with
its existing public-data configuration; startup output and the loopback listener
were checked. Live browser inspection remains blocked by the browser URL policy;
Node/UI and local test-server checks are not visual verification. The protected
executor was read back STOPPED/DISABLED and was not started or updated.

Installed-host qualification of this binary set, worker denial of the new pipe,
atomic approval consumption, actual account/instrument/rule/cost verification,
arming, money-limit enforcement, real transport/reconciliation and protective
exits remain open. No real credential, capital limit or loss budget was configured.
See [operator review contract](../../contracts/v1/operator-review-v1.md).

## Installation-limit prerequisite

Commit `b867fef` contains the preceding supervision/account/cancellation/news/
backup work. The subsequent native implementation adds protected administrator
limit recording and `gym-ceiling get|set`: exact currency, unit epoch and precision,
retained T2 identity/history, stale-update rejection and operator-account increase
refusal. It uses the existing protected pipe and native order journal; the
credential journal is retained. CLI/installer and EN/FA Safety guidance are wired.
Eight new Rust tests and the three static UI contracts pass. Live browser
inspection was blocked by the browser URL policy and is not counted as verified.
The npm offline audit reports zero vulnerabilities. A fresh Python dependency
audit was attempted but its PyPI request timed out; no dependency changed.
The final Rust workspace/all-target suite and strict Clippy also pass. The
Windows service was read back as STOPPED with DISABLED startup; no new native
binary was installed. The changed PowerShell files pass syntax parsing.
Protected installation, real cap enforcement, T1 approvals/arming, venue order
transport/reconciliation and protective exits remain open. No real capital limit,
credential or funded order was configured. See
[installation capital limit](../../executor/docs/installation-ceiling.md).

## Current supervision, account inspection and recovery update

Added hard process supervision for heavy research calculations, bounded protected
open-order/history page contracts and shared sanitized parsers, durable pending
cancellation evidence, an explicit real public RSS adapter and connected backup/
restore receipt status. These reuse existing domain/journal owners, add no
dependencies and do not enable funded execution.

Full Python run: **925 passed, five skipped, 39 subtests passed** in 83.52s.
After the final supervised validation-error delivery refinement, **78 targeted
tests passed**. Rust workspace/all-target tests, strict Clippy, formatting and
release binaries passed; the added cancel-under-failed-entry-gates regression
also passed with its seven-case integration suite. Ruff and JavaScript syntax
passed. npm offline audit found zero vulnerabilities; pip-audit found none in
installed dependencies and could not audit unpublished editable gym-core.

The final account/backup follow-up passed **49 tests**, including four added
reader-route cases: invalid pagination never reaches either transport, privileged
helper arguments remain fixed, query extensions are refused and page-identity
conflicts remain uncertain. A damaged receipt database returns a bounded,
no-store UNREADABLE response. Rust workspace/all-target tests and strict Clippy
also passed again after the final cancellation regression. These checks did not
contact a private account or install new protected binaries.

Actual prospective paper run `e27a80643af51ff4` observed BTCUSDT from
2026-11-05 00:38:42 to 00:42:00 UTC, including warmup and a two-minute running
window. It retained 73 qualified observations and zero fills, with virtual equity
unchanged at 1,000 USDT. This is a short operational receipt, not strategy or
sustained-collection qualification. Receipt:
`.pi/paper-qualification/prospective-session.json`.

Real fixed-origin Federal Reserve RSS retrieval passed both directly and through
the supervised browser action. A live headline first received at 01:08:34 UTC
remains unavailable at its older publication time. The store records origin
PUBLIC_FEED_HTTP, actual knowledge time and unverified content/rights; it does
not infer sentiment or trading confidence. Separate-store raw-fetch receipt:
`.pi/feed-verification/receipt.json`; GUI: `.pi/public-news-20261105.png`.

The Backups page now reads authenticated native operation receipts in English
and Persian. Its actual NO_RECEIPTS state is shown without inserting synthetic
history or claiming current archive availability. Screenshot:
`.pi/backup-status-20261105.png`. Successful backup/restore operations record
sanitized metadata only, with concurrent/immutable-history tests and explicit
receipt-write failure reporting. Passphrases remain in the protected console.

The new native page/codec release builds are reviewable locally but were not
installed over the previously qualified protected binary set. That service
remains stopped/disabled. No real credentials, authenticated account call,
funded order, paid model completion, push or deployment was performed. T1/real
submit/cancel/reconcile, native venue protection, other provider-specific feeds
and independent-host/data-custody work remain open in the plan. The following
sections retain earlier receipts, not claims about these new builds.

## Current replay, observation and installed-host receipt

Implemented verified replay checkpoints/resume, immutable decision annotations,
linked equity/indicator panes, fixed-snapshot registry pages, persistent paper
entry locks, shared GUI/CLI journal/conversion/probe actions, supplied sequenced
depth validation, confirmation/component/unit-epoch observation contracts and
market-group breadth. Native collector writes now retain candle revisions from
schema 3 onward. Prior discarded vintages are unavailable. These additions use
existing owners and dependencies; supplied inputs remain unauthenticated.

Full Python suite: **907 passed, five skipped, 39 subtests passed** in 72.78s.
Ruff, JavaScript syntax and all three chart tests passed. Rust workspace tests,
Clippy with warnings denied and the release worker build passed after the native
launch fix. PowerShell parse/security self-tests passed. Offline npm audit found
zero vulnerabilities; pip-audit found none in installed packages, excluding the
unpublished editable application. No dependencies were added.

The installed Windows drill now passed under the actual ordinary ACER logon:

* Synthetic DPAPI provision, restart, corruption refusal and missing-ciphertext
  recovery preserved the retained journal/history.
* Actual no-capability AppContainer Python child denied all six existing targets:
  custody ciphertext, custody journal, STOP pipe, T2 pipe, profile canary and SCM.
  Its positive MCP response contained exactly the three read-only research tools.
* Operator status/pause/exit-only/halt acknowledged in **17/17/12/12 ms** with the
  main loop parked and startup DISARMED.
* Retained-handle containment of the suspended exact service process completed
  in **1,037 ms**. Normal restart completed; final audit confirmed stopped and
  disabled with protected code/data ACLs.

Two real defects were fixed during this qualification: parent-directory ACL
validation now uses intrinsic file attributes rather than provider-only metadata;
the worker environment contains only OS-resolved LOCALAPPDATA, required for
Windows AppContainer launch, instead of an unusable empty block. Caller variables,
keys, PYTHONPATH and DLL search paths are not inherited. These measured results
apply to this installation/token/policy, not arbitrary future deployments.

Receipts: `.pi/paper-qualification/custody-continuation.json`,
`launcher-publication.json`, `operator-20261105.json`, and `containment.json`.
Browser verification of actual saved run `9e989c89cc5882a8` confirmed linked
panes, exact stored values, keyboard selection and preserved open controls:
`.pi/replay-workspace-20261105.png`. Synthetic notes were not added to live runs.
The browser created checkpoint
`412916facc5e5182145ce5e16544551c95630a64f363134d38cd1cd4532b03a9`
from that recorded run; resume rebuilt 19 quotes and continued 466 with
EXACT_MATCH against saved and independent full replay. Registry paging returned
a fixed sequence ceiling and bounded events from the actual local journal.

Real venue transport/permissions/protection, authenticated feed adapters,
independent final-data custody, prospective paper evidence and actual measured
execution costs remain open. No real credentials, account API request, paid model
completion, funded order, push or deployment occurred. Separate physical-host
recovery cannot be tested because no second machine is available. The sections
below are historical receipts, superseded where the current receipt differs.

## Archive implementation and service publication update

Follow-up: aligned market-return correlations and bounded workbench delivery are
also implemented through shared native CLI/API/GUI actions. **889 Python tests
passed, five skipped, 39 subtests passed** in 79.66s; the final API correlation
case also passed with the workspace suite. Ruff and JavaScript syntax pass.
Recorded BTCUSDT/ETHUSDT report `01216786e5a83ad1` compares 57 identical adjacent
intervals per pair and explicitly excludes a disqualified bucket/gap in each
series. Its correlation is descriptive, not a diversification or confidence
claim. GUI proof: `.pi/return-correlations-20261105.png`. Responses exceeding
2 MiB fail without economic truncation and warn that mutations may have committed;
a real native-ledger regression verifies this uncertain-delivery behavior.

Added native decision-linked SVG replay with keyboard access, bounded
full/prefix and prehistory strategy diagnostics, and seeded saved-return block
diagnostics. Scheduled jobs now commit exact attempt claims before calculation;
explicit interruption fences late publication without holding a database write
lock during replay. Crash/publication failures remain visibly RUNNING with
unknown liveness until explicit recovery. These are paper-only capabilities;
the complete archive request remains open in [the plan](implementation-plan.md).

Verification: **880 Python tests passed, five skipped, 39 subtests passed** in
79.18s. Rust workspace tests, Clippy with warnings denied, formatting, release
build, Ruff, JavaScript syntax and two chart tests passed. Offline npm audit
reported zero vulnerabilities; pip-audit reported none for installed packages
and could not audit the unpublished editable application. No dependencies added.

Actual browser replay of saved run `9e989c89cc5882a8` supports next/previous,
marker selection and arrow-key navigation. Recorded-data causality report
`eecb263dcab5918a` matched 19 and 39 prefix decisions while reporting recursive
prehistory sensitivity. Saved-return report `ed555f927421f1cf` uses 56 intervals,
excludes one three-minute gap and reports two segments. Neither result qualifies
profitability or an unbiased strategy. Screenshot: `.pi/replay-chart-20261105.png`.
The local observatory was restarted; the resulting collection interruption is
not backfilled. The held missing-data job was not silently skipped.

The protected diagnostic service reached RUNNING_DISARMED, then was stopped and
disabled. Synthetic provisioning remained unacknowledged with service code 1011
(ciphertext publication). Empty inspection-created WAL/SHM sidecars required
owner repair to LocalService; existing ledger/history and ACLs were preserved.
An ordinary Windows regression subsequently reproduced the actual child-rename
sharing violation (OS 32). Ancestor directory pins now permit write sharing but
deny delete sharing, while ciphertext pins retain write denial. The regression
failed before this fix and passes after it. Stage diagnostics distinguish safe
startup/publication failures without disclosing credentials.

The next administrator prompt was canceled. Therefore the final local binaries
were **not installed or qualified** through custody/restart/corruption, actual
worker isolation or STOP/hung-process drills. The service remains stopped and
disabled; no real credential, account request or funded order was used. Second
physical-machine recovery remains unavailable as previously confirmed.

A fresh whole-record archive audit verifies **85 ZIP hashes**, all present in
Downloads/archive with none of those reviewed ZIPs loose in Downloads. Receipt:
`.pi/archive-verification.json`. Older sections below are historical snapshots.

## Current implementation update

The subsequent six-source review adds descriptive SMA200, close-to-average
distances and the range-based Awesome Oscillator to the existing native indicator
diagnostics. Full Python validation: **829 passed, five skipped, 39 subtests
passed** in 60.52s; Ruff passes. The 454-entry/30-family assessment and 61 strategy
references are in [trading source assessment](trading-source-assessment.md).
No source app/dependency, sample data, credentials or placeholder program was
installed; no new trading strategy, funded permission, commit or archive move.
The actual recorded BTCUSDT report `f2e08aa0a0bcfbf3` reads 2,208 observations,
178 closed bars and a final uninterrupted segment of 43 bars. Its 20-bar distance
is approximately +0.07243934 percent and Awesome Oscillator is -16.75886765 in
the quoted price unit; SMA50/200 remain WARMUP. CLI and the restarted GUI produce
the same report ID. Receipt: `.pi/reports/btcusdt-average-distance.json`;
GUI proof: `.pi/technical-diagnostics.png`. No synthetic records were imported.

### Previous resumed implementation receipt

The resumed pass adds measurement-aware supplied vintages, snapshot-consistent
two-series ratios/differences, receipt/fetch-cutoff candle checks, a GUI download
for the existing portable HTML report and canonical offline ticket review controls.
Python suite: **827 passed, five skipped, 39 subtests passed** in 67.23s. Ruff and
JavaScript syntax checks pass. The gateway and protected executor were not changed
or requalified in this pass. The prior receipts below remain historical evidence.

The local observatory was restarted under ACER with the reviewed project command.
An actual recorded-data candle check through the GUI reports POINT_IN_TIME and
MISSING_VENUE where the stored venue candle was unavailable at the cutoff; it
does not fetch a replacement. The preview GUI exposes its journal save control;
synthetic test previews were not saved to the live journal. Durable writes are
tested through the API against temporary journals.

The existing scheduled paper job is currently held on its 2026-11-04 03:13 UTC
window. A read-only replay confirmed `PaperDataUnavailable`: no qualified BTCUSDT
quotes in 02:13–03:13 UTC. Its retries and failure alerts are real missing-data
evidence. No backfill, successful-result substitution or silent clock advance was
applied. Sustained collection and explicit missed-window handling remain open.

Three new source ZIPs were inventoried and selectively reviewed without executing
them; see [assessment](research-source-assessment.md). No further commit/archive
move, credentials, paid model call or funded order was performed.

### Previous implementation receipt

The shared registry now has ten strategies. New indicator features, deterministic
numeric roles, resolution-time outcomes, future consume-once evaluations,
user-supplied observation vintages/screening, cash-flow return arithmetic and
forecast scoring are implemented. The CLI and advanced browser workbench share
`research_actions.py`; model controls have dedicated API/UI modules and one
private stdio gateway process. The **AI connections** page supports actual SDK
sign-in interactions and Windows DPAPI-stored API keys. No credentials were
entered, no live sign-in completed, and no paid provider request was made.

Current Python suite: **815 passed, five skipped, 39 subtests passed** in 64.44s.
Ruff passes. Gateway full suite: **29 passed, one privilege skip**, including
the actual stdio host roundtrip and stored-key SDK requests to a local server.
The suite uses synthetic credentials/local servers; Windows tests exercised
real DPAPI and ACL protection as ACER outside the restricted test sandbox.
Both npm audit and pip-audit reported no known vulnerabilities in this pass;
pip-audit excludes the editable application, which is covered by source tests.

One preceding repeated gateway run hit `attempts_exhausted` in the local
key-rotation fixture. Its isolated test and the subsequent complete suite passed
without changing retry limits. The intermittent local transport failure was not
reproduced or assigned a proven root cause; the runtime rejected that request.

Actual running browser checks show the ten-strategy catalog, advanced workbench
and AI settings in English/Persian. The new GUI numeric review reproduced saved
run `385bcd9aa23442dd`: −12.53677481 USDT, sampled drawdown 1.25367748 percent,
and the same cash-benchmark excess. Its three roles match stored arithmetic;
semantic grounding remains false. Screenshot: `.pi/ai-connections-persian.png`.
Expanded indicator receipt `e57c33ed39099448` reads the retained 2,208 BTCUSDT
observations: 178 closed bars and 43 final contiguous bars. ATR/ADX/Keltner are
available; EMA50/200, SMA50 and TRIX remain warmup. Receipt:
`.pi/reports/btcusdt-indicators-20261104.json`. No missing history was synthesized.
The observatory was restarted to load routes, briefly interrupting collection.
No gap was filled. The protected executor was not restarted or changed.
The unused 3 MB `repo_core_source.txt` generated dump was removed after verifying
there were no active references. The eight reviewed ZIPs were moved into
Downloads/archive with identical before/after hashes and no overwrites.

The broader plan is still open. [Architecture and interface coverage](architecture.md)
lists remaining terminal-only inputs. [Implementation plan](implementation-plan.md)
separates unimplemented integrations from operational gates. No installed custody,
funded venue transport/protection, independent final evidence or physical-machine
recovery is certified. Rust/installed-host and full desktop/mobile browser checks
below are prior receipts, not reruns for this slice.

## Earlier review snapshot

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

- **762 Python passed, five skipped, 39 subtests passed** in the full suite
  (78.54 seconds), including 25 technical-report cases, ten multi-window validation/CLI cases and ten
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

## Latest eight-source assessment

All 570 files from the latest eight Downloads archives are inventoried and
assigned to 52 documented family decisions; no members are unclassified and
all rehashed contents match. All 21 standalone Python files parse. The nested
desk package is a duplicate and the bundled Gemini database remains opaque.
The repeated-resolution technical CLI now shares a single observation snapshot
across up to four views, with independent warmup and no signal synthesis.
Ten additional tests, full Python and Ruff pass. Actual recorded-data report
f3f90d2996f1b1f8 binds all views to the same 2,208 observations.
No UI/API, Rust, gateway, Windows, dependencies or live processes changed.
Their runtime checks and network dependency audits were not repeated.
See [source assessment](source-assessment.md) for every decision and open item.
## Research workspace follow-up — 2026-11-04

The eight selected research modules now have native services and shared CLI/API
dispatch. Coverage/recovery and saved-decision replay have dedicated controls;
the other detailed offline inputs are in the advanced research workbench.
[Contracts and limits](research-workspace.md) document historical unknowns,
conditional cash, append-only attempt retention and explicit optional AI sending.

Browser checks on actual saved BTCUSDT observations produced coverage report
`03a603df7e7a72af` (178 observed and two degraded minute buckets) before the
subsequent addition of carried quote ages. Registered experiment
`7d5b93d2f501339d22e97fe32d0dda4dae2c5cab6bc5c42e826fc7d74a3698c4`
retained completed runs `8e59c9c1f3ca471b` and `4677f805201f710b`: modeled net
−16.38027536 and −19.63777658 USDT respectively. The latter used the disclosed
higher fee, 2s latency and two-minute outage assumptions. These initial GUI
receipts use trace version 7; current version 8 deduplicates rule snapshots.
They are historical diagnostics, not strategy promotion or prospective evidence.

The archive coverage check verified 53 documented reviewed ZIPs under
`C:\Users\ACER\Downloads\archive`; no documented reviewed ZIP remained loose
in Downloads. `.pi/archive-verification.json` retains the audit. Existing ZIPs,
extracted folders, protected custody state and unrelated working changes were
preserved. No paid AI call, provider sign-in, funded order, protected service
update, push or deployment was performed in this follow-up.

Final implementation verification: **856 Python tests passed, five skipped,
39 subtests passed**; Ruff and JavaScript syntax checks passed. Browser checks
confirmed the final compact replay view, previous/next navigation and English/
Persian labels. Repeating the recorded-data experiment through trace version 8
produced runs `b721c3626ce1683e` and `9e989c89cc5882a8` with the same modeled net
results as above. Evidence packet
`d214ea79e9989b0dde0b871efd5fc0d1c28dc9c33b1e6795a428943d1c1deda8`
was prepared from the first run; `paid_request_sent` remained false. Visual
receipt: `.pi/research-workspace.png`. Actual paid completion and physical-host
qualification were not exercised.
## Scope decision — 2026-11-04

Predictive ML/RL training, neural forecasting, automated model search and
trained-model order execution are removed from current delivery commitments.
They are not completed features or release blockers. Working research tools,
supplied-forecast scoring and optional AI provider connections remain in scope.
The [implementation plan](implementation-plan.md) records the conditions for any
separately approved future ML research. No runtime feature or dependency was
removed by this plan update.
