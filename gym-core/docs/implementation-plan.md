# Implementation and acceptance plan

Updated 2026-11-06 (Asia/Tehran). The request to complete all archive-derived work remains open.
Implemented code, passing local tests and operational acceptance are separate.
Nothing in this plan enables funded orders or promotes a strategy.

## Current implementation follow-up

The comprehensive [recorded-data paper campaign](paper-qualification.md) is complete:
1,973 historical attempts across 373 markets, ten strategies and eleven fixed
timeframes; 1,945 completed and 28 explicitly incomplete for unavailable data.
Twelve LONG/SHORT margin replays and four completed prospective 15-minute watches
supplement the campaign. One original startup abort is retained beside its
successful tested-fix retry. All ten strategy repeats matched; postings/equity/
waterfalls were audited. Stale marks, no-trade/warmup cases and short observation
periods prevent promotion or sustained qualification claims.

The campaign also closes three implementation defects: unrelated markets no
longer exhaust experiment quote budgets; equal startup clock readings no longer
abort prospective watches; prospective artifacts work through the shared verified
reader/decision debugger while missing baselines remain unavailable.

All five protected GET resource families now commit matching native observations.
Open-order/history pages retain service-owned page bounds, sanitized orders and
original-body digests through restart, helper, CLI, SQLite snapshot, guarded API
and EN/FA account page. Missing pagination echoes, completeness, absence and
settlement stay unverified. Failed refreshes invalidate the same page identity.

Current regression: **1025 Python passed, five skipped, 39 subtests; 152 native
tests**. Independent reviews found no medium-or-higher issues. The exact current
bundle passed installed ACER review/preparation/revocation, seven R0 denials and
four STOP acknowledgements in 67/11/10/11 ms, then stopped/disabled. Receipt:
`.pi/qualification/20261106T1139159526512`. No account API or order was called.

The following earlier follow-up records remain historical evidence.

Known-order GETs now join balances and fees in the service-owned protected
observation journal. Requested client identity, exact partial-fill totals,
fee currency, runtime/key generation, clocks and committed sequence/hash reach
the helper, CLI, saved SQLite account snapshot, guarded API and EN/FA account
details. Restart preserves distinct order identities. Failed refreshes cannot
reuse that order's prior receipt. Repeated correlations, wrong identities,
inexact amounts and altered stored details are refused. Missing/empty fills,
unknown statuses and all settlement remain explicitly unverified.

Current full regression is 1012 Python passed, five skipped and 39 subtests;
150 native tests, strict checks and Windows release build passed. The new bundle
passed actual current-logon ACER review, seven isolated-worker denials and four
STOP acknowledgements in 10–85 ms, then stopped/disabled. The paper backlog is
caught up through eight replays and four verified empty-window skips; collector
and the existing paper scheduler are running. These are bounded local results;
see [current acceptance receipt](acceptance-status.md) for evidence and limits.

This completes known-order observation delivery, not live admission. The actual
remaining code is service-owned instrument/unit/rule/permission and complete
exposure validation, arming and admission, real submit/cancel/reconciliation,
and protective Exit Guard/capped Autopilot integration. Maker, trade-credit,
relay and multi-leg execution retain their distinct unfinished contracts.
Public margin rules/previews and LONG/SHORT paper replay are implemented;
funded borrowing and margin execution are not. Further vendor adapters require
specified provider contracts rather than fabricated data or credentials.

Separate acceptance work remains prospective sustained data/paper evidence,
real account and measured-cost qualification, independent final-evaluation
custody, and physical-host recovery (the user has no second machine). No
positive exchange loss budget has been supplied. These limits do not turn
unfinished execution code into completed work.

