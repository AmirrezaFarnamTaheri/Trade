# Indicator, charting and execution library assessment

Reviewed 2026-11-04. The fourteen supplied Downloads ZIPs contain **9,257 file
entries**, all hashed and assigned to **64 module-family decisions** below.
**530 indicator-related source files** are separately catalogued, including
helpers and interfaces; this is not a count of distinct formulas.

This is complete file accounting, module-family assessment and selected source
inspection, not an audit of every line or a claim that every useful feature has
been implemented. No donor application, strategy, installer, compiler, test suite,
model, exchange server or database was executed. No donor implementation,
dependency, credential or market observation was imported into Trade.

The ignored review records are `.pi/trading-library-inventory.json`,
`.pi/trading-library-code-index.json`, `.pi/trading-library-assessment.json` and
`.pi/trading-library-indicator-catalog.json`. Bounded text extraction covers
8,387 entries, with SHA-256 checked against the inventory. OpenTrader's
`packages/prisma/.env` symbolic-link entry was hashed without following it or
reading its target. Python was syntax-parsed where possible;
Java, Julia, Go, C/C++ and JavaScript declarations use approximate static indexing,
not compiler validation. Donor AGENTS, skills and prompts are review data only.

| Archive | Entries | Local license evidence | SHA-256 |
| --- | ---: | --- | --- |
| ta4j-master.zip | 1,890 | MIT declaration in pom.xml and SPDX source headers | `103006d15d9554081000361e9ac2285ad105e8eff03e80672c1ce37795b407a6` |
| Planar.jl-master.zip | 985 | Apache-2.0 root text; nested components have their own notices | `1c7f02b4ef162907add1cfd04a8a24ec3781fcf451d82b7b6adf8c44100058c4` |
| technicalindicators-master.zip | 529 | MIT | `bf149bb011e765b457edf958bbc7fce0d3d637e0bf2ef3d85c095e2d9dba0c0c` |
| lightweight-charts-master.zip | 2,213 | Apache-2.0 plus NOTICE and README attribution/link requirements | `958f124813223532a52074c7c798c94ad1d717d1bc83451b233939ea2379a5b9` |
| cassandre-trading-bot-development.zip | 566 | GPL-3.0 root text | `e356a1b4b1bf643f0b913c8f18ec44e3dd9e93e84e6defb13b821ae73857624c` |
| opentrader-dev.zip | 683 | Apache-2.0 | `7bfcf7e42edec1c8277701514238b48ab75aa747a0afa10e8f30ef6650ddd922` |
| ta-master.zip | 79 | MIT | `b258f8dd45d2740ceb4d3e1e4debecd7bf5c6de99c160fb2b219ed0ff8b4c668` |
| KLineChart-main.zip | 981 | Apache-2.0 plus NOTICE and third-party licenses | `fbede672159e676b484c5f53ddb9682962a1f1997a62a9139d733acaa0ee26e8` |
| kelp-master.zip | 424 | Modified Apache-derived license; retain exact text | `4b26a62dd220ec0338826f7bc8b3492636c8563112465a83bf84604d4d9bd6f8` |
| QtBitcoinTrader-master.zip | 348 | GPL-3.0 text and source OpenSSL exception notices | `e11b7c5a90e7cdf96eeeb59403cfc0f4cb6cd04ac6722eb651c4148eaf45796c` |
| crypto-trading-bot-master.zip | 177 | MIT text | `44b8014f86db402605688c8259e263784161c6d2784a4fd8fc5b1961900a209f` |
| gunbot-quant-main.zip | 75 | MIT | `eb95f916414a619cd51a5757fe3cad98e80693c892985d260f132d08eca28c0b` |
| node-binance-trader-master.zip | 72 | MIT | `aaea66ffdb90f1a37d4bbcfca9788b05fc28406c1b407adf96a9ba9af8cd52c4` |
| viabtc_exchange_server-master.zip | 235 | MIT | `2e38a919b1c024e9e735c30ae67628a9584a81f52678f921d8697cb4019442a0` |

