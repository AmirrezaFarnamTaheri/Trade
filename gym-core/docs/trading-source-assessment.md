# Trading source assessment

Reviewed 2026-11-04. Six unique Downloads archives were inspected; the repeated
`undervalued-crypto-finder-main` request refers to the same archive. The two
`awesome-systematic-trading` archives are distinct projects, not duplicate copies.
This supplements the earlier [research-source assessment](research-source-assessment.md).

## Accounting and verification

All **454 file entries** were hashed and assigned one of the **30 module-family
decisions** below. Inventory and decisions: `.pi/trading-source-assessment.json`.
Static symbols/imports and review flags: `.pi/trading-code-index.json`.
The 61 strategy examples have a separate static interface catalogue, including
the extensionless Python file `pairs-trading-with-stocks`. One documentation
symlink was inventoried without following or materializing it.

Static Python parsing succeeded for 126 `.py` files and the extensionless example.
`quant-trading` has one additional Python file that fails parsing: `Oil Money
project/Oil Money NOK.py`, line 132, unterminated string literal. Parsing does not
establish runtime correctness. No donor imports, installers, dependency upgrades,
tests, exchange calls, scripts, deployments or external catalogue links were run.
Review covered every module family and selected implementation paths; it does
not establish that every source line or externally linked project was audited.
Images, sample datasets, generated clients, configuration, CI and documentation
are included in accounting. No donor account data or sample prices enter Trade.

| Archive | Files | License evidence in this snapshot | SHA-256 |
| --- | ---: | --- | --- |
| aioquant-master.zip | 53 | MIT-style `LICENSE.txt`, attributed there to PyPA | `8d7d3dea9c6d2255f08e424bd7e22dafb572a09c931d99a2036d09cf762ec859` |
| dingir-exchange-master.zip | 128 | No standalone license file found | `dfe125fe8ec62e35d05a6898a5dc987d14bb734432752a9b1ec7f9b1c625a179` |
| undervalued-crypto-finder-main.zip | 6 | GPL-3.0 | `4977402021bd7866f42397d3fc3e6df83de552e1a51edc75a54ef6bc4954ff3e` |
| awesome-systematic-trading-main.zip | 73 | No standalone license file found; linked code/data have separate provenance | `e324628baff4313cb02cd8483fe42d12edf1af173f4755e64b35bd4dbd86d26b` |
| awesome-systematic-trading-master.zip | 17 | MIT; README also describes a CC-BY option | `539b59d1323bf7be9a888cdd4457341aa85100ce5bcd7f1b86156f061141ed3f` |
| quant-trading-master.zip | 177 | Apache-2.0 | `bbd5842bbb0b14222582af278702fd539a2a7cdcbcded5e3c70f9eb8590f5499` |

No source implementation was copied. New calculations extend Trade's existing
exact-decimal indicator owner and do not add dependencies.

## Native additions

`domain/technical_features.py` and the existing batch indicator interface now
report SMA200 and `sma_distance_20_percent`, `sma_distance_50_percent`,
`sma_distance_200_percent`: **100 × (last close / SMA − 1)**. The denominator is
explicitly the average. A negative value means below that historical average;
it is not an estimate of intrinsic value, an undervaluation claim or a buy signal.

Closed-bar range diagnostics also include `awesome_5_34`: the five-bar average
of `(high + low) / 2` minus its 34-bar average. Missing range inputs remain null;
closes are not substituted for high/low. No saucer/crossover trading strategy was
enabled. These metrics are available through the existing technical CLI and
advanced GUI workbench, which share the same bounded read snapshot and gap rules.
Streaming storage is bounded to 200 closes and 34 range midpoints.

Periods mean **observed contiguous bars**, not necessarily days. The current
technical report's 31-day limit cannot supply a 200-day SMA. Short or gapped
history remains WARMUP. Existing strategies retain their rules and registry IDs.
Report fingerprints change when their indicator output changes, as intended.

Verification: **829 Python tests passed, five skipped, 39 subtests passed** in
60.52 seconds. Ruff passed. New independent checks establish the 200-bar warmup,
average-denominator arithmetic, range-based oscillator value and bounded state.
Existing tests cover streaming/batch parity, gaps, forming bars and API workbench
access. No donor numerical parity, profitability or live-execution claim.

