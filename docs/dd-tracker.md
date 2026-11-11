# Appendix B · Findings tracker (status as of 2026-11-11)

This mirrors the report's Appendix B line for line: the same 68 findings and 5 owner decisions, with the report's
titles, ratings and effort. A box is ticked only when the finding's recommendation is fully met. An unticked item
carries a status note saying what exists and what remains. Evidence for each tick is in `CHANGELOG.md` and
`docs/dd-report-status.md`.

Architecture (6)
[ ] A-1 · Research and executor share no execution semantics · High · Effort XL
    Status: step 1 done (golden fill vectors, cross-language conformance). Step 2 partly done: native exact standalone sizing, settlement bridge and locked optional installation are available. Contextual simulator sizing and impact-cost resizing retain the Python implementation; native default activation remains unqualified.
[x] A-2 · Single-venue dependency, and collection is currently blocked · High · Effort M
[x] A-3 · The serial privileged pipe holds the vault mutex across blocking venue reads · Medium · Effort M
[x] A-4 · Golden fixtures cover the v1 contracts only · Low · Effort M
[ ] A-5 · The T2 thread's fate is the whole service's fate, and its startup replays the entire ledger inside a 5 s window · Low (Medium before funding) · Effort M
    Status: startup progress is reported for up to 120 s. Actual service startup now verifies and recovers in one pass: 200k rows measured 2.369 s versus 4.159 s before, under the unchanged 20 s bound. Later verification still rechecks the chain. Persistent checkpoints and larger live histories remain unqualified.
[ ] A-6 · The reservation book is a single-anchor batch, and the funded reservation and review-v2 paths are not wired to the service · Low · Effort L
    Status: model decided (ADR 0003), ActiveHoldBook with property tests, explicit dust tolerance, paths documented as test-only. Not wired.

Engineering (10)
[x] E-1 · Five functions are extreme complexity hotspots · Medium · Effort M
[x] E-2 · Candle parsing breaks the exact-decimal chain · Medium · Effort S
[x] E-3 · Non-ASCII auth header returns a 500 · Low · Effort S
[ ] E-4 · Collector SQLite writes run on the event loop at 373 markets · Low · Effort M
    Status: subscription acknowledgment gating is repaired and all 18 shards connected. A live 3.312 s lag spike coincided with high host CPU, but its owner is unproved; latency qualification remains open. Isolated rotation did not justify a writer rewrite.
[x] E-5 · Instrument-spec versioning is two separate autocommit statements · Low · Effort S
[x] E-6 · The account-observation freshness rule compares across unrelated resources using the wall clock · Low · Effort S
[x] E-7 · u64 quanta arithmetic is checked on admission paths, unchecked in reserved(), and bounded only by an 18-decimal scale limit · Low · Effort S
[x] E-8 · Rust and Python accept different fill-timestamp grammars · Low · Effort S
[x] E-9 · Hand-rolled binary codecs have golden fixtures but no fuzzing or property tests · Low · Effort M
[ ] E-10 · Mutation testing is advisory and covers two files · Low · Effort M
    Status: seven actionable survivor gaps now have independently reviewed regression tests. The expanded weekly assessment fails visibly. A 49-mutant critical cohort is implemented but its timing-suspicious result was rejected; no passing baseline or full five-file qualification is claimed.

Security (13)
[x] S-1 · Credential protection is strong only on a Windows service host · Medium · Effort M
[x] S-2 · Consumer-subscription OAuth in a third-party gateway · Medium · Effort S
[x] S-3 · Large unsafe surface in the executor with no crate-level guard · Medium · Effort S
[x] S-4 · CI supply-chain hygiene · Medium · Effort S
[ ] S-5 · The gateway's dependency tree is much larger than its job · Low · Effort M
    Status: audit and measured decision recorded in the gateway README. Retain the active SDK: 87 locked packages, 68.8 MB installed files, 283 ms median fresh-process runtime import. Replacement remains deferred; no speculative fork or protocol rewrite.
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
[ ] R-3 · Tamper-evident ledger exists but is anchored only on the host · Low · Effort M
    Status: local signed anchors exist. Independent remote custody is not established by local storage or same-account transport.
[x] R-4 · An open raw segment is not in the manifest until it closes · Medium · Effort S
[ ] R-5 · Backups cover the executor ledger only, to a local independent volume · Medium · Effort M
    Status: encrypted research backup (market database, runs, closed segments) and restore drill work locally. Real Drive transport of a synthetic encrypted ledger matched all 8,677 bytes and restored two events. Live backup, retention and unattended scheduling remain open.

Performance (3)
[ ] P-1 · One exact SQLite store serves both collection and analysis · Low · Effort L
    Status: measured decision to retain indexed SQLite for now. A synthetic 373-market/223,800-row exact DataPortal read took 1.692 s median over three runs and used book_top_avail without a temporary sort. This does not qualify longer-history/concurrent workloads. Revisit a columnar tier when a representative measured query misses its deadline; no additional storage dependency is justified by this bounded result.
[x] P-2 · The replay deadline is a constant with about a third of headroom, and the disk floor stops collection · Medium · Effort M
[x] P-3 · The browser polls every two seconds · Low · Effort S

Operations (6)
[ ] O-1 · The operating model assumes one Windows host · Medium · Effort M
    Status: disaster-recovery runbook written. Available-host clean-folder restore and timed VM checks remain the qualification targets.
