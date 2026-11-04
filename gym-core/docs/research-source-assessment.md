# Research source assessment

Reviewed 2026-11-04. This continues the earlier [source assessment](source-assessment.md).
The three ZIPs were moved to `C:\Users\ACER\Downloads\archive` with matching
SHA-256 hashes; `.pi/reviewed-archive-receipt.json` records the moves.
No source application, installer, migration, trading script or dependency was run.
No implementation, credentials, saved accounts, sample market data or model weights
were copied from these sources into Trade.

## Scope and provenance

Every regular ZIP entry was streamed through SHA-256: **4,353 files** total.
The bounded inventory is `.pi/source-review.json`; selected textual entries were
extracted under `.pi/sources/` without importing or executing them. Python AST
parsing succeeded for 256 OpenAlice, 288 Zipline and 21 AITD files. This is file
accounting and module-family review with selected implementation reads. It does
not establish line-by-line correctness, runtime compatibility or exhaustive
absorption of every potentially useful feature.

| ZIP | Files | License notice found | SHA-256 |
| --- | ---: | --- | --- |
| OpenAlice-master.zip | 3,836 | AGPL-3.0 | `43bb4f4bfb05b78de0fb9f0babc518f566639c1137799e88a622026be68ada88` |
| zipline-master.zip | 458 | Apache-2.0 | `151d2b8ffd19b7cb923d26ac6a5a28bcec0d7746481013416ce980e7790d027b` |
| AITD-main.zip | 59 | All rights reserved; notice limits use and requires permission for redistribution/commercial integration | `bc2d3dc812401baf374e7c2179240d34be65baf1486dbc6131779acb9769fc6b` |

## Implemented native extensions

| Capability | Native owner | Contract |
| --- | --- | --- |
| Measurement-aware supplied observations | `services/research_protocol.py` | Optional `measured_at` is distinct from release, revision and actual receipt. It cannot follow publication. Old records and their hashes are preserved; absent clocks remain unknown. NEWS cannot supply this numeric measurement field. |
| Aligned ratios and differences | `services/research_series.py`, shared research dispatch | Exact source/series/subject/kind/unit references; latest measurement and known vintage at the cutoff; both inputs use one read snapshot. Freshness and clock skew are explicit. Missing clocks/inputs, stale values, misalignment and zero divisors yield unavailable values. Differences require identical units. Decimal arithmetic uses 160 significant digits and half-even rounding. |
| Point-in-time candle checks | `services/feed_crosscheck.py`, CLI `candles --as-of`, workbench `candles` | Filters trades by actual receipt and venue candles by fetch time, strictly before the cutoff. Later collector rows cannot prove earlier coverage. The web action reads local data only, caps windows at 31 days and observations at 100,000, and cannot fetch or overwrite candles. Superseded venue vintages are unavailable rather than reconstructed. |
| Portable GUI report | Existing `services/portable_report.py`, `/api/runs/{id}/summary.html` | Downloads the same allowlisted, escaped, script-free HTML as the CLI, behind the operator token. No private notes or account records. |
| Offline review controls | Existing `OfflineReviewJournal`, `api/offline_reviews.py`, account/ticket GUI | Save a canonical preview, acknowledge or reject it once, retain the native hash chain. Web reviews use the actual server clock and cannot backdate. Read and write use the same journal file, including an explicitly supplied journal. No T1 approval, order or money permission results. |

## OpenAlice module decisions

