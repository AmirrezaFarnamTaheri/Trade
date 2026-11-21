# Complete Active Task Menu Disposition Matrix (21 Nov 2026)

**Date:** 2026-11-21 (UTC) · **Pinned Base:** `master` `8fba0b15115b617067fc93b9c9769c9351472900` / `2eedb5e7590b42c8df0244e15d582a2281dcfb6e`  
**Scope:** Explicit, evidence-backed disposition of every task across all 12 lanes (`G`, `E`, `M`, `X`, `F`, `S`, `C`, `U`, `O`, `H`, `I`, `R`) of *TradingGYM — Updated Active Task Menu (21 Nov 2026)*.  
**Hard invariants preserved:** `TradingGYMExecutor` remains `DISARMED / NOT CERTIFIED`, zero funded-loss budget, zero remote backups auto-enabled, two-trial concurrency budget respected, zero historical data fabricated or overwritten.

---

## Lane G — Baseline Integrity, Release State & Owner Decisions (`G001–G012`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `G001` | **VERIFIED** | Master CI Validate run `44834196697` on `8fba0b1` green (extended weekly mutation skipped; HOST not implied) |
| `G002`, `G009` | **VERIFIED** | Full local `.\tasks.ps1 rust python browser` + Rust kernel + SBOM receipts in `evidence/2026-11-21-baseline-and-sprint1-receipt.md` |
| `G003` | **IMPLEMENTED** | PRs #102–#107 reconciled as delivered in `docs/review-disposition.md` |
| `G004`, `G005` | **INSTALLED STATE OBSERVED** | The baseline receipt recorded the November 6 installed binaries, ACLs, `custody_requalified: false` and zero capital. The follow-up Windows service query returned `Stopped` and `Disabled`. Qualification of a current-source installed bundle remains open. |
| `G006`, `G011` | **IMPLEMENTED** | Frozen `2027-02-08` stop/go protocol and domain sign-off matrix published in `docs/2027-02-08-checkpoint-protocol.md` |
| `G007` | **IMPLEMENTED** | 2026-11-16 off-machine backup cancellation exception prominently disclosed in `gym-core/docs/disaster-recovery.md` and UI Overview checkpoint banner |
| `G008` | **TRIAGED & POSTED** | Factual non-closing triage comment posted to GitHub Issue #13 (`issuecomment-7060511449`); issue stays OPEN pending installed-host/venue qualification |
| `G010` | **IMPLEMENTED** | Economically qualified "net" evidence ladder + refusal rules published in `gym-core/docs/evidence-and-sampling-contract.md` |
| `G012` | **IMPLEMENTED** | Source-of-truth document hierarchy added to `gym-core/docs/README.md` |

## Lane E — Future Studies, Registered Evidence & Independent Custody (`E001–E022`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `E001`, `E002`, `E003` | **PROTOCOL DOCUMENTED** | Git-anchored preregistration, a future window, identity schema and threat model are documented in `gym-core/docs/independent-custody-protocol.md`. Independent signing, verification and custody remain open. |
| `E004`, `E006`, `E007` | **IMPLEMENTED & TESTED** | Outcome-perturbation no-peek invariants, overlapping-window refusal, and monotonic pre-read consumption tested in `gym-core/tests/test_no_peek_and_journal_idempotency.py` |
| `E005`, `E008`, `E009`, `E018`, `E020`, `E021`, `E022` | **LOCAL ENFORCEMENT** | The release formatter retains negative outcomes. The detached Ed25519 verifier checks a pinned digest and an out-of-band public key, with mutation and wrong-key refusal tests. SQLite registrations apply the two-evaluation cap and retain supersession in the same transaction. External signer operation, independent custody and the separate forward-trial log remain outside this boundary. |
| `E010`, `E016`, `E017` | **IMPLEMENTED & TESTED** | `journal_continuity_report` separates process heartbeat vs evidence days, stale quotes, missing days (zero invented returns), and verifies exact Decimal cash/base/fee parity; `Install-AllocationJournal.ps1` & `Install-BreadthJournal.ps1` now propagate nonzero `$LASTEXITCODE` |
| `E011`, `E012`, `E013` | **LIVE CONTINUITY GAPS** | The follow-up read on 2026-11-21 found 7 BTC, 3 mix and 1 breadth entries. BTC and mix reach November 20 with gaps and three stale or non-ready rows each. Breadth ends November 17 even though the 15:00 task returned zero. The local CLI now returns nonzero when the required completed UTC day is missing and leaves the journal untouched. Deployment and the next scheduled receipt remain unverified. |
| `E014` | **FUTURE WINDOW OPEN** | The baseline receipt captures the archive state as of inspection. Completeness of the entire funding-forward scoring period can be assessed after the February 2027 cutoff. |
| `E015` | **IMPLEMENTED & TESTED** | Cross-process OS file lock + `fsync` append (`gym-core/src/gym/services/_journal_lock.py`) wired into `allocation.py`, `mix_journal.py`, `breadth_journal.py` with 6-way parallel contention tests |
| `E019` | **IMPLEMENTED & TESTED** | `/api/evidence` + Overview UI expose trial budget, checkpoint date, `DISARMED` badge, backup exception, and all 3 forward journals (including `breadth-trend-forward`) |