License entries record evidence in these particular ZIPs, including modified
licenses and notices. They do not establish permission to copy all bundled or
vendored content. No code was copied into production.

## Highest-value native fits

These are integration candidates with concrete acceptance conditions, not new
delivery promises. Existing implemented behavior and open operational gates remain
described in [the implementation plan](implementation-plan.md) and
[research workspace contracts](research-workspace.md). Predictive ML,
reinforcement learning and automated model search remain outside current delivery.

| Priority | Mechanism and sources | Native owner and acceptance condition |
| --- | --- | --- |
| 1 | Stable event identities, order/trade reconciliation and balance conservation: ViaBTC, Cassandre, Planar, ta4j | Existing executor ledger/state machine and account observations. Duplicate, reordered, partial and corrected fills must conserve available + reserved balances with explicit fees. Unknown execution stays unknown. Acknowledgement must follow durable recording; reconstruction must not grant spending authority. |
| 2 | Indicator contract and correction fixtures: ta4j, technicalindicators, Python ta | `domain/indicators.py`, `technical_features.py` and `technical_strategies.py`. Specify seed, first valid bar, flat input, gaps, input order and rounding. Batch versus streaming and full-history versus bounded-cache results must agree under the same declared contract; a correction must invalidate every affected dependent value. |
| 3 | One decision chart with controlled historical corrections: Lightweight Charts or KLineChart | Existing `ui/app.js` and `ui/research.js`, backed by saved replay/coverage. Keep missing data visibly missing; distinguish live last-bar replacement from historical revisions. Link markers to saved decision IDs and show receipt/decision/execution times separately. Verify keyboard access, resize, cleanup and bounded data retention before adopting either library. No chart migration was made. |
| 4 | Cancellation that remains available when entry constraints fail: Kelp, QtBitcoinTrader | Protected executor and operator controls. Stale prices, minimum sizes and entry filters may block new exposure but must not suppress permitted cancellation/stop. Retry and acknowledgement require explicit state; no UI-only emergency stop. |
| 5 | Explainable closed-bar screening and matched experiment comparison: Gunbot Quant, OpenTrader, crypto-trading-bot | `services/research_market.py`, `experiment_registry.py`, native paper replay and robustness laboratory already cover the core fit. Potential additions are finer exclusion reasons, exit-reason breakdowns and revision identifiers, with comparable windows, retained failures and identical cost assumptions. |
| 6 | Typed bounded strategy context and clear rule/status views: OpenTrader, Cassandre, QtBitcoinTrader | Existing rules, replay snapshots and shared `research_actions.py` CLI/API dispatch. Any additional control must use a fixed native action and display its real readiness/result; embedded JavaScript/Julia evaluation is not adopted. |

The indicator catalogue is a discovery aid. Adding hundreds of overlapping
indicators or a second trading engine would add maintenance without establishing
better decisions. Only a feature with an explicit native consumer, contract and
verification belongs in implementation. Derivatives, margin borrowing, Stellar
wallet signing and hosting an exchange are not implied by this review.

## Selected source findings and boundaries

Source paths below are relative to their archive roots, extracted under ignored
`.pi/sources/<archive-name>/`. Each entry hash is retained in the inventory.

### ta4j

`ta4j-core/src/main/java/org/ta4j/core/indicators/CachedIndicator.java` explicitly
tracks recursive dependencies, a moving cache floor and last-bar invalidation.
`indicators/RSIIndicator.java` returns NaN before its unstable-bar count; after
warm-up, zero gain and zero loss produce **0**. Native `domain/indicators.py`
uses fifteen prices for its first fourteen-change Wilder RSI and **50** for a
flat series. Neither a shared name nor a Wilder label establishes parity.
`src/test/.../indicators/RSIIndicatorTest.java` supplies useful moving-window versus
unbounded-history and warm-up acceptance cases; the test was read, not run.

