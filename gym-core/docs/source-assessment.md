# Source assessment

Updated 2026-11-04. This assessment covers the eight latest Downloads archives,
all 570 regular files, and their connections to Trade. Every inventoried file is
assigned a decision ID below in `.pi/source-assessment.json`; no file is left
unclassified. This means complete file accounting and module-family assessment,
not a claim that every source line is correct or that these applications have
been run. Code paths were inspected selectively within each family. Tests,
documentation, deployment files, assets, duplicate bundles and bundled state are
included in accounting. The eight original ZIPs are now in
`C:\Users\ACER\Downloads\archive`. All eight SHA-256 values matched the review
before moving and after archiving; no destination was overwritten. Receipt:
`.pi/archive-receipt.json`. Extracted source folders were not moved.

## Provenance

| ZIP | Files | License found | SHA-256 |
| --- | ---: | --- | --- |
| dex-trade-agent-kit-master.zip | 294 | MIT, OKX | `d3950f7da773529865b19ba350bc380b929f6fc99e3b4b701d8eb1051837939f` |
| nof1.ai-main.zip | 108 | AGPL-3.0 | `275ed6768d68028bf7c66ec48c978bffb73180a6ce05dbacbeea71bbd251bb09` |
| rizzo-trading-agent-main.zip | 20 | MIT | `ac74d4bb42d75f1336dadb39a94ecce678db1e7790a0b7479de2b3d6162fd79a` |
| agentic-trading-desk-main.zip | 17 | MIT | `88389eb39f946e840bf160ecf7eb3d7df516b3af37e25be96f99535095286144` |
| ai-trading-agent-gemini-main.zip | 33 | No license file found | `8d040ac4378b86aadc1f380af9a6e1970a87bd20052f7657d5e1056e6477075b` |
| gpt-trading-agent-main.zip | 9 | No license file found | `02caea84b2531fa376d3777b9f9a75cff6d86e8b6cb8881483cca19b7ec15a8b` |
| ai-trading-agent-main (1).zip | 5 | No license file found | `26e815ad2eaca08cf228b1d2c162c2707373dd8343126eed9280decaaf905728` |
| nof1-tracker-master.zip | 84 | MIT | `c920528b709859365ca41813fdabe9887aee871dcdca58dcfc18b65311edfced` |

The `(1)` archive extracts to `ai-trading-agent-main`. The 21 standalone Python
files parse on the target Python version, including four duplicated desk scripts.
No source implementation, dependencies, keys, portfolio samples, database state
or model weights were copied into production. The new timeframe feature is an
independent extension of Trade's existing report and consolidator.

## Integrated and existing coverage

The useful addition is **multiple technical timeframes from one observation
snapshot**, motivated by nof1's multi-timeframe service, Rizzo's multi-interval
inputs and the desk's deterministic-calculation separation. Repeat `--res`:

```text
gymctl technicals BTCUSDT --from 2026-11-03T17:13:00Z --to 2026-11-03T20:13:00Z --res 1min --res 15min --res 1h --output timeframes.json
```

The original single-resolution JSON contract and default 15-minute resolution
are preserved. Two to four distinct fixed resolutions produce a
`technical-timeframes/1` report. All views share a bounded read snapshot,
observation digest and exclusive end cutoff; each independently excludes partial,
forming and bad-quote bars and resets warmup after gaps. The combined request
is limited to 10,000 bar periods, 100,000 observations and 31 days. Insufficient
history stays null. No source's zero/neutral substitution, floating-point sizing,
confidence score, synthesized volume or majority-vote trading rule was added.

Existing native owners already cover several valuable patterns: fixed read-only
tool discovery, explicit demo/live stores, exact units/fees, shared-cash paper
sizing, freshness checks, durable intent and unknown-order holds, bounded
research jobs, output fingerprints, claim checking and private-field-excluding
reports. Replacing them with a second source runtime would duplicate authority
and persistence paths. The following tables record the remaining decisions.

## DEX trade agent kit

Despite its archive name, this snapshot implements an OKX CEX toolkit. It is not
evidence of a qualified decentralized-exchange executor.

