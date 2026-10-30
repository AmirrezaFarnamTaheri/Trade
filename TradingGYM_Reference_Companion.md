# TradingGYM: Reference Companion

*Companion to the Master Specification and Plan, Revision 6 (30 October 2026). Reference material only: nothing here is a normative requirement.*

Contents: Appendix C (absorption matrix of 49 open-source projects and anti-patterns).

## Appendix C. Absorption matrix (49 open-source projects)

Four parallel scouts covered: trading engines (12 repos), LLM multi-agent frameworks (10), autonomous AI bots (10), and RL/ML/research/exchange engines (18). The GitHub API was disabled in this environment, so **no star counts, push dates or file trees were available**. Scouts read READMEs and selected source files through `raw.githubusercontent.com`. The main session then re-fetched the key claims and confirmed them:

- Alpha Engine `code.java` (1,057 lines): `Runner` and `LocalLiquidity` classes, surprise constants 0.08338161 / 2.525729 at lines 695-700, `tryToClose` at line 772 [proof: AntonVonGolub/Code/code.java].
- nautilus `bar.rs` and `enums.rs`: `PriceType`, `BarAggregation`, `OrderStatus::Denied` vs `Rejected` [proof: nautilus_trader/crates/model/src/enums.rs:326,1439,1449,1953].
- Lean `PeriodCountConsolidatorBase.cs`: `IPeriodSpecification`, `_workingBar`, `WorkingData` [proof: Lean/Common/Data/Consolidators/PeriodCountConsolidatorBase.cs:41,47,130].
- hikyuu README: environment → condition → signal → sizing → exit → slippage → cost; portfolio as strategy; run modes A/B/C [proof: hikyuu/readme.md:37,73,115].
- SignalBet README: `hybrid` and `compare` modes; compare never orders [proof: coinbase-trading-agent/README.md:114-115].
- TradingAgents `conservative_debator.py`: `opponent_argument_or_opening`, `report_or_absent` [proof: TradingAgents/tradingagents/agents/risk_mgmt/conservative_debator.py:5-19].
- Wyckoff `ARCHITECTURE.md`: `prepare_tool_call` gate and `BACKGROUND_TOOLS` [proof: WyckoffTradingAgent/docs/ARCHITECTURE.md:320,332].

Items a scout described from README text only, or from memory, are marked `{unverified}` below. Not inspected at all: BaggaT236/AI-Trading-Skills (unreachable), Algoloop (empty README fetch), frank-quant/ai-trading-videos, paulperry/quant, Harvard-Algorithmic-Trading-with-AI, Quant-Developers-Resources, viabtc, fmstephe, SubMicroTrading and Order-Book-Matching-Engine. The last four are order-book or exchange engines, judged irrelevant from their descriptions alone.