## Lane M — Market-Data Collection, Provenance & Venue Snapshots (`M001–M022`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `M001` | **MEASURED ON LIVE ROOT** | The baseline recorded three gaps over 24 hours, 15 unclosed segments and a collector crash. The collector now defers a contended scheduled publication tick and records a gap on recovery in local tests. Live deployment and other writer paths remain open. |
| `M003`, `M004`, `M005`, `M013` | **VERIFIED & TESTED** | Reconnect overlap multiplicity & `GAP` detection tested in `tests/test_execution_qualification.py`; identical-print ambiguity sensitivity implemented in `maker_queue_fill`; causal availability & late-print fixtures verified across `test_collector*` and `test_no_peek_and_journal_idempotency.py` |
| `M006` | **SAMPLED FRAME INTEGRITY** | A read-only BTCUSDT sample on November 21 checked five trade and five book references and encountered one unclosed segment. The follow-up verifier checks each sampled sequence and raw payload digest inside the closed archive. The verifier now matches normalized trade fields, receipt clock, request or channel symbol, and multiplicity for WebSocket and symbol-tagged REST frames. Legacy REST request symbols, both depth sides and complete replay input lineage remain open. |
| `M002`, `M007–M012`, `M014–M019`, `M021–M022` | **DIAGNOSTICS AND BENCHMARKS** | Focused tests cover ingestion clocks, catalogue/rule receipt times, as-of rule vintages, quality calendar, SLO, fee/ratio parsing, cross-feed checks, historical listing and REST failures. The earlier benchmark measured a 10 MiB rollover at 28.17 ms and catalogue write amplification at 32.01×. |
| `M020` | **IMPLEMENTED & TESTED** | Outage duration (`1h+/6h+/12h+/24h+`) & disk pressure (`<15/<10/<5 GiB`) escalation buckets added to `gym-core/src/gym/services/alerts.py` & `tests/test_trial_governance_and_alerts.py` |

## Lane X — Historical Execution Qualification, Liquidity & Paper Orders (`X001–X024`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `X001–X015`, `X018–X022` | **PARTIAL** | Execution qualification, depth walking, latency, queue modeling, fill audits and cost scenarios have domain implementations. Complete historical trade-level evidence and engine qualification remain open. |
| `X016` | **PAPER PREVIEW AND REPLAY INTEGRATED** | The preview accepts `TRAILING_STOP` with a positive delay. Standalone and shared-cash replay accept opt-in `exit_venue_stop=2`, using received-trade high-water and trigger timing, delayed order activation, and displayed liquidity caps. The prior fixed-stop mode and legacy identities have separate regressions. Evidence stays modeled paper. |
| `X017` | **VERIFIED** | Market vs limit comparison on shared received quotes/trades verified in existing `test_simulation.py`, `test_limit_print_provenance.py`, and `bench_baseline.py` |
| `X023`, `X024` | **DEFERRED (OPT)** | Require authenticated order lifecycle (`HOST`) or a new preregistered trial within the 2-trial budget (currently saturated at 2/2) |

