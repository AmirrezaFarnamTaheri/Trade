# Chart and trading-platform source assessment

Reviewed 2026-11-04 after local commit `ffda2e3`. This assessment is a separate
review from that commit. The current [delivery scope](implementation-plan.md)
excludes predictive ML/RL training, neural forecasts, automated model search and
trained-model order execution. Source capabilities below do not change that scope.

## Coverage and provenance

All **3,085 archive file entries** were streamed through SHA-256 and assigned
one of **31 module-family decisions** below. One TradeX entry, `ADX`, is a symlink;
it was inventoried without following or extracting it. Generated bundles, source
maps, large sample datasets, binary WASM, images and other non-text assets were
hashed, not executed. Text extraction was bounded to 4 MiB per file: 2,499 entries.

Review records: `.pi/interface-source-inventory.json`,
`.pi/interface-code-index.json`, `.pi/interface-source-assessment.json`.
Python declarations were indexed by AST; JavaScript/TypeScript/Vue declarations
were indexed approximately by text patterns, not a full language parser. Reads
covered module families and selected implementations, not every line. No donor
application, build, test, migration, strategy, binary or dependency was executed.
No secrets, sample prices, account state, model or donor implementation was copied
into Trade. Nested source instructions and build scripts were treated as data.

| Archive | Entries | Root license evidence | SHA-256 |
| --- | ---: | --- | --- |
| TradeX-chart-master.zip | 1,395 | GPL-3.0 text | `d0d1d176ceeddd460b7c66c42c105189858835aeee7dc85df5863f4f430ae588` |
| QuantDinger-main.zip | 1,242 | Apache-2.0 text | `49c3cd8085df9ac0af6b7141fd8d4d20b03c3398ebe8636f692c22943b830a01` |
| trading-vue-js-master.zip | 275 | MIT in LICENSE.md | `77ef756a1c0e67ab86cf8c0318697d6dfbff6baedc195643253a1150028c5636` |
| solie-main.zip | 173 | GPL-3.0 text | `5c9bd6ef551e29c7818b1078715f30895eb4abd8ddf43f69627c54b2dce18d29` |

QuantDinger has 965 Python files parsed successfully by Trade's installed Python
3.11 parser. Solie has 67 parsed and six rejected for newer syntax in concurrency,
parallelism, conversion, lock, standardization and overlay-popup modules. Solie's
package explicitly requires Python >=3.12; these are compatibility results, not
evidence that its declared supported runtime is broken. Neither chart library was
built or browser-qualified. Root notices do not establish every bundled component's
provenance or automatically resolve integration obligations.

## Most valuable mechanisms

| Mechanism | Native fit and disposition |
| --- | --- |
| Linked price/indicator/equity panes, crosshair and range navigation | **Candidate UI enhancement.** TradeX's renderer/scales/state and TradingVue's pane/overlay architecture suggest synchronized exploration of a saved run. Feed native closed MID bars, preserve gaps, and link markers to actual decision/order identities. Label modeled fills and supplied observations separately. Keep backend calculations authoritative. No chart dependency or replacement frontend framework was installed. |
| Persistent drawings and annotations | **Candidate UI enhancement.** Store annotations by run/output digest, symbol, resolution and timestamp; keep them separate from immutable economic evidence. Imported chart state must be validated and text escaped. A drawn support line must not silently become a trading rule or retrospective signal. |
| Incremental stream updates and bounded chart work | **Candidate optimization.** TradeX stream state and TradingVue DataCube aggregation provide useful patterns. Preserve timestamp identity, out-of-order handling, explicit forming bars, range limits and reconnect invalidation. A chart worker does not qualify source data or establish secure code execution. |
| Versioned strategy-review evidence and server-owned AI context | **Covered substantially** by native verified artifacts, engine/config/output hashes, evidence packets and numeric claim checks. QuantDinger's bounded context assembly and AST source outline/redaction are useful if a future feature actually needs code explanations. Do not import arbitrary strategy code, conversations or credential-bearing client context into a prompt. |
| Cumulative fills, fee units, ownership and execution drift | **Covered partly; acceptance cases retained.** Native supplied-fill comparisons preserve fill IDs, nonfills, partial observations and fee conversion assumptions. QuantDinger's cumulative REST/stream reconciliation, account/strategy ownership shortfalls and native-protection modules add cases for future protected-executor work. No account adapter or live permission was added. |
| Durable commands, inbox claims and fencing | **Candidate for protected runtime integration.** QuantDinger separates HTTP, evaluation, submission and durable coordination. Preserve idempotency, payload/owner identity, lease fencing and unknown outcomes in native owners. A single-host application does not need a Kafka/Redis/PostgreSQL platform solely to reproduce these invariants. |
| Resumable simulation and collection progress/readiness | **Covered partly; useful UX candidate.** Solie separates collection, simulation, strategy and transaction workers and exposes readiness/progress. Native coverage/recovery and immutable experiment attempts already provide the core boundary. Future checkpoints must bind engine/config/data/cursor and preserve pending outcomes; cached pickle state is not a trusted run artifact. |
| Backtest budgets shared across human/agent entry points | **Covered** by native shared CLI/API dispatch, window/observation/bar/trial limits. QuantDinger's range policy is a useful consistency reference. Do not let a new assistant/MCP surface bypass the same native limits. |

