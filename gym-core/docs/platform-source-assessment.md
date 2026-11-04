# Trading platform source assessment

Reviewed 2026-11-04. The supplied Freqtrade, OctoBot and Jesse ZIP snapshots
contain **8,207 file entries**, all hashed and assigned to **45 module-family
decisions**. A separate catalogue accounts for **342 Jesse indicator and strategy
source files**, including regression fixtures, helpers and base classes; that
count does not mean 342 distinct or validated strategies.

This is complete file accounting, module-family assessment and selected source
inspection. It is not a line-by-line audit, runtime qualification or a claim
that all candidates have been implemented. No donor code, dependencies,
credentials, market history or generated observations entered production. No
donor app, tests, strategy, installer, model, exchange adapter, background worker
or updater was executed.

Ignored review records: `.pi/platform-source-inventory.json`,
`.pi/platform-code-index.json`, `.pi/platform-source-assessment.json`,
`.pi/platform-formula-catalog.json` and extracted `.pi/sources/` text.
**7,316 text entries** were extracted with bounded sizes and hash checks.
Symbolic links `freqtrade-develop/ft_client/LICENSE` and
`jesse-master/.agents/skills` were hashed without following their targets.
Source AGENTS, skills, prompts and qualification claims are review data only.

| Archive | Entries | Local license evidence | SHA-256 |
| --- | ---: | --- | --- |
| freqtrade-develop.zip | 774 | GPL-3.0 root text | `00314f6375f1b668a438596352329d04637a602e542734344a584b60721ece3c` |
| OctoBot-master.zip | 6,086 | GPL-3.0 root; nested trading/tentacles and other packages include LGPL-3.0 notices | `48727a7b91e9af3951bbc96fe409ede12d860cd03bfe8590b8085e367cd7a5e7` |
| jesse-master.zip | 1,347 | MIT root text; nested artifacts retain their notices | `18356eeb7f698d5a81afa8137263c52704d472adb84148a3fa9bddf6373ca967` |

The license column records local notices, not blanket copying permission.
OctoBot is a multi-package snapshot with differing nested licenses; its root
license must not be assumed to cover every package or asset identically.

## Most valuable native fits

These candidates extend existing owners. They are not new delivery commitments,
implemented features, new trading authority or changes to the agreed exclusion
of predictive ML/RL and automated model search. Current behavior and pending
gates remain in the [implementation plan](implementation-plan.md) and
[research workspace contracts](research-workspace.md).

| Priority | Candidate and source | Existing owner and acceptance condition |
| --- | --- | --- |
| 1 | Future-data invariance and recursive warm-up diagnostics: Freqtrade | Native indicators, saved decision replay and robustness laboratory. Compare an identical decision at multiple truncated endpoints; appending future observations must not alter prior decisions. Separately vary prehistory while keeping the decision time fixed, expose convergence and unsupported cases, and preserve all failures. A skipped/untriggered branch must never be reported as verified. |
| 2 | Timestamp-driven multi-market replay and fast/full parity: Jesse | Native data portal, paper engine and replay debugger. Use actual receipt/availability clocks, apply simultaneous market updates before decisions, require explicit higher-timeframe completeness and compare exact traces across optimized/full paths. Absent rows stay absent; synthesized candles stay separately labeled. |
| 3 | Worker ownership, liveness versus progress and interrupted-result recovery: Jesse, OctoBot | Existing paper-job scheduler, experiment registry and service lifecycle. A heartbeat is not evidence of progress; old claims cannot write after a new owner takes over. Every timeout/cancel/restart has a durable status, retained partial evidence, bounded logs and explicit retry eligibility. Process termination is not order cancellation. |
| 4 | Pending-cancel/partial-fill and portfolio synchronization: OctoBot, Freqtrade | Protected executor ledger and account observation services. Preserve unresolved status until evidence arrives; account for partial fill plus cancellation races and fees exactly once. Computed fees and forced local terminal states must remain distinguishable from authenticated venue receipts. |
| 5 | Persisted pair/global entry locks and explainable eligibility: Freqtrade | Native rules, exit guards and recorded market screening. Pair/global cooldown and drawdown conditions need explicit trigger evidence, scope, expiry/restart semantics and operator visibility. New-entry restrictions must preserve permitted cancellation and risk reduction. Current top-market lists are not historical universe evidence. |
| 6 | Bounded result pages, snapshots and degradation details: Jesse, OctoBot Flow | Shared research actions/API and GUI. Bound bytes as well as rows, keep failed/running/partial results visible, use immutable snapshot references and separate current/previous execution/error details. Redacted output is still not permission to send it externally. |
| 7 | Optional rule-level uncertainty diagnostic: Jesse | Existing experiment registry and robustness reports. A seeded block bootstrap on saved rule returns can complement chronological tests if sampling assumptions, dependence, all attempted trials and multiple-testing limits are exposed. Signal significance is not after-cost profitability, calibrated trade confidence or automatic promotion. No bootstrap module was implemented here. |
| 8 | Evidence-linked analyst roles: OctoBot agents | Existing model gateway and bounded research notes already own provider access, role notes and explicit sending. Optional input aggregation/critic views may be useful, but need run/evidence-version identity, timeout and missing-input states. No second agent runtime, autonomous trading team or model training. |