Operational data already uses SQLite; retain the compressed raw audit archive
and its SQL manifests as documented in [storage ownership](storage.md).
Actual OpenRouter authentication and two zero-reported-cost free completions
passed through the isolated native gateway; temporary credentials were cleared.
See the [gateway qualification](../../model-gateway/README.md#verification-and-limits).

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
| AI connections | Dedicated GUI/API and private gateway control process for supported SDK OAuth, DPAPI-stored API keys, connection status, preset sync/import/export and explicit advisory prompts. Actual isolated OpenRouter authentication/free completions, DPAPI storage and rotation passed. No real OAuth sign-in or paid provider completion was performed. |
| Shared CLI/browser workflows | `research_actions.py` owns fixed dispatch. Separate `api/models.py`, `api/research.py`, `ui/models.js` and `ui/research.js` avoid adding these workflows to the observatory monolith. See [architecture and interface gaps](architecture.md). |
| Measurement-aligned arithmetic | Optional numeric measurement clocks preserve old observation hashes. `research derived` resolves two known vintages in one snapshot, with explicit units/freshness/skew and unavailable results. No source authentication, sector model or forecast accuracy is inferred. |
| Point-in-time candle checks | Native crosscheck uses an exclusive receipt/fetch cutoff. Market schema 3 retains immutable revisions from migration onward and selects the last eligible vintage. Previously discarded revisions remain unavailable. |
| GUI report and ticket journal | Saved runs download the existing offline HTML report. Canonical previews can be saved and acknowledged/rejected from the GUI using the native journal and actual server review time. No Executor permission is issued. |
| Descriptive average distance and range oscillator | Shared indicator diagnostics include SMA200, close/SMA distance percentages for 20/50/200 observed bars and the 5/34 Awesome Oscillator from actual high/low ranges. Missing history stays warmup; no new strategy or intrinsic-value claim. |
| Decision-linked chart | Native bounded SVG replay displays up to 150 recorded points through the selected decision, explicit gaps, escaped exact-price labels and keyboard navigation. No chart framework or donor data imported. |
| Causality and warm-up audit | Shared `strategy-audit` action compares full versus truncated native decision traces at selected endpoints and separately varies prehistory. Missing comparisons stay unavailable; matching selected endpoints does not prove all branches unbiased. |
| Saved-return uncertainty | Shared `return-bootstrap` action verifies saved artifacts and computes seeded stationary-block centered-return diagnostics. Real timestamp gaps break block adjacency. Declared assumptions, interval counts, modeled costs and uncorrected strategy selection remain visible; no promotion verdict. |
| Aligned market-return correlations | Shared `return-correlations` action compares actual adjacent closed MID return intervals in one market snapshot. Reports pairwise overlap/missingness, disqualified buckets and stale exclusions; constant series remain unavailable. No price-level filling, diversification advice or statistical-significance claim. |
| Bounded workbench delivery | Authenticated research responses have a 2 MiB UTF-8 delivery cap alongside existing action row/work limits. Oversized outputs are not truncated: the response explicitly says a mutation may have committed and forbids automatic retry. GUI clears old output and asks for saved-state inspection. |
| Durable paper attempt ownership | Scheduler records an attempt before calculation and releases the write lock during replay. Exact-claim interruption fences late publication; crash claims remain visible until explicit recovery. CLI/API/GUI expose claim, start, progress and unknown liveness separately. This does not terminate processes or cancel orders. |
| Windows ciphertext publication | Reproduced and fixed child-file rename failure under strict ancestor sharing (OS error 32). Directory pins permit write sharing while denying delete sharing; ciphertext pins remain stricter. Installed synthetic custody/restart/corruption/recovery now passes with retained history. |
| Hard paper calculation deadlines | Fixed disposable Python processes run comparisons, chronological validation, scheduled ticks/catch-up, experiments, causality/bootstrap, checkpoints and final evaluation. Default deadline 120 seconds; exact-child kill/wait precedes lock release. Timeout/error delivery retains possible commits, forbids automatic retry and never advances a missing job window. This is process supervision, not AppContainer isolation. |
| Paged account inspection | Fixed protected GET contracts and shared sanitized parsers for explicit open-order/history pages (1..1000, 1..100 rows). Raw identity/partial fills remain observations; absent rows, missing pagination echoes and separate-page clocks never establish absence, complete account state or settlement. New helper/service builds are not installed or venue-tested. |
| Durable pending cancellation | Existing native attempt/journal tracks cancellation separately from order lifecycle, fill and settlement. Lost acknowledgements and restart preserve holds; recovered cancellation cannot invent no-byte proof. Cancel acknowledgement does not erase later fills or release reservations. Offline integration is tested; real DELETE transport remains missing. |
| Public news feed | Explicit FED_PRESS fetch uses the official fixed HTTPS RSS URL, no redirects/proxies/credentials, bounded XML and actual immutable receipt clocks. CLI/API/GUI share the implementation. Real retrieval passed; no paid provider, historical knowledge, independent signature or verified interpretation is inferred. |
| Recovery status in GUI | Protected-console backup/restore commands append sanitized successful-operation receipts. Authenticated read-only status drives the EN/FA Backups page. Empty status does not create a database or invent an archive; paths/passphrases are omitted. Current archive availability and second-host recovery remain unverified. |

| Work | Implementation | Verification |
| --- | --- | --- |
| Joint ranked paper allocation | `domain/portfolio.py`, existing `paper-research` command, model `portfolio-sizing` | Shared cash reserve, individual position caps, combined modeled stop-loss cap, aggregate allocation cap, fees/slippage and downward step rounding; 11 cases. It models new entries only, not verified existing holdings or an executable portfolio. |
| Typed numeric claim verification | `services/research_grounding.py`, `research claim-check` | 16 cases for saved-run identity/output digests, allowlisted fields, matched-input arithmetic, explicit rounding, invented profit, private fields, malformed artifacts and selected store. The actual recorded run `385bcd9aa23442dd` matched its −12.53677481 USDT result. Prose, causal claims, forecasts, malicious artifact replacement and feed authenticity are not verified. |
| Portable offline research reports | `services/portable_report.py`, `summary --format json|html --output FILE` | Nine cases, including private-data omission, escaping, malformed inputs and no-overwrite output. Actual recorded-data HTML opened in the browser, with working provenance disclosure, no scripts and no overflow at 390px. It is an English paper summary, not a full replay bundle or localized cockpit replacement. |
| Closed-bar technical diagnostics | domain/indicators.py, services/technical_analysis.py, `technicals` CLI | 15 cases and real recorded-data report `fbf96b7fde2b7681`; null warmup, invalid-quote/gap handling, bounded read snapshot and no-overwrite output. Descriptive only; no new strategy or authority. |
| Multiple technical timeframes | Existing `technical_analysis.py`, repeated `technicals --res` | Ten further cases: one observation snapshot/digest, per-view closed bars and warmup, combined work bounds, invalid selections, unchanged single-view output and real writer between calculations. Recorded-data report `f3f90d2996f1b1f8`. No consensus/confidence or trading rule. |
| Useful custody failure diagnostics | `gym-provision` retains the existing fixed client failure/OS error instead of discarding it | Rust regression distinguishes request failure, timeout and disconnected client. The reviewed helper is now installed and synthetic custody passes; uncertain-commit wording grants no authority. |
| Installed custody and isolation | Reviewed protected binaries, retained journal and synthetic-only continuation | Actual service provision/restart/corruption refusal/recovery passed. Actual ACER child denied all six private targets, four STOP commands acknowledged in 12–17 ms and suspended-process containment took 1,037 ms. Service stopped/disabled. Real venue and funded ledger remain unqualified. |

The new commands use existing dependencies. The original three-tool MCP surface
and research ledger schema are retained; outcome/vintage/final-window records use
a separately versioned protocol database. The protected worker/runtime and
funded boundary were not expanded by these research features.

## Remaining execution and acceptance work

Receipt delivery is now end to end: actual native journal sequence/hash and
service context pass through a versioned header, protected helper, strict Python
parser, saved snapshot, token-guarded API and EN/FA account details. Both consumers
check the raw body digest; exact fee fractions and 64-bit identifiers are
displayed without floating-point conversion. Receipt copies remain unverified
local references, not spendable balances or admission. The current bundle was
published and passed ordinary-user review, seven-target isolation and all four
STOP checks; service cleanup left it stopped/disabled. No private account call
was made. See [account delivery](../../contracts/account-read-v2.md).

The active paper schedule is caught up: four actual replay windows completed,
two independently checked empty windows were recorded as skipped, and its next
window is future. The original retired-version schedule remains paused with
history intact. The public collector was gracefully restarted with current code.

The protected service now captures exact balance/fee receipts from its own
fixed-origin transport, binds key generation/runtime/receive clocks and commits
sanitized data before delivery. Replays, duplicate identities, stale keys,
regressed clocks and malformed money are refused. Decoded JSON credential echoes
are blocked. This implements observation capture only: it does not establish
permissions, spendability, instruments, complete exposure or executable admission.
The helper/CLI/GUI keep their existing read-only contracts; internal native
receipts are not represented as authenticated portfolio holdings. See
[protected account observations](../../executor/docs/account-observations.md).

Real prospective paper run ca730c8a5b186393 completed ten running minutes with
93 qualified observations and two modeled fills. Virtual 1,000 USDT became
995.70570135 USDT (net -4.29429865); postings, equity and the reported cost
waterfall reconciled separately. Assumed fees and absent depth/queue modeling
still prevent actual-cost or sustained strategy qualification. The current
earlier Windows publication attempt was canceled at elevation. The subsequent
current-bundle operator/isolation/STOP qualification passed; authenticated venue
observations and current-build custody corruption/recovery remain unqualified.

The native offline join from prepared review to exact ticket/attempt/reservation
is implemented and replay-checked in one journal event. It rechecks current
review context, shared cash, cross-account quote holds and explicit units.
Revocation and unknown outcomes cannot silently free a hold. This closes the
local journal transaction only; the service exposes no reservation command and
authenticated account/instrument/cost evidence, arming and real money-path
integration remain required.

Unavailable hypothesis revisions now stop automatic retries with an explicit
reason in the scheduler and EN/FA GUI. Backward-clock paper shutdown preserves an
explicit aborted receipt. The old engine-6 job was paused without deleting its
history; a separate engine-8 hypothesis/schedule retains its original strategy
parameters and begins with a new future window. Four confirmed empty historical
windows were recorded as skipped, not replayed or filled with invented data.

The next prerequisite now has native code: administrator-only installation-limit
recording in the protected execution ledger, exact currency/unit-epoch/precision,
OS-derived administrator identity, retained history and stale-update rejection.
The configured operator cannot raise it. CLI and installer wiring are implemented;
installed zero-budget recording/readback passed. Executable admission/arming and
actual money-path limit enforcement remain open. See [installation capital limit](../../executor/docs/installation-ceiling.md).

Protected operator intent recording/revocation now has a separate OS-authenticated
pipe, protected helper, exact bounded Python/Rust wire contract and durable native
journal. The CLI and explicit EN/FA Operate controls use the same adapter; DEMO,
research and MCP cannot invoke this workflow. Receipts carry no funded authority.
Payloads bind the current runtime, limit and key generation and expire within
30 seconds. Ordinary ACER installed-host review/preparation/revocation passed;
atomic consumption by a real order intent remains open. See
[operator review](../../contracts/v1/operator-review-v1.md).

The `prepare` operation now consumes that exact review once for a durable
preparation record, rechecking identity/logon, runtime, key generation, current
limit, expiry and stop mode at service time. The consumed marker and immutable
ticket reference share one committed event; restart/lost acknowledgement cannot
consume it again. Revocation remains available. This does not create a money
reservation or executable order intent. Worker qualification now requires seven
explicit private targets, including the operator pipe; the isolation drill
exposes that pipe only to return refusal. Old six-target results are historical
and do not qualify this build.

Existing-install publication is now implemented with an exact hash-pinned bundle,
protected retained-code backup, reverse-order rollback and an incomplete-update
startup veto. Operator rebinding now grants the review helper and removes the
previous operator's explicit grants. Local filesystem/protocol self-checks pass.
The installed update and ordinary ACER qualification passed at 15:05 UTC on
2026-11-05: synthetic review/preparation/duplicate refusal/inspection/revocation,
actual R0 denial of all seven private targets and four STOP acknowledgements
in 11–84 ms. The service was stopped/disabled and strict installation audit passed.
The helper now uses SCM and connected-pipe identity without requesting access to
the protected process object; administrator hard containment still pins that
process. Earlier failed receipts are retained. No account API/order call occurred.
See
[protected service publication](../../executor/docs/service-publication.md).

| Work | Current state | Concrete completion requirement |
| --- | --- | --- |
| Installed custody/recovery | Passed on this host with synthetic credentials | Protected publication, provision/restart/corruption refusal/recovery passed with retained history. The service is stopped and disabled. Real credentials and future funded-ledger recovery are unqualified. |
| Actual worker isolation | Passed on this host under ACER | Actual no-capability AppContainer child denied custody ciphertext/journal, STOP/T2 pipes, profile canary and SCM access; the positive MCP check returned exactly three read-only tools. Repeat after deployment/policy changes. |
| Independent STOP and hung containment | Passed on this host | Operator commands acknowledged in 12–17 ms under the parked loop; suspended-process containment took 1,037 ms. Normal restart completed, then service stopped/disabled. No funded authority was granted. |
| Service-owned venue permissions/exposure | Protected balance/fee receipt capture and bounded page transport/parsing implemented; actual acceptance open | Install reviewed builds and establish the actual key permission contract, instrument/rule/unit identity, complete locked/external exposure, pagination echoes and manual-order lifecycle. Native receipts retain exact amounts and clocks but confer no spendability or settlement. No actual authenticated request was made. |
| Trusted T1 and real submit/cancel/reconcile | Installed review/preparation/revocation and seven-target denial passed; offline atomic reservation join implemented | Integrate service-owned authenticated account/instrument/rule/cost checks with admission. Add arming, fixed-origin transport, durable first-byte outcomes and unknown-order reconciliation. Exercise offline failures before any separately approved venue probe. |
| Protective stops, Exit Guard and capped Autopilot | Missing integration | Qualify native venue protection, disjoint quantities, restart/reopening and loss/installation caps through the real money path. Existing offline policy outputs remain advisory. |
| Sustained prospective paper evidence | Additional ten-minute session with two modeled fills recorded; sustained qualification open | Run ca730c8a5b186393 captured 93 qualified observations and ended normally with virtual net -4.29429865 USDT under assumed fees. Earlier short/failed sessions remain recorded. Continue prospective evidence with actual clocks, gaps and stale marks; this operational check is not profitability, cost calibration or sustained acceptance. |
| Actual-versus-modeled costs | Open | Independently reconcile measured fills, fees, depth and latency with modeled assumptions. Real orders require a specific approved probe and loss budget; neither is supplied by this broad implementation request. |
| Physical-machine recovery | Blocked: user confirmed no second machine is available | Restore and verify on a separate physical host, explicitly reprovision credentials, retain DISARMED state. Same-machine WSL does not satisfy this gate. |

## Open archive-derived implementation and acceptance

The latest request makes the useful documented integration candidates active work;
the historical assessments' wording that they were only candidates is not a
completion claim. The additions above close only their stated local contracts.
Correction-aware indicator/replay fixtures, resumable verified replay recipes,
saved annotations, linked chart panes, sequence-checked supplied depth,
snapshot-bound registry pagination, persistent paper entry locks and shared GUI
journal/conversion/probe inputs are now implemented and tested. Replay resumes
rebuild a verified prefix and reject changed engine/source/rules; they do not
deserialize executable objects. Protected worker tests now pass on this host.
Real venue, portfolio settlement, vendor feeds and independent-custody
contracts below remain open. Excluded predictive ML and unrelated donor
applications are not silently reinstated. No unavailable operational acceptance
is replaced with a mock or marked complete.

| Capability | Required work before claiming completion |
| --- | --- |
| Semantic analyst/debate roles | Bounded cited role notes, disagreement and exact numeric checks are implemented. Independently authenticated observations and verified prose semantics remain unestablished; numeric matching never certifies them. |
| Outcome reflection | Resolution-time numeric memory and immutable evidence-linked narrative notes are implemented. A model's narrative lesson remains unverified judgment and is never persisted as economic truth. |
| Independent final evaluation | Local consume-once enforcement is implemented. Independent custody/access control, a real prospective future window and external qualification remain open. Repeated historical windows are diagnostics. |
| Indicator-based strategy qualification | ATR/ADX/Keltner/TRIX, EMA slopes and four closed-bar strategy rules are implemented and tested. Real prospective cost/coverage evidence and independent selection accounting remain required before any promotion. No TA-Lib numerical parity is claimed. |
| Portfolio execution and partial exits | Exact supplied-mark return arithmetic, reservation-aware target preview and supplied partial-fill comparison are implemented. Actual holdings/basis, authenticated fee reconciliation and partial settlement remain required for executable targets and tiered exits. |
| Additional clocks/component forms/unit-epoch derived views | Implemented optional confirmation clocks, exact component reconciliation, explicit unit epochs and source/factor-linked conversions. Knowledge includes confirmation/actual receipt; mixed epochs fail without explicit conversion. Old omitted fields preserve hashes; no raw rows are relabeled. Vendor authenticity remains unestablished. |
| New news/fundamental/social/vendor feeds | Fixed official public Federal Reserve RSS adapter and actual receipt-vintage storage are implemented and retrieved successfully. Other provider-specific adapters/contracts, credentials/rights and independent release/revision authentication remain open. Live retrieval never substitutes earlier knowledge. |
| Macro/whale/funding/open-interest diagnostics | Source-specific screening, forecast scoring, aligned ratios/differences and explicit nonoverlapping market-group breadth are implemented. Group classifications remain supplied/unverified. Authenticated transfer context and feeds remain unavailable. Predictive training and forecast generation are outside current scope; vendor scores or Prophet intervals are not measured confidence. |
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
parity for saved native checkpoint replays and bounded registry publication are
now checked. Hard calculation-process deadlines and durable cancel evidence are
implemented. Real order transport/reconciliation and other contracts retain their
separate implementation and acceptance requirements.

## Evidence and authority

Current target verification and the older Rust/gateway evidence are recorded in
[system status](system-status.md). Read-only host receipts are
`.pi/paper-qualification/host-inspection.json` and
`.pi/paper-qualification/custody-ledger-inspection.json`; the old failure receipt
is retained. The actual exported example is
`.pi/reports/paper-385bcd9aa23442dd.html`.

No real account call, paid job, exchange credential replacement, funded order or
push was performed. Isolated free model completions and the earlier protected
local publications have their own dated receipts. Missing implementation above is still
missing code; operational blockers do not convert it into completed work.
