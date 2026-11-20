# GPT and Gemini review coverage

The source reports, `GPT Review.md` and `gemini review.txt`, were supplied privately and are not stored in this repository. The ranges below partition those supplied files. This index groups recommendations by the evidence needed to close them. It does not mark an untested proposal as a fix. See [review disposition](review-disposition.md) for implemented changes and regressions.

## GPT Review.md

| Source lines | Recommendation or finding | Disposition |
| --- | --- | --- |
| 1-244 | Product, architecture, and newcomer setup | DEMO setup documented. Improve navigation and onboarding in the workspace separately. Preserve separation of observatory and executor. |
| 245-323 | Observation quality, feed comparisons, opportunity cost, strategy explanation and abstentions | Existing quality and abstention reporting covers part of this. Feed authenticity, clock quality, coverage presentation, and signal diagnostics remain open. |
| 324-412 | Execution assumptions, latency, queue, cost attribution, research metrics and trial interpretation | Stale runs, mark spacing, dependence adjustment, and turnover addressed. Queue sensitivity, measured latency, cost uncertainty, and independent validation remain open. Keep negative trial results. |
| 413-578 | Portfolio, margin, FX, page usability, automation, account observations, tickets, executor qualification | Preserve currency boundaries and paper authority. Open: margin debt accounting, FX reporting, guided UI, account evidence age, ticket clarity, cancellation, reconciliation and independent STOP tests. |
| 579-630 | Loopback privacy, route tests, backup and recovery | Uniform response headers added. Public saved-run policy unchanged. Off-device copy and independent restore need an approved destination and a drill. |
| 631-732 | Engineering findings, roadmap and product claims | Ruff pins and portfolio limit corrected. Edge passed; Linux Chrome was not verified locally. No funded-performance or host qualification claim. Complexity work remains open. |
| 733-1235 | Peer projects, profitability, costs, statistical power, licensing, outside dependencies | Independent edge not established. Prefer targeted tests and research oracles over wholesale ports. Open: capacity, slow-strategy robustness, selection adjustment, minimum detectable effect, and prospective evidence. License selection needs the owner's decision. |
| 1236-1423 | Cleanup, docs, translations, action registry and archive | Executor source/installed claims separated. Retain evidence and historical reproducers. Open: script inventory, stable translation keys, server-owned action manifest, and narrower modules. Do not delete installers or reproducers without reference checks. |
| 1424-1704 | UI redesign, navigation, tables, guides, narrow layouts and accessibility | Open: saved-run filters, timeline, scorecard, decision explorer, quality calendar, cost lab, guided forms, loading states, keyboard and RTL checks. Verify the same workflows on Edge and Chrome. |
| 1705-2010 | Financial accounting, liquidation versus marking, point-in-time specs and attribution | Report missing constraint fields and label fee-adjusted bid estimates as model-only. Strict gate, depth-constrained liquidation, and model attribution remain open. |
| 2011-2238 | Passive queues, latency, impact, fee vintages, portfolio ordering, tail risk, FX and token references | Open. Benchmark causal fill scenarios, disclose samples, preserve same-time determinism and currency units. Last-known portfolio marks already marked provisional. |
| 2239-2448 | Margin and statistical qualification, signal diagnostics, independent custody, peer adoption | Local holdout overlap fixed for the long-history study. Independent custody, margin invariants, predictive diagnostics, and calibrated inference remain open. |
| 2449-2675 | Risk matrix, contracts, verification program, phases and build/buy recommendations | Map to the corresponding rows above. Still need versioned financial contracts, scenario ladder, accounting parity, selection custody, and executor crash recovery. Keep experimental and real execution evidence distinct. |

## gemini review.txt