| ID / module family | Value and decision |
| --- | --- |
| DEX-DATA — market, market-filter, indicator, news, smartmoney, audit tools | Screening/ranking, indicator discovery and traceable tool calls are useful. Native observed market statistics/technicals, fixed MCP catalog and research ledger remain the owners. Source indicators are a vendor API response, not local reproducible historical calculations. New smart-money/news/OI/funding data needs recorded identities, availability, freshness and vendor contracts before integration. |
| DEX-EXECUTION — account, spot, swap, futures, contracts, options, algo, DCA/grid, earn, event, conversion and shared tool helpers | Keep native exact sizing, reservations and evidence gates. Product units and settlement differ across these tools. Transfers, borrow, derivatives, structured earn, on-chain earn, bot creation and event orders are excluded from this spot-paper integration. TP/SL and trailing workflows remain useful requirements for the separately unqualified real executor. Server defaults, contract multipliers and JavaScript number conversion do not replace exact native instrument metadata. |
| DEX-RUNTIME — REST client, config, constants, rate limiter, signature, errors, logging and safe-file utilities | Bounded timeouts, endpoint-specific rate limits, trace IDs, typed errors and avoiding ordinary POST retry are useful existing native contracts. Source opt-in retries for some writes cannot grant venue idempotency. Its lexical archive-path check does not itself prove symlink containment; temporary-file rename may replace an output, unlike native exclusive report creation. Retain native adapters/storage rather than importing another network client. |
| DEX-MCP — server, capability snapshot, index and transport | Read-only/destructive/idempotence annotations are useful and already adapted from the earlier related OKX source. Retain the three fixed native R0 tools. Tool annotations and credential flags do not authenticate a T1 principal or qualify an installed boundary. No money tool was exposed. |
| DEX-CLI — registry, parser, help, formatter, diagnostics, commands and config profiles | Discoverability, routing validation and diagnostics are useful existing native CLI/test responsibilities. Do not install a second CLI, copy broker remediation commands or expand private credential/profile access. Native `technicals` now documents repeated resolutions. |
| DEX-INSTALL — auth binary, Pilot manager/cache/resolver, skill marketplace, setup, upgrade and install scripts | Download/checksum/version patterns are useful references for the existing release/update gate. Exclude downloaded executables, auto-upgrades, proxy/auth helpers, arbitrary skill installation and client-config edits; none ran. |
| DEX-TEST — core/CLI/MCP tests, smoke/scenario scripts and mock binaries | Boundary, routing, permission and malformed-response cases informed the review. Fixtures are tests, not market observations. No source test ran: smoke/scenario scripts can involve real endpoints and orders. Native tests validate the adapted feature. |
| DEX-REFERENCE — module docs, architecture references and skill workflows | Account, bot, auto-earn, earn, event, futures, market, news, options, smartmoney, spot and swap families are all accounted for. Templates/prompts are advisory references, not execution policy. No source skill was installed or followed as an instruction. |
| DEX-PACKAGE — manifests/locks, CI, editor/hook settings, licenses and project metadata | Inventoried for supply-chain/context boundaries. Retain native locks, workflows and Windows installation design; no package install, hook, CI dispatch or publishing occurred. |

## nof1.ai

| ID / module family | Value and decision |
| --- | --- |
| NOF-DATA — exchange facade, Gate/OKX clients, WebSocket, multiTimeframeAnalysis and news client | Adapted only the multi-timeframe concept into one native observation snapshot. Source independent parallel requests do not provide that snapshot guarantee. Missing EMA/price/volume can become zero and missing RSI becomes 50; these fallbacks were excluded. Keep native publication clocks, raw segments and explicit outages. WebSocket cache/reconnect and vendor news need their own recorded-feed qualification before use. |
| NOF-STRATEGY — aggressive, aggressiveTeam, aiAutonomous, alphaBeta, balanced, conservative, mediumLong, multiAgentConsensus, rebateFarming, swingTrend, ultraShort, index/types | Profiles expose useful distinctions between horizon, risk and observation context. They mix prompts and leveraged futures settings; labels and consensus are not measured predictive ability. Retain six native paper strategies and temporal diagnostics. No leveraged profile, rebate turnover strategy or purported profitable preset was imported. |
| NOF-AGENT — tradingAgent, analysisAgents, aggressiveTeamAgents and tradeHistoryUtils | Separate analyst perspectives and recent closed outcomes are useful future grounding inputs. Model-written decisions, confidence and debate remain advisory; closed-trade-only win rates and null-P&L-to-zero summaries cannot certify whole-account results. Native numeric claim checks and actual availability-bound outcome references remain required. |
| NOF-SCHEDULER — tradingLoop, accountRecorder, stopLossMonitor, trailingStopMonitor and partialProfitMonitor | Persistent peak/partial-exit state, account snapshots and measured stop workflows are useful requirements. Retain native durable research scheduling and reservations; do not import another cron loop or competing close monitors. Polling a stop and labeling a close are not verified venue protection or settlement. Real partial/trailing exits remain open work. |
| NOF-EXECUTION — trading marketData/newsData/accountManagement/tradeExecution tools | Keep native exact read normalization and narrow execution boundary. Gate/OKX contracts, leverage mutations, model-accessible actions and floating quantities are not an approved Wallex transport. No tool, account or order call ran. |
| NOF-UNITS — contract mapping/utils, encoding, time/log utilities, Gate/OKX types | Contract unit conversion is valuable; source default multipliers (including generic fallback) and cached fallback metadata were excluded. Preserve native explicit units, decimal strings, availability timestamps and unknown metadata. Local formatting/timezone helpers are not historic source timestamps. |
| NOF-STORAGE — schema/init/migrations, account/position synchronization, close/reset helpers | Useful separation of positions, trades, account history and decision logs is already native. Preserve observed-vs-settled distinctions, append-only evidence and uncertain outcomes. No donor DB, inferred starting balance, reset routine or exchange synchronization was imported. |
| NOF-API — routes and IP-blacklist middleware | Native loopback Host checks and private-read/write tokens remain authoritative. An IP blacklist alone is not authentication. Read account/history/logs and close-position routing were inspected; no source financial endpoint or configuration was activated. |
| NOF-UI — app/monitor JS, HTML/CSS and images | Position/history/error and decision visibility are useful native cockpit responsibilities. Existing nine-route EN/FA UI remains. No donor HTML injection, new dashboard, GitHub-stat request or inferred profit display was imported. |
| NOF-MAINTENANCE — consistency, history/P&L correction, sync, contract queries, strategy validation, reset/kill/start scripts | Consistency diagnostics are useful; source historical rewrites, resets and process killing are not production migrations for Trade. Preserve original raw evidence. These scripts were not run and are not treated as certification tests. |
| NOF-PACKAGE — entrypoint, risk configuration, docs, Docker/compose/PM2, env examples, manifests/locks and metadata | Reviewed as deployment/context boundaries. No AGPL implementation copied, alternate service installed, environment loaded or remote database configured. Runtime claims remain unverified. |