## Module decisions

### AIOQuant — 53 files

| ID | Files | Modules, value and disposition |
| --- | ---: | --- |
| AQ01 | 7 | Runtime, configuration, heartbeat, tasks, constants/errors and package initialization. Useful: separate lifecycle and task registration. Native collector/research runner remains owner. Donor heartbeat schedules tasks without waiting for prior instances, and delayed-task forwarding drops keyword arguments; do not import that scheduler. |
| AQ02 | 2 | Event center and market objects. Useful: typed event families and explicit exchange/symbol routing. Native market models and availability clocks remain owner. Donor timestamps alone do not establish receipt/confirmation ordering; unbounded zlib decompression and message dispatch are not imported. |
| AQ03 | 1 | WebSocket/HTTP utility. Useful: reconnect lifecycle and session reuse. Native collector/gateway transports remain owner. Donor creates detached callbacks and connection sessions without a complete shutdown contract; raw request/response logging is unsuitable for secrets. |
| AQ04 | 4 | Binance, OKEx spot/futures market adapters and initializer. Useful: initial-book versus delta distinction, level deletion and resubscription. Existing Wallex books retain source-specific semantics. Donor float conversion and old channel contracts do not qualify a new venue adapter; no authenticated sequence/checksum contract is assumed. |
| AQ05 | 6 | Trade facade, platform initializers/adapters, orders and positions. Useful: explicit order lifecycle callbacks and initialization failure. Native durable intent, unknown-order reconciliation and custody remain owners. Do not copy arbitrary hosts, copied credential parameters or callback state as settlement. |
| AQ06 | 4 | Lock decorator, logger, time/decimal tools and utility initializer. Useful: exclude overlapping operations. Donor lock release runs even if a waiter is cancelled before acquisition, so it can release another coroutine's lock. Native `async with` and cancellation/ownership tests remain the correct implementation. No float-to-string laundering. |
| AQ07 | 29 | Docs, examples, sample configs, images, packaging and root files. Included in accounting. README architecture/performance and risk/storage/Web-management descriptions exceed the code supplied in this ZIP; no missing subsystem is marked implemented. No RabbitMQ/MongoDB/extra service deployment. |

### Dingir Exchange — 128 files

| ID | Files | Modules, value and disposition |
| --- | ---: | --- |
| DG01 | 3 | Market/order/trade matching. Useful: deterministic price then order-ID ordering, remaining-plus-filled conservation, maker/taker distinction, frozen balances and before/after state. Native simulated execution and executor ledger remain owners. Exchange-side matching is not a client-side estimate of Wallex queue position or fill certainty. |
| DG02 | 4 | Asset/balance management and update controller. Useful: account/asset/business-scoped operation identity and insufficient-balance rejection. Donor deduplication is an in-memory TTL cache, also periodically cleared; it is not durable exactly-once settlement. Keep native durable identity and reconciliation. |
| DG03 | 25 | Snapshot/log persistence, history/sequencer, messaging, SQL storage and migrations. Useful: snapshot plus ordered operation replay, bounded pagination, separate trade/order/balance events, delivery acknowledgment. Native hash-chain ledger/backups/outcome states remain owners. Do not copy dummy persistence, unbounded delivery queues, infinite flush, reset migrations or panic-on-storage-error behavior. |
| DG04 | 7 | Controller, server, users, Ethereum event guard, DTOs, test mocks and initializer. Useful: serialize mutation and key chain events by block/transaction/log identity. Real chain integration needs finality/reorganization contracts; block monotonicity is not enough. Transfer RPC contains a signature-verification TODO. Debug/reset/mock paths cannot become funded capabilities. |
| DG05 | 11 | REST public/personal history, management, TradingView, state/errors/types and initialization. Useful: history projections and explicit market metadata. Do not import mock chart defaults, management/reload routes or internal error text. Existing local token/Host checks and recorded-candle portal remain owners; full service authorization must be established separately. |
| DG06 | 46 | JS/TS bots, signer/client/CLI examples, stress/order/transfer tests and generated Python clients. Useful test ideas: partial execution, fee roles, batch outcomes and multi-market identity. They submit/reset/deposit against a server, not offline qualified Trade tests. No signer server, RPC client or example credentials are installed. |
| DG07 | 32 | Binaries, configuration, utility/type code, CI/build/release files and remaining root material. PostgreSQL/Timescale, Kafka, Unix `fork`/save and git-based dependencies are separate infrastructure contracts. No second matching engine, daemon, database, release pipeline or Windows compatibility claim. |

