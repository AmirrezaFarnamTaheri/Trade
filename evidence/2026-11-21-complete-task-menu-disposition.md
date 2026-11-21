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
| `G004`, `G005` | **VERIFIED** | Installed Nov 6 binaries & ACLs audited (`TradingGYMExecutor` Stopped, `custody_requalified: false`, `capital_quanta: "0"`) in `evidence/2026-11-21-baseline-and-sprint1-receipt.md` |
| `G006`, `G011` | **IMPLEMENTED** | Frozen `2027-02-08` stop/go protocol and domain sign-off matrix published in `docs/2027-02-08-checkpoint-protocol.md` |
| `G007` | **IMPLEMENTED** | 2026-11-16 off-machine backup cancellation exception prominently disclosed in `gym-core/docs/disaster-recovery.md` and UI Overview checkpoint banner |
| `G008` | **TRIAGED & POSTED** | Factual non-closing triage comment posted to GitHub Issue #13 (`issuecomment-7060511449`); issue stays OPEN pending installed-host/venue qualification |
| `G010` | **IMPLEMENTED** | Economically qualified "net" evidence ladder + refusal rules published in `gym-core/docs/evidence-and-sampling-contract.md` |
| `G012` | **IMPLEMENTED** | Source-of-truth document hierarchy added to `gym-core/docs/README.md` |

## Lane E — Future Studies, Registered Evidence & Independent Custody (`E001–E022`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `E001`, `E002`, `E003` | **IMPLEMENTED (ACTIVE DEFAULT ADOPTED)** | Genuine final-data custodian architecture (active default: Git-anchored preregistration + untouched future window + clean CI release bundle), preregistration identity schema, and full no-peek threat model published in `gym-core/docs/independent-custody-protocol.md` |
| `E004`, `E006`, `E007` | **IMPLEMENTED & TESTED** | Outcome-perturbation no-peek invariants, overlapping-window refusal, and monotonic pre-read consumption tested in `gym-core/tests/test_no_peek_and_journal_idempotency.py` |
| `E005`, `E008`, `E009`, `E018`, `E020`, `E021`, `E022` | **IMPLEMENTED & TESTED** | Two-trial concurrency budget enforcement (`enforce_two_trial_budget`), digest-bound `release-bundle/1` retaining negative/aborted outcomes, append-only `analyst_peeks.jsonl` in `gym-core/src/gym/services/trial_governance.py` & `tests/test_trial_governance_and_alerts.py` |
| `E010`, `E016`, `E017` | **IMPLEMENTED & TESTED** | `journal_continuity_report` separates process heartbeat vs evidence days, stale quotes, missing days (zero invented returns), and verifies exact Decimal cash/base/fee parity; `Install-AllocationJournal.ps1` & `Install-BreadthJournal.ps1` now propagate nonzero `$LASTEXITCODE` |
| `E011`, `E012`, `E013`, `E014` | **AUDITED ON LIVE ROOT** | Exact live journal & Binance archive continuity receipts recorded in `evidence/2026-11-21-baseline-and-sprint1-receipt.md` §4 (flagged Nov 20 `api.wallex.ir` outage + masked exit codes + `AAPLXUSDT` stale candles) |
| `E015` | **IMPLEMENTED & TESTED** | Cross-process OS file lock + `fsync` append (`gym-core/src/gym/services/_journal_lock.py`) wired into `allocation.py`, `mix_journal.py`, `breadth_journal.py` with 6-way parallel contention tests |
| `E019` | **IMPLEMENTED & TESTED** | `/api/evidence` + Overview UI expose trial budget, checkpoint date, `DISARMED` badge, backup exception, and all 3 forward journals (including `breadth-trend-forward`) |

## Lane M — Market-Data Collection, Provenance & Venue Snapshots (`M001–M022`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `M001` | **MEASURED ON LIVE ROOT** | Full 22-day live archive continuity audit (3 gaps >24h, 15 unclosed segments, collector crash on `2026-11-20T06:29Z`, `gymctl doctor` output) in `evidence/2026-11-21-baseline-and-sprint1-receipt.md` §3 + `MarketDB` `busy_timeout=30000` lock fix |
| `M003`, `M004`, `M005`, `M013` | **VERIFIED & TESTED** | Reconnect overlap multiplicity & `GAP` detection tested in `tests/test_execution_qualification.py`; identical-print ambiguity sensitivity implemented in `maker_queue_fill`; causal availability & late-print fixtures verified across `test_collector*` and `test_no_peek_and_journal_idempotency.py` |
| `M002`, `M006–M012`, `M014–M019`, `M021–M022` | **IMPLEMENTED & TESTED** | `gym-core/src/gym/services/market_quality.py` & `tests/test_market_quality_and_diagnostics_api.py` implement `ingestion_clock_metrics` (p50/p95/p99 lag & backward-clock count), `verify_raw_sql_provenance` (SHA-256 raw↔SQL check), `as_of_rule_index` (explicit missingness per vintage), `symbol_quality_calendar` (completeness separate from freshness), `feed_slo_report`, `parse_structured_fee` (`/v2/structured-fee`), and `parse_margin_ratio` (`/public/ratio/{market}`) |
| `M020` | **IMPLEMENTED & TESTED** | Outage duration (`1h+/6h+/12h+/24h+`) & disk pressure (`<15/<10/<5 GiB`) escalation buckets added to `gym-core/src/gym/services/alerts.py` & `tests/test_trial_governance_and_alerts.py` |