`backtest/BarSeriesManager.java` defaults to next-open execution **and zero cost**.
`TradeOnNextOpenModel.java` resolves a later execution target; the separate
current-close model is a different assumption. Native observed bid/ask, latency,
fees and quote readiness must remain explicit. `ExecutionFill.java` and
`ExecutionMatchPolicy.java` separate intents/fills, fees/correlation and
FIFO/LIFO/average/specific-lot matching. Those are useful account/basis test
cases, not evidence that native authenticated lot accounting is complete.

### Planar.jl

The split between `PlanarCore` data/orders/executors/simulation and `Planar`
paper/live/watchers is useful for mode ownership. In
`Planar/src/PaperMode/orders/limit.jl`, modeled fills are capped by observed trade
amount and unfilled order quantity; tasks are registered and reservations
released on close/error. However, `_asdate` substitutes the current clock when
`datetime` is missing. The loop advances a timestamp cursor from the last trade;
duplicate trade identities and equal-timestamp paging need dedicated contracts
before using this mechanism. Trade-based paper fills still do not prove queue
priority or actual venue fills.

`Planar/src/LiveMode/orders/sync.jl` temporarily maximizes local cash and clears
commitments while reconstructing open orders. That reconstruction technique must
never escape into native spendable balances; replay/reconciliation needs a
separate non-authoritative state. Selected
`PlanarCore/src/Simulations/slippage.jl` overloads reference `df` without defining
it locally; that is an unresolved source concern, not a runtime test result.

The CCXT gateway separates processes, requests, heartbeats and timeouts.
`ccxt-gateway/src/ccxt_gateway/core/protocol.py` carries API key/secret fields in
its request envelope. `api/rest.py` accepts credential query parameters and
routes exchange/method calls; `exchange/methods.py` exposes name-based helpers.
These interfaces are not a replacement for native fixed action allowlists,
request bounds, credential custody or authorization. No gateway was launched.
Optimization, feature-selection, synthetic research and remote-command modules
are accounted for without expanding current scope.

### technicalindicators and Python ta

`technicalindicators/src/oscillators/RSI.ts` supports batch and `nextValue`, returns
only post-lookback outputs and rounds ordinary RSI results to two decimals.
Its zero-loss branch gives **100**, including the flat gain/loss case. Reversed
input handling temporarily reverses the supplied arrays and restores them in the
normal path; native immutable input expectations need explicit tests. Tests under
`test/oscillators/RSI.js` provide fixture ideas. Deterministic candles and chart
transforms are distinct from the TensorFlow pattern detector and `tf_model`
artifact, which are excluded from current delivery.

`ta-master` is the Pandas-based Python `ta` package, distinct from the previously
reviewed Rust `ta-rs`. `ta/utils.py::_check_fillna` can forward-fill and, for the
`-1` sentinel, backward-fill earlier missing results from later values. Enabling
fill also lowers rolling minimum periods. `ta/momentum.py::RSIIndicator` uses
exponential recurrence from its initial transformed changes and returns **100**
when its smoothed loss is zero. Native warm-up/gap policy must not silently
inherit these choices. CSV expected outputs remain test fixtures, not qualified
market history.

### Lightweight Charts and KLineChart

Lightweight Charts has data/series/pane separation, whitespace bars, markers,
primitives and rendering fixtures. `src/model/data-layer.ts` rejects an older
normal update; explicit historical updates require an already existing point.
`src/model/data-validators.ts` skips ordering and value-type checks in production,
so a native ingestion boundary must validate independently. The local README
requires the NOTICE attribution and a user-visible TradingView link if used;
this review did not install or select the library.