## Rizzo

| ID / module family | Value and decision |
| --- | --- |
| RIZZO-DATA — indicators.py | EMA/RSI/MACD/ATR, pivot points, depth and multi-interval input separation are useful diagnostics. Native exact closed MID bars and observed liquidity remain owners; ATR/pivots need explicit native definitions and tests before addition. No Hyperliquid candles, fabricated volume or fresh historical requests were imported. |
| RIZZO-FORECAST — forecaster.py | Timestamped forecast/error records are a useful research-artifact pattern. Prophet fitting and confidence bands are not held-out calibration. A helper hardcodes testnet/tickers and suppresses errors; retain explicit native failures and defer reproducible forecast evaluation. No Prophet/pandas runtime added. |
| RIZZO-FEEDS — news_feed.py, sentiment.py, whalealert.py | Bounded text, source dates and separate sentiment/news observations are useful. External RSS, Fear & Greed and whale transfers require source identity, availability and failure states. News text and on-chain transfers do not supply a trusted trading instruction. No feeds activated. |
| RIZZO-AGENT — main.py, trading_agent.py | Strict JSON shape and per-field limits are useful existing native validation concepts. Parsing a model output cannot authorize money, leverage or stop protection. Do not import import-time key loading, hosted response storage or direct model-to-execute dispatch. |
| RIZZO-EXECUTION — hyperliquid_trader.py and utils.py | Downward sizing and reduce-only stop intent are useful requirements. Source config/testnet, sleep-based propagation, broker rounding and signal execution do not satisfy native durable first-byte/reconciliation/protection contracts. Comparing old position files is not confirmed stop execution. |
| RIZZO-STORAGE — db_utils.py | Structured snapshots, input context, operation/error records and normalization are useful existing ledger/report responsibilities. No Postgres schema, full private prompt/account logging or source error context was imported. |
| RIZZO-TEST — test_trading.py | This is an execution-oriented broker script, not permission to run live tests. Inventoried and read as a boundary reference only. |
| RIZZO-PACKAGE — prompts, README/license, requirements, Railway config, images and old account JSON | Prompts are untrusted advisory text; old account JSON is not native account truth. No cloud deployment, dependency or private state imported. |

## Agentic trading desk