## Lane F — Exact Money, Inventory, Shared-Cash Portfolios & Risk (`F001–F026`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `F001–F006`, `F008–F009`, `F012` | **IMPLEMENTED & TESTED** | Independent double-entry balance oracle + 400 randomized sequences across base/quote fees, rebates, dust, Decimal precision contexts (`12/28/50`), modern posting refusal, legacy fallback, and standalone-vs-portfolio parity in `gym-core/tests/test_financial_conservation_oracle.py` |
| `F007` | **VERIFIED** | Built `exec-kernel 0.2.0` Rust wheel and passed all 19 differential tests (`2,000+` rational budget-walk vectors) in `tests/test_kernel_sizing.py` (`GYM_RUST_KERNEL=1`) |
| `F010`, `F013–F015`, `F017–F025` | **DOMAIN DIAGNOSTICS AND PORTFOLIO REPORTING** | Booked portfolio performance reports include quote-currency reconciliation and diagnostic opening-rate P&L versus terminal FX translation. Missing FX marks and corrupted USDT-equivalent totals are tested. The directional breakdown independently values gross buy/sell postings and signed fees at terminal bids and reports unexplained quote movement. Benchmark-relative causal attribution remains outside this accounting identity. |
| `F011`, `F016` | **CONSERVATIVE DEFAULTS ADOPTED** | Keep `legacy` default for frozen-run compatibility while recommending opt-in `inventory/2` for all new research (`F011`); retain deterministic symbol-sorted shared-cash allocation as canonical baseline unless a registered study specifies pro-rata (`F016`) |
| `F026` | **DEFERRED (OPT)** | External portfolio-risk libraries (PyPortfolioOpt/skfolio/Riskfolio-Lib) deferred pending measured need and license/security review |

## Lane S — Sampling, Calibrated Statistics & Multiplicity (`S001–S023`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `S001`, `S002` | **IMPLEMENTED** | Canonical sampling contract, strict monotonicity, date-clustering, and MDE/prospective power gate published in `gym-core/docs/evidence-and-sampling-contract.md` |
| `S003–S011` | **SCOPED STATISTICAL TESTS** | Tests cover Lo/HAC, PSR/DSR, mark counting and bounded SPA-style behavior. Those fixtures do not establish a particular forward study's power or a registered family outcome. |
| `S012`, `S014–S017` | **DIAGNOSTIC PROTOTYPES** | The local inference module exposes Hansen-style recentering, label-interval splits, PBO rank-logits, lower-bound-checked e-values, and paired uplift. External reference calibration and prospective deployment remain optional pending a registered decision. |
| `S013` | **DEFERRED (OPT)** | Preserve the eight-candidate limit until a registered comparison requires more capacity and has a measured budget. |
| `S018–S023` | **PARTIAL** | Local selection receipts and statistical refusal/control tests exist. Complete selection-family accounting and fit chronology depend on the actual study and its custody boundary. Existing scorecards retain their SPA-style label. |

## Lane C — Margin, Financing, FX Routing & Tokenized Assets (`C001–C018`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `C001–C008`, `C009–C017` | **IMPLEMENTED & TESTED** | `gym-core/src/gym/domain/token_and_margin_audit.py`, `market_quality.parse_margin_ratio`, and `tests/test_portfolio_token_and_fault_recovery.py` + `tests/test_portfolio_and_margin_contracts.py` verify 1x margin-vs-spot reconciliation, debt/collateral currency safety, 4h financing across unsettled crashes, credit-subaccount separation, directional FX spread/fee round-trip checks, `/public/ratio/{market}` parsing, and Wallex token tradability/premium/depth checks without proxy backfilling |
| `C018` | **DEFERRED (OPT)** | Alternate currency/derivative/leveraged constructions deferred pending 2-trial budget availability |