### Crypto finder — 6 files

| ID | Files | Modules, value and disposition |
| --- | ---: | --- |
| CF01 | 1 | Universe scraping, historical averages, daily movers and descriptive OHLC ratios. Moving-average distance is adapted above. Native scanner should retain listing identity, source availability, completed bars and missing-history status. Donor `dropna`/zero filtering can silently shorten the advertised 200-day window. Its current-average comparison is not a crossing event; below-average price is not intrinsic undervaluation. |
| CF02 | 5 | Config, requirements, README, license and ignore rules. Defaults are research choices, not calibrated parameters. No Yahoo scraper/yfinance/HTML-session dependency, 2023 cycle assumption or blanket current asset catalogue is imported. A complete cross-market daily screener still requires qualified historical coverage. |

### Strategy collection (`main`) — 73 files

| ID | Files | Modules, value and disposition |
| --- | ---: | --- |
| AS01 | 61 | All strategy code files, individually catalogued below. Useful research families: trend/momentum, reversal, relative strength, pairs, rebalancing, seasonality, fundamentals and term structure. These require QuantConnect/LEAN lifecycle, historical universes, source calendars, fees, data-release clocks or derivative/shorting contracts. No example is added directly to the live registry. |
| AS02 | 4 | Table generation, link checking, count updates and paper metadata. Useful: reproducible catalogue generation and clear active-window/gross-cost labels. Generated rankings select strong in-sample t-statistics across many tests and unequal calendars; they are not independently selected net results or prospective confidence. No remote dataset download or link-check job ran. |
| AS03 | 8 | Three README languages, CI/editor/ignore files and image. Resource links and catalogue claims are source references, not verified dependencies, provider facts or working native features. No subscription, account unlock, research-credit use or external service was activated. |

The Bitcoin seasonality example uses a particular venue/hour and sets leverage;
the crypto rebalancing example includes a synthetic short portfolio and a path
that can reuse last prices after trading has begun. Paired switching uses a
current-price return denominator. Preserve useful hypotheses, not those assumptions.
Fundamental, earnings, filing-language, borrow, option and futures examples need
their own vintage, corporate-action, calendar and cost data before meaningful tests.

### Resource catalogue (`master`) — 17 files

| ID | Files | Modules, value and disposition |
| --- | ---: | --- |
| AC01 | 12 | General/crypto catalogues, translated docs, MkDocs/theme/comment templates, image, funding/CI and license material. Useful: discovery taxonomy spanning alpha, data, execution, order books, risk, ML and infrastructure. Linked projects are separate review candidates, not contained implementations. Performance/maintenance/pricing claims were not verified or imported. |
| AC02 | 5 | Python, Go and Rust demonstrations plus Rust manifest/lock. Python/Go only print messages; Rust constructs a toy fruit table. These are placeholders/examples, not trading modules. None enters production and no Polars runtime is added. |

### Quant trading — 177 files

