# Changelog

## Unreleased

Hardening from the 2026-11-09 technical due-diligence review (finding IDs in brackets).

- Seeded property tests for every exec-ipc frame codec: mutated frames never panic a decoder, and every
  accepted frame re-encodes byte-for-byte [E-9].
- Shared fill-timestamp profile (`contracts/v1/fixtures/fill-timestamps.json`) enforced identically by the
  executor and gym-core; v2 operator-review golden frames checked from Rust and Python [E-8, A-4].
- Executor account-observation freshness is checked per resource, so a fees read is no longer refused because
  a balances read was in flight; stale reads of the same resource are still refused [E-6, partial].
- Weekly mutation testing now also covers the cash book, portfolio policy and margin math [E-10].
- `gymctl backup-research`, `research-restore-drill`, `restore-research` and a nightly schedule script: encrypted
  snapshots of every research store and the raw archive, with an authenticated restore that never overwrites;
  `doctor` reports the age of the last snapshot [R-5, OD-4 groundwork].
- Holdout custody for the long-history study: every look at a test window is recorded in an append-only
  ledger; a second look is withheld unless `--rescore-holdout`, and then the deflated Sharpe counts the
  configurations tried across every look [R-1].
- Research workers log their deadline use (`research_worker` in events.jsonl) and warn above 75% of it [P-2].
- UI: the refresh banner names the failing sources and the last complete refresh, and polling backs off to
  30 s while the service keeps failing; covered by the real-browser smoke test [U-8, P-3].
- UI: a ratchet test stops inline Persian copy from growing outside the shared vocabulary [U-7, partial].
- Conformance vectors for the ticket quote envelope (`contracts/v1/fixtures/ticket-envelopes.json`): Rust and
  Python accept and refuse the same 16 tickets at the same rounding boundary [A-1 step 1, partial].
- Model gateway: optional `policy.allowedHosts` pins custom endpoints to approved hosts [S-7].
- Executor-ledger head anchors in the backup folder: each verified backup records (sequence, head hash); a
  truncated or rebuilt ledger is refused before older bundles are rotated, and the restore drill checks the same [R-3].
- Simulator: seeded property tests over 4,000 random market orders (cash conservation, no overspend, precision,
  never better than the touch, no fill before latency, non-fills move nothing); `market_order` split into sizing,
  modeled-cost, price-guard and settlement helpers, complexity 40 to under 20 and enforced in CI [E-1].
- Signed executor updates: `gymctl release-keygen|sign|verify` (ECDSA P-256); the elevated update script verifies
  natively against a pinned key and keeps the manifest, and helpers are re-hashed against it before launch [S-6, S-11].
- Research-assistant runs carry provenance outside the run identity (model, prompt and reply hashes, bounded reply
  text, rationale), shown on the run page [L-3 partial, L-5].
- Model gateway: a first-class `local` connection for loopback model servers, keyless and pinned to 127.0.0.1,
  ::1 or localhost, without the test-only HTTP switch [L-1].
- Docs: disaster-recovery runbook; ML scope amended to paper-only and gated; DESIGN.md chart text corrected
  [O-1, M-1, U-3].
- Evidence index: every `.pi/` receipt the docs cite has a SHA-256 in the tracked `evidence/INDEX.json`,
  with a verifier and a docs test [G-6].
- Architecture decision records: authority split and fail-closed money path (accepted), reservation model and
  bounded startup replay (proposed) [G-5, A-5, A-6].
- Health alerts: `gymctl doctor --quick --notify [--webhook https://...]` plus a 30-minute schedule script;
  a Windows toast (and optional webhook) only when the set of failing checks changes, and on recovery. `doctor`
  now reports collector feed freshness [O-3].
- UI copy review sheet: `scripts/ui_copy_extract.py` collects about 1,090 English/Persian pairs from every UI
  file into one CSV for a native-speaker review, and lists the lines it cannot pair [U-7].
- `gymctl drift SYMBOL`: population-stability index of spread and 1-minute returns, recent window against a
  reference window, with conventional STABLE / MODERATE / SHIFTED bands (4.10 drift monitor).
- `gymctl recover-segments [--apply]`: registers crash-tail raw segments with their real hash and readable
  sequence range plus a SEGMENT_RECOVERED event; files are never changed and recently written ones are skipped.
  Applied to the live store on 2026-11-10: 33 crash tails, about 4.66 million readable records [R-4 follow-up].
- Proposed reservation model `ActiveHoldBook` (ADR 0003) implemented and property-tested against a simulated venue;
  not wired, `ReservationBook` stays authoritative. The current book's dust-credit wedge is recorded in a test [A-6].
- Executor startup waits up to two minutes for the journal, reporting START_PENDING progress, instead of failing
  after five seconds; replay cost measured at 0.31 s per 200k rows in release builds [A-5].
- Executor account reads no longer hold the vault lock across the venue request; mode and key generation are
  re-checked before recording [A-3].