## Lane U — Evidence-First Product, Guided Research, Accessibility & UX (`U001–U037`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `U001–U006`, `U008`, `U011–U014`, `U017`, `U019`, `U025`, `U031` | **SCOPED IMPLEMENTATION AND TESTS** | The evidence banner, SLO panel, quality calendar, preflight, depth preview, action registry and cost lab are wired to read-only diagnostic data. Existing tests cover these components; individual menu criteria and authenticated evidence need separate verification. |
| `U007` | **FILTERABLE TIMELINE INTEGRATED** | Health loads a bounded, source-filtered timeline of feed gaps, experiment events, evaluation outcomes, backup events and safety records. The API discloses absent/unreadable sources. Independent signed receipt availability remains open. |
| `U015` | **TOP-OF-BOOK FX INSPECTION INTEGRATED** | Direct and bridged routes show per-leg quote time, bid/ask, spread, modeled fee and displayed base size. Capacity uses input currency and output uses the receiving currency. Savings are suppressed if either route exceeds displayed capacity. Depth beyond the touch and actual settlement are outside the preview. |
| `U022` | **SAVED-RUN FILTERS INTEGRATED** | The browser sends symbol, strategy, date, model, modeled fee, evidence, benchmark, gap and status filters to the catalog endpoint. Filtering precedes offset pagination. Missing metadata stays unknown. |
| `U033`, `U034` | **VERIFIED & TESTED** | Automated EN/FA vocabulary & `{placeholder}` parity gate across all keys in `tests/test_security_and_drift_contracts.py`; `dir="ltr"` / `digits(...)` preserved for RTL numbers/ISO dates |
| `U026` | **SAVED-RUN MAKER TIMELINE INTEGRATED** | The timeline filters recorded orders by status before applying the 100-row bound and displays modeled placement, queue, eligible prints, possible duplicate capacity, fill, child remainder and cancellation status. Missing timestamps and print evidence are explicit. Edge smoke covers recorded and missing evidence. |
| `U016` | **GUIDED PAPER REGISTRATION INTEGRATED** | The comparison form freezes a hypothesis, symbol, candidates, dates, matching quote-cash benchmark, minimum modeled uplift and evidence scope. Matched evaluation reports target attainment only with current terminal marks. Old registrations remain readable and continue to use their original contract. |
| `U009–U010`, `U018`, `U020–U021`, `U023–U024`, `U027–U030`, `U032`, `U035–U037` | **SCOPED SMOKE AND PERFORMANCE EVIDENCE** | The current checks exercise routes, keyboard focus, accessibility markup, offline review and 400-market rendering. Every chart's screen-reader behavior still needs task-specific acceptance. |

## Lane O — Backups, Operational Diagnostics, Local API & Accepted-Risk Controls (`O001–O024`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `O001`, `O002` | **LOCAL RECEIPTS AND POLICY DISCLOSED** | The follow-up chronology reported a local restore receipt about 2.43 hours old, no local backup age, and off-machine age `UNKNOWN`. The existing recovery runbook records the owner's canceled off-machine schedule. A recent local restore receipt does not establish off-host recovery. |
| `O003–O011` | **IMPLEMENTED & TESTED** | Timed isolated full local restore rehearsal (`10.85s`, `PINNED`, `FULL_RESTORE 74/74`, `cross_host_verified: false`, schema 5→6 migration, `doctor: PASS`, `DISARMED`) + negative fault tests (missing closed segment, open segment cutoff, bad manifest/digest, malformed v2 header, tar path-traversal escape) in `tests/test_recovery_and_isolation.py` + `tests/test_research_backup.py` |
| `O012`, `O013` | **IMPLEMENTED & MEASURED** | Live storage runway (`16.15 GiB` free / `33.20 GiB` raw / `10.10 GiB` `market.db`) recorded in `evidence/2026-11-21-performance-and-hygiene-audit.md`; `backup_status.receipt_chronology()` wired into `/api/slo` reporting unverifiable off-machine backup age explicitly as `UNKNOWN` (`None`, never `0`) |
| `O014` | **DEFERRED (OWNER POLICY)** | Off-machine backup policy remains canceled per 2026-11-16 owner decision; no silent opt-in |
| `O015–O018` | **VERIFIED & TESTED** | Loopback `Host` DNS-rebinding refusal (403), token/CSRF enforcement, no CORS allow-origin, security headers, no secret echo, no live order route, malformed input bounds tested in `tests/test_security_and_drift_contracts.py` + `tests/test_security_regressions.py` |
| `O019`, `O021`, `O023`, `O024` | **VERIFIED** | Portability probe (`test_portability_cli.py`), reliability checks (`doctor.py`), safe-stop behavior, and updated `disaster-recovery.md` / `offline-recovery-runbook.md` verified |
| `O020` | **IMPLEMENTED & TESTED** | Formula-injection-safe exact-Decimal CSV exporter (`gym-core/src/gym/services/csv_export.py`) tested in `tests/test_trial_governance_and_alerts.py` |
| `O022` | **IMPLEMENTED & TESTED** | Worsening outage duration & disk runway alert escalation implemented in `gym-core/src/gym/services/alerts.py` & tested |