## Selected implementation findings

Paths below are relative to their supplied archive roots under ignored
`.pi/sources/<archive-name>/`. Every entry's hash is retained for review.

### Freqtrade

`freqtrade/optimize/analysis/lookahead.py` compares full and truncated indicator
frames and checks selected entry/exit signals. `recursive.py` compares indicators
using different startup histories. These are distinct failure modes: future-data
dependence versus sensitivity to the amount of past data. The included
`tests/optimize/test_lookahead_analysis.py` provides intentionally biased fixtures.
None was executed. In the inspected recursive calculation, zero comparison
values fall through to a NaN difference rather than a relative percentage;
native diagnostics should distinguish zero baseline from missing evidence.

`docs/lookahead-analysis.md` explicitly limits conclusions to triggered, checked
signals. Single-pair verification may differ from a cross-market ranking
strategy, and market-order overrides can bypass custom-price behavior. Native
tests must preserve the original universe and strategy context or report that
comparison as unsupported. These checks do not establish a universal absence of
lookahead. The analysis preparation also has a FreqAI model-directory deletion
branch; no source cleanup, retraining or analysis command was run.

`freqtrade/strategy/strategy_helper.py` shifts slower informative candles to the
point where their close can be known, handles monthly boundaries separately and
rejects merging a faster timeframe through this helper. It is a useful alignment
reference, but native receipt availability and delayed observations remain
additional conditions beyond bar close.

`freqtrade/data/converter/converter.py` defaults to filling missing periods with
previous-close OHLC and zero volume. That can support a dense calculation grid,
but is synthetic data and must not become observed coverage, liquidity or
fill evidence. `docs/backtesting.md` records stop/ROI/intrabar priority
assumptions; smaller detail candles reduce ambiguity without revealing actual
tick ordering or order queue priority.

`freqtrade/exchange/exchange.py` has a dry market-fill calculation that walks
displayed orderbook levels, extrapolates remaining size at the last inspected
level and caps the modeled price with a worst-rate assumption. It returns the
requested modeled fill, not a measured partial fill or proof of available depth.
The native paper engine must not fill unseen size by extrapolation. Dry order
identifiers and wallet records remain clearly simulated.

Pairlist filters include spread/precision/age/liquidity/volatility checks and
missing-ticker exclusions (`plugins/pairlist/SpreadFilter.py`). Protections under
`plugins/protections/` include global/pair stoploss locks, cooldown and drawdown.
Their useful fit is explicit reason/scope/expiry, not replacing protected stop
authority with an ordinary Python plugin. Wallets, persistence, exchange
adapters, RPC/API authentication, commands, logging, plotting, templates,
FreqAI/RL, hyperopt, user data and deployment support all have dispositions.

### OctoBot

The archive includes **16 functional package directories** in addition to the host
application: trading, tentacles, commons, async_channel, backtesting, evaluators,
agents, flow, protocol, client, services, sync, copy, node, binary and
tentacles_manager, plus package-root support. Each functional package has its
own disposition below.

