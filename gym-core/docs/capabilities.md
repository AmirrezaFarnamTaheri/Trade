# Capabilities and design sources — 2026-11-04

Reviewed local sources:

- `D:\GitHub\AGI\jev-trader-main.zip`, SHA-256
  `1f3481d146871d1d23970a7f60c271253fd63e62963ae5dff14f51f833519dee`.
  Its 62 regular files were extracted into the ignored review directory;
  the archive's editor-rule symlink was skipped. The ZIP is not a directory.
- `C:\Users\ACER\Downloads\AI-Trader-main (1)\AI-Trader-main`: 149 files,
  including 74 Python files. Its README advertises MIT, but this downloaded tree
  has no LICENSE file. No source code was copied.
- `C:\Users\ACER\Downloads\Vibe-Trading-main\Vibe-Trading-main`: 2,882 files,
  including 2,047 Python files; root MIT license and component notices.
  Counts exclude dependencies, Git and bytecode caches.
- `C:\Users\ACER\Downloads\archive\ai-algotrading-agent-master.zip`: 64 files,
  SHA-256 `b41ea4b0a6eb44d08aa16e07cbcea24f8d757450aeab89e9899547fbc0688d7b`.
- `C:\Users\ACER\Downloads\archive\agent-trade-kit-github-main.zip`: 343 files,
  SHA-256 `a997f9a59a34d7134831c95d1a5861475c6535d7211a67744e7cd65d61abadad`.
  The source identifies itself as OKX Agent Trade Kit.
- `C:\Users\ACER\Downloads\archive\agentic-trading-main.zip`: 64 files,
  SHA-256 `b44a0c5b83024503d1019893c17227089e67964ef55cc7afc728691abf97b040`.
  The similarly named `agentic-trading-desk-main.zip` was not the requested source.
- `C:\Users\ACER\Downloads\archive\FriesTrader-main.zip`: 14 files, MIT license,
  SHA-256 `4beb6a2431ac43c975bea49cc6c014a3c4fcfa97a30e83b0d39bbfdad14cb476`.
- `C:\Users\ACER\Downloads\archive\Code-master.zip`: 11 files, GPL-3.0 license text,
  SHA-256 `15cc68c12eb8145dab4a6d1725a194d2747c2aded94eae55776e60c29d5a4e05`.
  README identifies the Alpha Engine research implementation; no Java code copied.
- `C:\Users\ACER\Downloads\archive\Clawtrade-master.zip`: 273 files, MIT license,
  SHA-256 `1a13b10da31c34e5be9471221988a9ee4e964ec6641590130dbec6ca820e0300`.
- `C:\Users\ACER\Downloads\archive\AlphaQuanter-main.zip`: 31 files; no root LICENSE,
  SHA-256 `e977b733c414cb38c8f96414a600d641d04b9c74ed1240fd83a87ae3f623a9d4`.
  No training code, datasets, weights, pickle files or dependencies imported.
- `C:\Users\ACER\Downloads\archive\Harvard-Algorithmic-Trading-with-AI-main.zip`: 18 files,
  SHA-256 `79c6a7fa8b85f8630665c39e741be8e22228aff7680ce3c06b1b1deb22b1324d`.
  No root license file was found; no source implementation copied.
- `C:\Users\ACER\Downloads\archive\llm-agent-trader-master.zip`: 83 files, MIT license,
  SHA-256 `7023435c68811ee0614e6202320524e2bcc0f02bdfd0c047065b3270225804e0`.
- `C:\Users\ACER\Downloads\archive\MAHORAGA-main.zip`: 118 files, MIT license,
  SHA-256 `f75cb668c96ac50c25756e915ce7c36871e08845f20dbf70c5d1ffde8eecbaed`.
- `C:\Users\ACER\Downloads\archive\LLM_trader-master.zip`: 362 files, root MIT license
  and third-party notices; SHA-256
  `1b43404a79ffa8b8905719532a972f046fbcd805213ee91b19df208e9024d1e0`.
  Source architecture instructions were read as repository context; its runtime,
  configuration and deployment policy were not transplanted into Trade.

These are local snapshots, not a claim about latest upstream versions. No donor
application was launched, no donor credentials/configuration/data were imported,
and no donor trading or model request was made. Native Trade implementations
adapt the concepts below without new dependencies.

- `C:\Users\ACER\Downloads\archive\Trading-Agent--main.zip`: 31 regular files, MIT license,
  SHA-256 `12500fbbd3326201fa3baa50eafb023328e63cca5e3bfac700dcc9c389e4c061`.
- `C:\Users\ACER\Downloads\archive\TradePipeline-master.zip`: 18 regular files; no root LICENSE,
  SHA-256 `0a1f3b1f4360a1d91537deb955d39c96fdea5e876d597c79ff3554c1f9373257`.
- `C:\Users\ACER\Downloads\archive\TradingAgents-main.zip`: 213 regular files, Apache-2.0 text,
  SHA-256 `7d7d2cf8d2ed7409ff0557b832b198656a26be3f88dcbdb424c47408a7fd3ad4`.
- `C:\Users\ACER\Downloads\archive\TradzQAI-master.zip`: 68 regular files, Apache-2.0 text,
  SHA-256 `9bf761de15e3e62751acacf8f428a7abde86bb27a27946805cd4bac54130b229`.
  All four were extracted without running them. No source code, model weights,
  datasets, secrets, dependencies or source branding entered the application.

- `C:\Users\ACER\Downloads\archive\prism-liquidity-agent-main.zip`: 508 regular files, MIT license,
  SHA-256 `c3290bc8b7b674ac28f714a193f1922cb95fe6eee761afdae192867165db83e4`.
- `C:\Users\ACER\Downloads\archive\moon-dev-ai-agents-for-trading-main.zip`: 27 regular files;
  no root LICENSE. SHA-256
  `6fae25e482baa60ddb528069e455258e03e068c3cc7b8018a7c17291b571f792`.
- `C:\Users\ACER\Downloads\archive\multi-agent-trading-system-main.zip`: four regular files,
  MIT license, SHA-256
  `016aa7a9a6eea0bb51f1cf7f8b88b919436d23aceb159bc6c12da69144207641`.
  The `(1).zip` download is byte-identical. This is a tutorial/notebook, not a
  second packaged implementation; its 28 code cells were inspected statically.