| Family | Useful mechanism and disposition |
| --- | --- |
| `src/core` (74 files), migrations (18) | Typed artifact origins, session/native process identity and mutation fingerprints are useful. Native saved-run/output identities and append-only journals remain owners. No second state hierarchy or donor migrations. |
| `src/ai-providers` (17) | Separate credential reachability from actual model capabilities; unknown capabilities must remain unknown. Existing gateway owns auth, catalog and request validation. Donor model names/limits are not accepted as verified current provider facts. |
| `src/workspaces` (231), `packages/cli` (167) | Session bindings, supervised schedules and native process lifecycle are useful design references. Trade retains bounded jobs and fixed process bridge. Arbitrary terminals, project imports and code injection are outside trading control routes. |
| `src/domain` (108): analysis, calculator, snapshot, simulation, rotation | Explicit dates, source metadata, bounded calculator panels and separation of fetching from math informed the aligned-series interface. General expression execution, equity sector universe and close-only stop simulation are not installed as a qualified Wallex strategy or protective stop. Sector rotation and excursion reports remain potential research extensions. |
| Market-data routing and adapters within `src/domain` | Stable source identity and explicit partial-provider failures are valuable. Native Wallex data portal retains availability ordering and units. No silent vendor replacement, generic provider framework or unsupported asset identity. |
| News collector within `src/domain` | Separate publication from receipt; an RSS item without a publication date cannot be given a fabricated release clock. A real bounded, authenticated/attributed feed adapter remains unimplemented. Donor `res.text()` and regex parsing are not imported. |
| `services/uta` (116), broker packs | Context assembled once before sequential guards; fill identity and WAC bookkeeping are useful references. Keep native custody and exact accounting. Empty-guard dispatch, approximate basis reconstructed from current marks, specialized equity/derivative brokers and mock brokers do not qualify the executor. Actual basis/reconciliation remains open. |
| `packages/ibkr` (735), `packages/opentypebb` (356), UTA protocol (17) | Broker/protocol/provider-specific implementations, generated files and Python references are accounted for. No IBKR/OpenBB runtime or market fixtures imported. Different asset/session/corporate-action contracts need a scoped adapter before reuse. |
| Guardian runtime (23), update lifecycle (20) | PID plus creation time, owner token, heartbeat and exact version/artifact identity are valuable operational mechanisms. Existing Windows service, package verification and recovery gates retain ownership; no second guardian or updater is installed. Installed-host proof remains open. |
| Web UI backend (63), tool registry (46), server (18), services (29) | Explicit authentication, socket identity versus forwarded addresses, fixed tools and activity provenance are useful. Preserve Trade's loopback Host/token controls. Do not copy localhost auth passthrough or remote exposure. |
| Connector service (49), connector protocol (12) | Channel adapters and delivery identity are specialized infrastructure. No remote chat, third-party messaging or credential forwarding is enabled by source review. |
| UI source (968), desktop (75), public assets (172) | Provider failures, recoverable loading states, credential-specific forms, execution history and source labels are relevant UX references. Use the current EN/FA app and gateway; no second React/Electron stack, demo service worker, workspace office, stickers or synthetic dashboard state. Full GUI parity remains open for the documented operations. |
| Defaults, plans, docs, safe playbooks, root, patches, scripts, CI, tests | Inventoried as supporting material. Plans are proposals; donor tests are not Trade evidence. No installer/release workflow is executed and no donor terminal patches or demo harness enters production. Selected tests and playbooks informed boundary review. |

Selected implementation reads include `core/provenance-store.ts`, `core/sealing.ts`,
`webui/middleware/auth.ts`, `ai-providers/model-semantics.ts`, `analysis/simulate.ts`,
`analysis/sector-rotation.ts`, `analysis/calc-v2/evaluator.ts`, market-data reference
term structure, news RSS parsing, UTA guard pipeline and cost basis, guardian
runtime lock, update verification and `ui/src/pages/AIProviderPage.tsx`.

## Zipline module decisions