KLineChart's `src/Store.ts` appends newer single bars, replaces an equal-time last
bar and leaves older single updates unapplied in the inspected branch. Its
loader has subscribe/unsubscribe lifecycle and separate historical loading.
Drawings, axes, hotkeys and tooltip extensions are useful presentation references.
Timestamp interpolation and nearest-index lookup are chart-coordinate operations,
not proof that a market observation existed or was available then. NOTICE also
records third-party attribution. Use a single chart owner if implementation is
later selected; neither chart is an exchange adapter or trusted indicator engine.

### Cassandre and OpenTrader

Cassandre's `spring-boot-starter/autoconfigure/src/main/.../batch/TradeFlux.java`
filters trades to known orders, compares stable trade IDs and persists new or
corrected values. That is useful reconciliation structure; trades whose orders
are not yet known require an explicit native unresolved state and recovery.
`util/dry/TradeServiceDryModeAOP.java` adjusts modeled balances at last ticker
price and reports open database orders as filled. This is dry-mode behavior,
not measured liquidity, fee, partial-fill or service-isolation evidence.
GraphQL, position services, reactive batches, DTOs/mappers, migrations, archetypes
and mock helpers are all assigned dispositions without importing their stack.

OpenTrader separates typed bot contexts/processors, exchange normalization,
storage/event bus, simulation and CLI/RPC controls. In
`packages/backtesting/src/market-simulator.ts`, market entry orders are filled at
the current candle close and limit entries use the close comparison and limit
price, with a direct placed-to-filled transition. Those outcomes cannot establish
partial fills, queue position or observed execution latency. Templates, indicators,
DB/Prisma schemas and daemon tooling are references only; no unseen submodule
content was fetched or assumed present.

### Kelp and QtBitcoinTrader

`kelp/plugins/orderConstraintsFilter.go` deliberately keeps zero-amount deletion
operations and can transform an existing noncompliant offer into deletion.
`plugins/submitFilter.go` documents merge/order rules for existing offers and
new operations. `trader/trader.go` has error-cycle offer deletion and an exit
fallback; even this distinguishes submission from successful cancellation.
Candidate native invariants are cancellation surviving entry filters and
liability/reservation reconciliation. Stellar ledger liabilities, transaction
sequence rules, float conversions and signing remain venue-specific. Kelp's root
license is explicitly modified/Apache-derived; do not label it ordinary Apache.

QtBitcoinTrader supplies order/depth/history models, explicit rule fields,
precision settings and network/time-error presentation. Its
`src/script/scriptobject.cpp` invokes an embedded engine's `evaluate`; a local
script engine is not a constrained strategy interface or service boundary.
`src/julyhttp.cpp` uses peer verification and forwards SSL errors in the selected
path; this is not a complete transport security review. `src/timesync.cpp`
adjusts wall-clock time with a shift, which is distinct from a monotonic timeout
clock. No profile login, updater, desktop app or exchange connection was run.

### crypto-trading-bot, Gunbot Quant and node-binance-trader

`crypto-trading-bot/src/modules/strategy/v2/typed_backtest.ts` constructs decisions
from the current close and computes signal-price percentage returns/capital,
including closing the final open position. Those are modeled assumptions;
the inspected reporting path does not establish bid/ask, queue, latency or fees.
`src/utils/resample.ts` groups candles by closing boundary and removes the oldest
aggregate, but does not require the newest aggregate to contain a complete set of
constituents. Native readiness must check coverage and closure, not infer them
from a future closing timestamp. Its year conversion also multiplies
`60 * 24 * 7 * 356`; do not import that duration. Typed strategy context, profile
order controls, repositories, validation and UI are retained as references.

Gunbot Quant has scenario/backtest/screener history and exit-reason reports.
`gunbot_quant/core/backtest_engine.py` enters/exits at the indexed close with
quantity `cash / price` in the inspected loops. `calculate_stats` returns initial
capital and zero return whenever the trade table is empty, even if a supplied
nonempty equity curve has an open position. It annualizes per-bar returns using
sqrt(365), which requires a matching sampling assumption. Native mark-to-market
and fee/latency-aware comparisons must not inherit these shortcuts. Dynamic
optimization and its JS vendor strategies remain outside current delivery.

