# Appendix B tracker: status on 2026-11-10

Key: `[x]` done with tests · `[~]` partly done, or done but deliberately not wired, or not provable on this
machine · `[ ]` not done. Details for each item are in `docs/dd-report-status.md` and `CHANGELOG.md`.

## Architecture (6)
- [~] A-1 Shared execution semantics: kernel stages 1-3 (golden vectors, Rust kernel, PyO3 bridge, byte-identical under `GYM_RUST_KERNEL=1`, CI job). Stage 4, the kernel as the default plus sizing and cost pricing, is not done.
- [x] A-2 Single venue (OD-1): freshness alerting through `doctor --notify` and `collector_feed`.
- [~] A-3 Vault lock released before venue I/O: code done; needs the installed service identity to exercise.
- [x] A-4 v2 golden fixtures.
- [~] A-5 Startup waits 120 s with progress and replay is measured; the fault rule is tested. Checkpointed replay is not built (not needed at the measured 0.31 s per 200k rows).
- [~] A-6 `ActiveHoldBook`, dust tolerance, ADR 0003 and the test-only paths documented; not wired.

## Engineering (10)
- [~] E-1 Four of the five hotspots are below 20; `_portfolio` is 65; a CI ratchet stops growth.
- [x] E-2 Decimal candle parsing.
- [x] E-3 403 on a non-ASCII token.
- [~] E-4 Event-loop lag is measured in `/api/health`; the writer thread waits for the host numbers.
- [x] E-5 Instrument-spec SAVEPOINT.
- [x] E-6 Per-resource freshness; sequence-ordered `verified_available`.
- [x] E-7 Checked sum; release `overflow-checks`.
- [x] E-8 Shared timestamp fixture.
- [x] E-9 Codec property tests.
- [x] E-10 Wider mutation scope.

## Security (13)
- [~] S-1 DPAPI purpose entropy and link refusal are done. The gateway still stores credentials unencrypted off Windows.
- [x] S-2 API keys are the default; OAuth needs a bilingual terms opt-in.
- [x] S-3 `forbid(unsafe_code)` on the three pure crates.
- [x] S-4 SHA-pinned actions, pinned toolchain, Dependabot, CODEOWNERS.
- [~] S-5 Dependency audit recorded; the SDK tree is not trimmed.
- [x] S-6 ECDSA-signed update manifest.
- [x] S-7 Gateway host allowlist.
- [x] S-8 Public-read decision in SECURITY.md; route-enumeration test.
- [~] S-9 Known-folder path, and the wrong message is gone. The owner and DACL check on the SID file and a rebinding runbook are not done.
- [x] S-10 Gateway environment allowlist.
- [x] S-11 Helpers re-hashed before launch.
- [x] S-12 Decoded replies wiped; protected DACL and owner check on the key store.
- [ ] S-13 `style-src 'unsafe-inline'` is still in the CSP.

## Reliability (5)
- [x] R-1 Holdout ledger.
- [x] R-2 Bias harness (look-ahead and warm-up).
- [x] R-3 Ledger anchors.
- [x] R-4 Segments registered at open; `recover-segments`.
- [~] R-5 Research backup and restore drill work locally; the cloud destination waits on OD-4 (postponed by the owner).

## Performance (3)
- [ ] P-1 Columnar analytics tier: deferred (it would add a dependency).
- [~] P-2 Deadline use is logged with a 75% warning. Scaling the deadline with the work and the disk-growth refusal are not done.
- [x] P-3 Backoff; banner names the failing sources.

## Operations (6)
- [~] O-1 DR runbook is written; the clean-machine drill can't run without a second machine.
- [x] O-2 Freshness and lag on the API; alerts.
- [x] O-3 Launcher uses `/api/ready`; webhook alerts (you run `Install-HealthAlerts.ps1`).
- [x] O-4 `gymctl doctor`.
- [~] O-5 The gate is split in the docs; the cold-image rebuild in CI is not done.
- [ ] O-6 The collector still has a 999-restart limit and an interactive logon; backups still don't wake the laptop.

## Product and UX (9)
- [x] U-1 Root README leads with the real state.
- [~] U-2 Cost, fill and latency are in the run identity; per-signal attribution views are not done.
- [~] U-3 DESIGN.md fixed and a drift test added. Collapsing the token scales and regrouping navigation are your design call.
- [x] U-4 One action table; operator timeline.
- [x] U-5 Real-browser axe smoke.
- [x] U-6 System theme; forced colours.
- [~] U-7 Persian ratchet and review-sheet tool. The inline pairs are not moved, the ISO tooltip is not added, and a native-speaker review is needed.
- [x] U-8 Per-source banner; backoff.
- [x] U-9 Labelled bilingual dialog.

## Governance (6)
- [ ] G-1 Second maintainer and independent review: needs people (`docs/onboarding.md` is their checklist).
- [x] G-2 Root README.
- [x] G-3 Coverage floors; `.impeccable/` resolved.
- [x] G-4 Strategy count guarded by a test; docstring fixed.
- [~] G-5 SECURITY, CHANGELOG, CODEOWNERS, ADRs 0001-0006, `tasks.ps1`, SBOM job, onboarding. No version tags yet (needs you).
- [x] G-6 `evidence/INDEX.json` and its lint.

## Gated opportunity (2)
- [x] M-1 Scope amended to paper-only and gated.
- [~] M-2 Step 1 done (point-in-time test, fits counted as trials, artifact registry). Step 2, a first model, is not built (see below).

## LLM tier (8)
- [x] L-1 Gateway `auth.type: "local"`.
- [x] L-2 Strict parser with one repair retry; invalid-reply rate logged.
- [x] L-3 Assistant runs labelled and counted.
- [x] L-4 Daily and monthly caps.
- [x] L-5 Prompt and reply provenance on each run.
- [x] L-6 `assistant-eval` with a no-model baseline.
- [ ] L-7 MNN-Pocket pilot: deferred until after L-8.
- [~] L-8 Client built (`research entailment-check`); the pilot needs your labelled pairs and a local model.

## Owner decisions (5)
- [x] OD-1 One venue.
- [~] OD-2 Policy options installed (cost-probe), preflight, arm record and kill rules. The privileged arm path is not wired (needs the independent review).
- [x] OD-3 Licence dropped.
- [ ] OD-4 Cloud backup: postponed by you.
- [~] OD-5 Fault stops the service and restart is disarmed (tested); the verified-available rule is built but not wired.

## Totals
- 68 findings: 44 done, 19 partial, 5 not done (S-13, O-6, P-1, G-1, L-7).
- 5 owner decisions: 2 done, 2 partial, 1 postponed.