- `C:\Users\ACER\Downloads\archive\clawquant-trader-main.zip`: 81 regular files, MIT license,
  SHA-256 `8601fbb73ed3449b057e97037ff7b4f402627dbc5ab67690d3cb0b91f4fd903d`.
  The trailing `[` in the request was punctuation, not part of the archive name.

## Reuse decisions across the modules

| Source modules / capability | Decision and target |
| --- | --- |
| ClawQuant `backtest/walkforward.py`: repeat selection/evaluation across successive windows | **Adapted independently** as `gymctl validate --folds 1..5` in native `services/temporal_validation.py`. One SQLite snapshot spans every window; each disjoint block has its own existing 70/30 selection, one decision-period purge, flat paper account and warmup. Per-window selection/run fingerprints and explicit statuses are published using the existing immutable run store. The original single-window result/identity remains; Research and the validation API expose the same bounded window choice. This is blocked historical evaluation, not expanding training or calibrated independence. |
| ClawQuant batch/sweep, evaluation metrics/scorer and result aggregation | **Retain native costs, fingerprints and qualification limits.** Source walk-forward reuses its strategy instance between trials/windows and substitutes zero test return/score when evaluation fails; neither shortcut is inherited. Missing selection data rejects the native request; stale or inactive outcomes remain explicit and cannot produce a complete result. No composite 0–100 quality score, annualized Sharpe from a short window, random search result or compounded independent-account curve is promoted to evidence. |
| ClawQuant engine/events/execution/portfolio/risk and built-in DCA/grid/MA/RSI/Bollinger/MACD/breakout | **Keep the native simulator/registry.** Next-open execution is a useful causal model, but floating notional sizing/full-history user signal generation do not replace availability-safe quotes, exact received-asset fees, nonfills and actual holdings. SMA cross and volatility bands already exist. Adding more indicators is deferred until definitions, costs, warmup and meaningful data tests justify them. Neither source defaults nor its same-close option are copied. |
| ClawQuant data fetch/cache/inspection/alignment, runtime loader and sandbox | **Keep native provenance and worker boundary.** Empty/outage/duplicate data must remain visible; timestamp intersections can hide coverage gaps. Dynamic Python strategy discovery is not needed by the fixed registry. The source sandbox joins a daemon thread with a timeout but does not kill the thread or isolate credentials; Windows memory-read failure becomes zero. Those are not accepted as installed-worker containment evidence. Synthetic loader validation fixtures remain separate from actual observations. |
| ClawQuant radar/explainer, deploy manager/runner, reports/CLI/skills and Binance/ccxt wrappers | **Retain native research jobs, errors and allowlisted reports.** Source radar's recent-signal accuracy/confidence is a heuristic, not a measured probability; zero defaults and generic reassuring risk prose are excluded. The live runner logs `Would place` and contains an order-placement TODO, so it is not transplanted as working live execution. No second CLI framework, proxy setup, provider configuration, generated charts or skill-based order authority is imported. |
| Prism fee-capture/entry budget/risk/churn/PnL halt/position-loss/TP ladder | **Keep native economics, entry/exit/reopening and authority separation; record portfolio extensions as deferred.** Net revenue after conversion/harvest costs, reserves and entry-only churn limits are valuable concepts. Native sizing/spacing/trade-economics already retain explicit assumptions and costs. LP fee concentration, impermanent loss, SOL gas reserves and source USD thresholds cannot stand in for Wallex costs. Source missing-history fail-open behavior is not a safety fact, and close/reopen TP ladders do not establish partial settlement or protected stops. |
| Prism candidate lifecycle, discovery/market/launch gates, depeg/liquidity drain and token security | **Retain native fresh two-sided readiness and explicit unknowns.** Fresh non-fallback evidence, consecutive healthy observations and reason-category rejection summaries are useful for future entry-candidate review. Mint/freeze/transfer-tax, pool TVL and stable/stable ratio screening are chain-specific. A relative stablecoin ratio cannot identify which coin lost its USD peg; a TMN or volatile pair is not a USD peg oracle. No ranking score, unknown token metadata or inferred volume authenticity grants entry permission. |
| Prism adapter/retry, reconciliation, atomic rebalance, RPC/Jupiter/Pyth/DEX feeds, wallet and native Rust/Bend work | **Keep native venue-qualified mutation/recovery contracts.** Simulation, pending receipts and actual chain settlement are distinct. Source price lookup contains hardcoded fallback prices; live-candidate guards distinguish fresh evidence, but no fallback dollar price or heuristic position mark is imported into Trade. Solana key files/SDK transactions, alternate RPCs, program IDs and performance/parity claims are not Wallex transport or Windows qualification. No source adapter, native binary, fee wallet or key provisioning was run. |
| Prism proposals/transports/MCP, model calibration/cache, memory/embeddings and reporting | **Retain fixed read-only tools and optional advisory gateway.** Separate proposal/approval credentials and model advice below hard rules are useful boundaries; a parsed model proposal or low-confidence exit is not an authenticated capability. Cached soft judgments need disclosed age. Default hash-vector embeddings explicitly lack semantic meaning, and the default backtest source is synthetic; neither is imported as semantic memory or real performance. Native replay fingerprints and observed-data diagnostics remain authoritative. |
| Prism CLI/setup/update, subscription/referral/revenue, feedback/alerts/telemetry, Cloudflare/Telegram and plugin/skill packages | **Deferred or unrelated to the local product.** The current source guide warns that older architecture docs are stale. Source family review follows current code. No cloud account, outbound alert/error telemetry, installation script, background process, self-update, provider entitlement or monetization flow was activated. Existing native signed-release/backup and local evidence controls remain. |
| Moon Dev trading prompt/allocation, bot/nice-functions, data collector and configuration | **Retain native bounded collection, exact sizing/cash reserve and disabled money path.** Separating observations from allocation is useful, but model confidence is parsed from prose with a default, per-position capping does not establish total cash feasibility, and repeated transaction submission after a broad exception is not unknown-order reconciliation. Hardcoded token addresses, size/slippage settings, mutable allocation CSV, temporary-data deletion and direct Solana order loops are excluded. No source code was copied, particularly without a root license. |
| Moon Dev risk/sentiment, roadmap and tutorial multi-agent notebook | **Do not import placeholders as capabilities.** Moon's `risk.py` and `sentiment.py` are empty. The tutorial's analyst/bull/bear/risk roles, bounded loops and audit schema are useful design examples already covered by the prior TradingAgents assessment. Notebook cell 59 writes a hypothetical $1,000 return into model reflection; live search is not historical availability proof, and an LLM consistency audit is not deterministic verification. On the target Python 3.11 parser, cell 30's backslash-containing f-string expression is incompatible (newer Python permits that syntax). All 28 cells remain unexecuted; no fabricated lessons, Chroma store, model signal-extraction call or LangSmith tracing was added. |
| TradePipeline `TradeJob.scala`, `price_functions.py`: VWAP, volume, notional and average trade size | **Adapted independently** in native `services/market_statistics.py` and `gymctl trade-flow`, reusing the existing report/export command structure. Exact Decimal totals preserve base/quote units; buy/sell/unknown volumes and aggressor imbalance supplement VWAP. Native recorded trades supply the data; no Kafka/NiFi/Flink stack or donor code is copied. Report groups pool dates by pair/Tehran hour. Processing-time windows and integer stock-size assumptions are not inherited. |
| TradingAgents `date_window.py`, verified market snapshots, filed/revision vintages and missing-data semantics | **Adapted the availability contract to the new trade-flow diagnostic.** Both event and receipt clocks constrain the cutoff; later receipts never enter an earlier report. Legacy UTC timestamp shapes and tiny scientific-notation amounts remain valid; invalid rows are counted/excluded, empty observations are unavailable, unknown aggressors are not neutral. Native bars, data portal, readiness and tool provenance already preserve related boundaries. Deterministic indicators and typed analyst grounding remain useful future work; computed values alone do not certify a feed or validate an LLM claim. |
| TradePipeline Kafka/NiFi/Polygon ingestion, Flink infrastructure, broker/asset/portfolio/state and allocation | **Keep native collector, durable journals, bounded adapters and Rust money authority.** Source agent instantiates Alpaca at import and cancels orders during initialization; ranking/allocation uses random Dirichlet weights and stock/integer sizing. These are not imported. The base broker deliberately contains unimplemented methods; neither those stubs nor the Alpaca transport establish Wallex behavior. RV/BV jump attribution differs between Python/Scala and is not a calibrated probability. Multi-asset capital allocation needs actual shared cash/reservation/valuation contracts. |
| Trading-Agent DQN/target-DQN/double-DQN, replay buffer, training/evaluation CLI and stock-price windows | **Deferred ML research, not a seventh strategy or pretrained execution engine.** Target-network/replay and separate train/evaluation data are useful designs. Source `act` forces its first buy, methods allow repeated purchases without a cash account and score realized price differences without execution fees/open-inventory liquidation valuation. Evaluation also appends to the training memory used by later episodes. Warmup pads initial prices instead of reporting unavailable history. Do not import its advertised profits, checkpoints, bundled stocks, TensorFlow/Keras runtime or visual theme as evidence. Native cash/fees/holdings, warmup and chronological validation remain. |
| TradingAgents analyst teams, bull/bear debate, risk debate, structured schemas, ratings and trader/portfolio-manager handoffs | **Retain native advisory/authority separation; defer the orchestration.** Typed arguments, explicit absent reports and bounded discussion rounds are valuable for a future grounded analyst. A Buy/Sell rating is not an order or a filled position. The source can retry structured failures as prose and tolerates/coerces optional numeric fields; these are not accepted as money-authority inputs. No multi-agent graph, model-generated probability or prompt-based risk approval was wired into execution. |
| TradingAgents decision memory, settlement/reflection and ticker/date backtest grid | **Deferred with concrete timing requirements.** Pending outcomes remain pending until the holding window and benchmark have closed; lessons must carry their resolution/availability time before reuse. The source explicitly evaluates decision quality rather than cash-account performance; its rounded alpha and model reflections are not reproducible execution P&L. Native immutable research jobs, shadow observations, matched accounts/baselines and temporal validation remain separate. Future lessons need authenticated run references and disjoint final evaluation; no live-memory contamination from backfills. |
| TradingAgents graph checkpoints/parallel analysts, scoped config, provider tiers, retries/tokens and CLI/reporting | **Keep native durable job clocks, fingerprints, optional gateway, limits and authenticated summary exports.** LangGraph state, a second SQLite checkpoint system, raw agent transcripts and a separate HTML/CLI application are not necessary additions. Script-free escaped portable reports are a useful later presentation improvement. Provider sign-in/refresh/revocation, credentials and remote endpoints were not imported or exercised; existing secure local credential handling remains authoritative. |
| TradingAgents Yahoo/Alpha Vantage/SEC/FRED/Reddit/StockTwits/Polymarket vendors, portfolio input and symbol mapping | **Defer new feeds; preserve unknown versus empty account and source-specific identity.** Filing and real-time vintages, unavailable-versus-empty errors and observation snapshots are valuable contracts. US equity fundamentals, macro revisions, social screening and prediction-market odds do not become Wallex spot facts. No speculative ticker alias, inferred historical company profile, news scraper or unqualified feed fallback was added. |
| TradzQAI environment/state/data loader, classic/CFD wallet/inventory/reward and indicator library | **Retain native exact accounting, actual warmup and explicit observations.** Source supports tick/bar inputs and composable state columns, but pads initial windows, has shell-interpolated data loading, synthesizes missing bar rows and defaults to clipping negative rewards (`no_neg=True`). Its classic contract sets fee zero, and floating wallet/exposure calculations do not replace the native simulator. No artificial candles, clipped losses, inherited fee tiers, indicator defaults, shorts or CFD assumptions were imported. |
| TradzQAI Tensorforce agent specifications, worker/session threads, saver/logger, Coinbase order book/websocket/order adapters | **Deferred/excluded runtime.** Config/weight identity and local-versus-live separation are useful ideas already represented by native run fingerprints and mode boundaries. Static parsing found an unexpected indent in `agents/DQNN.py`; advertised agent names are not proof of working trainers. Dynamic imports, model files, old exchange endpoints, busy retry loops and threaded maker/cancel management do not qualify custody, order ownership, STOP or unknown outcomes. No donor application was executed. |
| Jev `src/book.ts`, `model.ts`: cumulative depth bands and imbalance | **Adapted** in `services/liquidity.py`, `/api/markets`, and expanded Markets rows. Actual received bid/ask levels supply 10/25/50-bps quantities and notional totals; base-quantity imbalance is separate. Exact decimals replace donor floats. Missing, stale, future, crossed, nonpositive, nonfinite and duplicate-price books publish no numeric depth aggregates. Side timestamps and received-level counts remain available. This neither reconstructs the full book nor certifies fill capacity. |
| Jev `src/trader.ts`, `trades.ts`: intent, receipt and fill states | **Retain native Rust lifecycle/reservations/recovery.** A sent order is not a fill; an unknown receipt cannot release its reservation. Kuru/Monad gas, margin and fire-and-forget execution conventions cannot stand in for Wallex facts. |
| Jev `src/chain.ts`, `server.ts`: bounded history/newest-event display | **Retain native observation clocks and bounded inspectors.** Block coalescing must not delete accounting or observation events. SSE is a possible presentation refinement; wildcard CORS is excluded. |
| Jev `src/model.ts`, `config.ts`: model/live selection | **Excluded.** Default `MODEL=mock` returns heuristic probabilities and simulated latency/token counts. Private-key presence can select live trading there. Target retains explicit synthetic fixtures, no model fallback and disabled funded authority. |
| AI-Trader `service/server/research_exports.py`: selected research columns and private-content exclusion | **Adapted** as the allowlisted `paper-summary/1` card in `services/reports.py`, authenticated `/api/runs/{id}/summary`, and Research download. Original run/output/data/config fingerprints, period, rule mode, exact values, cost assumptions, valuation age and sampled drawdown are retained. Private notes, account records, arbitrary evidence blobs and model transcripts are excluded. This is a summary, not an anonymized full replay bundle or proof of source-file authenticity. |
| AI-Trader `worker.py`, `tasks.py`: background/HTTP separation | **Already addressed natively.** Collector maintenance does not await REST refresh; scheduled research has a foreground runner, durable clocks and transactions. The source's `fcntl`/Redis worker is not a Windows replacement. |
| AI-Trader `experiment_metrics.py`, `routes_trading.py`: windowed scores/equity | **Selective concepts only.** Native paper accounts keep their actual starting cash. Source snapshot code initializes `risk_violation_count=0` without measuring violations, and empty history can become zero profit/drawdown. These are not copied as safety/performance evidence. |
| AI-Trader signals, rewards, teams, experiments, copy trading and Polymarket | **Deferred or out of scope.** Community infrastructure adds an unrelated identity/database system. Social approval is not venue evidence, and prediction-market settlement does not qualify Wallex spot execution. |
| Vibe `agent/backtest/metrics.py`: initial cash/first-loss risk | **Adapted** as native sampled mark-to-bid drawdown. High-water mark starts at actual cash, includes the end estimate, and records peak/trough times. Missing paths are unavailable, not zero. Nonfinite, negative or out-of-order equity fails. Sparse marks cannot establish continuous risk or justify annualized Sharpe claims. |
| Vibe `agent/backtest/run_card.py`: compact structured provenance | **Adapted** in the portable summary. Risk/valuation remain structured; a summary digest supplements original run/output references. No fabricated model identity or unlimited transcript is attached. |
| Vibe `agent/backtest/validation.py`, `benchmark.py`, loader health | **Retain native matched baselines, chronological validation and readiness.** Bootstrap significance, inferred annualization and factor libraries need longer appropriate observations and separate statistical validation. |
| Vibe grounding evidence/figures/registry/release and strategy provenance | **Valuable future integration for a tool-using analyst.** The optional gateway currently returns ungrounded advisory text without trading tools. A figure gate needs typed observation references and arithmetic provenance across real tool results; a keyword/number filter would falsely imply grounding. |
| Vibe providers, scheduled research, strategy store, shadow account, portfolio and brokers | **Keep native equivalents.** Research ledger, strategy registry, shadow journal, protected account observation parser and model gateway already exist. Missing positions must remain different from an empty account; no multi-broker aggregation/shared portfolio execution was added. |
| Vibe agents/swarm, memory, channels, Pixel Office, desktop packaging, documents and OpenBB/factors | **Deferred.** Generic orchestration, outbound messages, document ingestion and a second desktop/frontend stack do not repair the execution boundary. They bring more tools, credentials and dependencies. No dormant donor runtime was added. |
| AlgoTrading `src/strategies/entry.ts`, `indicators/sma.ts`; Agentic `alphabot/agent.py`: SMA crossover | **Adapted** as registered `sma-cross`, separate from SMA mean reversion. Only closed bars are consumed; previous/current windows require `slow + 1` bars. A crossing from equality is recognized. Native Decimal features and actual holding state drive paper requests; a missing quote or rejected/unfilled buy is not an assumed position. CLI replay/live-paper, scheduled jobs, comparisons, validation, MCP catalog and dynamic UI consume the same registry. |
| AlgoTrading `src/risk/stops.ts`: fixed/trailing thresholds | **Retained as a future policy idea, not transplanted as protection.** A price comparison does not establish order ownership, quote freshness, executable quantity, venue stop availability or settlement. Native exit/reopening policies remain advisory until the real protected money path is qualified. |
| AlgoTrading backtest/tick/cache/live modules | **Keep native engine and identities.** Source cache key omits strategy functions, commission, EMA settings and data fingerprints; its additive rounded trade percentages and same-row decisions are not independent economic evidence. Target hashes data/config/costs and models later settlement. `realtime.ts` explicitly logs that feeds are not wired; that stub and legacy exchange dependencies are excluded. |
| OKX kit `packages/core/src/tools/types.ts`, `packages/mcp/src/server.ts`: explicit tool capabilities | **Adapted** read-only/non-destructive/idempotent/local-world annotations and a capability snapshot to the existing three research tools. The snapshot is scoped to this tool server and explicitly does not attest runtime isolation. Enforcement still uses the fixed dispatch allowlist; annotations alone are not access control. No order tool or new network permission was added. |
| OKX REST/signatures/orders/earn/bots, discovery/diagnostics and rate limiting | **Keep native venue/permission controls.** OKX signatures, order types and instrument identifiers cannot qualify Wallex. Target already has bounded adapters, pacing, venue facts, provider cooldown, durable mutation rules and explicit diagnostics. Per-module filtering is useful when a real larger tool surface exists; importing 170 tools would create unrelated authority. |
| Agentic `riskguard/rules.py`, typed payload/outcome and A2A risk tool | **Retain native deterministic risk separation and explicit rejection reasons.** A remote agent's `approved` response cannot replace trusted principal/capability checks or reconciliation. Source floats, caller-supplied limits/portfolio and single-asset demonstration balances are excluded. Its random-market simulator and cloud/ADK services are not actual observations or necessary dependencies. |
| FriesTrader `scripts/position_sizing.py`; Clawtrade `internal/risk/engine.go`: deterministic sizing, reserve and risk-distance caps | **Adapted** as `position-sizing` through native `domain/market_models.py` and the existing offline `paper-research` command. Explicit finite Decimal inputs determine a long-only gross quantity bounded jointly by modeled stop loss, position value and spendable cash after reserve, rounded down to the supplied quantity step. Both received-asset fees and adverse entry/exit slippage are included. Binding constraints, normalized assumptions and `NO_CAPACITY` are retained. No USD/broker minimum, conviction threshold or live setting is inherited. A modeled stop is not verified protection; no portfolio allocation or order is constructed. |
| FriesTrader entry gate, ranking, P&L denominator, stop/trailing exit, profit tiers and conviction trim | **Keep native entry/exit/reopening and durable evidence boundaries.** Separating thesis from fresh-price checks is already required. Ranked joint portfolio allocation, cash-flow-adjusted performance and tiered partial exits are useful deferred work needing verified holdings, basis, fills and cash-flow history. US equity earnings calendars/wash-sale settings, Robinhood MCP, account IDs and Git-push scheduling are not Wallex spot functionality and were not imported. Prompt prohibitions alone do not create runtime protection. |
| Code-master `Runner.java`, `LocalLiquidity.java`, `Tools.java`: intrinsic-time directional change, overshoot and surprise | **Already covered natively** by `periods.py`, `Consolidator`, and the offline liquidity diagnostic. Native clocks retain availability ordering/confirmation time, disqualifying quotes and exact prices; liquidity publishes assumed-null variance and uncalibrated status. No duplicate event engine, normal-CDF probability or Java runtime was added. Source Java float arithmetic and its H2 expression were not copied. |
| Code-master `CoastlineTrader.java`, `AlphaEngine.java`, `LimitOrder.java`, entry points | **Deferred/excluded execution assumptions.** Its eight long/short coastline agents, inventory cascades, quote-crossing fill tests and profitability targets do not establish venue fills, queue position, partial settlement, fees or a total risk budget. `AlphaEnginePublic.java` still requires a user-supplied `priceFeed`. Existing native paper fills, spacing-cost diagnostic, reservations and reconciliation remain the foundation. |
| Clawtrade/AlphaQuanter agent tool definitions, bounded loops and results | **Adapted narrow response provenance** on the existing three read-only research tools: tool name, native argument digest and SHA-256 of exact response text in MCP result metadata. Existing content/types stay unchanged. This supports traceable inputs/results without copying model reasoning or granting any trading tool. Hashes are not signed source evidence or semantic grounding, and the optional advisory gateway was not upgraded into a trading agent. |
| Clawtrade risk/what-if, backtest/optimizer/arena and performance widgets | **Retain native paired replay, cost stress and chronological validation.** The source what-if engine uses chosen uniform random paths/weights, not measured scenario probabilities. Its backtest evaluates the current candle and trades at that candle's close. Neither is imported as independent P&L/stop-fill evidence. Sharpe/annualized metrics and optimizer wins require appropriate sampling, selection controls and final evaluation. |
| Clawtrade UI, adapters/normalizer/router, events/streaming, vault/permissions/dead switch, alerts/briefings, memory, plugins/SDKs/voice/PWA | **Keep native equivalents; defer unrelated services.** `PriceChart.tsx` generates random fallback candles; `AgentStatus.tsx` generates synthetic history. These are excluded. Native observed-only UI, timestamps, protected custody, fixed tools, scheduler/alerts and journal remain. `execPlaceOrder` directly calls the selected adapter, independently of the separately exposed `risk_check`; that tool path is not transplanted. Multi-venue identity/currency aggregation, outbound Telegram/Discord, dynamic plugins, conversational memory and a second Go/React runtime require separate scope/contracts. No credentials, notification targets or schedules were imported. |
| AlphaQuanter data collectors, dated market/fundamental/news/macro/indicator tools | **Retain native availability-safe observations and strict read boundaries.** Source tools use local pickle/CSV stores and a placeholder `DATA_PATH`; calendar-date filtering alone does not establish publication vintages or revision availability. A future analyst may use typed, timestamped public evidence through bounded tools; no pickle loading, social/news ingestion or unverified retrospective data was added. |
| AlphaQuanter dataset builder, reward function, LangGraph loop and modified PPO trainer | **Deferred as a separate ML research program.** Forward-return labels are training targets, not actual account rewards. Action accuracy, reasoning-format/tool-count shaping and the provided random reward function do not qualify execution or profitability. The trainer contains a fixed-date Backtrader evaluation with assumed commission; native Trade does not train/serve these models. Integration would need complete dependencies/data, release-vintage controls, disjoint train/validation/final periods, artifact identity, calibrated costs and hardware evaluation. |
| Harvard `backtest/bb_squeeze_adx.py`, LLM_trader volatility terminology: rolling population-deviation bands | **Adapted the band concept** as native `bollinger-reversion`, with versioned/bounded parameters, exact Decimal mean/variance/square root, closed-price warmup and actual holding state. Enter below the lower band, exit at the mean; zero-variance windows do not fabricate an entry. It reaches replay, live paper, comparisons, validation, scheduler, MCP catalog and EN/FA UI through the existing registry. This is deliberately a separate long-only research strategy, not a replica or acceptance of the source's squeeze/ADX breakout. |
| Harvard research/backtest/implementation stages, CSV loader, templates, bot and exchange helpers | **Keep native qualification stages and adapters.** The supplied backtest searches final equity on its sample; that optimized result is not an untouched evaluation. Implementation uses Hyperliquid credentials, leverage, global state and external scheduling. Its hardcoded local CSV path, wallet setup, account/position configuration and dependencies were not imported. ATR/ADX/Keltner squeeze remains useful deferred research requiring tested indicator definitions and a matching execution model. |
| llm-agent-trader engine, trend benchmark/enhanced technical analysis, confidence sizing and unrealized P&L | **Retain native accounting and comparisons.** Hand-labeled trend phases are bounded examples, not general validation. Source strategy generates signals separately from the simulator, uses stock-share/commission conventions and forces final liquidation with zero commission. Target preserves received-asset fees, settlement/nonfill states, stale end marks, immutable identities and explicit abstainers. No source capital, share size or confidence return weighting was imported. |
| llm-agent-trader daily feedback, streaming analysis API, Next UI and provider/data wrappers | **Keep explicit failures and native outcome marks.** The source daily-feedback exception path returns generic analysis/suggestions; it is not copied as a completed model result. Bounded retrospective feedback is a future advisory feature; it must not rewrite decisions or leak later outcomes into earlier signals. Streaming progress is a presentation option, not permission to expose raw private prompts or run models. No paid provider/data request or second web stack was added. |
| MAHORAGA policy engine/broker, HMAC approvals, risk-state store, kill switch and stale-position exit rules | **Retain native protected authority/reservations/reconciliation.** Order-preview binding/expiry, deterministic checks and separate strategy/broker layers are sound design goals already represented. Source validation and consumption are separate operations; its no-DB broker fallback initializes kill state off and daily loss to zero. These cannot substitute for trusted, durable native admission. Source momentum/social staleness is distinct from quote freshness; missing entry metadata must not become proof of a healthy position. Alpaca equity/options/crypto rules are not Wallex qualification. |
| MAHORAGA Durable Objects, cron/session harness, pluggable strategies, D1/KV/R2 persistence, LLM/news/social/scraper providers, MCP and dashboard | **Keep local equivalents and defer cloud/social expansion.** Native foreground scheduling, durable jobs, alert history, fixed tools, gateway and protected storage remain. Cloudflare resources, outbound notifications, dynamic model tools, social sentiment, US-market calendar and multi-account credentials require separate scope, data provenance and operations. No cloud resources, schedules or broker/provider configuration were created. |
| LLM_trader `scripts/results_report.py`, cost storage and risk/reward analysis | **Adapted cost-aware arithmetic** as offline `trade-economics`: explicit long stop/target/quantity/fees/slippage, optional quote-denominated round-trip inference cost, modeled reward/risk and two-outcome break-even fraction. Unknown inference cost leaves after-inference results unavailable; explicit zero remains distinct. Cost-dominated targets have no feasible break-even fraction. No provider price or missing ledger cost is silently treated as measured zero. This neither imports reported performance nor forecasts a win rate. |
| LLM_trader analyzer/patterns/indicators, RAG/untrusted context, structured parsing and provider orchestration | **Retain explicit typed boundaries; defer the analyst pipeline.** Closed candles, deterministic indicator claims, bounded prompts, external text as data and classified provider failures are valuable. A keyword quarantine is not a complete injection defense, and chart/RAG/vision output must not grant execution. Native gateway remains advisory without dynamic trading tools. No 79-indicator stack, Numba, Chroma, vision renderer, scraper or model fallback chain was added. |
| LLM_trader executor handoff/reconciliation, brain/memory/reflection, risk/guards/exits, statistics, dashboard and claims tooling | **Keep native executor and evidence gates.** Confirmed fills, raw ledger retention, rejection/unknown states and separating sandbox execution from market evidence match native invariants. The separate executor service is not present in that archive; local policy/helper code cannot qualify it. Learned rules, matching historical trades and a public claims manifest are not calibrated authority or proof of profitability. Brain lessons, adaptive thresholds, external dashboard/notifiers and source test/performance numbers were not imported. All source families are inventoried; review is not a line-by-line certificate. |