`node-binance-trader/src/trader/trader.ts` serializes execution through an in-memory
queue, but validates/selects the trading sequence before enqueueing. That alone
does not provide atomic fresh checks or durable duplicate suppression. The file
explicitly leaves minimum/maximum quantity checks as TODO, and `roundStep`
truncates floating-point decimal text rather than enforcing an arbitrary exact
lot step. Signal/strategy identity and ambiguous open trades need explicit native
rejection/reconciliation. Borrow/repay and external notifications were not enabled.

### ViaBTC exchange server

`matchengine/me_market.c` compares decimal prices and order IDs for order priority
and tracks maker/taker fees and remaining amounts. `me_balance.c` separates
available and frozen values with nonnegative/insufficient checks;
`me_update.c` rejects a repeated business key before applying a balance update.
`me_persist.c` and `me_load.c` provide snapshot plus operation-log reconstruction.
These support conservation, deterministic replay and duplicate-update test ideas.

Durability is a material limit: `me_server.c` mutates a limit order, calls
`append_operlog` and replies. `me_operlog.c` appends to an in-memory list and
flushes asynchronously through a timer/job queue. The selected path does not wait
for the database write before acknowledgement; do not transplant it as a durable
money-action contract. Native protected execution needs its existing durable
ledger boundary. Gateway/network/history/marketprice/alert code, SQL, vendor
utilities and Python-2-era test clients are inventoried; this exchange server was
not built, deployed or contacted.

## Complete file-family dispositions

Each inventoried entry has exactly one assignment in the review JSON. Generated
bundles and bindings are accounted for without counting them as independent
implementations. Support groups include non-code assets, documentation, test
fixtures, packaging and CI; selected deep inspections above identify the limits.

