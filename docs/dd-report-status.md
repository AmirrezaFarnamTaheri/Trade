# Due-diligence report (2026-11-09): disposition of every finding

Status as of 2026-11-11, branch chain `hardening/dd-quick-wins` -> `dd-medium-term` -> `dd-conformance` ->
`dd-alerts` -> `dd-remaining` -> `dd-arming` -> `dd-final`. **Done** means implemented with tests; **Decided**
means the owner or an ADR settled it; **Deferred** and **Blocked** say why. Details are in `CHANGELOG.md`.

## Architecture

| ID | Status | Where |
|---|---|---|
| A-1 | Partial | Shared sizing/depth/guard/settlement vectors and PyO3 rules exist; locked optional source installation now works. Simulator settlement uses the shared fee rule. Contextual sizing, modeled-impact resizing and default activation remain open: exact native sizing is not interchangeable with historical Decimal intermediate rounding. Boundary regressions preserve the current simulator; ADR 0005 records the remaining version contract. |
| A-2 | Decided | OD-1: one venue only. Freshness alerting (`doctor --notify`, `collector_feed`) carries the weight. |
| A-3 | Done, unverified on host | `begin_account_read`/`finish_account_read`: credential copied out under the lock, venue I/O outside it. Needs the installed service identity to exercise. |
| A-4 | Done | v2 golden fixture, `contracts/v2/`. |
| A-5 | Done at measured scale | Actual journal startup now verifies and returns history in one pass. Isolated debug open/replay of 200,000 300-byte rows improved from 4.159 s to 2.369 s, retaining the strict 20 s test bound and all integrity checks. Full Rust tests, including doctests, passed. No checkpoint was added; larger live histories and release-profile timing remain unqualified. |
| A-6 | Done, not wired | `ActiveHoldBook` (`holds.rs`), explicit default-zero dust tolerance in `ReservationBook`, review-v2 and prepared reservation documented as test-only (`executor/README.md`, ADR 0003, 0006). |

## Engineering

| ID | Status | Where |
|---|---|---|
| E-1 | Ratchet implemented | `scripts/complexity_ratchet.py` and `complexity-baseline.json` retain 17 named hotspots above 20, with a maximum of 30; listed functions may only shrink and new hotspots fail. The research dispatcher no longer carries unreachable sentinel fallbacks; all 83 actions remain registered. |
| E-2 | Done | `parse_udf` parses Decimal. |
| E-3 | Done | `token_matches`, 403 on non-ASCII. |
| E-4 | Measurement implemented; stall diagnosis open | Full-frame, actual API and rotation tests preserve every observation; a 200.2 MiB rotation took 208 ms. A 30-second live stack profile caught no long stall. Rolling live lag has still exceeded its warning bound, so neither a writer rewrite nor resolution of the historical pauses is claimed. |
| E-5 | Done | Instrument-spec SAVEPOINT. |
| E-6 | Done | Per-resource freshness; `verified_available` orders by venue sequence. |
| E-7 | Done | Saturating `reserved()`, release `overflow-checks`. |
| E-8 | Done | `fill-timestamps.json` shared fixture. |
| E-9 | Done | `codec_properties.rs`. |
| E-10 | Scoped local qualification; broader assessment open | The expanded five-file weekly job now fails visibly. All seven actionable survivors from the historical 24/971 assessment have individually verified regression oracles. After rejecting the timing-suspicious run, one fresh complete 49-mutant critical cohort under unchanged timing rules recorded 48 killed and only the proved-equivalent Decimal quantum-coefficient survivor. The exact-fingerprint baseline requires complete results and rejects new survivors. Hosted execution and full five-file qualification remain open. |

## Security

| ID | Status | Where |
|---|---|---|
| S-1 | Done | DPAPI purpose entropy with legacy migration; link refusal. |
| S-2 | Done | Gateway README default; UI opt-in dialog quoting the terms (`models.js`). |
| S-3 | Done | `#![forbid(unsafe_code)]` in exec-core, exec-store, exec-ipc. |
| S-4 | Done | SHA-pinned actions, Rust 1.96.0, Dependabot, CODEOWNERS. |
| S-5 | Done (audit) | Recorded in the gateway README; replacing the SDK deferred (low value, high churn). |
| S-6 | Done | ECDSA P-256 signed manifest, `-Signature` in the update script. |
| S-7 | Done | `policy.allowedHosts`. |
| S-8 | Done | Decision in `SECURITY.md`; `test_api_contract.py` enumerates every route. |
| S-9 | Done | Known-folder path in `main.rs`. |
| S-10 | Done | Gateway environment allowlist. |
| S-11 | Done | Helpers re-hashed against the kept manifest before launch. |
| S-12 | Done | Decoded venue replies wiped; Python key store protected DACL and owner check. |
| S-13 | Done | Browser CSP uses `style-src 'self'` without `unsafe-inline`; `tests/test_ui.py` asserts the policy. |

## Reliability, performance, operations