`packages/trading/octobot_trading/personal_data/orders/states/fill_order_state.py`
distinguishes FILLING from FILLED, permits cancellation-related transitions and
uses portfolio locking while updating balances. If venue fees are unavailable,
it can compute fees locally. `cancel_order_state.py` distinguishes CANCELING
from CANCELED and permits an intervening fill. Both have forced-final-state
paths. Those distinctions are valuable adversarial cases; native custody must
not treat local forcing or computed fees as authenticated finality. Associated
order groups require separate ownership and partial-fill accounting contracts.

`octobot/task_manager.py` coordinates a loop/thread, stop coroutines, child-process
shutdown and timeouts, including forced exit behavior. The commons
`managed_child_process_registry.py` tracks managed PIDs and can rebind a bootstrap
PID to the authoritative application PID. Graceful-stop bookkeeping is useful,
but an in-process PID registry alone does not establish parent-crash containment,
PID-reuse safety or a service security boundary.

`packages/flow/octobot_flow/entities/automations/execution_details.py` separates
current/previous trigger information, completion and degraded/error state. That
maps well to explicit job recovery and GUI evidence. `octobot/automation/` has
trigger/condition/action composition; adoption should use native fixed actions
rather than introducing a dynamic trading automation engine.

`octobot/backtesting/minimal_data_importer.py` derives its reported interval from
a sample market selected by dataset length and adds a timeframe offset to the
endpoints. A longest series does not establish coverage for every market or
timeframe. Native coverage must remain per market, per interval and tied to
receipts/readiness.

The agent consumer in
`packages/agents/octobot_agents/agent/channels/ai_agent.py` aggregates a dictionary
by source name and considers itself ready when the expected input count is met;
its queue-size default is unlimited. Run/version identity and bounded retention
must be explicit before borrowing aggregation mechanics. Managers, critics,
judges and memory are interpretation infrastructure, not numerical verification
or trading permission. No provider call, source agent or persistent memory was
activated.

Protocol Python/TS/OpenAPI models, client controls, add-on evaluators and trading
modes, DSL, provider/service feeds, backtesting collectors, synchronization,
copy-trading, node orchestration, binary/updater and add-on installer code are
accounted for. Generated clients, interfaces and samples are not tested native
capabilities. No third-party resource was changed.

### Jesse

This snapshot contains observed-timestamp replay, research-session fencing,
statistical diagnostics and MCP tools in addition to indicators/strategies.
`jesse/research/backtest.py` validates observed source rows before mutating the
runtime; dense-only paths retain explicit contiguous-minute checks.
`services/candle_service.py` and `store/state_candles.py` separate source candles,
generation and warm-up. In `modes/backtest_mode.py`, gaps or unequal instrument
timelines select timestamp replay. The inspected timestamp loop applies an event,
then executes updated routes in stable order before updating simulated orders.
Batching is constrained by active orders/positions and route events. Fast and
full paths are a useful parity target; `tests/test_simulator_parity.py` uses a
seeded synthetic fixture to compare the candles strategies actually see.
Neither that fixture nor its expected outcome became native market evidence.

`services/session_liveness.py` separates lease renewal from progress, uses claim
IDs to fence runner writes, and estimates database time with a cached offset.
The selected clock path falls back to local time/last offset when database time
cannot be read; the clock is not independently authenticated. The fence is
conditional on a claim ID, so native ownership tests must cover every mutation
and legacy/unclaimed paths. Heartbeats and exit status do not prove a trading
action failed or was cancelled at the venue.

`services/session_results.py` bounds row counts, page bytes, text and log scans,
and preserves running/stopped/partial status notes. Snapshot identity and bounded
pagination are useful references for the native replay/experiment interfaces.
`services/research_jobs.py` bounds concurrency, deadlines, log size and retention,
and uses process groups/Windows Job Objects through `process_tree.py`. Its own
contract explicitly says generated/research code runs with the same user's
filesystem, environment and network privileges; path validation is not a
sandbox. It also records a POSIX crash/orphan limitation. No arbitrary-code job
or MCP trading/filesystem tool was added to Trade or executed.