## Lane X — Historical Execution Qualification, Liquidity & Paper Orders (`X001–X024`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `X001–X016`, `X018–X022` | **IMPLEMENTED & TESTED** | Strict executable-net gate (`qualify_executable_net`), non-extrapolating `depth_walk_liquidation`, 6-phase `model_latency_phases`, post-only/cancel-race/identical-print `maker_queue_fill`, causal `simulate_trailing_stop` + `STOP_LIMIT` non-guaranteed exit tests, and `paired_cost_ladder` in `gym-core/src/gym/domain/execution_qualification.py` & `tests/test_execution_qualification.py` |
| `X017` | **VERIFIED** | Market vs limit comparison on shared received quotes/trades verified in existing `test_simulation.py`, `test_limit_print_provenance.py`, and `bench_baseline.py` |
| `X023`, `X024` | **DEFERRED (OPT)** | Require authenticated order lifecycle (`HOST`) or a new preregistered trial within the 2-trial budget (currently saturated at 2/2) |

## Lane F — Exact Money, Inventory, Shared-Cash Portfolios & Risk (`F001–F026`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `F001–F006`, `F008–F009`, `F012` | **IMPLEMENTED & TESTED** | Independent double-entry balance oracle + 400 randomized sequences across base/quote fees, rebates, dust, Decimal precision contexts (`12/28/50`), modern posting refusal, legacy fallback, and standalone-vs-portfolio parity in `gym-core/tests/test_financial_conservation_oracle.py` |
| `F007` | **VERIFIED** | Built `exec-kernel 0.2.0` Rust wheel and passed all 19 differential tests (`2,000+` rational budget-walk vectors) in `tests/test_kernel_sizing.py` (`GYM_RUST_KERNEL=1`) |
| `F010`, `F013–F015`, `F017–F025` | **IMPLEMENTED & TESTED** | `gym-core/src/gym/domain/portfolio_diagnostics.py` & `tests/test_portfolio_token_and_fault_recovery.py` implement `aggregate_portfolio_trade_stats`, `portfolio_inventory_timeline`, exact-zero-residual `economic_portfolio_attribution`, and `qualify_es_tail` (`UNDERPOWERED_TAIL` vs `QUALIFIED_TAIL_SAMPLE` with bootstrap CI); loss-latch monotonicity and valuation bases tested in `tests/test_portfolio_and_margin_contracts.py` |
| `F011`, `F016` | **CONSERVATIVE DEFAULTS ADOPTED** | Keep `legacy` default for frozen-run compatibility while recommending opt-in `inventory/2` for all new research (`F011`); retain deterministic symbol-sorted shared-cash allocation as canonical baseline unless a registered study specifies pro-rata (`F016`) |
| `F026` | **DEFERRED (OPT)** | External portfolio-risk libraries (PyPortfolioOpt/skfolio/Riskfolio-Lib) deferred pending measured need and license/security review |

## Lane S — Sampling, Calibrated Statistics & Multiplicity (`S001–S023`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `S001`, `S002` | **IMPLEMENTED** | Canonical sampling contract, strict monotonicity, date-clustering, and MDE/prospective power gate published in `gym-core/docs/evidence-and-sampling-contract.md` |
| `S003–S011`, `S018–S023` | **VERIFIED & TESTED** | Lo/HAC positive/negative autocorrelation oracles, PSR/DSR monotonicity & small-sample refusal, irregular/duplicate mark counting, SPA-style 2–8 scope + null/positive/placebo controls tested in `tests/test_statistical_calibration_oracles.py` + `test_spa.py` + `test_return_bootstrap.py` |
| `S012–S017` | **IMPLEMENTED & TESTED (DIAGNOSTIC-ONLY)** | `gym-core/src/gym/domain/statistical_inference.py` & `tests/test_statistical_inference_suite.py` implement calibrated Hansen (2005) consistent/liberal/conservative `hansen_spa`, label-interval `purged_cpcv_splits`, `pbo_rank_logit`, anytime-valid `sequential_e_process` with lower-bound refusal & optional-stopping null check, and date-clustered `paired_baseline_uplift` (preserving existing `stationary_spa` labels untouched) |

## Lane C — Margin, Financing, FX Routing & Tokenized Assets (`C001–C018`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `C001–C008`, `C009–C017` | **IMPLEMENTED & TESTED** | `gym-core/src/gym/domain/token_and_margin_audit.py`, `market_quality.parse_margin_ratio`, and `tests/test_portfolio_token_and_fault_recovery.py` + `tests/test_portfolio_and_margin_contracts.py` verify 1x margin-vs-spot reconciliation, debt/collateral currency safety, 4h financing across unsettled crashes, credit-subaccount separation, directional FX spread/fee round-trip checks, `/public/ratio/{market}` parsing, and Wallex token tradability/premium/depth checks without proxy backfilling |
| `C018` | **DEFERRED (OPT)** | Alternate currency/derivative/leveraged constructions deferred pending 2-trial budget availability |

