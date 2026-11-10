# Appendix B · Findings tracker (status as of 2026-11-10)

This mirrors the report's Appendix B line for line: the same 68 findings and 5 owner decisions, with the report's
titles, ratings and effort. A box is ticked only when the finding's recommendation is fully met. An unticked item
carries a status note saying what exists and what remains. Evidence for each tick is in `CHANGELOG.md` and
`docs/dd-report-status.md`.

Architecture (6)
[ ] A-1 · Research and executor share no execution semantics · High · Effort XL
    Status: step 1 done (golden fill vectors, cross-language conformance). Step 2 partly done: Rust kernel, PyO3 bridge, byte-identical under GYM_RUST_KERNEL=1, CI job. The kernel is not yet the default, and sizing and cost pricing are not moved.
[x] A-2 · Single-venue dependency, and collection is currently blocked · High · Effort M
[x] A-3 · The serial privileged pipe holds the vault mutex across blocking venue reads · Medium · Effort M
[x] A-4 · Golden fixtures cover the v1 contracts only · Low · Effort M
[ ] A-5 · The T2 thread's fate is the whole service's fate, and its startup replays the entire ledger inside a 5 s window · Low (Medium before funding) · Effort M
    Status: startup progress is reported for up to 120 s; replay measured at 0.31 s per 200k rows; the fault decision is recorded (ADR 0006) and tested. Checkpointed suffix replay with background verification is not built.
[ ] A-6 · The reservation book is a single-anchor batch, and the funded reservation and review-v2 paths are not wired to the service · Low · Effort L
    Status: model decided (ADR 0003), ActiveHoldBook with property tests, explicit dust tolerance, paths documented as test-only. Not wired.

Engineering (10)
[ ] E-1 · Five functions are extreme complexity hotspots · Medium · Effort M
    Status: market_order, research_action, make_app and weights are below 20; _portfolio is at 65; a CI ratchet blocks growth.
[x] E-2 · Candle parsing breaks the exact-decimal chain · Medium · Effort S
[x] E-3 · Non-ASCII auth header returns a 500 · Low · Effort S
[x] E-4 · Collector SQLite writes run on the event loop at 373 markets · Low · Effort M
[x] E-5 · Instrument-spec versioning is two separate autocommit statements · Low · Effort S
[x] E-6 · The account-observation freshness rule compares across unrelated resources using the wall clock · Low · Effort S
[x] E-7 · u64 quanta arithmetic is checked on admission paths, unchecked in reserved(), and bounded only by an 18-decimal scale limit · Low · Effort S
[x] E-8 · Rust and Python accept different fill-timestamp grammars · Low · Effort S
[x] E-9 · Hand-rolled binary codecs have golden fixtures but no fuzzing or property tests · Low · Effort M
[x] E-10 · Mutation testing is advisory and covers two files · Low · Effort M

Security (13)
[x] S-1 · Credential protection is strong only on a Windows service host · Medium · Effort M
[x] S-2 · Consumer-subscription OAuth in a third-party gateway · Medium · Effort S
[x] S-3 · Large unsafe surface in the executor with no crate-level guard · Medium · Effort S
[x] S-4 · CI supply-chain hygiene · Medium · Effort S
[ ] S-5 · The gateway's dependency tree is much larger than its job · Low · Effort M
    Status: the dependency audit is recorded in the gateway README. The SDK tree is not replaced or trimmed.
[x] S-6 · Executor updates are verified by hash only, with no signature or provenance · Low · Effort M
[x] S-7 · Provider keys follow whatever HTTPS host the gateway config names · Low · Effort S
[x] S-8 · Saved run results are readable without the token · Low · Effort S
[x] S-9 · The provisioned SID files are checked by type and size only, from an environment-derived path, and one error message is wrong · Low · Effort S
[x] S-10 · The Node gateway inherits the whole parent environment · Low · Effort S
[x] S-11 · The Python-to-Rust helper binaries are located safely but not integrity-checked at run time · Low · Effort S
[x] S-12 · Secret zeroization is partial, and the Python key store has no path hardening · Low · Effort S
[x] S-13 · The browser policy is tight but allows inline styles · Low · Effort S

Reliability (5)
[x] R-1 · The "scored once" test window can be reused · Medium · Effort M
[x] R-2 · No differential bias harness, only partial diagnostics · Medium · Effort M
[x] R-3 · Tamper-evident ledger exists but is anchored only on the host · Low · Effort M
[x] R-4 · An open raw segment is not in the manifest until it closes · Medium · Effort S
[ ] R-5 · Backups cover the executor ledger only, to a local independent volume · Medium · Effort M
    Status: encrypted research backup (market database, runs, closed segments) and restore drill work locally. The cloud destination from OD-4 is not done (postponed by the owner).

Performance (3)
[ ] P-1 · One exact SQLite store serves both collection and analysis · Low · Effort L
    Status: not started. A columnar tier would add a dependency to a four-dependency product.
[x] P-2 · The replay deadline is a constant with about a third of headroom, and the disk floor stops collection · Medium · Effort M
[x] P-3 · The browser polls every two seconds · Low · Effort S

Operations (6)
[ ] O-1 · The operating model assumes one Windows host · Medium · Effort M
    Status: disaster-recovery runbook written. The timed clean-machine restore drill needs a second machine.