`research/rule_significance_testing/rule_significance.py` collects signals without
submitting orders, aligns next-bar detrended returns, retains neutral bars and
computes an observed mean. `bootstrap.py` resamples contiguous random-length
blocks from centered rule returns using a seeded generator independent of batch
count. The reported empirical tail fraction is a diagnostic under those sampling
assumptions. It does not include measured fill/fee/turnover evidence, correct for
all searched rules or establish prospective profitability. Keep all attempts
and untouched chronological evaluation; synthetic pipelines remain separate from
observations. Predictive ML and optimization expansion remain excluded.

`services/simulation_assumptions.py` rejects contradictory spot/futures aliases
and validates 252/365 annualization inputs. Clear assumptions are worth retaining;
derivatives support is not implied. The sandbox exchange creates modeled order
objects with generated IDs/current supplied prices, not venue acknowledgements.
Indicator files, strategy lifecycle and regression fixtures, order/position
models, repositories, vendor import drivers, UI bundles, controllers, services,
MCP tools, reports, cache and test helpers are all assigned dispositions.

## Complete file-family dispositions

Each of the 8,207 unique source/path pairs has one assignment in the review JSON.
Support groups cover assets, fixtures, docs, configuration, packaging and CI;
they do not imply every line was manually inspected. The selected reads above
identify the actual depth and limits.