These are assessed integration decisions, not promises to add all source features
or claims of completed chart functionality. The reviewed examples do not restore
ML/RL to the delivery plan. Community, payments, referrals, marketplace, other
brokers, derivatives/leverage and donor deployment infrastructure remain excluded.

## Concrete hazards and semantic differences

* TradeX `src/model/validateData.js:validateShallow` checks the endpoints, a random
  row and a small ordering sample. It cannot certify the full history. Its deep
  path checks all rows but permits equal timestamps. Native bar identity, finite
  OHLC validation and availability checks must not be replaced by sampled checks.
* TradeX `Gaps.findFillGaps` inserts null-valued rows and records them as gaps.
  That is a chart representation, not a received observation or executable quote.
  Native warmup resets and gap exclusions must survive visualization/export.
* TradingVue `DataCube` defaults include `scripts: true`, `script_depth: 0`
  (all data) and `ww_ram_limit: 0`. `script_env.js` generates `Function` bodies;
  `script_ww_api.js` creates a Blob-backed worker. Its "sandbox" description is
  not an OS/process isolation or resource-budget guarantee. No user script engine
  or arbitrary worker endpoint is imported into the local app.
* Solie `logic/analyze_market.py:make_indicators` interpolates candle data and
  appends a zero-valued synthetic row. Interpolation can depend on later endpoints;
  those values cannot become native historical decision-time evidence. The native
  pipeline keeps missing bars missing and distinguishes forming/available bars.
* Solie persists collection/simulation state with pickle and generates simulation
  order IDs using `secrets.randbelow`. Its files are not opened as trusted native
  artifacts; its simulation identifiers are not assumed deterministic. Native
  checkpoints would need a validated format and stable input-bound identities.
* Solie `UniqueTask.spawn` cancels the previous task and starts the next without
  awaiting completion. That is suitable only where overlapping cancellation cleanup
  is acceptable. It must not replace native shielding/serialization around durable
  research mutations or protected order submission.
* QuantDinger `dry_run_deviation.py` uses the previous closed candle as an assumed
  signal price and defaults unknown timeframe strings to 60 seconds. This does not
  establish the actual strategy's decision quote or timestamp. Native comparison
  retains the saved modeled order reference and measured/supplied fill clocks.
* QuantDinger's `live_trading/execution_lock.py` dispatch wrapper falls through to
  the wrapped function when credential identity is missing, and bypasses live
  locking for other execution modes. This is a selected-path observation, not a
  claim that all downstream submission guards fail. Native protected live paths
  must reject missing principal/account/payload identity rather than infer it.
* QuantDinger's evidence helpers explicitly reject fills without positive executed
  quantity/price instead of substituting order instructions. Preserve that useful
  distinction. Its default virtual fee/slippage constants remain assumptions and
  do not qualify Wallex fees, spread, depth, ownership or settlement.

## Every module family

The table below partitions all entries, including tests, docs, generated output,
binary/sample assets, support files and the unfollowed symlink. A support grouping
does not assert that every generated bundle or test line was independently audited.