## Lane H — Protected Rust/Windows Execution Acceptance (`H001–H029`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `H001–H029` | **BLOCKED BY DESIGN (HOST — DISARMED)** | Per Task Menu & `PRODUCT.md`: remains **DISARMED** and must **not** be implemented/armed by research/UI work. Source-level Rust contracts (`cargo test --locked --workspace --all-targets`: arming, active holds, fake-venue chaos, restricted service identity, stalled venue, Windows stop security) all pass; actual installed-host qualification waits for the `2027-02-08` checkpoint, signed current-source bundle, owner approval, and independent OS/venue reviewer. |

## Lane I — Engineering, Measured Performance, Optional Architecture & Hygiene (`I001–I021`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `I001–I003`, `I005`, `I012–I014` | **MEASURED** | Live SQLite query latencies (`0.64–42.24 ms`), index plans, limit/portfolio compute (`62.6 ms` / `391.3 ms`, `3.05 MiB` peak), schema 5→6 migration (`0.159s`), and UI payload (`414.8 KB`) recorded in `evidence/2026-11-21-performance-and-hygiene-audit.md` |
| `I006` | **PUBLICATION CONTENTION MITIGATED LOCALLY** | Scheduled publication skips a busy writer immediately, retries at the next tick and records the gap on recovery. The writer-actor prototype remains optional. Other synchronous writes and live venue behavior are unverified under sustained contention. |
| `I004`, `I007–I011` | **DEFERRED WITH EVIDENCE (OPT)** | The earlier query and rendering benchmarks do not establish a need for these migrations. |
| `I015` | **FIRST VIEW MODULE VERIFIED** | The evidence timeline request and response handling is a content-hashed native ES module loaded on first use. Edge checks that it is absent at startup and requested once on use. The rest of the classic-script workspace remains outside this first phase. |
| `I016`, `I017`, `I020`, `I021` | **VERIFIED** | `complexity_ratchet.py` (`0 problems`), `test_mutation_contracts.py` / `test_mutation_gate.py`, CycloneDX Python+Rust SBOMs (`.\tasks.ps1 sbom`), and honest CI/HOST labels verified |
| `I018` | **COMPLETED** | Full 38-script classification table in `evidence/2026-11-21-performance-and-hygiene-audit.md` §4 (zero blind deletions) |
| `I019` | **IMPLEMENTED & TESTED** | Automated cross-document & runtime drift test in `gym-core/tests/test_security_and_drift_contracts.py` |