| Source | Family | Entries | Decision and native fit |
| --- | --- | ---: | --- |
| freqtrade-develop | FT-BIAS | 6 | Truncated-history/lookahead and recursive warm-up comparisons. Strong candidate robustness diagnostics; sampled trade checks are not proof of no future leakage and source cleanup paths are not executed. |
| freqtrade-develop | FT-OPTIMIZATION | 78 | Backtest timing/cost/statistics/reporting retained as references; hyperopt, FreqAI and reinforcement-learning search/training remain outside current delivery. |
| freqtrade-develop | FT-STRATEGY | 17 | Closed informative-timeframe alignment, guarded callbacks, interfaces and dynamic loaders. Reference native closed-bar context; no arbitrary Python strategy loading or plugin authority. |
| freqtrade-develop | FT-FILTERS | 22 | Spread/precision/liquidity/age/volatility/eligibility filters and exclusions. Native market screening owns comparable as-of inputs; remote lists/current rankings are not historical universes. |
| freqtrade-develop | FT-PROTECTION | 9 | Pair/global cooldown, stoploss/drawdown guards and lock manager. Candidate auditable entry gates; cancellation and exits must remain available, locks need persistence and explicit expiry. |
| freqtrade-develop | FT-MONEY | 47 | Exchange normalization, trade/order state, wallets/fees, dry fills and leverage. Reference reconciliation and reserve cases; no CCXT replacement, leverage or liquidity extrapolation adopted. |
| freqtrade-develop | FT-DATA | 21 | History/provider/converter formats and caches. Missing-candle resampling creates carried-price zero-volume rows; native observations remain distinct from synthesis. |
| freqtrade-develop | FT-HOST | 78 | Authenticated RPC/WS, CLI/client, schemas and config migration. Reference GUI/API/CLI parity and fixed schemas; no donor auth/credential or bot control imported. |
| freqtrade-develop | FT-CORE | 89 | Worker scheduling, enums/types, logging/plotting, utility/vendor indicators and templates. Candidate progress/error/retention contracts; no framework migration. |
| freqtrade-develop | FT-TESTS | 205 | Unit/integration fixtures including analysis, protections, exchange, strategy and data behavior. Selected static reads only; no donor tests or fixture market history used. |
| freqtrade-develop | FT-SUPPORT | 202 | Docs/assets, sample user data/config, build/deploy/CI and root license accounted for. Symbolic link hashed without following; no scripts or services started. |
| OctoBot-master | OB-ORDERS | 155 | Explicit pending/filling/canceling/closed states, order groups, portfolio locks and balances. Strong reconciliation test cases; forced final states and computed fees must not become authenticated execution evidence. |
| OctoBot-master | OB-TRADING | 491 | Exchange/accounts/market data, modes/signals/DSL, supervisors, storage and tests. Reference native precision/readiness/lifecycle; no venue, derivatives, wallet signing or general DSL expansion. |
| OctoBot-master | OB-TENTACLE-MARKETS | 636 | Exchange/blockchain adapters, deterministic TA/realtime/strategy evaluators and trading modes. Catalogue references only; social/current signals are not historical truth or qualified strategies. |
| OctoBot-master | OB-TENTACLE-OTHER | 1,272 | Agent/automation/services/backtesting add-ons, profiles, metadata and scripts. Candidate explicit action/result shapes; no dynamic add-on install or autonomous money tools. |
| OctoBot-master | OB-COMMONS | 285 | Managed child registry, clocks, serialization, logging/redaction, profiles, data and tests. Candidate graceful-stop and restart cases; PID registry is not isolation or crash-proof process ownership. |
| OctoBot-master | OB-CHANNELS | 38 | Producer/consumer filters, queues, priorities and lifecycle. Candidate bounded backpressure and event ownership cases; unlimited queues and event loss need explicit policy. |
| OctoBot-master | OB-BACKTEST | 77 | Collectors/importers, time-controlled replay, data formats and fixtures. Native receipt coverage and quote-side simulation remain authoritative; source datasets are not imported. |
| OctoBot-master | OB-EVALUATORS | 65 | Evaluation matrices, evaluator lifecycle and tests. Separate unavailable, numeric evidence and interpretation; no composite-score promotion. |
| OctoBot-master | OB-AGENTS | 48 | Manager/critic/judge teams, bounded-token provider calls and memory. Reference native evidence-linked roles and disagreement; no second agent runtime, persistent external memory or paid calls. |
| OctoBot-master | OB-FLOW | 212 | Trigger/condition/action flow nodes, execution details and tests. Candidate fixed-action audit/progress schema; no arbitrary automation engine introduced. |
| OctoBot-master | OB-PROTOCOL | 622 | OpenAPI/Python/TS protocol models and tests. Reuse native fixed contracts; generated clients are not independent validation or authority. |
| OctoBot-master | OB-CLIENT | 135 | Web/operator controls and client state. Reference real readiness/status and control parity; no frontend stack replacement. |
| OctoBot-master | OB-SERVICES | 74 | Interfaces, provider feeds/notifications and service wrappers. Reference availability and redaction; no external sends, secrets or vendor connections. |
| OctoBot-master | OB-SYNC | 95 | Synchronization/publication transport and tests. Candidate revision/ownership evidence; cloud/shared-state replication is not local ledger integrity or independent custody. |
| OctoBot-master | OB-COPY | 58 | Copy-trading configuration and consumer/provider lifecycle. Excluded execution expansion; source/owner separation remains a useful boundary case. |
| OctoBot-master | OB-NODE | 238 | Node/worker orchestration and transport ownership. Reference bounded recovery; no remote worker dispatch or network infrastructure. |
| OctoBot-master | OB-BINARY | 13 | Binary packaging/bootstrap/distribution. Inventory only; no downloaded/updater binary launched. |
| OctoBot-master | OB-MANAGER | 141 | Add-on discovery/install/update/configuration and tests. Inventory/reference only; not a new plugin installer or credential authority. |
| OctoBot-master | OB-APP | 155 | Main lifecycle/task manager, automation, backtest importer, producers, storage, optimizer, API and community/updater surfaces. Reference explicit stop and data bounds; optimization/community monetization/updates excluded. |
| OctoBot-master | OB-TESTS | 175 | Host/lifecycle/backtesting tests and source qualification records. Inventoried/selected static reads only, not executed evidence. |
| OctoBot-master | OB-SUPPORT | 1,101 | Docs, build/Rust/Node/Pants metadata, tooling, images, CI, source instructions and remaining support. No package installs, agents, deployment or source tools executed. |
| jesse-master | JE-REPLAY | 3 | Observed-timestamp replay, same-time boundaries, higher-timeframe closure and missing-data/warm-up checks. Strong native replay/coverage acceptance cases; no replacement candle engine or Rust dependency. |
| jesse-master | JE-SESSIONS | 6 | Claim fencing, liveness versus progress, bounded result/log pages and process-tree deadlines. Candidate recovery contracts; arbitrary generated-code jobs are not a sandbox or native action. |
| jesse-master | JE-RESEARCH | 21 | Signal-only block-bootstrap significance, Monte Carlo, backtest wrappers and synthetic perturbations. Static diagnostics candidates only; predictive ML/search excluded and synthetic series cannot become observed data. |
| jesse-master | JE-MODES | 86 | Backtest/import/optimization/Monte Carlo/significance/live runner coordination and vendor drivers. Reference mode lifecycle; no exchange account, optimizer or live runtime activated. |
| jesse-master | JE-MONEY | 47 | Spot/futures models, order/fill/fee/accounting and persistence. Reference cash/reservation/partial-fill tests; sandbox order objects are not venue receipts or authenticated balances. |
| jesse-master | JE-INDICATORS | 176 | Individual indicator source catalogue. Formula names are not equivalence; require native seed/warm-up/gap/precision contracts before adding any consumer. |
| jesse-master | JE-STRATEGIES | 167 | Strategy lifecycle/rules/position sizing plus explicitly named regression/test strategies. Catalogue as source fixtures, not real profit evidence or new live strategies. |
| jesse-master | JE-MCP | 70 | Tool/resource schemas, session inspection, filesystem/research and live controls. Useful bounded result shapes; loopback/tool exposure does not grant native money or arbitrary-code authority. |
| jesse-master | JE-HOST | 107 | HTTP auth/controllers, session runtime/config/cache/scheduling/reporting/logging and state. Native GUI/CLI fixed dispatch remains owner; no second process-wide state runtime. |
| jesse-master | JE-DISTRIBUTION | 519 | Bundled/generated UI assets, numerical helpers and vendor/native boundaries. Assets inventoried; generated UI and compiled components were not runtime tested. |
| jesse-master | JE-CORE | 13 | Factories/testing utilities, config/helpers/enums/exceptions and root package support. Test doubles remain review references; no fallback or fake market data imported. |
| jesse-master | JE-TESTS | 102 | Session isolation/liveness, sparse replay, mode contracts, simulator parity, significance and order tests. Selected implementation/fixture reads only; no donor suite execution. |
| jesse-master | JE-SUPPORT | 30 | Docs/assets, root license, setup/CI, source instruction symlink and SQL/helper scripts accounted for; not executed or followed. |