- `gymctl arm-preflight`: read-only READY / BLOCKED checklist for a future funded probe (owner policy with loss cap
  and kill rules, executor running, STOP gate, credentials, fresh account observation, reconciliation, feed,
  backup, no failing check); it never arms and READY is not permission [OD-2 groundwork].
- `gymctl assistant-eval [--preset P]`: fixed 30-case prompt set, a no-model baseline sampling the catalogue,
  and a verdict with thresholds set in advance (JSON validity, valid proposals, repeats of earlier tests) [L-6].
- Gateway dependency audit recorded (no telemetry or unexpected outbound path; heavy SDKs are hard dependencies);
  ADR 0005 stages a shared execution kernel [S-5, A-1 step 2].
- First shared execution-kernel rule: `exec-core` `kernel::sellable` in exact integer arithmetic and the simulator's
  `sellable_quantity` agree on `contracts/v1/fixtures/sizing.json`; `kernel::walk` and `kernel::settle` agree with
  `_walk` and `_settle` on `fills.json` [A-1 step 2, ADR 0005 stage 1-2].
- Arming policy: three validated options (cost-probe, pilot, extended) in `contracts/arm-policy/`, a per-order cap
  and daily order limit in the schema, `gymctl arm-policy list|show|set`, and `docs/arming-policy.md`; cost-probe
  installed as the active policy (records limits only; nothing is armed) [OD-2].
- `ReservationBook::with_credit_tolerance`: an explicit, default-zero allowance for venue dust credits on settled
  release; a shortfall is never tolerated and replay is unchanged at zero [A-6].
- Rust kernel bridge (PyO3, `executor/exec-kernel-py`): with `GYM_RUST_KERNEL=1` the simulator runs sellable, walk
  and price-guard rules in exec-core; the whole suite passes and 4,000 random orders are byte-identical to the Python
  path where venue precision is known; a CI job builds the wheel and runs the suite on it [A-1 step 2, ADR 0005 stage 3].
- Arm record and kill rules (`exec_core::arming`), verified-available rule across both vault journals
  (`exec_core::available`), tested privileged-fault supervision; ADR 0006; review-v2 and prepared reservation
  documented as test-only [OD-2, OD-5, A-6].
- Complexity: `research_action` (101) and `make_app` (88) become handler registries, `weights` (38) splits into stages,
  `_portfolio` 85 -> 65; a CI ratchet fails on any new function above 20 or any listed hotspot growing [E-1].
- One research action table (`CLI_ACTIONS`, `CLI_ONLY_ACTIONS`, `gymctl actions`) with a test that every action is a CLI
  choice and has a browser form or a stated reason; `diagnostic`, `technicals`, `spreads` and `trade-flow` were
  browser-only and are now CLI choices. Read-only operator timeline (`gymctl timeline`, `/api/timeline`) [U-4].
- Model artifact registry (`services/model_artifacts.py`): content-addressed JSON artifacts, registration only after
  the fit is a `model-fit` trial (so fits raise the deflated-Sharpe N), schema and cost digests bound into run
  identity, ABSTAIN on missing, corrupt, expired or incompatible artifacts [M-2 step 1].
- `tasks.ps1` mirrors the CI jobs (rust, python, node, browser, sbom, kernel); CycloneDX SBOMs for Python, Node and
  Rust (`scripts/cargo_sbom.py`) built in a CI job; `docs/onboarding.md` with the schema-migration rule; the public
  read set recorded as a threat-model decision in SECURITY.md [G-5, S-8].
- Secrets: the executor wipes the decoded copy of every venue reply after the key-echo check; the Python key store
  writes a protected single-user DACL before any ciphertext and refuses a key file owned by another account [S-12].
- Adding a browser sign-in (OAuth) model connection now requires accepting a bilingual provider-terms warning; API
  keys stay the default [S-2].
- Collector event-loop lag sampler (p50, p99, max over a rolling window) in `/api/health`, so the real host decides
  whether trade writes need a writer thread [E-4].
- Optional `cost_declaration` on `final-register` (trades per month, round-trip cost, expected gross edge): an
  arithmetically dead strategy, or a cost below two venue fees, is refused before any window is spent; a declared
  gate is bound into the evaluation identity [report 4.10 TS-3].
- Romano-Wolf stepdown (`domain/multiple_testing.py`): family-wise adjusted p-values for several candidates against
  one benchmark with a shared circular block bootstrap [report 4.10].
- Advisory typed-decision client (`gymctl research entailment-check`): loopback-only, pinned model hash, redirects and
  malformed replies degrade to null, never sets semantic grounding; `docs/model-pilots.md` [L-8, L-6, L-7].
- Design-token drift test (font sizes, radii, light and dark colours against DESIGN.md) [U-3]; written 90-day
  checkpoint with a stop rule in PRODUCT.md [roadmap].
- `gymctl paper-sweep`: every strategy x resolution x market in parallel, sharing parsed quotes, rule versions,
  baselines and data digests, one compact SQLite row per run, resumable, every configuration a recorded trial;
  rows match full `paper()` runs exactly. Replay hot paths (`instant`, bar ordering, idle scans, `BarSpec.step`)
  skip redundant work with identical results; about 5x faster per run.