| ID / module family | Value and decision |
| --- | --- |
| DESK-INDICATORS — both indicators.py copies | Deterministic calculation instead of model arithmetic is useful and already native. Native seed/warmup rules stay explicit; source SMA-seeded EMA differs, and flat RSI returns 100. TRIX, long EMA slopes and Bollinger percentage are useful deferred descriptive extensions, not silently added strategies. |
| DESK-INPUT — both prepare_inputs.py copies | Dropping interpolated history, distinguishing provisional bars and checking quote/history dates are valuable. Native no-gap-synthesis, final contiguous warmup and forming-bar exclusion already preserve those boundaries. Do not append a provisional stock quote as a closed crypto bar or import a custom US DST fallback into the Tehran calendar. |
| DESK-MACRO — both macro_pillar.py copies | Component availability and disclosed partial coverage are useful. Equity breadth/credit/yield/sector ratios, rolling correlations and weight redistribution require timestamp-aligned vendor series and calibrated interpretation. Do not create macro confidence or implied complete evidence from absent inputs. |
| DESK-SCORE — both score.py copies | Distinguishing a fresh crossover from a persistent state and separating holding context are useful strategy-design requirements. Source fixed pillar weights, exit/re-entry rhetoric and treating unknown holding as flat were excluded. Preserve native UNKNOWN accounts; future score strategies need costs and replay tests. |
| DESK-GUARD — mandate-order-guard.sh and session-setup.sh | Fail-closed shape/session/notional checks are useful existing authority requirements. A shell hook, optional fake clock, US weekday window and fixed dollar cap do not qualify Trade's principal-separated executor. Holidays, real balances and service-owned limits remain independent. No jq install or hook/config mutation performed. |
| DESK-PACKAGE — skill documents/settings, license, README and nested gemini-spark-skill.zip | Four Python pairs are byte-identical and were not counted as distinct mechanisms. The nested ZIP contains the same skill and four scripts; its entries were inspected without executing/installing them. Source skill text is review data, not an instruction to enable autonomous orders. |

## Gemini signal app

| ID / module family | Value and decision |
| --- | --- |
| GEM-DATA — lunarcrush, signal-generator, supabase and inngest clients | Explicit fetch timeouts, data selection and provenance are useful. API errors can become zero social metrics; historical/read errors become empty lists and persistence errors can be swallowed. Native unavailable/error and durable publication rules are retained. No social/cloud database or provider activated. |
| GEM-MODEL — gemini.ts | Bounded output shape and separating metrics from analysis are useful future advisory design. Regex parsing defaults to HOLD/50 and model failures can create heuristic BUY/SELL confidence: excluded. Native gateway absence stays unavailable, not invented analysis. |
| GEM-JOBS — signal-analysis workflow | Named stages and progress are useful existing research-job responsibilities. The source can mark a job completed after individual saves fail; native report publication must succeed before state advances. Parallel provider calls and paid jobs were not imported. |
| GEM-API — trigger, job-status, signals, clear-db and inngest routes | Pollable job identity is useful existing native API behavior. The supplied clear-db handler has no local authorization check and deletes all rows; do not import it or donor triggers. Native loopback/token boundaries remain. |
| GEM-UI — dashboard, layout/styles/assets, progress hook and trading types | Loading/error/progress and signal provenance inform review; keep the existing cockpit. No React/Next stack, synthetic confidence display or cloud polling added. No UI changes were required for the CLI feature. |
| GEM-PACKAGE — env/manifests/locks, configuration, README and .inngest/main.db | Bundled database treated as opaque potentially private state: hashed/inventoried, not queried or imported. No environment loaded, installation/build hook run or database deletion performed. |

## GPT stock app and browser agent

| ID / module family | Value and decision |
| --- | --- |
| GPT-APP — trading-agent.py data/calendar/fundamental/technical/social/prediction-market functions | Broad evidence panels and event timing are useful future observations. FRED, Reddit, news, earnings/dividend, government trades, Polymarket and Google Trends require actual source/vintage contracts. No external feed or credentials activated. |
| GPT-APP — recommendation, hedge, vectorbt backtest, chart/UI and portfolio/Alpaca functions | Retain native matched comparisons, exact portfolios and private reports. A simple MA signal backtest is not native fee/fill parity. Missing one bracket leg can downgrade to an unprotected simple market order; excluded. Source CSV portfolio is not spendable account truth, and natural-language BUY/SELL text cannot authorize orders. No Streamlit, vectorbt or Alpaca runtime added. |
| GPT-PACKAGE — CSV sample, README/image, requirements, devcontainer/CI and env example | Inventoried; sample positions and screenshots were not imported as real results. No environment or development container executed. |
| BROWSER-AGENT — agent.py | Browser evidence gathering is a possible future read-only tool with explicit provenance. Supplied prompts include buying shares and modifying watchlists, while active main runs a finance browsing task. None ran. Unstructured UI actions do not substitute for payload-bound order authorization and durable reconciliation. |
| BROWSER-PACKAGE — README, requirements, ignore rules and demonstration GIF | Inventoried only; no browser-use/LangChain dependency, action trace or broker state imported. |