## Verification and archive state

Implementation follow-up, 2026-11-05: native `strategy-audit` now checks selected
decision prefixes and recursive prehistory; `return-bootstrap` provides a seeded
saved-return diagnostic with explicit gap resets and uncorrected-selection
limits. Scheduled paper attempts now have durable claim fencing and explicit
interruption through CLI/API/GUI. These implement parts of priorities 1, 3 and 7;
they do not close timestamp parity, hard deadlines, actual venue reconciliation,
persisted entry locks or independent evaluation. See the current
[implementation plan](implementation-plan.md) and [contracts](research-workspace.md).
The original review-only verification below remains a historical receipt.

Assertions verify all archive/member counts, unique assignments, nonempty groups,
catalogue membership and extracted-text SHA-256 values. Static Python parsing
passed for **4,627 files**; six were rejected by the local Python 3.11 parser.
Those syntax limits are recorded in the code index and are not runtime defect
claims or dependency qualification. No donor test suite or native production
test suite was run for this documentation-only review.

All three ZIPs were moved to `C:\Users\ACER\Downloads\archive` after matching
their review hashes, and their destination hashes were verified. The receipt is
`.pi/platform-archive-receipt.json`. A whole-record audit verified **85 documented
reviewed ZIPs**, all with matching hashes and none of those ZIPs left loose in
Downloads. Extracted folders and archives outside Downloads were preserved.
`.pi/archive-verification.json` records the audit.

Only review documentation and ignored inspection records were added. No
production behavior, dependency, credential, live order or funded setting changed.