| Repo | Fit | What to take | Mode | Lands in |
| --- | --- | --- | --- | --- |
| QuantConnect/Lean | High | Pluggable-period consolidator with queryable working bar; `CashBook` (currency → amount, rate, account currency); `SecurityExchangeHours` (tz, weekday hours, holidays, early/late) + add halt overlay; Alpha→Portfolio→Risk→Execution split {unverified}; per-security fill/fee/slippage models {unverified} | P/A | Data Portal, paper accounts, VenueRegime, component registry, simulator |
| nautechsystems/nautilus_trader | High | `BarSpecification{step, aggregation, price_type BID/ASK/MID/LAST}` + `BarType` string as subscription/storage key; `Denied` vs `Rejected` order status; injected Clock for backtest/live parity {unverified}; `SYMBOL.VENUE` ids {unverified}; partitioned Parquet catalog {unverified} | P/A | Resolution type, Executor lifecycle axis, Data Portal, multi-venue ids |
| fasiondog/hikyuu | High | Strategy as composed parts (environment, condition, signal, money manager, stop, take-profit, profit goal, slippage, cost); "portfolio as strategy" with three run modes (signal aggregation / fund allocation / shared account) | A | Component registry, Research, PortfolioTarget |
| StockSharp/StockSharp | Med | Visual Designer (click-built strategies); per-venue connector pattern; Hydra-style data-health view {unverified} | U/A | Later visual builder, Health |
| quantopian/zipline | Med | Pipeline API (point-in-time factors/filters over a universe) and trading-calendar abstraction {unverified}; README is from the Quantopian era | A | Universe module, research factors |
| AlexWan/OsEngine | Med | Per-bot source tabs (instrument × timeframe), optimizer UI {unverified} | U | Research UI, multi-TF strategy setup |
| fbertram/TuringTrader | Low-Med | Desktop backtester; report templates {unverified} | U | Research reports |
| Capnode/Algoloop | Low | Windows desktop shell around Lean (not inspected) | — | — |
| paulran/aioquant | Low | Async event framework on a message broker; too heavy for one operator | — | — |
| Bohr1005/xcrypto | Low-Med | Rust server with strategies attached over WebSocket; echoes the Executor boundary | A (confirmation) | — |
| 0xemmkty/QuantMuse | Low | README is marketing-heavy | — | — |
| OpenByteInc/QuantDinger | Low-Med | Idea → backtest → paper → live product flow; multilingual docs | U | Onboarding flow |
| TauricResearch/TradingAgents | High | Look-ahead fixes in its changelog as an **eval checklist**; three rebutting risk critics; `report_or_absent`; tiered model providers; settings recorded per report; decision log settled later into memory | A/F | Model Gateway, eval harness, HypothesisRegistry |
| YoungCan-Wang/WyckoffTradingAgent | High | `prepare_tool_call` gate (exists/schema/scope); per-surface tool allowlists; refuse to start if dangerous tools are registered; background tools; **shadow ledger** of every signal; data-quality contract (coverage gate, unknown units stay missing) | A/F | Tool dispatcher, Journal, Data Portal |
| zubair-trabzada/ai-trading-claude | Med | Command catalog (`quick`, `technical`, `thesis`, `compare`); parallel specialists; report export. Reject its unvalidated 0-100 score | F/U | Research skills menu |
| LLMQuant/awesome-trading-agents | Med | Pointers: DeepFund / "Time Travel is Cheating" (arXiv 2505.11065) on LLM look-ahead; live-trade-bench and LLM-Trading-Lab (forward-only evaluation); QuantGPT (hypothesis→backtest MCP); ContestTrade (internal competition with abstention) {unverified} | R | Eval protocol, research tools |
| kweinmeister/agentic-trading | Med | Minimal typed `TradeProposal → RiskCheckResult` with ordered rules; use as a Python pre-validator and test oracle | P | Python-side checks, Executor test oracle |
| NoFxAiOS/nofx | Med | "Frontier": up to three labeled plans overlaid on the chart, nothing sent until approved; exact-decimal net reward/risk and min-notional checks; **preferences cannot lower hard limits**; late slices expire rather than burst | U/A | Operate plan-compare widget, Executor rules |
| HKUDS/AI-Trader | Low | Social/leaderboard platform; remote self-registering skills are an anti-pattern | — | — |
| Yaolinwang/AITD | Low | Anti-patterns (one-click paper→live; untimestamped "learning") | — | — |
| QuantVela/build-your-onchain-agent | Low | Thin tutorial | — | — |
| BaggaT236/AI-Trading-Skills | n/a | Unreachable | — | — |
| signalbetorg/coinbase-trading-agent | High | `compare` mode (rule vs AI per tick, never orders); `hybrid` (AI may only confirm/reject a rule signal); confidence floor; risk-per-trade + max-quote caps; validated config | A/F | Research Arena, Model Gateway, Executor RESIZE |
| 195440/nof1.ai | Med | Tiered drawdown ladder (warn / block entries / *prompt* to flatten); max hold time; max open positions; decision log panel | F/U | Executor policy ladder, Operate gauge, Journal |
| SnowingFox/open-nof1.ai | Med | Per-decision "why" view (inputs, reasoning, action); equity normalized to a common start; separate valuation and decision cadences | U/A | Journal drawer, Arena chart |
| Gajesh2007/ai-trading-agent | Med | Indicators as on-demand model tools; JSONL diary with local tail API (copy the idea, not its 0.0.0.0 binding or free `path` parameter) | A/F | Gateway tools (point-in-time), Health log viewer |
| yolojewjitsu/moon-dev-ai-agents | Med-Low | Idea catalog: research-to-backtest drafting, risk narrator, audible alerts, multi-provider model factory with local models | F | Research intake, alerts, Gateway providers |
| daydy-dev/moon-dev-ai-agents-for-trading | Low | Repackaged copy | — | — |
| algotrading-lab/ai-algotrading-agent | Low | SMA backtester; claims not shown | — | — |
| Dennis-bv/dex-trade-agent-kit | Low | Branding mismatch over another vendor's tooling; one-line installer. **Do not install** | — | — |
| picotts544/hyperliquid-ai-signal-bot | None | Fork-farm signals, unverifiable P&L, private key on the command line. **Avoid entirely** | — | — |
| Abomination81/copybot | Med | Rust executor + Python guardian (validates TradingGYM's split); explicit arming per strategy lane; its documented unsafe default as a cautionary example | A | Operate arming per workload |
| AntonVonGolub/Code | **High** | Directional-change `Runner` (bid confirms upturns, ask confirms downturns); overshoot events; `LocalLiquidity` surprise indicator; coastline cascade/decascade with inventory-dependent thresholds | P | Event sampler, features, strategy zoo |
| tensortrade-org/tensortrade | High | Registered Action / Reward / Observer / Stopper / Informer components; long-only all-in/all-out and fractional actions; `MaxLossStopper`; its README shows profit at 0% commission turning to loss at 0.1% | A/P | RL Environment Registry, regression test |
| AI4Finance-Foundation/FinRL-Trading | Med | Weight-centric chain: selection → allocation → timing → risk overlay, same weights in backtest and live; KAMA timing overlay; rotation with residual momentum {unverified} | A | PortfolioTarget pipeline |
| je-suis-tm/quant-trading | Med | Small strategy scripts: Heikin-Ashi, Parabolic SAR, Awesome Oscillator, MACD, Bollinger W-bottom, RSI patterns, Shooting Star, Dual Thrust, London-style session breakout, pair trading | P | Strategy zoo, shape fixtures |
| Alinebm17/trade-backtesting-engine | Med | DCA (safety orders, dynamic sizing) and grid (range, spacing, levels) parameter schemas; no cost model, so its P&L is not trusted | A | Stress fixtures, conversion/DCA workload |
| samre12/deep-trading-agent | Low | Lessons in what to avoid: overlapping episodes, no cost model, no held-out test | R | RL traps list |
| waylandzhang/ai-quant-book | Low-Med | Parts on costs and execution | R | Curriculum |
| scumabo/AI-for-Trading | Low-Med | Overfitting and cost-aware optimization notebooks | R | Curriculum, tests |
| EliteQuant/EliteQuant | Low | Link list | R | — |
| fluidex/dingir-exchange | Low | Append-only operation log with snapshot replay, as a Fake Venue journaling idea {unverified} | A | Fake Venue |
| Other link lists and courses (ai-trading-videos, Quant-Developers-Resources, paulperry/quant, Harvard course) | Unrated | Not inspected | R | — |
| Order-book and exchange engines (viabtc, fmstephe, SubMicroTrading, Order-Book-Matching-Engine) | None (from descriptions) | Only relevant if an order-book venue is added later | — | — |

### C.1 Anti-patterns and security warnings

- **Model with order authority** (nofx Autopilot, nof1 clones, Nocturne, AITD one-click live, TradingAgents' approving manager). TradingGYM keeps Proposal → Executor.
- Remote self-registering skills and `curl | bash` installers: supply-chain and prompt-injection risk.
- Memory or "learning" without publish-time discipline; unvalidated composite scores and "Strong Buy" labels; leaderboards built on single live runs.
- Per-tick multi-round debates: cost and latency with no demonstrated benefit.
- Sending balances or account identifiers to third-party model providers. Send normalized, redacted views.
- Cost-blind RL rewards, hold bonuses, zero-padded warmup, overlapping-episode leakage.
- Unsafe defaults seen: dashboards bound to 0.0.0.0, free `path` parameters, flatten-on-first-signal defaults.
- **Do not clone or run** `picotts544/hyperliquid-ai-signal-bot` or `Dennis-bv/dex-trade-agent-kit` on any machine. Treat repos with forks far exceeding stars as untrusted. Never place any of these repos on the machine holding the venue key.