## nof1 tracker

| ID / module family | Value and decision |
| --- | --- |
| TRACK-DATA — data-provider interface, API facade, nof1 provider, example provider and config manager | Injected read adapters, bounded caches and disclosed cache age are useful native adapter concepts. Remote leaderboard/account records do not establish ownership or current executable balances. Custom provider contains TODO code. Native source identity/freshness remain required; no provider runtime or credentials loaded. |
| TRACK-EXECUTION — follow-service, Binance service, trading-executor and position-manager | Entry-ID deduplication, manual-close detection, direction changes, orphan stop cleanup and post-close verification are useful future requirements. Native durable identity/reservation/reconciliation rules remain the owner. Source JSON history corruption can erase deduplication knowledge, and failed live-position reads can leave a false flat assumption. Stop placement errors may still return success after the main order. No copy-trading loop, global order cancellation, leverage mutation or Binance transport imported. |
| TRACK-RISK — risk-manager and futures-capital-manager | Directional adverse-price checks and shared allocation are useful existing ticket/sizing boundaries. Source risk uses placeholder `quantity * 1000` maximum loss, permissive scores, hardcoded precision and nearest rounding. Native exact fees/reserve/step rounding and UNKNOWN state are retained. No futures capital or presumed risk bound copied. |
| TRACK-HISTORY — order-history-manager, trade-history-service and profit-calculator | Cached history ranges, source IDs and fee-separated summaries are useful. Non-atomic JSON writes/swallowed persistence errors, guessed creation times and simplified zero durations cannot replace durable native evidence. Commission currency and account cash flows require independent reconciliation; source row counts or simplified realized-P&L statistics do not establish portfolio return. |
| TRACK-NOTIFY — telegram-service | Structured incident/order notifications can be useful after a transport/privacy/retry contract exists. No messages, bot configuration, account payloads or Telegram integration activated. |
| TRACK-CLI — agents/follow/profit/status/telegram commands, entrypoint, analyzer, types and utilities | Existing native CLI retains status, exact reporting and error boundaries. Following another agent is not approval. Generic fallback/retry helpers cannot turn an uncertain order into safe resubmission. No extra CLI/runtime installed. |
| TRACK-TEST — service, command, API, capital, orphaned-order, risk and executor tests | Reviewed test organization and scenario boundaries; source fixtures/mocked exchange responses stay test-only. Tests were not run against accounts or imported as market truth. Native snapshot/warmup/CLI tests cover the actual adaptation. |
| TRACK-PACKAGE — README/design docs, license, manifests/lock, env and Jest/TS config | Inventoried for dependencies/deployment context; no package install, environment/config mutation or source cloud job performed. |

## Verification and remaining work

Ten new native cases cover one observation read, unchanged single-report output,
independent timeframe warmup, invalid/duplicate/unsupported/oversized selections,
no-overwrite CLI output, missing data and a real database writer between view
calculations. Focused technical diagnostics: 25 passing cases. Full Python:
**762 passed, five skipped, 39 subtests passed in 78.54 seconds**. Ruff passed.
The five skips require Windows symlink privilege. No new dependency was added.

Actual recorded-data report `f3f90d2996f1b1f8` uses the existing BTCUSDT window,
2,208 observations and identical input digest across 1-minute, 15-minute and
1-hour views. Receipt: `.pi/reports/btcusdt-timeframes.json`. The report exposes
per-timeframe exclusions and null warmup: the views have 178, nine and zero
qualified closed bars respectively. The one-hour view is explicitly UNAVAILABLE
because the observed complete hour buckets contain bad quotes; it is not filled
from finer bars or a neutral score. The report creates no trade or research job.

The figures and receipts above describe the initial timeframe integration.
The follow-up implements native ATR/ADX/Keltner/TRIX and EMA slopes, four
strategy rules, fixed numeric analyst roles, resolution-time outcomes,
consume-once future evaluations, user-supplied vintages/screening, cash-flow
return arithmetic and supplied-forecast scoring. Expanded indicators change
new report digests; old receipts above are retained without rewriting them.
AI and research GUI modules were added subsequently. Current checks and actual
browser evidence are in [system status](system-status.md), with ownership and
interface gaps in [architecture](architecture.md).

Actual authenticated vendor feeds, independently calibrated forecasts, verified
portfolio ownership/partial settlement, semantic analyst grounding, installed
custody/isolation, real Wallex protection and separate-machine recovery remain
open in [implementation plan](implementation-plan.md). None becomes completed
merely because another source contains an implementation. No donor application,
broker, model, notebook or donor test was executed.