| Family | Useful mechanism and disposition |
| --- | --- |
| Pipeline (50): loaders, terms, dependency graph, factors, filters, classifiers | Knowledge/event timestamps, explicit missing values, dependency ordering and bounded term outputs are useful. Native measurement/receipt vintages and aligned arithmetic are implemented above. No NetworkX/Pandas/Cython computation engine is added for two-input operations. General factor graphs remain a separate expansion. |
| Data (29), sources (4), assets (12) | Past-only FX lookup, instrument lifetimes, identifier ambiguity and explicit corporate actions prevent backfill errors. Native point-in-time portal/rules remain owners. Equity splits, dividends, calendars, futures rolls and historical bundles are not applicable Wallex price corrections. No adjusted history overwrites raw observations. |
| Finance (22): blotter, commission, slippage, controls, ledger, metrics | Shared per-bar volume limits, incremental fee minima, transaction identity, cash-flow-aware returns and order lifecycle are useful mechanisms. Existing native exact fees, supplied cash-flow returns, paper ledger and durable executor remain owners. Bar-volume impact parameters and simulated fills are not measured venue execution. No log-only risk bypass or unlimited fixed-slippage fill capacity. |
| Gens (5), algorithm/API, protocol | Explicit before-session/bar/end ordering is a useful reference. Preserve Trade's UTC availability/decision order and continuous-market rules. The archived Python 2.7/3.5/3.6 runtime is not installed or presented as compatible with the current environment. |
| Lib (14), utils (39), resources (32) | Specialized array/ranking/adjustment kernels, currency metadata and utilities are inventoried. Standard library and current domain helpers suffice for the native changes. Static resources cannot authenticate current exchange units or fees. |
| Testing helpers, tests, examples, docs, CI/conda/build/root | Included in file accounting. Examples and fixtures remain examples. AST parsing does not prove compilation or numerical parity; donor dependencies/tests/build scripts were not run. |

Selected reads include event loaders and loader utilities, in-memory FX,
volume-share slippage, controls, commission, adjustments, simulation blotter,
ledger, pipeline graph, asset lookup and the minute simulation clock.

## AITD module decisions

| Family | Useful mechanism and disposition |
| --- | --- |
| Config, instances, utilities | Named independent paper sessions and configuration history are useful. Retain native isolated stores and immutable run IDs. No instance directory derived from unchecked user paths, cloning of credentials, plaintext key files or non-atomic configuration writer. |
| Engine, live-trading, exchanges (six files) | Distinguish paper from real accounts, persist decision history and display protection failures. Native money path remains separate. Failed stop-leg warnings, silent input downgrades and cancel-all fallback cannot qualify protection. No exchange leverage or live-mode toggle is imported. |
| Market and candidate source | Deterministic universe screening and explicit invalid-symbol output are useful; existing catalog and supplied-observation screener cover these paths. Do not expose `exec(source_code, scope)` or arbitrary user Python from the browser. Candidate scores remain descriptive, not confidence. |
| Evolution and analysis script | Outcome references and time-limited observation windows are useful; native resolution-time memory already implements a stricter known-outcome contract. Donor terminal price moves and similarity ranks are not actual fills or independent training evidence. Narrative self-learning remains unverified judgment. |
| HTTP client and exchange cooldown | Honor 418/429 and Retry-After, retain cooldown state and distinguish fresh/stale cache metadata. Existing pacing/gateway controls remain owners. Do not copy unbounded reads, raw error-body disclosure, stale-cache-as-current behavior or automatic retries of uncertain orders. |
| LLM provider and prompts | Provider/transport separation, prompt presets and traceable decisions are relevant. Existing gateway owns credential protection and protocol selection. Model text cannot mint execution authority or verified performance. No automatic provider probe or paid call. |
| Server and dashboards | View account/decision history and actual failure state. GUI report and offline journal controls are extended above. Donor code editor, credential JSON settings, reset/flatten routes and remote controls are excluded. New manual import/probe/conversion GUI controls remain explicit unfinished work. |
| JSON defaults, screenshots, docs, root/setup | Inventoried as examples and supporting files. Source screenshots do not prove working native features; default accounts and model decisions are never production data. The source notice is retained as a reuse constraint. |

Selected reads include engine protection validation/fallback, evolution outcome
and lesson generation, dynamic candidate execution, instance path/index handling,
HTTP transport/cache, cooldown persistence, provider request extraction, server
prompt/universe routes and the utility JSON writer.

## Remaining work

Useful source ideas are not all implemented. New data adapters, sector rotation,
excursion reports, general factor graphs, actual holdings/basis reconciliation,
semantic model workflows and remaining GUI operations require additional native
work. The wider execution, RL and operational backlog stays open in the
[implementation plan](implementation-plan.md). File accounting is not a completion
waiver. No further commit or archive move was made in this pass.