| ID | Status | Where |
|---|---|---|
| R-1 | Done | `holdout_ledger.py`, `--rescore-holdout`. |
| R-2 | Done | `services/bias_harness.py`. |
| R-3 | Local implementation | `ledger_anchors.py` exists; independent remote custody is not established by a local anchor or a same-account cloud upload. |
| R-4 | Done | Segments registered at open; `recover-segments` applied to live data. |
| R-5 | Local implementation; cloud qualification partial | Native backup/restore and schedule scripts exist. A real Drive upload/download of an 8,677-byte synthetic encrypted ledger matched SHA-256 and restored two exact events. This does not qualify a live research backup, retention or unattended scheduling. |
| P-1 | Measured decision: retain SQLite | A 373-market/223,800-row exact DataPortal read took 1.692 s median and used the existing index without a temporary sort. Longer histories/concurrent writes remain unqualified; add a storage tier only when a representative deadline failure justifies it. |
| P-2 | Done | Worker deadline logging. |
| P-3 | Done | Banner names sources; backoff. |
| O-1 | Runbook implemented; qualification open | `gym-core/docs/disaster-recovery.md` exists. Current-build clean-folder and timed recovery evidence remains incomplete; a runbook alone does not qualify recovery. |
| O-2, O-3 | Done | `/api/ready` in the launcher; `services/alerts.py`, `Install-HealthAlerts.ps1` (owner runs it). |
| O-4 | Done | `gymctl doctor`. |
| O-5 | Available-host checks | Synthetic downloaded-archive restoration passed. Current-build operational recovery remains bounded by its actual restore and runtime evidence. |

## Product, governance, research, models

| ID | Status | Where |
|---|---|---|
| U-1 | Done | Root README leads with the real state. |
| U-2 | Partly present | Cost, fill and latency are in run identity; per-signal attribution views deferred. |
| U-3 | Done (drift guard) | DESIGN.md fixes; `test_design_tokens.py`. Collapsing the token scales and regrouping navigation is a design decision left to the owner. |
| U-4 | Done | One action table (`CLI_ACTIONS`, `CLI_ONLY_ACTIONS`, `gymctl actions`), `gymctl timeline`, `/api/timeline`. |
| U-5 | Done | Browser smoke with axe in CI. |
| U-6, U-9 | Done | System theme, forced colours, labelled confirm dialog. |
| U-7 | Done (review tooling) | Persian ratchet test, `ui_copy_extract.py`. Automated vocabulary and rendering checks govern delivery. |
| U-8 | Done | Per-source banner, backoff. |
| G-1 | Decided | Single-operator delivery; `docs/onboarding.md` and automated contract/security checks govern changes. |
| G-2 | Done | Root README (licence dropped, OD-3). |
| G-3 | Done | Coverage floors; `.impeccable/` is tracked design source and no longer ignored, with a test that no tracked file matches an ignore rule. |
| G-4 | Done | Strategy count guarded by a test. |
| G-5 | Implemented; release qualification open | SECURITY, CHANGELOG, CODEOWNERS, ADRs, `tasks.ps1`, SBOM job and onboarding exist. Current-commit hosted checks, release artifacts/tags and protection settings still need qualification. |
| G-6 | Done | `evidence/INDEX.json`, `scripts/evidence_index.py`. |
| M-1 | Done | Scope amended to paper-only and gated ML. |
| M-2 | Done (step 1) | Bias harness point-in-time test; `model_artifacts.py`; fits are `model-fit` trials. Steps 2-3 wait for 300 closed trades. |
| L-1 to L-6 | Done | Local connection, strict parser, provenance, usage caps, `assistant-eval`. |
| L-7 | Runtime blocked; adoption refused | Pinned official weights loaded, but original case 00 exceeded the 60-second budget (64.94 s, one token). Full 30-case evaluation remains incomplete. Separate gateway initialization failed its Windows ACL check before inference; see `docs/model-pilots.md`. |
| L-8 | Synthetic pilot evaluated; enablement refused | Pinned local model and unchanged client ran the held-out EN/FA fixture. Persian adversarial accuracy drop 0.125 exceeded the predeclared 0.05 limit. Advisory role remains off and semantic grounding unverified; see `docs/model-pilots.md`. |

## Owner decisions

| ID | Status |
|---|---|
| OD-1 | One venue; recorded. |
| OD-2 | Policy options and `arm-policy set` (cost-probe installed); `arm-preflight`; arm record and kill rules in `exec_core::arming` with a shared digest fixture. The privileged arm request, armed mode and approval screen are not wired: they need passing automated pre-funding checks (ADR 0006). |
| OD-3 | Licence dropped. |
| OD-4 | Approved, in progress: cloud synthetic transport/restore passed; live backup, retention and unattended scheduling remain open. |
| OD-5 | Fault stops the service and restart is disarmed (tested); `verified_available` blocks on stale data and disarms on journal disagreement (pure rule, not wired). |

## Report section 4.10 proposals

Adopted and built: pre-registration cost gate (TS-3), excluded families in PRODUCT.md (TS-5), `gymctl doctor`,
point-in-time test, fits as trials and artifact registry, PSI drift monitor (`gymctl drift`), codec property tests,
test renames, Romano-Wolf stepdown (`domain/multiple_testing.py`), written 90-day checkpoint (PRODUCT.md).
Present already: deflated Sharpe with skew and kurtosis, square-root impact, queue-ahead fills, premium lead-lag,
dual-numeraire valuation. Deferred by the report's own verdict (no measured costs, no labelled fills, or a funded
path): TCN, bandit and RL execution, BOCPD upgrade, order-book toxicity, Almgren-Chriss, Kelly barrier, L2 archive,
micro-live canary, other venues, services sub-package split, deleting V1 wire formats.