| Decision | Entries | Disposition |
| --- | ---: | --- |
| QD-AI | 24 | Server-owned bounded AI context, sources and tool contracts: reinforce native evidence packets; no autonomous code execution, new provider runtime or predictive ML. |
| QD-API | 178 | Remaining routes, auth/security/settings, notifications, reports, OpenAPI/MCP and utility services: preserve allowlists and credential boundaries, not a second identity/API/database system. |
| QD-BROKERS | 10 | Other broker transports and reconciliation: reference edge cases only, no new account integration. |
| QD-EVIDENCE | 12 | Versioned evidence, measured/model differences, virtual assumptions and portfolio reporting: map to native saved runs, execution quality and rebalance previews; no fallback fill prices. |
| QD-EXECUTION | 128 | Ownership, cumulative fill/fee accounting, recovery, native protection and order locks: valuable acceptance cases for protected execution; no venue authority or derivatives imported. |
| QD-LIFECYCLE | 51 | Durable lifecycle commands, idempotency, leases/fencing, inboxes/checkpoints and process roles: useful invariants; no Kafka/Redis/PostgreSQL deployment added to the single-host app. |
| QD-MARKETS | 74 | Provider/symbol/catalog, schedule, availability and fundamental coverage: candidate provenance/capability contracts; not authenticated Wallex feeds or verified forecast models. |
| QD-PRODUCT | 16 | Payments, referrals, community and marketplace are excluded product scope. |
| QD-RESEARCH | 59 | Backtest budgets, parameter/indicator versioning and authoring review: native registry/experiments cover overlap; automated model search and user-code runtimes stay outside scope. |
| QD-SUPPORT | 690 | Tests, migrations, docs/compliance/deployment, metrics dashboards, scripts, CI and package support: native test/operational case references; no migrations, services or secret-generation scripts run. |
| SO-COLLECT | 3 | Explicit history-gap inventory, acquisition progress, receipt stream and readiness timeout: useful recovery UI ideas; historical repair never changes prior availability. |
| SO-CONCURRENCY | 8 | Unique tasks, process work, locks, requester/stream reconnect: compare cancellation, bounded queue and commit retention against native owners. |
| SO-EXECUTION | 3 | Account/order reconciliation and exchange limits: regression concepts only; Binance futures/leverage is not Wallex spot capability. |
| SO-GUI | 42 | Linked graphs, progress, logs and management GUI: research UX candidates; no Qt desktop framework replacement. |
| SO-SIMULATION | 3 | Chunked/resumable simulation and indicator/decision contexts: native replay/checkpoint concepts only; interpolation and synthetic rows are rejected as decision evidence. |
| SO-STRATEGY | 2 | Strategy versions/configuration and persisted decision/account schemas: use native registry and evidence lineage; no saved Python strategy execution. |
| SO-SUPPORT | 92 | Docs, images/craft UI, examples, packaging and workflow: no application, dependency stack or strategy example executed. |
| SO-UTILITIES | 20 | Time/calendar, formatting, user settings and remaining package utilities: reference constraints, not another mutable store or credential manager. |
| TV-CHART | 57 | On/off-chart overlays, panes, cursor, legends, tools and Vue lifecycle: UI concepts, without a Vue runtime migration. |
| TV-DATA | 9 | DataCube CRUD, aggregation, datasets and sampling: stable timestamp/overlay identity and bounded incremental updates are useful; no unlimited worker or history path. |
| TV-SCRIPTS | 9 | Worker scripting, series and multi-timeframe helpers: performance concepts only; generated Function code is not an isolation boundary. |
| TV-SUPPORT | 170 | Docs, generated distributions/maps, fixtures, test applications and webpack/tooling: no execution or copied dependency stack. |
| TV-UTILITIES | 30 | Time/layout/formatting, assets and app entry: reference only; native availability and locale rules remain authoritative. |
| TX-DATA | 10 | Range selection, validation, stream updates and gaps: useful gap/forming-bar, duplicate and reconnect contracts; no synthetic repairs become observations. |
| TX-INDICATORS | 34 | Indicator overlays and bundled WASM wrappers: use native available feature values; no duplicate strategy math or binary import. |
| TX-INPUT | 24 | Pointer, keyboard, touch, measurement and drawing tools: optional research navigation; no direct order or arbitrary script path. |
| TX-RENDER | 117 | Canvas panes, axes, overlays, legends, crosshair and widgets: UI candidates only; backend remains the source of numeric truth. |
| TX-STATE | 18 | Chart lifecycle, drawings and state persistence: preserve native run/store identity and separate annotations from evidence. |
| TX-SUPPORT | 1102 | Docs, generated pages/search/bundles/cache, assets, examples/data, types, tests and build/package support: static reference only; no sample or generated code enters production. |
| TX-UTILITIES | 25 | Time/number formatting, bounds, compression and definitions: verify UTC/Tehran calendars and exact serialized prices before adaptation. |
| TX-WRAPPERS | 65 | Next/React example and local module wrappers: not adopted; retain the native HTML/JS app. |

## Implementation and archive state

No production code or dependency was changed by this four-source assessment.
The existing eight-module workspace and the ML scope decision remain intact.
The assessment is separate from commit `ffda2e3`; it is not claimed to be included
in that earlier commit. Donor runtime behavior, performance claims and live venue
integrations remain unverified. Archive moves and SHA-256 checks are recorded in
`.pi/interface-archive-receipt.json` after review.