| Source | Family | Entries | Decision and native fit |
| --- | --- | ---: | --- |
| ta4j-master | TJ-INDICATORS | 436 | Indicator composition, recursive dependency readiness and cache invalidation. Native indicators keep explicit seed/flat-series semantics; no Java runtime or wholesale catalogue import. |
| ta4j-master | TJ-EXECUTION | 202 | Execution timing, cost policies, walk-forward windows and matched baselines. Reference native paper/research/experiment owners; zero-cost defaults and current-close fills are not native assumptions. |
| ta4j-master | TJ-CORE | 224 | Bars/builders, trading records, fill/intent correlation, lot matching, rules, numeric types and acceleration. Candidate contract cases for correction, partial exits and event ordering, not an accounting replacement. |
| ta4j-master | TJ-TESTS | 947 | Independent indicator, execution, window and cache fixtures plus examples/benchmarks. Selected reads only; neither passing donor tests nor numerical parity is claimed. |
| ta4j-master | TJ-SUPPORT | 81 | Remaining docs, releases, build/release tools, CI and source instructions accounted for; no Maven, hooks or source agents launched. |
| Planar.jl-master | PL-CORE | 187 | Time/data/exchange adapters, precision, order types/executors, strategy instances and simulation. Reference native availability, reservations and paper contracts; no Julia/CCXT migration. |
| Planar.jl-master | PL-PAPER | 9 | Trade-driven partial paper fills, tracked tasks and reserved-volume release. Missing trade timestamps and trade deduplication require stricter native contracts. |
| Planar.jl-master | PL-LIVE | 46 | Watchers, trade/order/balance reconciliation, cancel/send/sync/wait. Reference recovery tests only; temporary maximum balances during reconstruction cannot become spendable authority. |
| Planar.jl-master | PL-FEEDS | 72 | Incremental OHLCV/orderbook/provider watchers, download/cache/merge and source metadata. Candidates for gap/receipt/correction cases; no provider connection or data fabrication. |
| Planar.jl-master | PL-GATEWAY | 95 | Gateway protocol, subprocess lifecycle, timeouts and API bridges. Keep native fixed allowlists and credential custody; no generic remote exchange-method dispatcher. |
| Planar.jl-master | PL-RESEARCH | 70 | Statistics, optimization and feature selection. Descriptive statistics/window cases retained; automated search, ML and derivatives expansion excluded from current delivery. |
| Planar.jl-master | PL-HOST | 145 | Remaining engine/remote/REPL/dev/test/package surfaces. Lifecycle and errors are references; no arbitrary Julia strategy loader or Telegram trading authority. |
| Planar.jl-master | PL-SUPPORT | 361 | Docs, examples, synthetic research, vendored sources, package manifests, scripts and agent instructions accounted for; none executed. |
| technicalindicators-master | TI-ML | 3 | TensorFlow pattern inference and model artifact retained as inventory only; predictive pattern models are outside current delivery. |
| technicalindicators-master | TI-FORMULAS | 89 | Streaming/batch averages, momentum, directional, volume, volatility, deterministic candles, chart transforms and helpers. Candidate formula-contract fixtures; undefined lookback offsets and rounding must stay explicit. |
| technicalindicators-master | TI-TESTS | 131 | Seed, reverse-input, nextValue and candle fixtures. Selected reads/static index only; no runtime or equality claim. |
| technicalindicators-master | TI-DISTRIBUTION | 269 | Generated JS, bundles, declarations and bindings are duplicate distribution surfaces, not independent numerical evidence. |
| technicalindicators-master | TI-SUPPORT | 37 | Docs, scripts, metadata/build/CI and assets inventoried; no model/dependency install. |
| lightweight-charts-master | LC-DATA | 13 | Ordered data, whitespace gaps, latest versus historical correction and time conversion. Native chart adapter must validate inputs in production and preserve original availability. |
| lightweight-charts-master | LC-CHART | 240 | Series/panes/scales/crosshair, canvas/renderers, marker plugins, primitives and lifecycle. Candidate decision chart; one chart choice, not a second source of trading truth. |
| lightweight-charts-master | LC-EXTENSIONS | 924 | Drawing/custom series, comparison, indicators, interaction demos and package tooling. Evaluate selected UX mechanisms; examples do not establish accessible native behavior or trusted indicators. |
| lightweight-charts-master | LC-TESTS | 533 | Rendering/data/API/e2e fixture surfaces inventoried and selectively inspected; no browser/build execution. |
| lightweight-charts-master | LC-SUPPORT | 503 | Website/docs, attribution/NOTICE, assets, debug/build/CI and source instructions. Preserve notice and user-visible link requirements if adopted. |
| cassandre-trading-bot-development | CA-DRY | 4 | Explicit dry/live separation, simulated balances and fills. Do not import immediate last-ticker fills or classify dry balances as authenticated holdings. |
| cassandre-trading-bot-development | CA-CORE | 136 | Order/trade/position DTOs/entities, strategy services, reactive polling, repositories/mappers and migrations. Reference stable identities, reconciliation and position events; no Spring/XChange stack transplant. |
| cassandre-trading-bot-development | CA-TESTS | 219 | Replay fixtures/test helpers/archetypes. Test mocks stay source references; no sample credentials, database or synthetic observations enter Trade. |
| cassandre-trading-bot-development | CA-API | 57 | GraphQL authentication/schema/account/order/position queries and tests. Native fixed CLI/API actions remain authoritative; no alternate API or credential model. |
| cassandre-trading-bot-development | CA-SUPPORT | 150 | Documentation, utility tests, starter/build/security/CI support inventoried; no Java installation or migration execution. |
| opentrader-dev | OT-SIMULATION | 20 | Market simulator, in-memory exchange, reports and debugging tables. Useful explicit status diagrams; close-price all-at-once fills are not execution-quality evidence. |
| opentrader-dev | OT-STRATEGY | 171 | Typed strategy context, task processors, lifecycle/events and grid/DCA templates. Candidate bounded context and explicit reason views; no arbitrary strategy evaluation or automatic grid trading. |
| opentrader-dev | OT-EXCHANGE | 28 | Order normalization, polling/watch APIs and vendor adapters. Reference unknown/partial/cancel cases; generic CCXT support is not Wallex qualification. |
| opentrader-dev | OT-STORAGE | 109 | Persistence schemas, domain types and events. Reuse native ledger/registry owners; no competing state store or migrations. |
| opentrader-dev | OT-HOST | 262 | CLI/daemon/RPC, lifecycle, credentials and logs. Candidate GUI/CLI parity patterns; no daemon launch, passwords or external resources changed. |
| opentrader-dev | OT-SUPPORT | 93 | Build/CI/release, package metadata, sample configs and remaining support. Missing submodule content is not invented or fetched. |
| ta-master | PYTA-FORMULAS | 8 | Pandas trend/momentum/volatility/volume/return indicators and wrapper. Reference names and independent formula fixtures only; fillna and seeding change semantics. |
| ta-master | PYTA-TESTS | 38 | Expected-output CSV and class tests; data remains donor fixtures, not qualified market history. |
| ta-master | PYTA-SUPPORT | 33 | Docs/examples/assets, requirements/build/CI and license accounted for; no Pandas dependency added. |
| KLineChart-main | KL-EXTENSIONS | 70 | Drawings/annotations, figures, hotkeys, axes/themes and extension registries. Candidate event-linked annotations and readable price scales; arbitrary extensions get no money authority. |
| KLineChart-main | KL-CHART | 85 | Loader/subscriptions, Store timestamp behavior, panes/canvas/indicators/tooltips and lifecycle. Reference stale-stream cleanup and replay navigation; chart coordinates are not receipt timestamps. |
| KLineChart-main | KL-SUPPORT | 826 | Docs/examples, notices/third-party licenses, build/debug/CI and skills accounted for. Source instructions are not authority; no chart framework installed. |
| kelp-master | KE-STRATEGY | 63 | Composable maker/price/volume/order filters, balanced/mirror/TWAP strategies, exchange/feed adapters and tests. Most useful is allowing cancellation when entry filters fail; no DEX/margin expansion. |
| kelp-master | KE-ENGINE | 22 | Offer lifecycle, constraints, liabilities, shutdown and precision. Candidate reservation/cancel invariants; Stellar liabilities and wallet keys are not Wallex balances/custody. |
| kelp-master | KE-HOST | 214 | Bot lifecycle/status/forms and CLI surfaces. Reference explicit stop/status parity; no GUI replacement or automatic live submission. |
| kelp-master | KE-STORAGE | 78 | Config/metrics/database, transaction helpers, API compatibility and queries. Reference provenance/recovery; no database/network daemon started. |
| kelp-master | KE-SUPPORT | 47 | Examples/tests/resources/scripts/packaging and custom license accounted for. License is Apache-derived, not silently classified as standard Apache-2.0. |
| QtBitcoinTrader-master | QT-EXCHANGE | 18 | Vendor parsers, HTTP/SSL errors, nonces and time synchronization. Candidate clock/failure displays; no Qt/credential/network stack imported. |
| QtBitcoinTrader-master | QT-RULES | 25 | Rule groups, conditions/actions, execution states and embedded script engine. Candidate clear bounded rule UI; arbitrary engine.evaluate is not a safe native strategy contract. |
| QtBitcoinTrader-master | QT-ACCOUNT | 37 | Orders/cancel/history/depth models and profile login. Useful grouping/precision/status UX; local password UI does not establish service isolation. |
| QtBitcoinTrader-master | QT-SUPPORT | 268 | Desktop forms, translations, settings, updater/build/resources and remaining helpers accounted for. No application/updater/install code executed. |
| crypto-trading-bot-master | CB-STRATEGY | 26 | Typed signal context, strategies/backtesting, candle aggregation and TA validation. Candidate trace reasons; incomplete newest aggregate and same-close returns are not trusted native evidence. |
| crypto-trading-bot-master | CB-OPERATIONS | 39 | Exchange lifecycle, profile orders, CLI/HTTP/UI actions and notifications. Reference operator parity/status; no notification sends or new exchange authority. |
| crypto-trading-bot-master | CB-DATA | 15 | SQLite/candle/ticker/signal repositories, caches, price services and queues. Reference bounded data lineage; no source market state or observations imported. |
| crypto-trading-bot-master | CB-UI | 49 | Charts, orders, profiles and backtest views; selected UX reference without a framework replacement. |
| crypto-trading-bot-master | CB-SUPPORT | 48 | Tests, docs, assets/sample files, build/package metadata and source instructions accounted for; no donor commands executed. |
| gunbot-quant-main | GQ-RESEARCH | 13 | Screening, native indicator wrappers, backtest/scenario/optimizer and data management. Reference matched baselines and exit reasons; dynamic search and model-selection expansion excluded. |
| gunbot-quant-main | GQ-BRIDGE | 17 | Gunbot data/API integration and JS strategy copies. Inventory/reference only; no vendor trading or externally sourced state becomes native authority. |
| gunbot-quant-main | GQ-HOST | 35 | Scenario/screening/backtest API, CLI and reports/history UI. Candidate experiment comparison; no Gunbot server or frontend replacement. |
| gunbot-quant-main | GQ-SUPPORT | 10 | Docs/combined-code copy, screenshot, packaging and entrypoints accounted for; duplicate source document is not independent evidence. |
| node-binance-trader-master | NB-EXECUTION | 9 | Signal mapping, order sequencing, borrowing/repayment and rounding. Candidate duplicate/unknown/precision tests; no margin or external signal trading enabled. |
| node-binance-trader-master | NB-HOST | 16 | Socket/HTTP, notifications, logs and backtest proxy. Single queue is not durable idempotency; no remote signals, notifier credentials or service started. |
| node-binance-trader-master | NB-SUPPORT | 47 | Tests/docs/deployment/metadata and unrelated bundled PDF accounted for; PDF/sample data are not imported into Trade. |
| viabtc_exchange_server-master | VB-MATCHING | 30 | Decimal price-time matching, available/frozen balances, fees/history, business-key update deduplication, snapshots and operation replay. Valuable conservation/recovery adversarial cases; asynchronous operation-log queue is not durable-before-ack. |
| viabtc_exchange_server-master | VB-GATEWAY | 73 | RPC/WS access, subscriptions, candles, paginated history and alerts. Reference sequenced data/health states; no exchange server or SQL jobs deployed. |
| viabtc_exchange_server-master | VB-SUPPORT | 132 | Network/util/decimal wrappers, vendored hiredis, SQL schemas, test clients/build/config/docs accounted for. No database, matching engine, test client or vendor libraries executed. |

## Verification and archive state

Inventory and classification assertions check fourteen archives, 9,257 unique
source/path pairs, 64 nonempty groups and 530 catalogue entries. Extracted text
hashes are checked against the per-entry inventory. Python syntax parsing passed
for 115 entries; two ViaBTC test clients use syntax rejected by the local Python
3.11 parser. This is not a claim that those historical clients are invalid under
their original interpreter. Static indexing does not execute imports.

All fourteen reviewed ZIPs were moved to
`C:\Users\ACER\Downloads\archive`, with source and destination hashes checked
against this assessment. The move receipt is
`.pi/trading-library-archive-receipt.json`. A whole-record audit verified **82
documented reviewed ZIPs**, all matching their recorded hashes, with none of
those ZIPs left loose in Downloads. Extracted folders and archives outside
Downloads were preserved. `.pi/archive-verification.json` records that audit.

Only source-review documentation and ignored review records were added. No
production code, dependencies, live state or credentials changed. The native
test suite was not rerun for this documentation-only review; previous test
results do not qualify these donor runtimes or the pending operational gates.