- CSP drops `style-src 'unsafe-inline'`: chart markers are positioned through the DOM style API and the waterfall grid
  sizes itself in CSS; a test refuses any style attribute in the UI [S-13].
- Collector task gains a 5-minute watchdog trigger (past the 999-restart cap) and an opt-in `-RunWhileSignedOut` (S4U);
  backup tasks wake the laptop; `doctor` reports the longest collection gap in 24 h, so sleeps and sign-outs alert on
  return [O-6].
- Gateway credentials off Windows are sealed with AES-256-GCM under a user-held passphrase, or refused unless
  plaintext is explicitly accepted [S-1].
- Provisioned SID files: owner and DACL verified before parsing (only SYSTEM, Administrators or TrustedInstaller may own
  or write them), with the rule tested on any OS and a Windows test refusing a user-created file; rebinding runbook
  `docs/operator-rebinding.md` [S-9].
- Venue reads go through `read_outside_lock` (vault lock only to copy the key out and record the result); a
  stalled-venue test shows other privileged work and the T0 stop gate proceed within 200 ms while the read stalls [A-3].
- Full-universe collector load test (373 markets changing every tick, trades included): loop-lag p99 6 ms, tick p99
  under 150 ms on the laptop; bounds asserted in CI; no writer thread needed [E-4].
- Research deadline scales with the stored quotes a request replays (0.4 ms each, 2.5x headroom, 120..600 s); a
  preregistered window the archive volume cannot last through is refused at registration [P-2].
- Host-instance recovery rehearsed in CI: the clean-VM job verifies a fresh instance reports DISARMED and records the
  rebuild time in the job summary; acceptance rows updated [O-5].
- First learned component: advisory feed-anomaly classifier (logistic, pure Python, JSON artifact, fits counted as
  trials, ABSTAIN on a bad artifact); held-out AUROC 0.995 against 0.959 for the rule baseline on real data [M-2 step 2].
- Per-signal attribution: closed trades grouped by entry and exit decision reasons in the performance report and a
  bilingual run-view table [U-2].
- All Persian copy now lives in the vocabulary (about 390 pairs moved from research, margin, portfolio, models and
  others; the ratchet allows none elsewhere); every rendered timestamp carries its ISO instant as a tooltip; the time
  zone (Tehran or UTC) is a stored preference with a sidebar toggle [U-7].
- Design tokens collapsed: six type steps (11, 12, 14, 17, 21, 30 px), four radii, spacing on a 4 px grid, mirrored
  in DESIGN.md and enforced by tests; navigation grouped into five workspaces; compact zone toggle [U-3].
- Bias harness (`gym.services.bias_harness`, `tests/test_bias_harness.py`): every registered strategy is
  replayed with truncation at two cuts, with every observation after each cut repriced (decisions up to the cut
  must stay byte-identical), and with a longer prehistory (positions must agree once settled). Three seeded
  faults prove it bites: a strategy that precomputes from the whole stored history, a data layer that publishes
  quotes a minute early, and a signal that depends on the replay start [R-2, M-2 step 1].
- API: a non-ASCII `X-Gym-Token` is refused with 403 instead of a 500 [E-3].
- Wallex candles are parsed as `Decimal` straight from the JSON text; non-finite values are rejected [E-2].
- Instrument-spec close and successor insert run in one savepoint [E-5].
- Raw segments get a manifest row when they open; `verify-segments` and the daily sweep report unclosed and
  unregistered files [R-4].
- Model gateway is started with an allowlisted environment [S-10].
- DPAPI blobs carry purpose-bound entropy (legacy blobs migrate on first read); linked key paths are refused [S-1, S-12].
- Executor: `forbid(unsafe_code)` in exec-core, exec-store and exec-ipc; saturating `reserved()`; release builds
  keep overflow checks; SID files resolve through the Program Files known folder [S-3, E-7, S-9].
- `gymctl doctor`: one read-only check of market.db, raw segments, journals, free space, backup receipts and key
  expiry, with a JSON receipt (`--json`) and exit 1 on any failure [O-4].
- Model usage ledger enforces daily and monthly call caps (200 and 2,000 by default) and optional cost caps,
  checked before a request reaches the gateway; set them with the `usage_limits` control [L-4].
- Research assistant extracts the first complete JSON array, retries once with a repair prompt, and reports
  `INVALID_MODEL_REPLY` instead of silently testing nothing [L-2].
- UI: first visit follows the system colour scheme; Windows forced-colours mode keeps borders and focus visible [U-6].
- UI: rule disable and preset load use a labelled bilingual dialog (Cancel focused, focus returned); covered by
  the real-browser smoke test [U-9].
- Launcher requires a real TradingGYM `/api/ready` answer and warns when market data is blocked [O-3].
- CI actions pinned by commit SHA, Rust pinned to 1.96.0, Dependabot and CODEOWNERS added [S-4].
- Docs: root README with the current state, strategy count corrected to sixteen and guarded by a test, excluded
  strategy families recorded, OAuth marked opt-in, public reads documented [U-1, G-4, S-2, S-8].