## Lane R — Conditional Research & Peer-System Menu (`R001–R013`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `R001–R003` | **OFFLINE DAILY SPOT WORKFLOW TESTED** | `gymctl research trend-replay packet.json` combines three EWMAC horizons, strictly prior volatility, a round-trip cost gate, bounded spot sizing, lot-aware bid/ask rebalancing and a matched quote-cash account. The CLI tests reconcile holdings and cash, perturb the input suffix and check cost rejection and minimum-notional dust. Prospective trial performance remains unobserved. |
| `R004` | **OFFLINE RANK-IC WORKFLOW INTEGRATED** | `gymctl research factor-ic-lab packet.json` accepts bounded caller-supplied factor and return maps with explicit label endpoints. The CLI refuses unfinished labels and purges overlapping windows. Tied ranks, Pearson IC, date-weighted forward-return quartiles and the seeded shuffle are covered. Independent feature and label lineage remain open. |
| `R005–R009` | **DEFERRED (OPT — TRIAL BUDGET 2/2 FULL)** | Funding-confirmed trend and breadth trend occupy the registered slots. Additional trials need new eligible observations, registration and budget. |
| `R010–R013` | **READ-ONLY CONTRACT COMPARISON** | See [peer-project contract comparison](2026-11-22-peer-project-contract-comparison.md). Fixed inputs exercised hftbacktest, pysystemtrade, Qlib, PyPortfolioOpt, skfolio and Riskfolio-Lib. The held-out allocation fixture produced no net improvement. Remaining peer engines and exchanges of full event histories remain open. |

## Local follow-up verification

The November 22 Tehran follow-up maps all 271 menu IDs exactly once. The Windows checkout was at `094f96ac57b0ece7aa8e485c97b444c23e22525e` with uncommitted changes. The SHA-256 of `git diff --binary HEAD -- gym-core` for the tested application tree was `c6f630e35600550a12896ced192f532c5943511ee6815ebb559954a1c28028fd`.

- `uv run --locked --group research python -m pytest -q --tb=short` passed 2,062 tests and 35 subtests, with five skips. The earlier intermediate runs exposed missing attribution after reload and an exception for records without terminal balances. Both regressions passed on the final tree.
- `node tests/browser_smoke.cjs` passed in Windows Edge for the reviewed UI. `uvx ruff==0.17.5 check src tests` and `git diff --check` passed.
- The live journal, backup chronology, sampled provenance and Windows service checks were read-only. The working-tree changes have no hosted CI or installed-service receipt.

## Extended local follow-up

- Windows suite after the catalog, FX, timeline and frame-audit changes passed 2,065 tests and 35 subtests with five skips. The focused suite after the attestation verifier passed 45 tests. Ruff and whitespace checks passed.
- Windows Edge and Linux Chrome 158 on WSL passed the browser smoke. Linux used the locked runtime and axe-core 4.10.2, with zero automatic violations reported on the nine checked views. The smoke exercised the filtered timeline, saved-run query and FX quote evidence. Manual assistive-technology checks for each chart remain open.
- Read-only checks still found gaps in BTC and mix through November 20 and breadth through November 17. Off-machine backup age remained unknown. The branch and protected service were not modified remotely or deployed.

## Replay and workflow follow-up

- The Windows locked suite passed 2,068 tests and 35 subtests with five skips after the trailing replay mode, Rank-IC action, attestation CLI, maker timeline and guided paper registration changes. Ruff and whitespace checks passed.
- Windows Edge and Linux Chrome passed the updated smoke. Linux axe reported zero automated violations in nine checked views. Browser checks confirmed the maker timeline renders recorded and missing evidence, and the content-hashed ES module loads only on demand. The built wheel contains the module.
- The read-only breadth check still found no journal entry after November 17. The Windows executor was stopped and disabled. PR #108 remained at `094f96a`. These local checks do not qualify the installed service or establish a hosted CI result for the working tree.

## November 22 publication verification

The Windows research suite passed 2,071 tests and 35 subtests, with five skips and three aiohttp WebSocket deprecation warnings. Windows Edge and Linux Chrome exercised the maker-status filter. Ruff, the complexity ratchet, the staged Gitleaks scan, the locked Python dependency audit, and the axe-core 4.10.2 npm audit passed. The wheel and source distribution built successfully. The executor service was stopped and disabled, and the Windows session lacked administrator privileges.