| ID | Files | Modules, value and disposition |
| --- | ---: | --- |
| QT01 | 4 | Awesome Oscillator, MACD, Heikin-Ashi and Parabolic SAR examples. AO arithmetic is adapted above; native MACD already exists. Smoothed Heikin-Ashi prices are derived views, never executable prices. SAR needs explicit seed/reversal rules and cost-aware tests. Existing native Decimal features remain the owner. |
| QT02 | 3 | Bollinger, RSI and shooting-star pattern recognition. Useful: explicit pattern/confirmation state. Shooting-star conditions use next-bar `shift(-1)` and full-sample body statistics before recording an earlier entry. A native implementation must delay availability and execution until confirmation, with past-only thresholds. No pattern strategy was copied. |
| QT03 | 2 | Dual Thrust and London breakout. Useful: session-defined prior-range thresholds. Need an explicit market/session/time-zone/DST contract and prior-only range data. Donor fixed historical clock windows and swallowed missing-day exceptions are not continuous crypto-session rules. |
| QT04 | 1 | Engle–Granger/error-correction pairs research and portfolio plotting. Useful: monitor relationship failure and cap pair exposure. Native reuse needs past-only fitting, appropriate residual testing, aligned availability, shared cash, fees/borrow and atomic/partial leg handling. No statistical-arbitrage or riskless-return claim. |
| QT05 | 9 | Monte Carlo experiment, README and previews. Useful: chronological split and distributional stress scenarios. No trained forecast or seed-stable artifact is supplied. GBM scenarios are model assumptions; cherry-picked paths/directional accuracy are not independently calibrated forecasts or tail guarantees. |
| QT06 | 77 | Oil CAD/COP/NOK/RUB studies, oil trading, production maps/cost curves, ore/FX studies, data and previews. Useful: explicit exogenous-series/unit/lag relationships. Data rights, release vintages, currency units, structural changes and train-only fitting need native adapters. NOK file fails parsing; no repaired or imported runtime is claimed. |
| QT07 | 45 | Agricultural consistency/cleansing/country selection, demand regression, constrained OLS, allocation forecasting, data/docs/previews. Useful: constrained optimization and input-consistency diagnostics. Dataset-relative globals, forward-filled assumptions and fitted cost coefficients do not generalize into crypto predictions. No FAO/agricultural data pipeline or model activation. |
| QT08 | 2 | Options straddle and VIX-style calculator. Useful: explicit expiry/settlement, strike selection, rate curves and bid/ask contract specification. Native option/volatility work needs complete chains, real calendars, quote freshness, exercise style and fees; the supplied natural-gas setup is not a crypto VIX feed. |
| QT09 | 34 | Root docs/license and sample CSVs/workbook/previews outside the studies. Research assets only. The archive has 27 CSVs total across all studies. The README explicitly assumes frictionless trading; screenshots and historical sample returns are not qualification. README references to portfolio-optimization/wisdom-of-crowds projects do not supply those implementations in this ZIP. |

## Prioritized further work

1. Continue the existing executor's durable operation/settlement and recovery
   tests, informed by Dingir's conservation/replay cases. Do not replace those
   contracts with TTL deduplication or a second exchange server.
2. Add a bounded cross-market descriptive screener once historical coverage
   supports it. Disclose excluded/stale/warmup markets and rank distance or return,
   never intrinsic value or calibrated confidence.
3. Research causal range breakout, time-of-day seasonality and rebalanced versus
   drifting allocations through the current hypothesis/preregistration system.
   Selection counts, comparable calendars, fees and missing windows must be retained.
4. Treat pairs, option/term-structure, fundamental and exogenous-data ideas as
   separate native capabilities with their missing data/ownership contracts.
   They remain research candidates, not installed trading functionality.

No commit or archive move was made. Wider deferred work remains tracked in the
[implementation plan](implementation-plan.md); inventory completeness does not
mean all source ideas are implemented or profitable.

## Individual strategy interface catalogue

Every row is **research reference only**, not installed. Interfaces are extracted
statically from each file; individual names retain provenance. They identify
review requirements, not successfully exercised APIs or audited strategy results.