## Verification and limits

Native additions reach the API, EN/FA UI, reports and tests. Regressions cover depth
boundaries/precision, missing/future/stale/invalid books, initial/final losses,
unavailable paths, download authorization, private-canary exclusion and summary
fingerprints. A real browser exercised all nine destinations, observed BTCUSDT
depth, chronological validation, sampled drawdown and a completed summary
download. Displayed negative paper results were retained.

The new crossover also ran against the recorded BTCUSDT window
2026-11-03 17:13:00.008408–20:13:00.008408 UTC, with one-minute closes,
1,000 virtual USDT, modeled 0.1% received-asset fees and 500-ms latency.
`sma-cross` (2/5), run `7db75d730720f6fe`, produced 29 modeled fills,
net **−61.89889340 USDT** and sampled maximum drawdown **6.18988934%**.
The matched EMA (2/5), run `456908a7d71b7740`, produced 23 fills and
net **−56.62608896 USDT**; holding BTC lost 5.93189390 USDT and holding
USDT stayed flat. This short historical diagnostic supports integration,
not profitability or prospective qualification. Five strategies now share the
native registry at that stage; the latest band addition brings the total to six.
Current full Python verification: 752 passed, five skipped, 39 subtests
(50.02 seconds).
The real downloaded crossover summary matched both its checksum and saved output;
decimal durations remain strings across the browser JSON round trip. Script/style
URLs now use content hashes after browser checks exposed retained older labels.