## Lane U — Evidence-First Product, Guided Research, Accessibility & UX (`U001–U037`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `U001–U008`, `U011–U012`, `U015`, `U019`, `U031` | **IMPLEMENTED & TESTED** | Enriched `/api/evidence` + new token-gated read-only routes (`GET /api/quality-calendar`, `/api/slo`, `/api/fx-route`, `/api/action-registry` in `gym-core/src/gym/api/diagnostics.py`) + Overview checkpoint banner, `breadth-trend-forward` card, and `continuityAlerts` attention strip in `workspace-overview.js` & `workspace-config.js` |
| `U033`, `U034` | **VERIFIED & TESTED** | Automated EN/FA vocabulary & `{placeholder}` parity gate across all keys in `tests/test_security_and_drift_contracts.py`; `dir="ltr"` / `digits(...)` preserved for RTL numbers/ISO dates |
| `U009–U010`, `U013–U014`, `U016–U018`, `U020–U030`, `U032`, `U035–U037` | **VERIFIED IN CURRENT WORKSPACE** | Existing SPA routes (`overview`, `markets`, `research`, `account`, `operate`, `rules`, `health`, `safety`, `backups`), keyboard focus, contrast, ARIA labels, offline 3-stage ticket review, and `414.8 KB` native bundle verified via `test_ui.py`, `ui_contract.cjs`, and real Windows `msedge.exe` `browser_smoke.cjs` |

## Lane O — Backups, Operational Diagnostics, Local API & Accepted-Risk Controls (`O001–O024`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `O001`, `O002` | **VERIFIED & DISCLOSED** | Live backup state (`backup_status.sqlite3` 195 restore receipts, 0 research backups, no remote schedule) verified & owner cancellation documented in `disaster-recovery.md` and `2026-11-21-baseline-and-sprint1-receipt.md` |
| `O003–O011` | **IMPLEMENTED & TESTED** | Timed isolated full local restore rehearsal (`10.85s`, `PINNED`, `FULL_RESTORE 74/74`, `cross_host_verified: false`, schema 5→6 migration, `doctor: PASS`, `DISARMED`) + negative fault tests (missing closed segment, open segment cutoff, bad manifest/digest, malformed v2 header, tar path-traversal escape) in `tests/test_recovery_and_isolation.py` + `tests/test_research_backup.py` |
| `O012`, `O013` | **MEASURED** | Live storage runway (`16.15 GiB` free / `33.20 GiB` raw / `10.10 GiB` `market.db`) recorded in `evidence/2026-11-21-performance-and-hygiene-audit.md` |
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
| `I004`, `I006–I011`, `I015` | **DEFERRED WITH EVIDENCE (OPT)** | No measured SQLite/UI bottleneck justifies Parquet/DuckDB, writer actor, DB consolidation, or frontend framework rewrite today |
| `I016`, `I017`, `I020`, `I021` | **VERIFIED** | `complexity_ratchet.py` (`0 problems`), `test_mutation_contracts.py` / `test_mutation_gate.py`, CycloneDX Python+Rust SBOMs (`.\tasks.ps1 sbom`), and honest CI/HOST labels verified |
| `I018` | **COMPLETED** | Full 38-script classification table in `evidence/2026-11-21-performance-and-hygiene-audit.md` §4 (zero blind deletions) |
| `I019` | **IMPLEMENTED & TESTED** | Automated cross-document & runtime drift test in `gym-core/tests/test_security_and_drift_contracts.py` |

## Lane R — Conditional Research & Peer-System Menu (`R001–R013`)

| IDs | Status | Evidence / Artifact |
| --- | --- | --- |
| `R001–R004` | **IMPLEMENTED & TESTED (UNREGISTERED PROTOTYPES)** | Causal multi-horizon `ewmac_forecast`, `vol_target_position` (zero-vol abstention & cost-of-speed gate), `edge_of_band_target`, and per-date `factor_ic_analysis` (with shuffled placebo control) implemented as unregistered paper-only building blocks in `gym-core/src/gym/domain/research_prototypes.py` & `tests/test_statistical_inference_suite.py` (trial budget stays 2/2) |
| `R005–R013` | **DEFERRED (OPT — TRIAL BUDGET 2/2 FULL)** | Active trial budget is full (`funding-confirmed-trend-forward` + `breadth-trend-forward`). Per roadmap & `E022`, no 3rd registered trial or external production dependency (LEAN/Nautilus/hftbacktest/pysystemtrade/Hummingbot/Qlib/Freqtrade/Zipline/vectorbt/PyPortfolioOpt) is added without a measured gap, supersession, registration, and license/security review. |