[x] O-2 · Evidence of runtime health is dated, not continuous · Medium · Effort S
[x] O-3 · No push alerting, and the launcher's readiness check is shallow · Medium · Effort S
[x] O-4 · There is no single integrity command, so "is my workspace intact?" has no one-step answer · Medium · Effort M
[ ] O-5 · The single-host recovery gate bundles two different losses · Low · Effort M
    Status: the gate is split into host-instance and hardware rows in the docs. The cold-image rebuild in CI is not scripted.
[x] O-6 · The collector and backup tasks assume an always-on, signed-in desktop · Medium · Effort S

Product and UX (9)
[x] U-1 · The pitch is ahead of the evidence · Medium · Effort S
[ ] U-2 · Features worth porting from peers · Low · Effort M
    Status: fee, fill and latency models are recorded in every run identity. Per-signal attribution views are not built.
[ ] U-3 · The UI's design tokens have drifted, and several external UI claims did not survive a check against the code · Low · Effort M
    Status: DESIGN.md chart line fixed; a token-drift test is in place. Not yet done: collapsing the type, radius and spacing scales, and grouping the ten destinations.
[x] U-4 · An operator activity timeline and one action registry would close the CLI-versus-UI gap · Low · Effort M
[x] U-5 · Accessibility and output-safety basics are in place; what is missing is automated proof in a real rendering engine · — · Effort M
[x] U-6 · The theme ignores the operating system preference and there is no forced-colours support · — · Effort S
[ ] U-7 · Translation lives in two mechanisms, and timestamps use a fixed time zone and a locale whose default calendar may differ from the exports · — · Effort M
    Status: a Persian-literal ratchet test and the review-sheet tool exist. Not yet done: moving the inline pairs into the vocabulary, the ISO tooltip on timestamps, and a stored zone preference.
[x] U-8 · Any failed request becomes one generic banner, and the slowest request sets the refresh pace · — · Effort M
[x] U-9 · Destructive actions use the browser's native confirm dialog · — · Effort S

Governance (6)
[ ] G-1 · Bus factor of one at extreme velocity · High · Effort L
    Status: ADRs 0001-0006 and docs/onboarding.md are written. A second maintainer and an independent review need people.
[x] G-2 · The repository root has no README (the licence is dropped, OD-3) · Medium · Effort S
[x] G-3 · No coverage floor, and a gitignore contradiction · Low · Effort S
[x] G-4 · Documentation drift on counts and on the "no order code" statement · Low · Effort S
[ ] G-5 · Release and transfer artefacts are missing · Medium · Effort M
    Status: SECURITY, CHANGELOG, CODEOWNERS, ADRs, task runner, SBOM job, signed manifests and onboarding are done. Not yet done: semantic version tags, manifest version and licence metadata, and branch protection (needs the hosted repository).
[x] G-6 · The acceptance evidence is cited in the docs but deliberately kept out of the repository · Medium · Effort S

Gated opportunity (2)
[x] M-1 · Meta-labeling is a deferred experiment behind a hard gate; keep it paper-only until the gate is met · — · Effort L
[ ] M-2 · Six reports propose ML tiers with conflicting sizes and runtimes; adopt the shared foundations first and decide the runtime by measurement · — · Effort M
    Status: step 1 done (point-in-time test, model fits counted as trials, artifact registry). Step 2 (the first non-trading model) is not built.

LLM tier (8)
[x] L-1 · A local model cannot be attached today without a test-only switch and a stored placeholder key · — · Effort M
[x] L-2 · The proposal parser takes any bracketed text it finds, with no constrained output, repair or retry · — · Effort S
[x] L-3 · The assistant sees earlier net results, so it searches against the window it is later judged on · — · Effort M
[x] L-4 · There is no spend or call cap, and one call can make up to three paid attempts · — · Effort S
[x] L-5 · The assistant's prompts and raw replies are not shown or kept for audit in the UI · — · Effort M
[x] L-6 · Define a System-1 and System-2 split, and a baseline, before adding any model · — · Effort M
[ ] L-7 · MNN-Pocket-0.3B: defer adoption; run a bounded offline pilot only after L-1 and L-2 · — · Effort S
    Status: not run. It comes after the L-8 pilot (docs/model-pilots.md).
[ ] L-8 · Typed decision models (the Jev family) fit the System-1 role better than a small generative model; pilot one behind a decision adapter, advisory only · — · Effort M
    Status: the client is built (research entailment-check). The pilot needs owner-labelled pairs and a local model.

Owner decisions (5)
[x] OD-1 · One venue only: no second venue or source
[ ] OD-2 · Arming approved, with an always-ready one-click path
    Status: policy options (cost-probe installed), arm-preflight, arm record and code-enforced kill rules (exec_core::arming) are done. The privileged arm request, armed mode and approval screen are not wired.
[x] OD-3 · Licence dropped
[ ] OD-4 · Scheduled cloud backup, Google Drive first
    Status: postponed by the owner.
[ ] OD-5 · Fail closed on a privileged-thread fault and on reservation
    Status: the fault stops the service and a restart is disarmed (tested). verified_available (stale data blocks; journal disagreement blocks and disarms) is built but not wired.

Totals: 47 of 68 findings ticked, 21 open; 2 of 5 owner decisions ticked.