| Source lines | Recommendation or finding | Disposition |
| --- | --- | --- |
| 1-139 | Review scope and engine walkthrough | Context. No implementation prescribed. |
| 140-155 | Small positions, fees, SPA, journals, portfolio metrics, blended signals, exact-hash custody and precision | Turnover and cross-market fee-context handling fixed. Local holdout overlap and HRP boundary rounding fixed. Open: global trial-family counting, stops, dust, exact historical costs, journal locking, unbounded indicators, snapshot identity and richer replay-cost serialization. |
| 156-177 | Collector pressure, schema, retries, adapters, backup and monitoring | REST pacing, redirect rejection, two range indexes, and nested SQLite snapshots fixed. Open: rollover hashing, catalog/trade batching, same-second reseeding, proxy policy, account parsing, backup custody, runway, and alert health. |
| 178-200 | Operator surfaces, API, browser and CLI | Refusal exit 2 already worked. Header and comparison errors fixed. Evidence diagnostics close the DB. Open: admission policy, API I/O, UI parity, packaged policy and link-file handling. |
| 201-241 | Executor settlement, locks, recovery, Windows service and priorities | Source/installed distinction corrected. Open: multi-order settlement, lock split, durable recovery, retention, permission checks and real lifecycle qualification. |
| 242-361 | Second audit of engine and statistics | Mapped to 140-155. Bartlett taper fixed hard truncation. Position, fee and historical portfolio semantics still need versioned replay fixtures. |
| 362-387 | Trial record, power and forward studies | Preserve frozen studies and negative evidence. Open: date-clustered tests, prospective journal changes, exact model parity and maker study. |
| 388-413 | Storage and ingestion details | Mapped to 156-177. No production migration or backup scheduling performed. |
| 414-434 | Detailed UI, API and CLI defects | Mapped to 178-200. Hot asset updates are tested; a startup-only cache would change behavior. |
| 435-528 | Executor security, performance and lifecycle | Mapped to 201-241. Do not relax account balance evidence to close a simulated deadlock. Preserve STOP ordering across sends and verify torn-commit cases. |
| 529-562 | CI, dependency audit, and priority order | Existing required checks remain. Open: independent installed-host and supply-chain evidence plus the unresolved items above. |
| 563-660 | Profitability and peer adoption | No real-money profit established. Proposed integration is research design, not dependency approval. Do not add peer frameworks to the executor. |
| 661-748 | Deletion, maintenance, UI and accessibility | Onboarding and doc corrections done. Open: candidate deletion/reference checks, custody retention, pilot UI parity, control translation, RTL, accessible charts and keyboard. |
| 749-865 | Financial audit, staged pipeline, and external research libraries | Mapped to engine, executor, and peer rows. Keep exact money, point-in-time data, and authority boundaries. Open: model and accounting parity and research-oracle comparisons. |
| 866-1248 | Hansen SPA, Newey-West, CPCV/PBO, sequential e-values and tests | Taper and bootstrapping resolution improved. A consistent Hansen test, purged folds with selection accounting, and an e-process under a justified null remain open. Do not treat bootstrap significance as eligibility. |
| 1249-1515 | Causal EWMA/EWMAC, position buffer, diversification and cost speed limit | Research proposal. Needs fixed parameters, causal data, execution-aware turnover, Decimal parity, and separate preregistration. |
| 1516-1839 | LEAN-style boundaries, Parquet, dual latency/queue, settlement, locks and recovery clones | Open. Keep typed boundaries, distinguish modeled and observed fills, and prove old/new data and execution semantics before replacement. |
| 1840-2413 | Lock-split patch, Parquet export CLI and maker trial runner | Open. Treat supplied patches as proposals. Require STOP/crash tests, causal export/restore evidence, and registration before scoring. |
| 2414-2766 | Executor tests, dual DataPortal, source hygiene, CLI refusal, middleware and UI | Exit 2 confirmed, response headers fixed, and literal NULs removed from the Rust test. Open: lock/settlement tests, backend equivalence, unwired Rust module checks, global Origin policy, and remaining UI parity. |
| 2767-3024 | Checkpoint scorecard, timeline and SQLite consolidation | Open. Derive progress from real receipts rather than static claims. Consolidation requires compatibility, scratch restore, interruption tests and an approved cutover. |
| 3025-3306 | Single writer and ES modules | Open. Verify queue overflow, durability and data ordering before a writer cutover. Preserve bilingual and security behavior in any JS migration. |
