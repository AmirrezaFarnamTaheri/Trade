# TradingGYM — Fresh Technical, Financial, Research, Security & Product Assessment

**Assessment date:** 21 November 2026 · **Repository:** [AmirrezaFarnamTaheri/Trade](https://github.com/AmirrezaFarnamTaheri/Trade) · **Pinned base:** [master at `8fba0b15115b617067fc93b9c9769c9351472900`](https://github.com/AmirrezaFarnamTaheri/Trade/tree/8fba0b15115b617067fc93b9c9769c9351472900), committed 20 November 2026 23:05:41 UTC. · **Output:** a new baseline report and prospective roadmap, **not** a replay of prior uncorrected findings.

**Companion:** [Current active implementation tasks, priorities and acceptance criteria](https://chatgpt.com/space/page_6c78d41849308191b57ca89bf08e1c82). Historical reference only: [prior full technical audit](https://chatgpt.com/space/page_6124107f988c8191a950ebfa2337e1c3) and [earlier 419-item inventory](https://chatgpt.com/space/page_68dc041f92048191a46e39d4ea104742). The present report is self-contained, and the new task menu excludes work verified as implemented in the current source.

## Executive summary

**TradingGYM is an unusually capable, but still research-only, single-venue market observatory.** It records Wallex spot quotes/trades/depth/rules, runs versioned paper strategies and shared-cash portfolios, offers native EN/FA inspection workflows, and has separate Windows/Rust custody infrastructure. The critical distinction is unchanged: **there is no established independently validated net trading edge, and the funded execution path is in source but not installed, qualified or armed**. A successful build, deterministic paper simulation or attractive historical asset return does not change either fact. [S1](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/README.md#L5-L16) · [S2](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/capabilities.md#L7-L40).

**The prior review defects have materially changed.** Six related pull requests, numbered 102–107, were incorporated and closed on 20 November 2026, leaving **zero open PRs** at the assessment snapshot. The final master source now: reconciles the complete returned REST trade overlap rather than truncating at the previous high-water event; withholds unconsumed holdout diagnostics in the long-history script; records incremental evidence-bound observed-volume OBV as an option; implements versioned exact-inventory paper policies and a more careful exit eligibility check; requires matching modern booked quote postings in standalone and shared-cash reporting; distinguishes backup segment inventory from actual decrypt scope, supports selecting retained snapshots, and pins manifest digests. Those fixes should **not** remain on the active backlog as though they were absent. [S3](https://github.com/AmirrezaFarnamTaheri/Trade/pull/107) · [S4](https://github.com/AmirrezaFarnamTaheri/Trade/compare/a0fea74c21344f70e784c19cec88b30baf0575b0...8fba0b15115b617067fc93b9c9769c9351472900).

**The decisive next work is not another unbounded strategy search.** It is to preserve/measure forward evidence, design an independent final-evaluation custodian, calibrate historical venue/economic reality, strengthen research inference against dependence and multiple selection, verify current recovery behavior under actual off-host constraints, and make existing results understandable through a coherent product journey. The source's own research-budget rule allows at most two concurrent registered trials and requires new information rather than another price-history sweep. [S5](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/roadmap.md#L6-L22).

**Two operational choices are explicit, not engineering oversights.** The project sets a funded-path checkpoint for **8 February 2027**, and the owner canceled automatic off-machine backup scheduling and second-machine restoration on **16 November 2026**, accepting a loss-of-data risk. The new roadmap respects that decision as an accepted exposure rather than silently calling recovery qualification complete or assuming consent to enable cloud backup. [S6](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/PRODUCT.md#L41-L54) · [S5](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/roadmap.md#L29-L49).

## 1. Evidence cutoff, method and status vocabulary

This is a **source and documentation audit** of the exact pinned GitHub tree, recent integrated changes, project-owned trial log, capability map, roadmap and CI metadata. It is **not** a direct inspection of the user's installed Windows service, authenticated Wallex account, on-device data root, external storage destination or live prospective journals. A local repository checkout could not be cloned in this execution environment because the shell's network DNS access was unavailable; therefore I did not run a fresh local test suite or inspect private runtime receipts. GitHub source, commit metadata and CI data were obtained through the connected repository integration.

**Terms used below:**

- **Implemented in source:** observable in the pinned master code; a specific targeted regression may also exist.

- **CI-qualified:** tested by the applicable GitHub runner on the indicated commit, with explicit skipped steps. Hosted CI is not evidence of installed-service privilege, venue authentication or independent research custody.

- **Research observed:** authentic recorded public market data; does not entail complete depth/history or authenticated fills.

- **Paper modeled:** simulator outputs with specified assumptions; not actual venue execution or reliable liquidation ability.

- **Registered / historical evaluated:** hypothesis and pass mark were defined, and historical validation/holdout was run under the disclosed local method. Locally stored flags and reproducible scripts are not independent custody.

- **Independent outcome:** independently withheld and released future information, with frozen model/data/time/fee/selection family identity and verifiable look history. The project has not established this standard for its current performance claims.

- **HOST:** installed-host authority, cryptographic trust, ACL, STOP/send race and real venue acceptance that only an authorized operating-system/venue reviewer can sign off.

- **Proposed / conditional:** recommendation requiring measurement, approval or a distinct preregistered trial; not a proven defect.

**Latest verified CI:** Master [Validate run 44834196697](https://github.com/AmirrezaFarnamTaheri/Trade/actions/runs/44834196697) **completed successfully** on the exact audited commit. Its Python, Rust Ubuntu/Windows, Rust kernel, secrets/dependency, SBOM, critical mutation, Windows Edge smoke, disposable Windows SCM/ACL and synthetic cross-platform encrypted-ledger jobs all succeeded. The extended weekly mutation assessment was **skipped**. This is a real hosted-CI result, but **not** a qualification of the installed Windows service, real Wallex account, authenticated order lifecycle, independent research custody or off-host recovery.

## 2. Current product boundary — what actually works, and how much it proves

| Area | Verified current source/product | Qualification limit and current next action |
| - | - | - |
| Public spot market | Wallex catalogue-wide observation, quote/depth/trade/candle capture, raw segments, SQLite publication and quality flags | Gaps, stale prices, incomplete historical precision/fee vintages and unknown trade IDs still limit economically qualified replay |
| Strategies | 17 native long/flat strategies plus signed-signal blends, regime gates, ATR/profit/time exits, optional received-trade fixed stop-market | Paper outcomes only; stop-limit/trailing policy and authentic stop execution remain incomplete |
| Portfolio | Single shared exact cash book, 2–500 distinct-base same-quote markets, conditional rebalance, volatility/risk-parity and cash/loss constraints | Old/new model identities differ; same-time allocation fairness, liquidation depth and tail estimator reliability require evidence |
| Paper inventory/accounting | Versioned `inventory/1` and `inventory/2` options, booked quote posting validation, fee-currency-aware lot ledger and portable summary v3 | Legacy behavior remains the default; paper-eligibility check is not a venue fill guarantee; old artifacts require explicit compatibility testing |
| Statistical research | Deflated/Probabilistic Sharpe, descriptive stationary-block return bootstrap, bounded SPA-style matched candidate test, temporal validation and local holdout look accounting | The SPA implementation is honestly labeled “SPA-style”; full Hansen SPA, genuine CPCV/PBO, anytime e-process and independent test custody require distinct qualification |
| Prospective research | Daily BTC allocation, Wallex token passive mix and breadth journal in current source/roadmap, plus registered Binance funding follow-up | Future days and actual schedule receipts are not verified from repository files alone |
| Margin, FX, tokens | Public margin/credit previews and paper LONG/SHORT, conversion-route preview, reference-data token models and Wallex token journaling | Actual credit terms/changes and depth, token premium, corporate actions and authenticated margin settlement need separate modeling |
| Rust protected path | Separate Windows authority and custody, review/approval/receipt concepts, source one-shot LIMIT send, STOP and local fault tests | Installed path predates current source; no qualified arming, cancel/protective exit transport or funded evidence |
| Recovery | AES-GCM encrypted snapshots, manifest authentication and optional trusted digest, closed raw segment cutoff, retained snapshot selection and labeled drill scope | An inventory-complete sampled drill is not full decrypt/cross-host recovery; owner-accepted off-device gap remains |
| Product UX | Loopback aiohttp single-page EN/FA research workspace, paper/portfolio workbench, saved result/replay, market and safety pages | Valuable workflows remain expert-heavy, with no single universally understood evidence-first route; retain current API/authority boundaries |
| Operations | CI, environment checks, diagnostics, historical campaign receipts, dry-run preview and Windows scripts | Last installed-host state, latest exact data coverage, backup destination and formal scientific power cannot be established from Git alone |

**Primary references:** [S2 capabilities](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/capabilities.md) · [S7 architecture](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/architecture.md) · [S8 research-workspace contract](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/research-workspace.md).

## 3. What has genuinely changed since the earlier audit

| Prior concern | Verified on current master | Closure treatment |
| - | - | - |
| Reconnect deletes distinct equal-timestamp or older late REST prints | `collector._seed_trades` counts exact event/price/quantity/side multiplicity across the **whole returned interval**, without the former previous-high-water cutoff | **Source fix implemented** for returned overlap. No venue IDs means indistinguishable duplicates vs distinct same-field fills remain an unresolvable source limitation; operational gap monitoring stays open |
| Historical long-study script leaks test-window statistics when validation fails | Explicit return before ridge and walk-forward diagnostics when no holdout custody, plus finite end scoping and new outcome-perturbation tests | **Source fix implemented for that script**. This is not independent custody across every research/read path |
| Recomputing OBV history and uncertain zero/missing volumes | Stateful incremental `OnBalanceVolume`, optional observed-trade-volume rule with missing/zero abstention, decision/evidence digests | **Source fix implemented** for that signal path; collection gaps and underlying venue completeness are separate |
| Standalone paper small holdings treated as flat by equity threshold | Explicit opt-in `inventory/1` or `inventory/2` treats any positive owned base as held; recorded position evidence includes dust and working order | **Source fix implemented opt-in**, not retroactive. Owner must decide default for new research once equivalence is proved |
| “Sellable” overstated by quantity-only tests | New `inventory/2` has explicit `exit_check` for rules, known quote freshness, market-order eligibility, capacity and warnings; user-facing language now refers to recorded minimum checks | **Scope refined**; retain distinction between paper eligibility and authenticated exit execution |
| Rounded fill prices alter FIFO realized cost | `booked_notionals` requires exactly one signed quote gross posting per modern fill; shared portfolio path passes postings; derived summary now `paper-summary/3` | **Source fix implemented** with explicit legacy fallback and model marker; continue financial property/differential tests |
| Backup restores import later-closed segments, conflate manifests and decrypt proofs | Snapshot copy determines closed/open segment set; manifests and contents authenticated; selector `--snapshot`, independent digest pin, `segment_coverage` vs `segment_integrity` distinguish scope | **Source fix implemented**; it does not cure accepted off-machine recovery gap |

**Code receipts:** [collector.py:267–286](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/collector.py#L267-L286), [long_history_study.py:519–657](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/scripts/long_history_study.py#L519-L657), [session.py:130–181](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/session.py#L130-L181), [performance.py:56–100](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/domain/performance.py#L56-L100), [portfolio.py:550–570](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/portfolio.py#L550-L570), [research_backup.py:396–469](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/research_backup.py#L396-L469).

**Do not reactivate these completed source changes as new defect tasks.** New checks in the task menu are **future qualification, coverage extension, owner choice or runtime validation**, not a claim that these code paths still contain the reviewed defect.

## 4. Empirical economic reality, current trials and dates

The registered trial log currently contains **21 distinct study entries**. Classification of the reported result cells is **17 failed, 2 narrowly/conditionally positive historical tests, and 2 not-yet-scored forward studies**. These are **entries**, not statistically independent asset-day observations, and one of the two positives used external *stand-in asset histories*. There is **no documented independently validated Wallex-executable edge**. [S9 trial log](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/trial-log.md#L11-L33).

The most consequential signals from that packet:

| Study group | Registered/evaluated finding | Correct interpretation |
| - | - | - |
| BTC daily trend | Historic BTC 50-day rule was marked **PASS, narrowly**, with a corrected 2024–26 venue replay around +80%; the held-out score was run twice after discovering a 202-day backfill hole | An encouraging **historical signal**, but second scoring and modeled execution limit independence; the future paper journal is the relevant next source |
| Passive six-asset mix | Historical stand-in 3,591-day result **+281.2%**, Sharpe **0.96**, max drawdown **28.3%**; Wallex paper mix record started 17 Nov 2026 | Positive reference-allocation result, not executable Wallex token returns; actual token premium, listing, liquidity and fee path are separate |
| Book imbalance | 5-minute directional mid drift **0.7–4.4 bps**, while taker round-trip costs consumed many times that edge; observed trial lost **42–45 bps** a trade after fee | Predictive directional information can be real while the trade is uneconomic; do not optimize it as taker alpha |
| Short and leveraged breakouts | Borrowing, reopening and liquidation costs destroyed many simulated short variants; best registered tests did not clear thresholds | Margin is a separate debt/credit contract, not a free volatility multiplier |
| Funding confirmation | Tested historical filter earned **+18.3%**, but positive-Sharpe probability **0.759**, below registered **0.90** | Its forward version must be scored **after 8 Feb 2027** on new information, not re-optimized |
| Breadth trend | Prospective registered journal from 20 Nov 2026, scheduled score **after 19 May 2027** | New future record only; results from exploratory pre-registration design are not proof |
| USDTTMN cross-rate, reversion and price gaps | Multiple failed after-cost trials and inadequate touch size | Continue only with genuinely new information or a materially different, pre-registered, cost-feasible execution hypothesis |

**Calendar:** [2027-02-08 product checkpoint](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/PRODUCT.md#L41-L54) concerns whether funded-path work may continue. The later [2027-05-19 breadth journal evaluation](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/roadmap.md#L8-L17) is a separate forward-science milestone, and should not be pulled forward to justify the February gate.

**Trial-management constraint:** max **two registered trials concurrently**; trials must add new information, not relabel the same historical sweep. Further ML/RL fitting is paper-only and its fit attempts must count as study selection. [S5](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/roadmap.md#L16-L22) · [S6](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/PRODUCT.md#L90-L96).

### Dated campaign evidence, not current continuous production metrics

The earlier recorded-data campaign document describes a **149,573-case planned** whole-market extension (373 eligible spot pairs × 401 cases) as running/incomplete in its 6 November snapshot. The separate earlier baseline held **1,945 completed historical cases**, **1,223 with modeled fills**, **722 without fills**, and **1,052 stale terminal marks**. Those numbers are **dated campaign observations**, not live figures for the current November 21 installation or proof the full 149,573 cases finished. [S10 paper qualification](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/paper-qualification.md#L1-L14) · [same source: completed counts](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/paper-qualification.md#L125-L132).

**Financial interpretation:** Historical “net” return is net of the **stated paper model**, not necessarily real fillable return after the account's historical fee tier, real queue/latency, available depth, actual time-vintage venue rules, token premium, FX conversion, dust, financing or liquidation. The system should make these evidence levels visible at every decision point.

---

## 5. Data correctness, venue economics and execution reality

### 5.1 Collector, timestamps and sources

The recently merged collector reconciles **every event in the returned REST overlap** against stored (event time, price, quantity, aggressor) multiplicity; it no longer drops distinct older late prints at the prior high-water time. It also uses REST response receipt time rather than request start time for depth and trades. The fix is real. The structural limitation remains: the checked public Wallex endpoints lack unique trade IDs, so two prints with identical fields cannot be classified with certainty as genuine distinct trades versus repeated transport delivery. Treat this as recorded-source uncertainty, especially when inferring maker capacity. [Collector lines 220–321](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/collector.py#L220-L321).

Outstanding: quantify actual event→receipt→publish lag, per-market missing data and source age, reconnect seed coverage, stale/crossed quotes, historical metadata and raw archival continuity. A passing collector heartbeat is not a 30-day quality proof. Future-data tests must show that a trade arriving late can influence research only after its availability timestamp. Distinguish an absent source event from a quote with legitimate zero volume. Archive and SQL entries must retain their raw source identities and unknown states. Current-machine performance and gap metrics could not be obtained from GitHub.

### 5.2 Realistic, versioned orders and fills

The engine has native historical market/limit paper models, venue rule snapshots, tick/lot/minimum constraints, optional depth walking, maker-fee scenarios, modeled latency and conservative nonfill logic. However, account-specific **historical fee-tier changes inside a run**, current eligible order type at the historical instant, actual queue cancellation behavior, authentic order acknowledgments and full exchange liquidity are not all independently observed. Some fee schedules are frozen at run start, and the structured fee endpoint is not currently collected. [Venue capability and gap table](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/capabilities.md#L47-L65).

Use an explicit **economic model ladder**: (1) mid/bar signal reference, (2) touch plus dated fee assumptions, (3) depth/capacity/latency/queue-constrained execution, (4) registered prospective paper, and (5) independently authenticated venue fill/fee evidence. Never promote a paper fill from one tier into a statement about actual order eligibility. Give a reasoned **UNKNOWN/UNAVAILABLE** when required metadata is missing rather than treating it as a zero fee or unlimited quantity.

Separate event, receive, publication, decision, send, acknowledgment, cancel, fill and settlement clocks. A resting maker limit cannot receive fills before its modeled activation; conservative queue removal requires qualifying traded prints at its price; cancellations are effective only after appropriate venue time assumptions. Pair every cost sensitivity with resulting cash/inventory/order paths, not a post-hoc deduction from a fixed return series. Stops are *attempted* exits: a halt, gap or depleted book may leave exposure and debt. Extend paper stop-limit and trailing stops only with declared data and mechanics. [Paper simulation](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/domain/sim.py) · [Paper session](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/session.py).

## 6. Financial and portfolio audit

### 6.1 Recognize current exact-money work

The integrated code requires unique, correctly signed quote gross postings for modern filled orders. It reconstructs FIFO realized cost/proceeds from booked amounts, accounts for fee currency and rebates, supplies postings to the shared-cash portfolio summary, defaults new portfolios to posted-cost accounting, uses a model identity marker and names derived portable output **paper-summary/3**. Prior defects about rounded execution prices and portfolio trade reporting should **not** be reopened without a new counterexample. [Exact ledger](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/domain/performance.py#L56-L164) · [Portfolio market ledger](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/portfolio.py#L550-L570) · [Portable report](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/reports.py#L12-L34).

The next accounting tasks are **independent conservation/property tests**, not an unscoped refactor. Test simultaneous base/quote fee legs, rebates, all-roundtrip closure, multiple partial lots, insolvency refusal, rounding under alternate Python Decimal contexts, legacy receipt fallback, corrupt new postings, benchmark-currency conversions, genuine dust after minimums change, and parity with optional Rust money kernel. Do not confuse realized P&L, bid-mark equity, modeled fee-adjusted liquidation and authenticated proceeds. All should show currency, source time and economic limitations.

### 6.2 Exact inventory modes

The *legacy* holding heuristic remains the default. Opt-in **inventory/1** treats any positive base balance as held; **inventory/2** adds an explicit exit check reflecting paper-rule status, fresh qualified quote, modeled market-order eligibility, displayed size and warnings. The user-facing language is now about recorded minimum/lot checks; PAPER_CHECKS_PASS is not a venue fill guarantee. [Strategy registry](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/domain/registry.py#L89-L158) · [Inventory and exit checks](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/session.py#L130-L181).

**Open owner decision:** retain the legacy default for new research or make the versioned accurate inventory semantics the default once validated. Old runs cannot be rewritten. If the latter is chosen, test the effect on matched baselines, independent paper sessions and UI presets and disclose the new identity.

### 6.3 Shared cash, exposure and risk

One shared portfolio account reserves quote currency and holds actual base balances. The existing policy supports risk-aware targeting, rebalance bands, cash buffers and loss latches, but *financial trust* still depends on time-specific marks and honest liquidation. Test two assets requesting cash at the same availability time, symbol-order invariance, quote-currency conservation, pending orders after risk-trigger, stale/missing asset marks, dust equity, same-currency benchmark and real multi-asset cost attribution. Distinguish a fixed deterministic policy from a claim of economically *fair* simultaneous allocation; owner approval determines the allocation rule. [Portfolio source](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/portfolio.py) · [Portfolio policy](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/domain/portfolio_policy.py).

Expected shortfall requires enough actual *adverse-tail observations*, not just a long total equity vector. Report tail count, dependence, missingness and sensitivity to block length, volatility window and correlation regime. Liquidity-sensitive exit valuation should walk actual dated displayed depth and say PARTIAL or UNKNOWN when too little is known. Comparing alternative shrinkage, hierarchical risk parity or external risk libraries is **conditional** on measured need.

### 6.4 Margin, FX and tokenized assets

Wallex public margin and credit previews, paper LONG/SHORT, funding-like fees in the modeled contracts and conversion-route previews exist, but the project identifies incomplete account-level terms, collateral changes, stop/take-profit behavior and historical fee/time-vintage coverage. A borrowed position needs a **debt ledger**: loan currency, borrowed principal, collateral, extension fee, accrual, liquidation attempt, repayment and surviving liability after no-fill. Trading-credit subaccounts are not equivalent to position margin or perpetual funding. [Margin/credit scope](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/capabilities.md#L26-L36) · [Venue gaps](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/capabilities.md#L49-L59).

Do not net TMN, USDT, dollars or token holdings without a timestamped executable FX route, size, fee and spread. The currently positive passive multi-asset mix is from *stand-in prices*; Wallex-token data, token premium/discount, calendar, corporate actions, halt/delisting and actual liquidation are separate qualifications. Actual expiry or dividend behavior cannot be imputed from a remote ETF or conventional equity reference. Missing FX/depth leads to separate per-currency display and withheld executable claims.

## 7. Statistical and research-evidence audit

### 7.1 Source statistics are real, but scope-limited

The master has deflated and probabilistic Sharpe, Lo/autocorrelation-aware Sharpe, sampled drawdown, descriptive stationary-block bootstrap, a **2–8 candidate SPA-style** scorecard with common resample indices and an upper Wilson bound, and explicit chronological selection diagnostics. The source itself says **SPA-style**, not full Hansen SPA. [Statistical domain](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/domain/performance.py#L180-L399) · [SPA implementation](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/spa.py) · [Descriptive bootstrap](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/return_bootstrap.py).

**Priority:** Verify actual sampling grain, mark monotonicity, irregular clocks, clustered market-date returns and realistic economic minimum detectable effect before extending inference. Add reference-calibrated complete Hansen consistent SPA only if a registered selection decision requires it, with studentization, null recentering and adequate Monte Carlo precision. CPCV/PBO should use true label-time purge and embargo, common candidate training information, and winner OOS rank diagnostics, but is a **diagnostic for selection instability**, not an independent final test. Optional sequential e-processes require proven lower bounds, previsible betting and optional-stopping null calibration; do not add them simply to increase the statistic count.

The present 70/30 repeated temporal validator explicitly calls itself historical diagnostic rather than consume-once independent final evidence. Missing samples, stale marks and heavy overlap must produce **not established** rather than a numeric proof of absence or presence of alpha. [Temporal validation](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/temporal_validation.py#L19-L110).

### 7.2 Independent custody remains the highest research integrity gap

The current local holdout ledger has append-only triggers and overlap-aware look accounting. The latest long-study script now withholds test-derived ridge and yearly diagnostics unless a look has been recorded; the ResearchProtocol writes local consumption before querying outcomes. These are real improvements in accident prevention. But a local database under the same operator and codebase is **not an independent external evaluator**. [Holdout ledger](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/holdout_ledger.py) · [ResearchProtocol](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/research_protocol.py).

Required for a *new independently evidenced edge claim*: independent outcome control; preregistered candidate-family, strategy/financial engine/data/fee/benchmark code digests; consistent timestamps and windows; all attempts/peeks registered across CLI, browser and scripts; hard refusal to display outcome-derived diagnostics until release; externally authenticated signed/anchored receipts, including failed and aborted evaluations. No local UI action should silently backfill a “fresh” consumption record after results have been seen. Prospective journal versions must match the authoritative settlement semantics.

### 7.3 Respect the registered trial budget

The active product roadmap caps concurrent registered trials at **two**; uses new information rather than another parameter search over the same historical candles; and forbids predictive ML/RL authority. EWMAC, maker-order timing, queue-based imbalance, actual token carry, factor IC, and peer-model tests are **optional new hypotheses**. Require a prospective power calculation, cost-of-speed budget, frozen candidate family and experimental log entry before any later evaluation. The most valuable ongoing research work is collecting untouched days without changing the economic model mid-stream. [Existing roadmap](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/roadmap.md#L6-L22) · [Trial log](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/trial-log.md).

## 8. Rust privileged execution remains separately gated

The project currently has source-only reviewed order authority and one-shot LIMIT send plus local fault tests, but the installed Windows bundle predates this source and is explicitly **NOT CERTIFIED/DISARMED**. The root README says there is no native cancellation or protective-exit transport. Source proof and Windows runner tests cannot substitute for operator-controlled installed principal, SID, DPAPI, authentic Wallex account, first-byte transport ambiguity, STOP responsiveness and actual recovery evidence. [Current README](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/README.md#L5-L16) · [Protected roadmap](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/roadmap.md#L29-L41) · [ADR 0007](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/docs/adr/0007-wiring-the-funded-path-behind-an-arm-button.md).

**HOST qualification prerequisites (separate future authorization):** exact signed installed binary and release manifest; actual service principal and protected pipe ACL; non-admin/worker negative admission; deterministic STOP-before-first-byte and in-flight revision semantics; network I/O outside long-held vault mutex without weakening STOP; multiple concurrent reserved-order balances or conservative one-open-order cap; cancel and unknown-delivery history; crash/restart under every durable transition; reconciliation of actual account locked cash and liabilities; finite bounded ExitOnly and protective-exit semantics if authorized; actual installed-host/venue evidence. No paper strategy or Python browser endpoint can satisfy them.

The only open GitHub issue at this snapshot is [#13: earlier B1 release acceptance](https://github.com/AmirrezaFarnamTaheri/Trade/issues/13). It was last updated 31 October and predates the now-source LIMIT path. **Triage it against the current ADR rather than assuming every old sub-item is still unimplemented, or closing it based only on a source commit.**

**Funded stop condition:** 8 February 2027 is a decision gate, not an arm date. Failing feed quality or no credible net edge means funded-path development pauses and the observatory remains the product. Even a pass requires published bundle, owner sign-off, installed host qualification and controlled venue evidence.

## 9. Recovery, API, operational and performance boundaries

### 9.1 Backup correctness is improved; independent survivability is a policy gap

Current master has authenticated AES-GCM backup manifests and payloads, explicit KDF parameters, optional externally retained digest pinning, preserved old-format reading, raw segment inventory tied to the copied market database, retained snapshot selection, separate inventory coverage versus number actually decrypted, and a fully decrypting restore mode. [Backup source](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/research_backup.py#L200-L471) · [DR guide](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/disaster-recovery.md#L20-L51).

**Policy exception, clearly documented:** On 16 November 2026 the owner canceled automatic off-device backup scheduling and second-machine restoration and accepted loss of data after the last manual copy. The *present committed workload* should maintain honest local backup diagnostics and a disarmed full local restore. **Turning on remote backups or independent credential escrow is a new owner decision**, not assumed consent. For future independently certified research or funded operations, a formal reconsideration is strongly recommended. [Roadmap owner policy](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/roadmap.md#L43-L49).

Do not confuse complete archive inventory with sampled decrypt success, full local recovery, or off-host disaster recovery. Make failure modes distinct: absent segment, bad digest/header, unpinned manifest, old replayable valid manifest, archive path injection, missing closed raw files, disk-full and interrupted restore. Protect frozen scientific records and make restarting a recovered executor DISARMED a hard invariant.

### 9.2 Loopback privacy is an explicit product contract

The current [SECURITY.md](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/SECURITY.md) explicitly documents certain public loopback reads, including saved paper run records. This is not an unrecognized code exposure by itself. Review the Host/Origin/CSRF/DNS-rebinding threat model and the exact permitted route manifest before changing it. The browser must never gain arbitrary local-process, direct trade POST, backup passphrase or automatic AI authority; private writes remain restricted by their established token and service access controls.

### 9.3 Storage and UI performance must be measured first

A single-writer actor, Parquet/Arrow/DuckDB cold research catalog, database topology consolidation, and native ES module migration are **conditional** engineering directions. They are not proof of a current bottleneck. First benchmark ingestion event-loop lag, raw rollover hash costs, Wallex market count, SQLite WAL/checkpoints, repeated limit settlement scans, multi-year query times, Python memory, browser DOM replacements, language switch and frozen artifact replay. Demand bytewise/financial/temporal parity and migration recovery before adopting a new architecture. Preserve executor storage in an independent authority domain.

### 9.4 Operational release evidence

The exact final master [Validate run](https://github.com/AmirrezaFarnamTaheri/Trade/actions/runs/44834196697) completed **successfully**, including Python, Rust Windows and disposable Windows SCM checks. The extended weekly mutation job was skipped. Windows hosted runners and cross-OS synthetic backup fixtures do not prove the installed-host security/custody requirements; retain the actual job and skipped-step evidence for each claimed capability. [Current master CI](https://github.com/AmirrezaFarnamTaheri/Trade/actions/runs/44834196697) · [CI definition](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/.github/workflows/validate.yml).

---

## 10. Product strategy — one coherent evidence-first experience

TradingGYM already exposes much of the research capability through the existing single-page interface. The quality opportunity is not a wholesale rewrite: it is an **operator journey that makes evidence, eligibility, uncertainty and the next honest action legible**. Preserve the established calm visual language, English/Persian translation, RTL, responsive layout, keyboard access and current loopback/authority separation. [Design system](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/DESIGN.md) · [Product principles](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/PRODUCT.md) · [Existing browser map](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/architecture.md#L26-L50).

### Proposed product navigation

| Destination | Primary user question | First view | Expert drill-down |
| - | - | - | - |
| **Overview / Checkpoint** | Is my research credible and what is blocked? | Feed coverage, independent-evidence verdict, forward journal continuity, backup/host status | Dated evidence and last successful actual operation receipts |
| **Markets** | Which recorded assets are eligible and liquid? | Filterable watchlist, bid/ask, spread/depth/freshness and gaps | Historical rule vintages, quality calendar, time-of-day books, provider differences, FX paths |
| **Research Lab** | How do I test an idea without leaking the final outcome? | Guided hypothesis→data→strategy→cost→risk→registered/preview state | Exact server action schema, advanced JSON, trial family, source/code hashes |
| **Run Explorer / Cost Lab** | Why did the model win, lose or abstain? | Synchronized equity, benchmark, drawdown, decision, order, nonfill | Quote/fee/queue/latency evidence and paired model sensitivity; full authoritative records |
| **Portfolios / Margin** | What is actually owned, reserved, financed or merely modeled? | Shared cash, held/dust/pending, portfolio exposures, collateral/debt, risk latches | Exact postings, mark freshness, tail samples, liquidation depth and FX routes |
| **Evidence & Trials** | Which tests are consumed, registered or still collecting? | Family attempt counts, released outcomes, future cutoffs, failed-day continuity | Method assumptions, local vs independent custody, run digests, calibration and decision thresholds |
| **Account & Tickets** | What did the read-only venue/account report, and what can I review? | Provenance/age of observations and offline review flow | Correlated immutable receipts, sanctioned operator review, blocked reason |
| **System** | Is the local workstation and recovery path trustworthy? | Actual process/feed status, WAL/storage runway, local backup and disarmed HOST state | Recovery scope, policy exception, signed release/installed-host qualification evidence |

**All headings are recommended IA, not a claim these exact pages already exist.** Current product routes can be renamed/mapped gradually, preserving deep links, saved form state, existing API permissions and research run identities. The best initial screen is the one that tells the operator **what is genuinely known** and **what action is safe next**, not a dashboard of decorative positive scores.

### Required interface semantics

- Explicit visual labels: *DEMO/SYNTHETIC*, *RECORDED SOURCE*, *MODELED PAPER*, *REGISTERED*, *RELEASED OUTCOME*, *AUTHENTICATED ACCOUNT*, *DISARMED* and *QUALIFIED INSTALLED HOST*. Don't reuse colors as authority.

- Every price, fee, size, Sharpe, risk, token return and FX conversion has **units, time, source and confidence/qualification**.

- Fail states explain reason + remediation: no data, stale quote, unknown historical fee, insufficient depth, failed study, interrupted journal, protected result withheld, absent account permission and incomplete restore.

- No animated market-table reflow during refresh: preserve table order, selected symbol, keyboard focus and live-region rate limits.

- Native, compact HTML/CSS/JavaScript remains acceptable. Module splitting should be triggered by testable maintainability/performance benefit, not an arbitrary fashionable framework.

- Automatic English/Persian key parity, correct bidirectional numbers/ISO timestamps, keyboard-only completion, contrast, accessible charts and reduced motion belong in the normal acceptance gates.

## 11. Engineering health, source hygiene and selective adoption

### 11.1 Testing priorities

The strongest engineering tests are **differential and metamorphic**, not feature-count or line-count totals:

- Adding genuinely future observations cannot change an earlier decision, snapshot digest or filled order.

- Reordering same-clock instrument events cannot change economic allocation unless a documented priority rule intentionally does; the reason must remain visible.

- Changing fee currency or sign cannot silently create quote/base balance; realized lot P&L equals exact cash postings with residual inventory.

- A quote without executable depth cannot produce a fully qualified size-sensitive exit.

- A legacy frozen replay reproduces its saved identity and economic outputs; new policies produce separate evidence identities.

- Rejected/unconsumed holdout never leaks through text, JSON, chart, CSV, notebook or intermediate fit diagnostics.

- Backup failure, untrusted manifest, missing closed segment, malformed archive and old restored snapshot cannot be called a verified off-machine recovery.

- Any protected STOP, service reconnect, first-byte timeout or partial fill leaves the money state conservatively documented; no UI request grants funded authority.

Use the current source-owned tests as starting fixtures; add independent financial or statistical oracles and deliberate corruption/fault injection. Keep random seeds, timestamps, currency precision and tested dataset size in every repeatable result.

### 11.2 Housekeeping

There are hundreds of source/test/document paths, including active jobs, historic strategy studies and preserved negative experiments. **Do not delete scripts solely because an import search finds no caller**: scheduled tasks, historical receipts, notebook links and old research artifacts can be legitimate consumers. First classify as operational, active preregistered, historical reproducer or genuinely unused; capture import/CLI/scheduler/reference callers, safe aliases and rollback. Leave separate Rust custody and archive codecs intact until host-compatible migration review. [Source layout](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/README.md#L19-L27) · [Architecture ownership](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/architecture.md).

Evaluate license/third-party obligations before direct code ports. Potential comparison oracles: LEAN for venue-specific fee/fill/currency contracts, hftbacktest for queue/latency sensitivity, NautilusTrader for event schemas, pysystemtrade for EWMAC/cost-of-speed, Hummingbot for finite market-making controllers, Freqtrade for lookahead checks, Qlib for feature/ML lineage, Zipline for point-in-time instrument universes, vectorbt for exploratory screening, and PyPortfolioOpt/skfolio/Riskfolio-Lib for portfolio-tail algorithms. **None should be added as a production dependency until a concrete test, measured gain, licensing and security review justify it.**

## 12. New staged roadmap — outcomes, dependencies and stop gates

Stages are **dependency gates**, not promises of calendar completion. Parallel teams may work independently, but no downstream result should bypass required evidence. The companion task menu contains the exact individual deliverables and tests.

| Stage | Scope / owner discipline | Exit evidence | Do not promote |
| - | - | - | - |
| **0 — Pin and verify current baseline** | Reconcile latest master CI, commit SHA, versioned financial/evidence schemas and merged behavior with previous defects; read current README/roadmap/accepted risk | Final SHA CI receipt, targeted golden regression run and explicit skipped/host limitations | Pending CI as green; merged as installed |
| **1 — Preserve future science** | Registered BTC allocation, token mix, funding and breadth journals; causal sources, actual schedules/aborted days, independent custodian proposal, family accounting | Verified exact strategy/model digests, no silent missing days, registered criteria and a reviewed custody architecture | Any new result viewed before preregistered release |
| **2 — Qualify economic reality** | Fee/rule vintages, quote/trade quality, depth/capacity, maker queue/latency stress, exact liquidation, shared cash and debt/FX meaning | Paired cost/latency/size scenarios, known/unknown matrix, exact ledger property tests and benchmark parity | Model “net” rebranded as authenticated fill |
| **3 — Calibrate research inference** | Dependence/sampling, economic power, candidate-family corrected SPA when needed, CPCV/PBO diagnostic if justified, independent final outcome protocol | Synthetic-null calibration, external reference results, family/selection provenance, withheld outcomes until release | Descriptive SPA-style/bootstrap as final evidence |
| **4 — Deliver evidence-first product** | Overview checkpoint, market quality, guided study, run/cost explorer, portfolio inventory/debt, trial and restore status, EN/FA and accessible states | Complete user journeys with real/synthetic labels; Windows Edge/Linux Chrome, keyboard, RTL and mobile evidence | Synthetic status, demo or paper as live authority |
| **5 — Measured architecture/operations** | Ingest W/L lag, SQL/restore/browsers benchmark; optional incremental scan, writer actor, Parquet/Arrow and DB consolidation only if justified | Controlled before/after, exact replay/receipt parity, full-size migration restore and rollback proof | Large storage migration based on an imagined bottleneck |
| **6 — Future protected host qualification** | Only if February gate and owner permission: installed signing, SID/DPAPI, STOP/send, real account read, cancel/partial/unknown outcomes, disarmed recoveries | Signed installed host qualification, actual venue and OS negative tests, independent reviewer and owner authorization | CI/test fixtures as funded trading approval |
| **7 — Carefully budgeted alpha research** | At most two registered trials, use genuine new predictors, fee-cost-power screening and economic baseline; peer libraries conditional | New future information, registration before measurement and independently released outcome | More tuning of already-seen 2024–26 asset history |

### Immediate 10-work-item queue

These are **recommended next actions**, not claimed source defects:

1. **Release certainty:** Check final master Validate run [44834196697](https://github.com/AmirrezaFarnamTaheri/Trade/actions/runs/44834196697) and run targeted integrated finance, collector, research and restore regressions on one pinned local tree.

2. **Research governance:** Agree who independently controls final outcomes; publish a no-unconsumed-peek threat model and test it across every result outlet.

3. **Forward continuity:** Verify actual BTC, token-mix, funding and breadth journal schedules, first/last day, gap reports and immutable process receipts on the operator data root.

4. **Venue reality:** Record as-of fees and trade/market rules where actual sources exist; enumerate historical intervals that cannot qualify an executable net claim.

5. **Cost/latency proof:** Run paired pessimistic partial-fill, depth, queue/impact and missing-data scenarios without retroactive fill adjustment.

6. **Money reconciliation:** Make property/differential fixtures authoritative for fee currency, true inventory, shared cash, partials, dust and debt.

7. **Statistical qualification:** Define economically material effect, dependence-aware uncertainty and actual future power for the two active trials before another model family.

8. **Recovery disclosure:** Validate current local full restore and distinguish it from sampled drill; document actual last off-device copy or the accepted absence.

9. **Product:** Ship an Overview readiness/claim-state path followed by run/cost and blocked-action explanation, not a sweeping frontend rewrite.

10. **Protected authority:** Maintain DISARMED; refresh old issue #13 with today’s source/host acceptance distinction and get owner decision at the February checkpoint.

## 13. Decision gates and owner choices

| Decision owner must explicitly resolve | Current state | Recommended decision rule |
| - | - | - |
| **New-run inventory default** | Legacy default; inventory/1 and inventory/2 opt-in | Keep existing identity stable; change default only with golden results and documented economic scope |
| **Independent final custodian** | Local research protocol and holdout ledger | Select genuinely separated evaluator/outcome access and authenticated immutable receipt before final claims |
| **Historical net-executable claim threshold** | Some historical fee/rule/depth data unknown | Refuse qualified label unless actual as-of rule/fee/source/size required for that order is known; allow labeled modeled research |
| **Family-adjusted significance** | SPA-style available, broader inference unqualified | Implement full SPA/CPCV/e-process only for a registered decision, with null calibration and sufficient power |
| **Simultaneous portfolio fairness** | Deterministic shared cash, sequential event handling | Name and test chosen policy; require rename/order invariance where not intentionally prioritized |
| **Off-machine backups and remote custody** | Owner canceled automatic off-device scheduling and second-machine restore 16 Nov | Keep risk accepted/disclosed; require a fresh explicit owner decision before enabling external backup or calling recovery complete |
| **Loopback saved-run privacy** | Public local reads intentionally documented | Revisit only with an explicit local adversary and compatibility threat model |
| **Protected outstanding orders and exit authority** | In-source one-shot LIMIT, no cancel/protective path; installed unqualified | No funded authority until independent host/venue qualification and explicit owner review |
| **2027-02-08 gate** | Future registered stop/go decision | If feed or credible net-edge gate fails, remain observatory; calendar alone never arms the executor |
| **2027-05-19 breadth result** | Future forward scoring | Release only after the registered date and independently controlled forward outcome |

## 14. Acceptance matrix: what would change the verdict?

| Claim | Minimum proof needed | What current evidence does NOT prove |
| - | - | - |
| A venue feed is reliable | 30-day actual per-day coverage, source publication lag, gap ages, raw/SQL consistency, independent spot checks | The collector started or CI passed |
| Historical orders are economically executable | Exact as-of eligible rules/fees + price, depth, size, latency/queue/stop constraints + unknown refusal | Successful modeled fill against a candle or midpoint |
| Financial results are reconciled | Exact Decimal cash/base/debt conservation across every posted event and oracle/differential fixtures | A positive P&L summary or passing float metric |
| Portfolio risk is stable | Fresh native-currency marks, sufficient tail observations, scenario sensitivity, capacity-aware exit and policy invariants | One observed Sharpe/ES number |
| A strategy has credible net edge | Registered family+benchmark, untouched future outcomes, independently released evaluation and economically positive threshold after realistic costs | Historical selection, revised backfill holdout, reference token proxy or paper journal alone |
| Research custody is independent | Separate evaluator/outcome access, signed/anchored receipt, no-peek negative tests and explicit release timing | Local SQLite append-only triggers or a salted hash |
| Backup is recoverable after laptop loss | Accessible independent copy, permitted key recovery and successful off-host restore rehearsal | A local decrypt or sampled drill |
| A privileged order can safely be sent | Exact installed signed host, SID/DPAPI/ACL, native STOP/cancel/recovery, real venue reads and owner authority | Source code, hosted Windows tests or browser preview |
| Product is usable | Successful real task paths in EN/FA, keyboard, screen reader, mobile, degraded feed, account and restore states | Attractive static screenshots or arbitrary dashboard scores |

## 15. Source index, reproducibility and limitations

**Primary pinned evidence:**

1. [README and capability boundary](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/README.md) — authoritative installed/armed status.

2. [Capabilities including venue support matrix](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/capabilities.md).

3. [Project roadmap](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/roadmap.md) — forward deadlines and owner recovery exception.

4. [Registered trial log](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/trial-log.md) — dated historical results and forward horizons.

5. [Research and product architecture](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/architecture.md).

6. [Current source delta](https://github.com/AmirrezaFarnamTaheri/Trade/compare/a0fea74c21344f70e784c19cec88b30baf0575b0...8fba0b15115b617067fc93b9c9769c9351472900) and [integrated review #107](https://github.com/AmirrezaFarnamTaheri/Trade/pull/107).

7. [Current CI run](https://github.com/AmirrezaFarnamTaheri/Trade/actions/runs/44834196697) — **completed successfully** on audited master; extended weekly mutation skipped and installed-host qualification not implied.

8. [Disaster recovery](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/disaster-recovery.md) and [backup implementation](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/research_backup.py).

9. [Statistical SPA-style code](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/spa.py) and [local holdout](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/holdout_ledger.py).

10. [Financial trade ledger](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/domain/performance.py), [portfolio](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/portfolio.py) and [inventory](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/src/gym/services/session.py).

11. [Protected release acceptance issue #13](https://github.com/AmirrezaFarnamTaheri/Trade/issues/13), **older/stale wording**, and [ADR 0007](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/docs/adr/0007-wiring-the-funded-path-behind-an-arm-button.md).

12. [Current UI brand, accessibility and product boundaries](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/PRODUCT.md).

**What this review did not verify:** private SQLite and raw archives, current device health and 30-day live coverage; exact stored prospective journal receipts; authenticated Wallex account orders or historical billing; installed Windows service binary, T0/T2 ACL, DPAPI/STOP race; off-device copies, passphrase recovery and independent machine restore. GitHub source and hosted CI cannot substitute for those. Lack of a verified runtime fact is reported as an evidence gap, not a guessed defect.

**Bottom line:** Continue building a **credible research observatory**. Protect the registered future evidence, ensure every “net” result is reproducible and economically qualified, ship a readable evidence-first interface, and do not use inferred performance to rush protected funded execution. The companion [new task list](https://chatgpt.com/space/page_6c78d41849308191b57ca89bf08e1c82) turns these decision gates into assignable, testable work.