The preceding FriesTrader/Code/Clawtrade/AlphaQuanter archives contain 329 regular
files in total. Their review added
25 passing native cases covering sizing limits/fees/rounding/invalid inputs,
the real offline command and provenance mismatch detection. All three research
tools also passed an actual stdio check against the existing local research and
public-market stores. No account read, model call or order was performed.
Provenance uses the optional result metadata defined in the
[project's MCP 2024-11-05 schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/schema/2024-11-05/schema.json),
without changing existing content, tool permissions or dependencies.

The preceding Harvard/llm-agent-trader/MAHORAGA/LLM_trader archives contain
581 regular files. `.pi/source-inventory.json` records membership/hashes and
top-level Python symbols without importing the sources; every Python file
parsed statically. Native inventory still covers 108 production files.
The end-to-end pass reran full Python, Rust, gateway, formatting/lint and Windows
script parsing. All nine browser routes loaded; a real matched comparison,
EN/FA band controls and a checksum-verified summary download passed.

The default band strategy replayed BTCUSDT observations from
2026-11-03 17:13:00.008408 to 20:13:00.008408 UTC: one-minute closes,
1,000 virtual USDT, modeled 0.1% fees and 500-ms latency. Run
`a525e7f63765b728` produced 10 modeled fills and net **−24.59355959 USDT**;
matched default SMA run `e93aa7039474c352` abstained with zero fills/flat cash.
The real browser comparison `6446637092710b27` normalized the cuts to whole
minutes and showed the same results; its band run `b5c48a637ca78c85` downloaded
with a verified summary digest. This is a short historical integration check,
not a profitability finding or sustained prospective paper qualification.

The preceding Trading-Agent/TradePipeline/TradingAgents/TradzQAI group contains
330 regular files and 261 Python files. Static parsing succeeded for 260;
TradzQAI's `TradzQAI/agents/DQNN.py` has an unexpected indent. This is a static
inventory, not a successful donor suite or line-by-line certification. Original
archives remain untouched; application/provider/training entry points were not run.

That pass added 12 native cases for trade-flow arithmetic, receipt/event cuts,
legacy timestamps, tiny decimal storage, malformed observations, unknown direction,
empty/demo states and actual read-only CLI/export behavior. Full Python tests
and Ruff passed. Rust, gateway, installed-host and browser checks above belong
to the preceding pass; their code/dependencies were not changed here.

The actual `trade-flow` CLI processed 89 stored BTCUSDT trades between
2026-11-03 17:13 and 20:13 UTC, four Tehran-hour groups, with zero invalid rows
excluded. Output `.pi/trade-flow-observations.json` has data digest
`1ba26e93a365c0592d68a07953fb153976cdabf5508b0ef5f1cf05e47ef118f4`.
This confirms the observed-data/report path, not complete venue tape, predictive
signal quality, execution capacity or profitable trading.

The latest Prism/Moon Dev/multi-agent tutorial/ClawQuant group contains 620
regular files. All 83 standalone Python files parsed without importing them.
Of 28 tutorial notebook code cells, 27 parsed on the target Python 3.11; cell 30
requires newer f-string syntax. The byte-identical duplicate tutorial ZIP was
not counted twice. Static inventory includes every file, but selected-module
review and parsing do not establish line-by-line review or donor runtime qualification.
The follow-up rehashed all 620 extracted files against the recorded inventory:
zero missing files or content mismatches.

Ten new native cases cover bounded window counts, independent flat accounts,
per-window purge/reference persistence, stale/abstaining states, missing-data
rejection, rollback, single-window compatibility and a real concurrent writer
while the multi-window snapshot stays pinned. Full Python and Ruff passed.
That CLI pass changed no Rust/gateway/UI/Windows/dependency/credential
configuration. Rust/gateway/Windows runtime checks and network vulnerability
audits were not repeated in this follow-up.

The actual `gymctl validate --folds 3` command replayed recorded BTCUSDT
observations from 2026-11-03 17:13 to 20:13 UTC with 1,000 virtual USDT per
account and default modeled costs. Validation `94ff958194e89855` saved nine
referenced runs. Each window selected EMA 3/8 using its own earlier observations;
the three later holdouts were **−1.66016392**, **−6.10882287** and
**−12.53677481 USDT** (`6d84a66ad77c1e68`, `ba89b338e6433151`,
`385bcd9aa23442dd`). These are separate short-window accounts, not compounded
returns, a sustained prospective session or profitability evidence.

The second pass connected the same bounded window choice to `/api/validate`
and Research, with English/Persian labels, per-window status/selection rows and
existing run inspection. Ten additional API/error-path cases cover strict bounds,
comparison-field rejection, artifact references, unavailable holdout data and
unexpected replay error propagation. Three UI runtime tests also passed; their
incomplete/abstaining response fixtures remain test-only. The actual browser
reproduced `94ff958194e89855` with three evaluated rows and the same negative
holdouts in both languages. No donor price fallback, hypothetical profit or
execution placeholder was introduced into production. Evidence screenshot:
`.pi/ui-verification/validation-windows.png`.

Full target checks and runtime limits are in [system status](system-status.md)
and [acceptance status](acceptance-status.md). These donor suites were not run;
reviewed designs are not certified donor runtimes. The earlier TradingGym source
and its 18 focused passing tests are in [research design](research-design.md).

The table explicitly distinguishes adaptations, existing coverage, excluded
shortcuts and useful deferred work. It does not claim every donor subsystem has
been integrated or every line of those large sources has been reviewed.

## Deferred-work implementation follow-up

The preceding 22 investigated Downloads ZIPs and the five sources below were
moved into `Downloads/archive`; extracted review folders were retained.

- **Joint paper sizing adapted:** `domain/portfolio.py` combines the previous
  single-position calculator with ranked candidates sharing cash reserve, modeled
  loss and new-allocation caps. It reaches `paper-research` as `portfolio-sizing`.
  This closes the shared-cash arithmetic gap, not executable portfolio authority,
  actual existing holdings, cash-flow returns or partial settlement.
- **Numeric grounding adapted:** `research claim-check FILE` verifies allowlisted
  native artifact facts, identity/output digests and matched-input arithmetic with
  explicit rounding. Invented figures mismatch; malformed artifacts reject. This
  is a numeric gate for future analysts, not a completed analyst/debate graph,
  semantic reasoning validator or independent source authentication.
- **Portable reports adapted:** `summary RUN_ID --format html --output FILE`
  exports the existing private-field-excluding summary into escaped, self-contained
  HTML with a restrictive CSP, no scripts/dependencies and an expandable source
  card. The actual saved negative holdout was checked at desktop and 390px widths.

These additions have 36 new Python cases. Source applications, provider requests,
model weights and funded execution were not activated. Remaining research and
executor work is explicitly open in [implementation plan](implementation-plan.md).

## OpenTrade, Pamela, Stock-Market, AutoHedge and OpenProphet

The supplied ZIPs were inventoried and extracted for static review without running
their applications. All 659 regular files have inventory entries; all 22 standalone
Python files parse. Selected implementation families were reviewed, rather than
claiming a line-by-line correctness certificate for every file. Originals remain
unchanged in `C:\Users\ACER\Downloads\archive`; extraction and inventory receipts are in
`.pi/sources` and `.pi/source-inventory.json` at the repository root.
The final rehash matched all 659 extracted files to that inventory, with zero
missing files or content mismatches.

| Archive | Files | License observed | ZIP SHA-256 |
| --- | ---: | --- | --- |
| OpenTrade-main.zip | 281 | Elastic License 2.0 | `f972c761390d9eca392d26d68b36063d9db2424085f05f20da42860a938820a6` |
| pamela-master.zip | 223 | README MIT badge; no license file found | `c961a9a1e53a3b93f0d8f3af0195302883b8cfcf32e3427973fbc746f35a44a3` |
| Stock-Market-master.zip | 8 | MIT | `4ac04c2487586554dbedab91fada215a6d878856fe34e8c80bdb4339f37db4b8` |
| AutoHedge-main.zip | 51 | MIT | `e998228572869b754f2aba3ee61016bf427ebc1159ad04421d945dc5e6f3767b` |
| OpenProphet-main.zip | 96 | CC BY-NC 4.0 | `fe575725fdd6a74eee125f6f5012d7fde43acfe455f18f64bfab0695bf6e829b` |

No source implementation was copied or new dependency installed. The native
indicator feature below independently implements the useful diagnostic concept.

| Reviewed family | Decision and native owner |
| --- | --- |
| OpenTrade scheduler wake coordinator, monitor runner and approval store | Retain bounded, durable research jobs and existing reservations/unknown outcomes. FIFO work, deadlines, stalled-session detection and expiring decisions are useful patterns. Arbitrary shell monitors and automatic approval do not enter the fixed read-only tool surface; a UI approval is not principal-bound executor authority. |
| OpenTrade local API, database backup, broker snapshots and analytics | Retain loopback authentication, native exact account normalization and encrypted no-overwrite recovery. Source backup failure can permit migration to continue, and its DB may contain broker tokens; that is not the native backup contract. Robinhood/options mappings do not qualify Wallex. Analytics is PostHog telemetry, not economic performance; no telemetry, feedback service, PTY host or second desktop stack was added. |
| Pamela portfolio valuator and confidence scoring | Reject the 0.5 price fallback, average-price/cash-only error fallbacks and price-edge-derived confidence as observed value or measured probability. Native two-sided quote qualification, unknown valuations and exact accounting remain authoritative. |
| Pamela expiring-market, allocation/fund and investment strategies | Close-to-expiry prices and a fixed 0.99 predicted probability do not establish outcome certainty or net return. Shared allocation arithmetic already has a native paper owner. Polymarket/USDC wallet settlement, token deployment, Telegram and TEE claims were not imported as Wallex execution or Windows containment. News caches need actual source/vintage contracts before use. |
| Stock-Market evolution strategy and prediction script | Exclude advertised profits and trained forecasts: fitting and buying share the same history; remaining-cash reward omits open inventory; fees/latency are absent. Prediction scaling fits the full series and future simulations are filtered. Obsolete TensorFlow APIs, first-price history padding, global data dependencies and fixed-file download/removal behavior were not introduced. Keep native temporal diagnostics, actual warmup, fees and holdings; reproducible independent ML evaluation remains open. |
| AutoHedge director, sentiment, risk, execution and quant workers | Keep deterministic calculation separate from advisory judgment. Prompt requests for risk probabilities and string outputs are not typed quantitative evidence or approval; prompts capture an import-time date. Native sizing and numeric claim checks cover the useful arithmetic boundary. No Swarms runtime, paid model or search request was activated. |
| AutoHedge Jupiter tools, environment loader and experimental/vendor feeds | Exclude Solana transaction signing, parent-directory environment loading and broker-specific execution from this integration. Real chain-writing code still does not provide the approved Wallex path. Yahoo/Polygon/Exa/Jupiter data and experimental bots require their own data and execution qualification. No source credentials were loaded. |
| OpenProphet technical analysis | Adapted descriptive SMA/RSI/MACD diagnostics into native `domain/indicators.py`, `services/technical_analysis.py` and `gymctl technicals`. Source insufficient-history 0/50 fallbacks, approximate MACD signal (`ema12 * 0.85`), bar-count-as-day labels and additive confidence were excluded. Native closed bars, explicit null warmup, Wilder RSI and EMA of MACD history replace those shortcuts. No strategy was added. |
| OpenProphet order controller, Alpaca transport and position manager | Durable intent/client-ID recovery is already covered by the executor's journal/reservations/unknown-state rules. Stops, partial exits and trailing protection remain useful open work requiring real ownership and settlement evidence. Source float quantities, broker-specific assumptions and unfinished options quotes do not qualify a Wallex money path. |
| OpenProphet permissions/MCP, heartbeat, agent server and memory | Retain the native three fixed read-only tools. Self-updated order permissions, mutable MCP tools and heartbeat switches cannot grant trusted authority. SSE/state/vector memory and seeded lessons do not justify a new dashboard or invented outcome history. Keep allowlisted private exports; no LAN listener, auto-update, embeddings, news provider or model runtime was activated. |

The technical report uses one bounded read snapshot and the existing quote quality
rules and midpoint consolidator. Partial/forming bars and buckets containing bad
quotes are excluded. Missing buckets reset warmup to the final contiguous segment;
bucket continuity does not certify continuous observations within each bucket.
Prices remain exact decimal strings. Volume, signals and calibrated confidence
are not synthesized. RSI14 needs 15 closes; MACD12/26/9 uses the native
first-close EMA seed and needs 34 closes for its signal. Seed conventions are
disclosed, without claiming third-party numerical parity. Definition references:
[TA-Lib RSI](https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_RSI.c)
and [TA-Lib MACD](https://raw.githubusercontent.com/TA-Lib/ta-lib/main/src/ta_func/ta_MACD.c).

Fifteen new cases cover independent numeric fixtures, warmup, flat/rising/falling
prices, bad quotes, gaps, historical cutoffs, bounded snapshots, stale/empty data
and read-only/no-overwrite CLI behavior. Independent review found no concrete
correctness or security issue. The full native Python suite passed 752 tests,
with five existing Windows symlink-privilege skips and 39 subtests; Ruff passed.

The actual recorded BTCUSDT CLI report `fbf96b7fde2b7681` covers 2026-11-03
17:13–20:13 UTC at one-minute resolution: 2,208 observations, 178 closed bars,
two excluded bad-quote bars and a final contiguous 43-bar segment. SMA20 is
77426.8475; SMA50 remains unavailable because 43 bars are insufficient. Receipt:
`.pi/reports/btcusdt-technicals.json`. No source application, broker, wallet,
notebook, model or weights ran. Rust/gateway/Windows/browser checks and network
dependency audits were not repeated for this Python CLI-only addition.
