# Market infrastructure source assessment

Reviewed 2026-11-04. This continues the [trading source assessment](trading-source-assessment.md)
and informs the existing [research workspace plan](research-workspace-plan.md).

All **432 archive file entries** were streamed through SHA-256 and assigned to
one of **32 decisions** below. No donor application, test suite, installer,
wheel, model, database or notification sender was executed. No donor dependency,
credential, market sample or implementation was added to Trade.

The ignored review records are `.pi/market-source-inventory.json` (entry hashes),
`.pi/market-source-assessment.json` (every entry's decision),
`.pi/market-code-index.json` (declarations, syntax and static flags) and
`.pi/indicator-source-catalog.json` (187 individual indicator declarations across
Finta and Fast Trade, including duplicates). Text was inspected under
`.pi/sources/`. Java and JSONC entries are included in extraction and review.
Archive moves are recorded in `.pi/market-archive-receipt.json`.

This is complete file accounting and module-family assessment with selected
implementation reads, not proof of line-by-line correctness or that every
possible useful idea has been implemented. Linked services, external datasets,
bundled wheels and the nested TA-Lib tarball were not independently audited.

| Archive | Entries | Root license text | SHA-256 |
| --- | ---: | --- | --- |
| stocklook-master.zip | 132 | MIT | `72b469b7c79ba1c391ff59744c62d29d5040808e858e4c9f5872e6b66f602bbf` |
| fast-trade-master.zip | 148 | AGPL-3.0 | `b8d4f913d6814663c635666d1d6aa4c356b271e5b219109bbe57df2d72758858` |
| Crypto-Signal-master.zip | 49 | MIT | `4607e5c9630e8abcb2e4421e308d890bf5a5e9919f9cd7367cf477d868579f70` |
| intelligent-trading-bot-master.zip | 66 | MIT | `8e1d54655e013edb36f1169a23bc09f5d742b3cb36e7c1768f819eb54096de15` |
| Order-Book-Matching-Engine-master.zip | 11 | No standalone license found | `8cc7398c51276dd460616791eeaa8049793eb6eabd1e5a4f4af440f8c0a9eaab` |
| finta-master.zip | 26 | LGPL-3.0 | `b9ec79dcf0801c2f2b41f57208217318a233ad9ee67a76d1007df8457b40621c` |

Root notices do not establish the provenance of every bundled component.
Python syntax parsing passed for 120 Stocklook, 97 Fast Trade, 35 Crypto Signal,
43 Intelligent Trading Bot and eight Finta files. Three Intelligent Trading Bot
files fail under Trade's installed Python parser: `inputs/collector_binance.py:196`,
`scripts/output.py:67`, `scripts/predict_rolling.py:296`, all nested f-string
syntax. This is a parser compatibility result, not a claim that they fail under
every Python version. Java compilation was not run.

## Most useful mechanisms and integration decisions

The first priorities remain the eight agreed workspace modules. These sources
strengthen their requirements rather than justify a second execution engine.

| Priority | Mechanism | Native owner and acceptance |
| --- | --- | --- |
| 1 | Fast Trade's chronological, purged walk-forward evaluation; Intelligent Trading Bot's exclusion of unrealized labels | Extend `services/temporal_validation.py` and the planned experiment registry/robustness laboratory. Any supervised label must be realized before the training cutoff; purge must cover its horizon, not an arbitrary one-bar gap. Retain all trials, including failed and single-class folds. Existing strategy validation is not an implemented ML trainer. |
| 2 | Intelligent Trading Bot's shared offline/online generators and dirty-tail recomputation | Keep `domain/technical_features.py` as the shared owner. Added regression coverage compares streaming and batch results at nine warmup boundaries through 205 bars and checks that later observations do not mutate retained results. Corrected historical observations require explicit invalidation/replay; tail-only repair cannot be assumed sufficient for recursive indicators. |
| 3 | Stocklook's gap inspection and paginated OHLC repair; Fast Trade missing-frequency report | Feed the planned coverage/recovery GUI from native `research_market.py`, `feed_crosscheck.py` and `research_ledger.py`. Keep observed gaps, receipt clocks and bad quotes explicit. Historical OHLC repair cannot recreate executable quotes or move their historical availability backwards. |
| 4 | Finta's indicator catalogue and tests | Keep exact native variants and independent fixtures. Catalogue every donor method before selection. Candidates include ROC, PPO, efficiency ratio, Donchian width and range oscillators; additions need a named strategy or diagnostic consumer, documented seed/warmup/zero-denominator behavior and prefix-causality tests. No bulk indicator import. |
| 5 | Crypto Signal's configured analyzer/informant separation and status-change notifications | Use native registry, descriptive indicators and durable research alerts. A threshold state is not necessarily a crossing event. Future notification delivery needs persistent deduplication and explicit channel authorization; no sender was enabled. |
| 6 | Stocklook depth snapshots and the matching engine's book-consumption examples | Extend native `services/liquidity.py`/simulation only when qualified depth and sequence evidence exist. Test same-price aggregation, partial consumption, no negative quantities and deterministic price priority. Current top-of-book paper fills do not establish queue priority or full depth capacity. |
| 7 | Fast Trade's run summaries, HMM screening, search history and CLI/tool coverage | Reuse saved reports and the planned screening/experiment interfaces. Persist attempted candidates and runtime budgets before adding optimization. HMM states are model interpretations requiring causal filtering and evaluation, not calibrated trade confidence. Tool parity should use explicit allowlisted actions, not arbitrary CLI passthrough. |

## Every module family

Decision IDs below are assigned to every entry in the machine-readable assessment.
Support groups include tests, examples, docs, CI, metadata and assets; they are
retained as review references, not imported into runtime. Prefix assignments are
an accounting partition, not a statement that a test has no relevance to its
corresponding functional module.

| Decision | Entries | Scope and disposition |
| --- | ---: | --- |
| SL-FEEDS | 8 | GDAX feeds and BitMEX websocket state. Snapshot plus monotone sequence and gap invalidation are useful invariants. Do not transplant threads, restart loops or exchange-specific message schemas. |
| SL-GAPS | 1 | `crypto/gdax/db.py`: time-gap discovery and chunked history fetch. Candidate requirements for coverage/catch-up; retain native receipt-time provenance and bounded retry. |
| SL-EXECUTION | 9 | Market makers, orders, position snapshots and controller. Useful reconciliation, hold/reservation and order-convergence scenarios for portfolio/execution analysis. Their create/cancel/withdraw paths are not authorized native capabilities. |
| SL-ANALYSIS | 11 | Quant functions, patterns, strategy analysis, chart data and order-book summaries. Native moving averages/RSI/MACD/TRIX already cover overlap; patterns contain empty methods. Depth walls and velocity remain descriptive candidates, not entry guarantees. |
| SL-ADAPTERS | 75 | Venue/chain/market-cap/Yahoo/FRED/Twitter APIs, account/database wrappers and colocated tests. Preserve useful provenance/unit/rate-limit concepts; do not add unrelated venues, social feeds or old authentication schemes. README explicitly calls Yahoo broken. |
| SL-UTILITIES | 9 | Credentials/config, time, HTTP and OHLC cursor helpers. Reuse native encrypted storage, UTC clocks and bounded adapters. No alternative credential cache or forward cursor enters decision-time features. |
| SL-SUPPORT | 19 | Packaging, launch/scripts, wheels, fixtures, tests and remaining support. Static references only; bundled binary wheels and SQLite test database are not installed or used as market evidence. |
| FT-WALK | 5 | Classifier and walk-forward engine/examples. Valuable horizon purge, disjoint tests, delayed signals and matched baselines. ML fit/calibration is a future extension with explicit dataset/model lineage, not an existing capability. |
| FT-SEARCH | 13 | Evolver, regime/Markov/HMM models, multi-market screeners and research examples. Bounded search with all attempts recorded is valuable. Pickle loading, full-sequence state inference and convergence need independent qualification. |
| FT-SIMULATION | 6 | Backtest, validation, account path, action logic and accelerator. Native availability/Decimal/rule/cost contracts take precedence over float/Numba speed. No second account simulator is added. |
| FT-DATA | 11 | Exchange archive, frame/resampling/transformer builders and missing counts. Useful explicit frequencies and acquisition diagnostics; preserve actual receipt times, distinct rows and partial bars. No synthetic upsampled bars become real observations. |
| FT-REPORTS | 5 | Summary, trade/portfolio metrics and effective-trade reporting. Compare definitions before adding metrics; retain zero-trade/undefined values and native exact balances. Summaries do not qualify a strategy. |
| FT-PORTFOLIO | 1 | Persistent portfolio state/actions. Candidate reservation/reconciliation cases only. Swallowed state failures and default-state recovery are unsuitable for account custody; its `apply_action` omits commission. |
| FT-TOOLS | 6 | CLI, MCP, macro context and visualization. Use interface-coverage ideas within native allowlisted actions. No generic command/path execution or macro API credential import. |
| FT-INDICATORS | 2 | Polars Finta variant and transformer mapping. All 95 indicator declarations catalogued separately from upstream Finta; equivalence is unverified and placeholders are excluded. |
| FT-SUPPORT | 99 | Tests, benchmark scripts/results, configurations, docs, examples, package/CI support. Useful test scenarios and benchmark methodology; published timings are not Trade measurements. Source AGENTS content is review data, not authority for this workspace. |
| CS-ANALYSIS | 18 | Indicator/informant/crossover dispatch, OHLC conversion and analyzer implementations. Reuse registry separation and explicit readiness; native semantic definitions remain authoritative. Volume-dependent paths require qualified volume. |
| CS-NOTIFICATION | 11 | Output formats and seven notification channels. Status deduplication and structured messages are useful requirements; in-memory previous state does not provide durable delivery guarantees. No messages sent. |
| CS-INGESTION | 2 | Exchange retrieval and behavior orchestration. Candidate stale/forming-bar and per-market failure cases. Do not scan every exchange by default or import unbounded retry/orchestration. |
| CS-SUPPORT | 18 | App/config/logging, dependency lists, Docker/docs and bundled TA-Lib tarball. Configuration ideas only; no install, secret import or nested dependency audit. |
| IT-FEATURES | 5 | Analyzer, generator dispatch and technical/statistical/depth features. Shared batch/live definitions and invalidation are useful. Separate future-label generators from causal features at the schema boundary. |
| IT-LABELS | 2 | Future high/low, first-crossing and extrema labels. Candidate offline target definitions with explicit horizon and ambiguity policy; never indicators available at the labeled historical time. |
| IT-MODELS | 8 | Four classifiers, model storage, training/prediction/rolling evaluation. Retain fitted-transform/model/config identities and purging requirements. No arbitrary pickle model import, optional ML dependency stack or untested probability claim. |
| IT-SIGNALS | 4 | Score combination/smoothing, thresholds and simulation. Candidate research-only parameter trials. Its profit percentage sums and configurable `eval` expressions do not become native accounting or input parsers. |
| IT-ADAPTERS | 11 | Binance/MT5/Yahoo ingestion, two live traders and service scheduling. Preserve health/readiness concepts; do not add live venue authority or copy order state into the protected executor. |
| IT-NOTIFICATION | 4 | Score-band/trade/diagram notifications and output dispatch. Useful research display candidates; transaction CSVs remain unauthenticated inputs and senders stay disabled. |
| IT-SUPPORT | 32 | Utils/types, scripts, JSONC configs, tests, docs/images and root support. Fixtures and decimal/interval cases inform native validation; dynamic configuration does not authorize imports or external output. |
| OB-ENGINE | 2 | Java matching engine and BBO. Only useful as adversarial invariant examples. Aggregate levels are not FIFO order queues; absent quotes reported as zero are not valid native prices. Implementation is not copied. |
| OB-SUPPORT | 9 | Java main, random generators, Pair helper, tests, README and IDE metadata. Existing examples miss same-price aggregation; stress timings lack native reproducibility. No Java runtime/dependency is added. |
| FI-INDICATORS | 1 | Upstream Finta TA class: all 92 indicator declarations catalogued, including six placeholders, displaced chart values and genuine-volume requirements. Native variants are not claimed numerically equivalent. |
| FI-UTILITIES | 1 | OHLC conversion, resampling and trend predicates. Native closed-bar clocks, gap semantics and symbol identity remain authoritative. |
| FI-SUPPORT | 24 | Unit/regression tests, sample CSV/JSON, notebooks, chart asset, package and GitHub metadata. Retain boundary-case ideas, not foreign numeric outputs as native correctness proofs. No sample data enters the live store. |

## Concrete hazards found

* `OrderBookEngine.java:addBidRestingOrder/addAskRestingOffer` uses `put(price,
  quantity)`, replacing rather than accumulating an existing price level. It has
  no order identities or time-priority queues, no finite/positive input checks,
  floating prices and only partially synchronized operations. The README's
  approximate microsecond claim does not establish production suitability.
* `fast_trade/calculate_perc_missing.py` subtracts row count from expected timestamps
  between observed endpoints. Duplicate rows can mask missing timestamps and
  missing leading/trailing periods are outside those endpoints. Native coverage
  must use an explicit requested window and distinct qualified buckets.
* `fast_trade/portfolio.py:save_state/append_log` catches and discards persistence
  errors; `load_state` can return the supplied default on corrupt state. A corrupt
  trades file can be replaced with only newly supplied rows. These are rejected
  recovery semantics for durable ledgers.
* `fast_trade/ml/regime.py` applies `predict` and `predict_proba` to complete input
  sequences. Those calls alone do not establish online filtering; historical
  states must be tested for invariance when future bars change. Both model stores
  load pickle objects. Donor models are not opened.
* Finta and Fast Trade each expose six methods raising `NotImplementedError`:
  LWMA, VIDYA, ALMA, MAMA, SWI and TMF. They are explicitly marked
  `PLACEHOLDER_REJECTED` in the catalogue. Stocklook's HigherHighs pattern also
  contains empty `last_high`/`last_low` methods.
* Finta's `ICHIMOKU` shifts Chikou close values backwards and `WILLIAMS_FRACTAL`
  uses centered windows. Chart labels require displacement/detection delay before
  they can become decision-time evidence. Future target generators in Intelligent
  Trading Bot are legitimate label tools only when excluded from feature inputs.
* Crypto Signal's `std_crossover` tests greater/less than at each row; it does not
  itself require a transition across the preceding row. Its VWAP informant uses
  high/low midpoint and an inclusive `period_count + 1` slice. Names alone do not
  establish equivalence to a native crossing rule or trade-weighted VWAP.
* `scripts/simulate.py` in Intelligent Trading Bot evaluates configured threshold
  expressions with `eval`. That mechanism is not a suitable JSON/API boundary.
  Native strategies keep allowlisted, bounded parameter schemas.

## Status

Integrated in this review: broader native streaming/batch readiness and retained
snapshot regression coverage. The remaining useful mechanisms are explicitly
mapped above to native owners and acceptance criteria; they are not represented
as implemented features. The existing eight-module implementation remains open.
Source review, archive integrity and passing native tests do not qualify funded
trading, donor runtimes, optional ML models or external notification channels.

Validation after this review: native Python suite **840 passed, five skipped,
39 subtests passed**; Ruff passed. The accounting self-check verified all 432
file dispositions, all 32 document groups, 187 indicator declarations and the
SHA-256 hashes of all 18 ZIPs moved across the preceding and current batches.
All six archives in this assessment are now in `C:\Users\ACER\Downloads\archive`.
Existing archives were preserved; extracted source folders were not moved.