| Source strategy | Static interfaces requiring native contracts |
| --- | --- |
| 12-month-cycle-in-cross-section-of-stocks-returns | AddEquity, AddUniverse, History, SetLeverage |
| 52-weeks-high-effect-in-stocks | AddEquity, AddUniverse, History, SetLeverage |
| accrual-anomaly | AddEquity, AddUniverse, SetLeverage |
| asset-class-momentum-rotational-system | AddEquity |
| asset-class-trend-following | AddEquity |
| asset-growth-effect | AddEquity, AddUniverse, SetLeverage |
| betting-against-beta-factor-in-country-equity-indexes | AddEquity, SetLeverage |
| betting-against-beta-factor-in-stocks | AddEquity, AddUniverse, History, SetLeverage |
| combining-fundamental-fscore-and-equity-short-term-reversals | AddEquity, AddUniverse, History, SetLeverage |
| combining-smart-factors-momentum-and-market-portfolio | AddData, AddEquity, SetLeverage |
| consistent-momentum-strategy | AddEquity, AddUniverse, History, SetLeverage |
| crude-oil-predicts-equity-returns | AddData, AddEquity, SetLeverage |
| currency-momentum-factor | AddData, SetLeverage |
| currency-value-factor-ppp-strategy | AddData, SetLeverage |
| dispersion-trading | AddUniverse, SetLeverage |
| dollar-carry-trade | AddData, SetLeverage |
| earnings-announcement-premium | AddEquity, AddUniverse, History, SetLeverage |
| earnings-announcements-combined-with-stock-repurchases | AddEquity, AddUniverse, SetLeverage |
| earnings-quality-factor | AddEquity, AddUniverse, SetLeverage |
| esg-factor-momentum-strategy | AddData, AddEquity, AddUniverse, SetLeverage |
| fed-model | AddData, AddEquity |
| fx-carry-trade | AddData, SetLeverage |
| how-to-use-lexical-density-of-company-filings | AddData, AddEquity, AddUniverse, History, SetLeverage |
| intraday-seasonality-in-bitcoin | AddCrypto, SetLeverage |
| january-barometer | AddEquity, SetLeverage |
| low-volatility-factor-effect-in-stocks | AddEquity, AddUniverse, History, SetLeverage |
| market-sentiment-and-an-overnight-anomaly | AddData, AddEquity |
| momentum-and-reversal-combined-with-volatility-effect-in-stocks | AddEquity, AddUniverse, History, SetLeverage |
| momentum-effect-in-commodities | AddData, SetLeverage |
| momentum-factor-and-style-rotation-effect | AddEquity, SetLeverage |
| momentum-factor-combined-with-asset-growth-effect | AddEquity, AddUniverse, History, SetLeverage |
| momentum-factor-effect-in-stocks | AddEquity, AddUniverse, History, SetLeverage |
| momentum-in-mutual-fund-returns | AddData, AddEquity, SetLeverage |
| option-expiration-week-effect | AddEquity, AddOption |
| paired-switching | AddEquity, History |
| pairs-trading-with-country-etfs | AddEquity, History, SetLeverage |
| pairs-trading-with-stocks | AddEquity, AddUniverse, History, SetLeverage |
| payday-anomaly | AddEquity |
| rd-expenditures-and-stock-returns | AddEquity, AddUniverse, SetLeverage |
| rebalancing-premium-in-cryptocurrencies | AddCrypto, SetLeverage |
| residual-momentum-factor | AddEquity, AddUniverse, History, SetLeverage |
| return-asymmetry-effect-in-commodity-futures | AddData, AddEquity, SetLeverage |
| reversal-during-earnings-announcements | AddEquity, AddUniverse, History, SetLeverage |
| roa-effect-within-stocks | AddEquity, AddUniverse, SetLeverage |
| sector-momentum-rotational-system | AddEquity, SetLeverage |
| short-interest-effect-long-short-version | AddData, AddEquity, SetLeverage |
| short-term-reversal-in-stocks | AddEquity, AddUniverse, History, SetLeverage |
| short-term-reversal-with-futures | AddData, AddFuture, SetLeverage |
| skewness-effect-in-commodities | AddData, SetLeverage |
| small-capitalization-stocks-premium-anomaly | AddEquity, AddUniverse, SetLeverage |
| soccer-clubs-stocks-arbitrage | AddData, SetLeverage |
| synthetic-lending-rates-predict-subsequent-market-return | AddData, AddEquity |
| term-structure-effect-in-commodities | AddData, AddFuture, SetLeverage |
| time-series-momentum-effect | AddData, SetLeverage |
| trading-wti-brent-spread | AddData, SetLeverage |
| trend-following-effect-in-stocks | AddUniverse, History |
| turn-of-the-month-in-equity-indexes | AddEquity |
| value-and-momentum-factors-across-asset-classes | AddData, AddEquity, SetLeverage |
| value-book-to-market-factor | AddEquity, AddUniverse, SetLeverage |
| value-factor-effect-within-countries | AddData, AddEquity |
| volatility-risk-premium-effect | AddEquity, AddOption, SetLeverage |
