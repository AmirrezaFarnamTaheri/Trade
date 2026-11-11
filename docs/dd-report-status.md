# Due-diligence report (2026-11-09): disposition of every finding

Status as of 2026-11-10, branch chain `hardening/dd-quick-wins` -> `dd-medium-term` -> `dd-conformance` ->
`dd-alerts` -> `dd-remaining` -> `dd-arming` -> `dd-final`. **Done** means implemented with tests; **Decided**
means the owner or an ADR settled it; **Deferred** and **Blocked** say why. Details are in `CHANGELOG.md`.

## Architecture

| ID | Status | Where |
|---|---|---|
| A-1 | Done (stages 1-3) | Golden fill vectors and conformance (`contracts/v1/fixtures/{sizing,fills,price-guard}.json`), `exec-core/src/kernel.rs`, PyO3 bridge `executor/exec-kernel-py`, `GYM_RUST_KERNEL=1` byte-identical on 4,000 orders, CI job `rust-kernel`. Stage 4 (kernel as default, sizing and cost pricing moved in) deferred: needs a defined division rule for unknown venue precision and the wheel in the install path (ADR 0005). |
| A-2 | Decided | OD-1: one venue only. Freshness alerting (`doctor --notify`, `collector_feed`) carries the weight. |
| A-3 | Done, unverified on host | `begin_account_read`/`finish_account_read`: credential copied out under the lock, venue I/O outside it. Needs the installed service identity to exercise. |
| A-4 | Done | v2 golden fixture, `contracts/v2/`. |
| A-5 | Done | Startup waits up to 120 s with StartPending; replay measured 0.31 s per 200k rows (`startup_scale.rs`); fault rule tested (`supervise_privileged`, `tests/privileged_fault.rs`). Checkpointed replay not needed at measured scale (ADR 0004). |
| A-6 | Done, not wired | `ActiveHoldBook` (`holds.rs`), explicit default-zero dust tolerance in `ReservationBook`, review-v2 and prepared reservation documented as test-only (`executor/README.md`, ADR 0003, 0006). |

## Engineering

| ID | Status | Where |
|---|---|---|
| E-1 | Done (four of five below 20) | `market_order`, `research_action`, `make_app`, `weights` split; `_portfolio` 85 -> 65 (its per-quote closure state stays, to keep the replay hot path free of attribute lookups); CI ratchet `scripts/complexity_ratchet.py` with `complexity-baseline.json`. |
| E-2 | Done | `parse_udf` parses Decimal. |
| E-3 | Done | `token_matches`, 403 on non-ASCII. |
| E-4 | Done (measurement) | Event-loop lag sampler in `/api/health` (`services/loop_lag.py`). A writer thread waits for the host's p99. |
| E-5 | Done | Instrument-spec SAVEPOINT. |
| E-6 | Done | Per-resource freshness; `verified_available` orders by venue sequence. |
| E-7 | Done | Saturating `reserved()`, release `overflow-checks`. |
| E-8 | Done | `fill-timestamps.json` shared fixture. |
| E-9 | Done | `codec_properties.rs`. |
| E-10 | Done | Wider mutation scope. |

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

## Reliability, performance, operations

| ID | Status | Where |
|---|---|---|
| R-1 | Done | `holdout_ledger.py`, `--rescore-holdout`. |
| R-2 | Done | `services/bias_harness.py`. |
| R-3 | Done | `ledger_anchors.py`. |
| R-4 | Done | Segments registered at open; `recover-segments` applied to live data. |
| R-5 | Done | `backup-research`, restore drill, schedule script. Off-host copy is OD-4 (postponed). |
| P-1 | Deferred | Columnar tier would add a dependency to a four-dependency product; revisit for multi-year studies. |
| P-2 | Done | Worker deadline logging. |
| P-3 | Done | Banner names sources; backoff. |
| O-1 | Done | `gym-core/docs/disaster-recovery.md`. |
| O-2, O-3 | Done | `/api/ready` in the launcher; `services/alerts.py`, `Install-HealthAlerts.ps1` (owner runs it). |
| O-4 | Done | `gymctl doctor`. |
| O-5 | Done | Recovery gate split into host-instance and hardware loss. |

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
| G-5 | Done | SECURITY, CHANGELOG, CODEOWNERS, ADRs 0001-0006, `tasks.ps1`, SBOM job, onboarding. Version tags need the owner. |
| G-6 | Done | `evidence/INDEX.json`, `scripts/evidence_index.py`. |
| M-1 | Done | Scope amended to paper-only and gated ML. |
| M-2 | Done (step 1) | Bias harness point-in-time test; `model_artifacts.py`; fits are `model-fit` trials. Steps 2-3 wait for 300 closed trades. |
| L-1 to L-6 | Done | Local connection, strict parser, provenance, usage caps, `assistant-eval`. |
| L-7 | Deferred | After L-8 (`docs/model-pilots.md`). |
| L-8 | Done (client); pilot is the owner's | `gymctl research entailment-check`; the pilot uses a versioned synthetic fixture set. |

## Owner decisions

| ID | Status |
|---|---|
| OD-1 | One venue; recorded. |
| OD-2 | Policy options and `arm-policy set` (cost-probe installed); `arm-preflight`; arm record and kill rules in `exec_core::arming` with a shared digest fixture. The privileged arm request, armed mode and approval screen are not wired: they need passing automated pre-funding checks (ADR 0006). |
| OD-3 | Licence dropped. |
| OD-4 | Postponed by the owner (cloud backup). |
| OD-5 | Fault stops the service and restart is disarmed (tested); `verified_available` blocks on stale data and disarms on journal disagreement (pure rule, not wired). |

## Report section 4.10 proposals

Adopted and built: pre-registration cost gate (TS-3), excluded families in PRODUCT.md (TS-5), `gymctl doctor`,
point-in-time test, fits as trials and artifact registry, PSI drift monitor (`gymctl drift`), codec property tests,
test renames, Romano-Wolf stepdown (`domain/multiple_testing.py`), written 90-day checkpoint (PRODUCT.md).
Present already: deflated Sharpe with skew and kurtosis, square-root impact, queue-ahead fills, premium lead-lag,
dual-numeraire valuation. Deferred by the report's own verdict (no measured costs, no labelled fills, or a funded
path): TCN, bandit and RL execution, BOCPD upgrade, order-book toxicity, Almgren-Chriss, Kelly barrier, L2 archive,
micro-live canary, other venues, services sub-package split, deleting V1 wire formats.