[x] O-2 · Evidence of runtime health is dated, not continuous · Medium · Effort S
[x] O-3 · No push alerting, and the launcher's readiness check is shallow · Medium · Effort S
[x] O-4 · There is no single integrity command, so "is my workspace intact?" has no one-step answer · Medium · Effort M
[ ] O-5 · The single-host recovery gate bundles two different losses · Low · Effort M
    Status: implemented. The rows are split in acceptance-status; windows-vm-smoke now times a clean-VM build, install and start to a verified DISARMED state, and the b3 jobs restore the ledger. It runs on GitHub's hosted runners, so the first timed run happens on the next push.
[x] O-6 · The collector and backup tasks assume an always-on, signed-in desktop · Medium · Effort S

Product and UX (9)
[x] U-1 · The pitch is ahead of the evidence · Medium · Effort S
[ ] U-2 · Features worth porting from peers · Low · Effort M
    Status: cost, fill and latency identity exists. Per-signal attribution views remain open.
[x] U-3 · The UI's design tokens have drifted, and several external UI claims did not survive a check against the code · Low · Effort M
[x] U-4 · An operator activity timeline and one action registry would close the CLI-versus-UI gap · Low · Effort M
[x] U-5 · Accessibility and output-safety basics are in place; what is missing is automated proof in a real rendering engine · — · Effort M
[x] U-6 · The theme ignores the operating system preference and there is no forced-colours support · — · Effort S
[x] U-7 · Translation lives in two mechanisms, and timestamps use a fixed time zone and a locale whose default calendar may differ from the exports · — · Effort M
[x] U-8 · Any failed request becomes one generic banner, and the slowest request sets the refresh pace · — · Effort M
[x] U-9 · Destructive actions use the browser's native confirm dialog · — · Effort S

Governance (6)
[ ] G-1 · Bus factor of one at extreme velocity · High · Effort L
    Status: ADRs 0001-0006 and docs/onboarding.md are written. Automated contract/security review and operator verification govern delivery.
[x] G-2 · The repository root has no README (the licence is dropped, OD-3) · Medium · Effort S
[x] G-3 · No coverage floor, and a gitignore contradiction · Low · Effort S
[x] G-4 · Documentation drift on counts and on the "no order code" statement · Low · Effort S
[ ] G-5 · Release and transfer artefacts are missing · Medium · Effort M
    Status: Done: manifests at 0.2.0 matching the dated CHANGELOG release (test-enforced) and `scripts/github/protect-branches.sh`. Needs the owner: push the `v0.2.0` tag and run the protection script with admin rights.
[x] G-6 · The acceptance evidence is cited in the docs but deliberately kept out of the repository · Medium · Effort S

Gated opportunity (2)
[x] M-1 · Meta-labeling is a deferred experiment behind a hard gate; keep it paper-only until the gate is met · — · Effort L
[x] M-2 · Six reports propose ML tiers with conflicting sizes and runtimes; adopt the shared foundations first and decide the runtime by measurement · — · Effort M

LLM tier (8)
[x] L-1 · A local model cannot be attached today without a test-only switch and a stored placeholder key · — · Effort M
[x] L-2 · The proposal parser takes any bracketed text it finds, with no constrained output, repair or retry · — · Effort S
[x] L-3 · The assistant sees earlier net results, so it searches against the window it is later judged on · — · Effort M
[x] L-4 · There is no spend or call cap, and one call can make up to three paid attempts · — · Effort S
[x] L-5 · The assistant's prompts and raw replies are not shown or kept for audit in the UI · — · Effort M
[x] L-6 · Define a System-1 and System-2 split, and a baseline, before adding any model · — · Effort M
[ ] L-7 · MNN-Pocket-0.3B: defer adoption; run a bounded offline pilot only after L-1 and L-2 · — · Effort S
    Status: pinned checkpoint loaded; original case 00 timed out at 64.94 s with one token. Full 30-case evaluation and actual gateway connection remain unqualified (docs/model-pilots.md).
[ ] L-8 · Typed decision models (the Jev family) fit the System-1 role better than a small generative model; pilot one behind a decision adapter, advisory only · — · Effort M
    Status: client and pinned-model synthetic pilot executed. Persian adversarial accuracy drop 0.125 failed the predeclared 0.05 limit. Advisory enablement remains off (docs/model-pilots.md).

Owner decisions (5)
[x] OD-1 · One venue only: no second venue or source
[ ] OD-2 · Arming approved, with an always-ready one-click path
    Status: policy options (cost-probe installed), arm-preflight, arm record and code-enforced kill rules (exec_core::arming) are done. The privileged arm request, armed mode and approval screen are not wired.
[x] OD-3 · Licence dropped
[ ] OD-4 · Scheduled cloud backup, Google Drive first
    Status: approved and in progress. Synthetic Drive transport/restore passed; live backup, retention and unattended scheduling remain open.
[ ] OD-5 · Fail closed on a privileged-thread fault and on reservation
    Status: the fault stops the service and a restart is disarmed (tested). verified_available (stale data blocks; journal disagreement blocks and disarms) is built but not wired.

Totals: 52 of 68 findings ticked, 16 open; 2 of 5 owner decisions ticked.
