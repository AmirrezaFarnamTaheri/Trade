# TradingGYM — Updated Active Task Menu

**Fresh backlog dated 21 November 2026** · Based on [master 8fba0b15115b617067fc93b9c9769c9351472900](https://github.com/AmirrezaFarnamTaheri/Trade/tree/8fba0b15115b617067fc93b9c9769c9351472900). **Companion:** [Full updated report and staged roadmap](https://chatgpt.com/space/page_5a17074f29a481919cb0fcf6fd4ccffd).

**Important status:** The five previously reviewed PRs (#102–#106), plus their reviewed integration (#107), are already merged; there were zero open PRs at the pinned cutoff. The source now handles old/late REST overlap, withholding certain unconsumed test diagnostics, opt-in true inventory, modern booked quote postings in portfolios, and snapshot-specific authenticated restore. **Those exact code changes are not re-listed as missing.** New items below concern unverified runtime evidence, correctness extensions, policy choices, feature boundaries and genuinely open work.

## How to use this menu

- **P0:** Important research/data/economic integrity, release or explicit product-policy decision. Close before making a stronger corresponding claim.

- **P1:** High-value financial, statistical or operational qualification. May be independent of other packages.

- **P2:** Product usability, engineering quality and routinely useful diagnostics.

- **OPT:** New strategy/library/migration capability; **not required** unless there is a measured need, registration and owner approval.

- **HOST:** Privileged Rust/Windows/venue acceptance. Remains **DISARMED** and must not be implemented or treated as authorized by research/UI approval.

- Each task is **uncompleted until a current, dated receipt demonstrates the stated acceptance**. Not finding the proof here does *not* demonstrate the underlying implementation is broken.

- Where the owner has accepted a risk (notably canceled automated off-device backup), the task is **disclose and monitor the exception**. A risk-reversing action is labeled owner-optional.

- The IDs here are fresh and unique. Older historical IDs A/B/C/D are useful cross-reference only; this menu replaces the older undifferentiated inventory.

- For optional tasks, the correct closure may be **REJECTED WITH EVIDENCE**, **DEFERRED**, or **NOT APPLICABLE** instead of implementing code.

**Global definition of done:** Reproduction/need and source URL; intended contract and explicit affected interfaces; focused positive, negative, boundary and regression tests; actual observed outputs/commands/OS/data; compatible run/economic/evidence identities; truthfully labeled missing/unknown; a reviewer suitable for the financial/statistical/security risk; documented rollback/restore/user-facing state. For HOST work, require installed actual OS/venue evidence, not just synthetic tests. For research acceptance, require independent outcome custody and registration.

## Dependency and release flow

| Lane | Blocking gate | Next eligible work |
| - | - | - |
| Baseline | Pin current CI and source/installed distinction | Evidence/financial/UX improvements on one verified tree |
| Research credibility | Future journal continuity and independent evaluation design | Preregistered forward assessment, not repeated historical test |
| Executable economics | Historical rule/fee/source availability and exact paper accounting | Paired scenario tests and credible risk limits |
| Product | Correct evidence classification and backing API contracts | Research/Cockpit/portfolio UX |
| Architecture | Actual benchmark and restore evidence | Optional Parquet/writer/database/frontend changes |
| Funded path | 2027-02-08 stop/go, owner sign-off and installed HOST qualification | Only explicitly approved protected work |

**Core date constraints:** **8 February 2027** funded research checkpoint; **after 8 February 2027** funding-confirmed-trend-forward scoring when archive completeness permits; **after 19 May 2027** breadth-trend-forward evaluation. The trial budget remains at most **two concurrent registered hypotheses**. The calendar is not an executor arming signal. [Current project roadmap](https://github.com/AmirrezaFarnamTaheri/Trade/blob/8fba0b15115b617067fc93b9c9769c9351472900/gym-core/docs/roadmap.md).

---

# G. Baseline integrity, release state and owner decisions

- [x] **G001 · P0 · Final current-master CI receipt — VERIFIED.** [Validate run 44834196697](https://github.com/AmirrezaFarnamTaheri/Trade/actions/runs/44834196697) succeeded on SHA 8fba0b1. Extended weekly mutation was skipped; hosted checks do not qualify the installed funded executor.

- [ ] **G002 · P0 · One pinned local integration run.** On a real working checkout, run finance, inventory, reconnect, long-study no-peek, backup snapshot and UI tests against the same SHA and record commands/results.

- [ ] **G003 · P0 · Reconcile task status with implementation.** Mark the merged old late-trade, accounting, inventory/2, holdout-script and snapshot-cutoff code as delivered; list only genuinely missing evidence or extensions.

- [ ] **G004 · P0 · Record installed-versus-source capabilities.** Capture actual signed installed bundle hashes and mark all source-only funded features NOT INSTALLED/NOT QUALIFIED.

- [ ] **G005 · P0 · Enforce the current funded stop condition.** Preserve zero funded-loss budget, DISARMED startup and no paper→funded promotion.

- [ ] **G006 · P0 · Publish the 2027-02-08 decision protocol.** Freeze exact 30-day feed gap criteria, net-edge test and required evidence/owner decision before observing that deadline.

- [ ] **G007 · P0 · Record the backup policy exception.** Make the 16 Nov canceled off-machine schedule and associated data-loss exposure visible without silently enabling remote services.

- [ ] **G008 · P0 · Triage old B1 GitHub issue #13.** Reconcile 31 October acceptance wording with current in-source LIMIT path; preserve unresolved installed/venue proof and close obsolete subclaims only with evidence.

- [ ] **G009 · P1 · Establish current evidence manifest.** List the exact code digest, docs revision, local record dates, read-only venue scope and unavailable runtime observations of this baseline.

- [ ] **G010 · P1 · Define economically qualified “net” labels.** Document observed, modeled, historically constrained, forward registered, independently released and authenticated meanings with a refusal threshold.

- [ ] **G011 · P1 · Approve decision ownership.** Identify who can sign finance math, statistical inference, research outcome release, private API changes, backups and installed HOST permissions.

- [ ] **G012 · P2 · Publish a source-of-truth document hierarchy.** README = first use/current status, capabilities = verified scope, trial log = frozen hypotheses/outcomes, roadmap = outstanding work, task menu = assigned execution.

# E. Future studies, registered evidence and independent custody

- [ ] **E001 · P0 · Define genuine final-data custodian.** Choose separate evaluator/outcome storage/persona not writable or queryable by the normal research operator; document access boundary and release ceremony.

- [ ] **E002 · P0 · Preregister evaluation identity.** Bind candidate family, strategy/config hashes, economic model, data origin, symbol universe, times, benchmark, costs, source cutoff and future criterion.

- [ ] **E003 · P0 · Build no-peek threat model.** Enumerate browser/API, CLI, notebook, long-study, job queue, cached artifact, chart, CSV and logging paths to an unreleased outcome.

- [ ] **E004 · P0 · Test no-peek via outcome perturbation.** Change only unreleased test prices and assert all unconsumed external outputs are identical; test text, structured JSON and exported summaries.

- [ ] **E005 · P0 · Record every attempted family selection.** Hyperparameters, assets, date windows, notebook queries, failed fits, alternate benchmark choices and plot inspections must count for the same family.

- [ ] **E006 · P0 · Protect look identity across overlapping windows.** Modified prices, shortened/shifted windows and revised config hashes cannot create an unjustified fresh test.

- [ ] **E007 · P0 · Require pre-read consumption receipt.** Every final evaluation is recorded before any withheld observation is loaded; cancellation, crash and refusal remain monotonic.

- [ ] **E008 · P1 · Authenticated release bundle.** Sign/externally anchor final outcome, code/data digests, evaluated attempts, sample count, decision criterion and failure/abort reason.

- [ ] **E009 · P1 · Preserve invalidated/negative evidence.** Historical studies and unsuccessful forward attempts remain reconstructible; deletion cannot reset search count.

- [ ] **E010 · P1 · Prove journal/engine economic parity.** Forward paper and historical replay using the same cost/version must match inventory, exact postings, decision times and no-fill.

- [ ] **E011 · P1 · Verify actual BTC trend journal continuity.** Inspect scheduled run receipts, missing days, first/last observation, frozen 50-day rule and 2027-02-08 eligibility.

- [ ] **E012 · P1 · Verify passive token-mix journal continuity.** Inspect actual Wallex instruments, weights, date/fee/depth assumptions, unlisted tokens, and all missing or stale days.

- [ ] **E013 · P1 · Verify breadth journal.** Confirm 15:00 Tehran scheduling, market/volume eligibility, versioned blend, registered 5% band and untouched days through 2027-05-19.

- [ ] **E014 · P1 · Verify funding forward-data completeness.** Confirm Binance monthly funding and spot archive hashes, last eligible dates, symbol coverage and absence of lookahead before after-2027-02-08 scoring.

- [ ] **E015 · P1 · Make forward journal schedules idempotent.** Parallel runs, retry and crash during append cannot create a second terminal decision for the same study day.

- [ ] **E016 · P1 · Distinguish process heartbeat vs evidence.** Run success, observation freshness, actual decision completion, zero-signal day and broken ownership each have separate status.

- [ ] **E017 · P1 · Make study gaps observable.** Record missing quote/trade/symbol, halted market, fee unknown and skipped day with precise cause and no invented zero return.

- [ ] **E018 · P1 · Precommit stop/extension rules.** Study continuation, early failure, missing-day handling and eventual trial threshold cannot be tuned after inspecting future outcomes.

- [ ] **E019 · P2 · Evidence-first trial browser.** Show family, registered pass mark, available/withheld outcomes, evaluator, consumed-look receipt and next eligible evaluation date.

- [ ] **E020 · P2 · Link trial log and machine receipts.** Every manual trial-log entry links reproducibly to code, cost assumption, actual dataset and selected scientific output.

- [ ] **E021 · P2 · Instrument human or AI analysis peeks.** Log the exact source packet and whether an analyst saw candidate OOS data; do not pretend generated prose itself is evidence.

- [ ] **E022 · P1 · Honor the two-trial budget.** The registry and planning workflow reject a third concurrently active registered hypothesis absent a documented supersession.

# M. Market-data collection, provenance, availability and venue snapshots

- [ ] **M001 · P1 · Measure actual 30-day feed continuity.** Daily pass/fail from doctor, missed market intervals, >24-hour raw gaps and per-market covered time; publish denominator.

- [ ] **M002 · P1 · Instrument all ingestion clocks.** Venue event, receipt, parse, raw append, SQLite commit and research publication watermark with actual p50/p95/p99 lag.

- [ ] **M003 · P1 · Audit REST reconnect overlap on current deployment.** Replay same-time and older-late prints, multiple restarts and distinct-vs-identical multiplicity; compare raw with normalized row counts.

- [ ] **M004 · P1 · Quantify unresolved identical-print ambiguity.** Surface potential duplicate transport capacity when no venue ID exists; prevent unqualified maker-fill claims.

- [ ] **M005 · P1 · Run causal availability fixture.** A late trade/quote modifies only decisions after its recorded publication/availability cutoff, not earlier signals.

- [ ] **M006 · P1 · Verify raw↔SQL provenance.** Every market tick in a qualified replay links to an exact archived segment and retained source digest; broken links block qualification.

- [ ] **M007 · P1 · Trace catalogue and rule request timing.** Confirm merged effective snapshots appear only after both source responses and retain original individual receipt times.

- [ ] **M008 · P1 · Build as-of market-rule evidence index.** Tick/lot/minimum, market versus limit enablement, halts, price guard, zero-fee and effective vintage with explicit missingness.

- [ ] **M009 · P1 · Capture venue fee changes when available.** Track maker/taker per-account tiers, structured fee source, timestamp, scope and missing/revised rate; keep earlier vintages.

- [ ] **M010 · P1 · Measure feed/venue clock skew.** Use observation timestamp precision, actual receipt jitter and invalid backward provider events instead of assuming provider event equals local time.

- [ ] **M011 · P1 · Track source completeness separately from freshness.** A recently delivered but incomplete trade batch must not be labeled full-volume evidence.

- [ ] **M012 · P1 · Record staleness and book anomalies.** Crossed/no-depth/zero-size/out-of-order/unstable spreads require searchable quality and sample counts.

- [ ] **M013 · P1 · Check reconnect gap detection boundaries.** Empty REST batch, REST window after last websocket print, partial source overlap and long offline gap keep honest GAP reports.

- [ ] **M014 · P2 · Verify per-shard heartbeats and errors.** Show reconnect counts, last frame by market/shard and duration since actual qualified publication.

- [ ] **M015 · P2 · Measure segment rollover blocking.** Profile SHA-256, compression/move and WAL checkpoint under sustained feed; bounded event-loop delay must be shown.

- [ ] **M016 · P2 · Reduce catalog write amplification only if measured.** Stable instrument facts should not be re-written just because 24h quote statistics change.

- [ ] **M017 · P2 · Normalize REST proxy/TLS/timeout handling.** Public/private reads honor documented proxy, certificate, slow response and rate-limited retry bounds.

- [ ] **M018 · P2 · Source cross-check on normalized symbols.** Compare event clock, base/quote, price and corporate action before describing two feeds as contradictory.

- [ ] **M019 · P2 · Data quality calendar per symbol.** Source availability, qualified bars, gaps, halt spans, archived source and reasons visible to users.

- [ ] **M020 · P2 · Repair stale health summaries.** Improving/worsening alert severity and elapsed outage must supersede simple duplicate-status suppression.

- [ ] **M021 · P2 · Confirm historical-universe causality.** No future listing/delisting/market-status leak into prior replay candidates.

- [ ] **M022 · P2 · Publish provenance-based feed SLOs.** Define meaningful budgets for real lag, unarchived raw hours, missing closed segments and storage runway; alert from measured breaches.

# X. Historical execution qualification, liquidity and paper order behavior

- [ ] **X001 · P0 · Define strict executable-net gate.** An unavailable as-of order eligibility field, fee, actionable quote or required depth yields REFUSED/UNKNOWN, not an implied fill or zero cost.

- [ ] **X002 · P1 · Verify venue order type at placement.** Historical market/limit enable, price guard, tick, minimum, symbol halt and subsequent rule change are checked at the correct clock.

- [ ] **X003 · P1 · Model order latency phases.** Event→receive→publish→decide→send→ack→active→fill/cancel; unknown legs receive conservative documented scenarios.

- [ ] **X004 · P1 · Stress distributional delay.** Jitter, spikes, reconnect stalls and missing acknowledgments alter fill paths and later decisions, not just performance labels.

- [ ] **X005 · P1 · Audit maker queue-ahead baseline.** Qualifying traded quantity alone drains known queue ahead; no unseen cancellations credited as free fills.

- [ ] **X006 · P1 · Test post-only activation.** Crossing an ask when intending maker buy is a rejection/changed order, not assumed passive execution.

- [ ] **X007 · P1 · Model cancellation race.** Fill between cancel request and effective acknowledgment remains possible; pending qty and cash reservation are conserved.

- [ ] **X008 · P1 · Audit identical prints in queue capacity.** Show the full modeled capacity contributed by indistinguishable same-field prints and apply adverse sensitivity.

- [ ] **X009 · P1 · Limit partial fills by observed depth.** No multi-level complete fill without sufficient actual levels or an explicitly labeled extrapolation.

- [ ] **X010 · P1 · Implement depth-walk liquidation report.** Full/partial/unavailable quote proceeds by instrument, quantity, fee and quote time; include residual unsold base.

- [ ] **X011 · P1 · Pair adverse impact and spread scenarios.** Compare identical strategy under plausible spread/depth/impact and show win/loss, drawdown and outstanding inventory.

- [ ] **X012 · P1 · Test minimum exit sellability.** Fee-adjusted received base, lot precision and min notional can leave real held dust; do not count an impossible exit as flat.

- [ ] **X013 · P1 · Test venue band/guard transitions.** Quote/reference discontinuity, stale first-mid surrogate, empty depth, outlier event and halt fail honestly.

- [ ] **X014 · P1 · Make stops non-guaranteed exits.** Gap, halt, delayed trigger, no quote, partial capacity, unknown trade receipt and active pending entry are distinct results.

- [ ] **X015 · P1 · Formalize stop-limit paper contract.** Activation and child limit queue, stop trigger history, cancellation and never-filled exit cases before adoption.

- [ ] **X016 · P1 · Formalize trailing-stop paper contract.** Causal high-water and trigger time, dynamic reference, delayed partial fills, source uncertainty and visible model version.

- [ ] **X017 · P1 · Compare paper market and limit on same received data.** No drift due to reference clocks, single-counted prints, shared fee currency and baseline/latency version.

- [ ] **X018 · P1 · Evaluate size participation.** Actual book units, available depth, order clip, quote age and time-of-day effects; refuse illiquid capacity.

- [ ] **X019 · P1 · Publish model sensitivity ladder.** Reference/touch+fees/capacity+latency/adverse queue/forward/venue-authenticated each get discrete evidence labels.

- [ ] **X020 · P2 · Add per-fill audit trail.** Decision cutoff, source vintage, fee source, matched trades, queue state, sent/active modeled times, cash posts and nonfill reason.

- [ ] **X021 · P2 · Build paired Cost Lab.** Run the same registered model through explicit scenarios without inventing new selection trials or retroactive tuning.

- [ ] **X022 · P2 · Add execution-difference diagnostics.** Report eligible fill fraction, cash unused, inventory carry, forced exit attempt, cost breakdown and cumulative benchmark impact.

- [ ] **X023 · OPT · Calibrate cancellation-front queue distribution.** Use authenticated order lifecycle if authorized; otherwise retain sensitivity-only not a point estimate.

- [ ] **X024 · OPT · Test time-of-day maker hypothesis.** New preregistration and a real capacity/markout metric are required; historical tight spread alone cannot qualify fills.

---

# F. Exact money, inventory, shared-cash portfolios and risk acceptance

- [ ] **F001 · P1 · Build an independent journal oracle.** For each filled buy/sell, compare authoritative base and quote postings, gross notional, fee currency and terminal cash balances with the new booked ledger.

- [ ] **F002 · P1 · Property-test exact conservation.** Across hundreds of random buy/partial sell/fee/rebate/dust sequences no currency balance appears or disappears beyond recorded event postings.

- [ ] **F003 · P1 · Validate base-fee sell consumption.** Sell gross quantity plus base-denominated fee must consume precisely its true base liability, including exact-lot closure and partial FIFO.

- [ ] **F004 · P1 · Validate quote fees and rebates.** Entry/exit fees or negative rebates in quote alter cost or proceeds exactly once, with correct sign and currency.

- [ ] **F005 · P1 · Test duplicate or missing modern posting refusals.** No modern FILLED receipt can be silently called reconciled if its unique correctly signed gross quote amount is absent.

- [ ] **F006 · P1 · Preserve genuine old receipt fallback.** Archived result lacking postings remains readable with explicit legacy semantics and old output digest; mutated modern receipts are rejected.

- [ ] **F007 · P1 · Compare Python/Rust financial kernels.** Differential exact Decimal test at rounding, overflow, tiny lot, max precision and negative fee boundaries, or explicit non-support.

- [ ] **F008 · P1 · Prove FIFO/average-cost consistency.** Across multiple lots, alternating partials and full closure, realized sums and open cost reconcile to original acquisition basis.

- [ ] **F009 · P1 · Prove open dust in equity.** Even unsellable fractional base stays owned and marked; balances cannot become FLAT from the old 1%-equity heuristic under opt-in inventory.

- [ ] **F010 · P1 · Compare model/identity replay families.** Frozen legacy, inventory/1, inventory/2 and booked-notional portfolio runs preserve their declared behavior and distinct new identities.

- [ ] **F011 · P1 · Decide new-run inventory default.** Owner reviews effects on baseline/strategy, UI compatibility and historical frozen records; document either intentional legacy default or exact inventory default.

- [ ] **F012 · P1 · Reconcile standalone versus portfolio P&L.** On a one-market-equivalent fixture, cash, inventory, realized fees, recorded orders and summary returns must match after declared differences.

- [ ] **F013 · P1 · Define multiple valuation bases.** Recorded bid-mark equity, net-if-sold touch estimate, full-depth partial liquidatable estimate and actual authenticated settlement cannot share one label.

- [ ] **F014 · P1 · Reconcile portfolio aggregate trade statistics.** Count closed, winning, losing, flat trades and expectancy from actual shared-account fills, not an average of independent symbol summaries.

- [ ] **F015 · P1 · Publish portfolio inventory/reservation timeline.** Held, resting/reserved, pending, canceled, dust, partial fill and explicit unknown are visible at each decision.

- [ ] **F016 · P1 · Specify simultaneous shared-cash fairness.** Decide owner-approved priority or pro-rata rule, test input-order/rename invariance and cash nonoverspend at identical timestamps.

- [ ] **F017 · P1 · Test risk latch and reserved cash.** Concurrent partial fills, canceled buys and risk triggers never release/reuse quote cash early or allow exposure-increasing orders.

- [ ] **F018 · P1 · Make stale mark effects explicit.** Preserve historical ledger but refuse fresh portfolio decision/risk interpretation if a currently held asset's mark is missing or too old.

- [ ] **F019 · P1 · Match investable portfolio benchmark.** Same eligible symbol universe, dates, cash floor, quote currency and modeled cost assumptions as active shared-cash portfolio.

- [ ] **F020 · P1 · Quantify economic portfolio attribution.** Cash, realized/unrealized inventory, fees, FX, directional market and unexplained residual reconcile; don't present decomposition as causal alpha.

- [ ] **F021 · P1 · Validate portfolio drawdown and exposure.** Exposure includes held and reserved quantities; account equity is one book; returns follow positive-time samples only.

- [ ] **F022 · P1 · Qualify ES/CVaR tail count.** Show total observations, actual adverse-tail count, missing calendar days and bootstrap uncertainty before a tail budget can be trusted.

- [ ] **F023 · P1 · Stress portfolio policy stability.** Covariance singularity, correlation jump, stale FX, volatile small universe, clamped weights and excessive rebalancing cannot create unsupported targets.

- [ ] **F024 · P1 · Verify partial-liquidation risk view.** Compute quote proceeds from dated depth, fee and min-exit eligibility, with residual base and unavailable depth reported separately.

- [ ] **F025 · P2 · Test strategy entry/exit risk interactions.** Limit/remainder, stop-risk sizing, band/rebalance, borrowed assets, unknown fee and stale quotes must not bypass shared allocation.

- [ ] **F026 · OPT · Compare external risk allocation oracles.** Evaluate covariance shrinkage, HRP, HERC, CVaR/CDaR/EVaR under exactly matched samples and real net costs before adoption.

# S. Sampling, calibrated statistics, multiplicity and evidence decisions

- [ ] **S001 · P0 · Publish one observation/return sampling contract.** Timestamp grain, duplicates, strict monotonicity, missing marks and mark-age cutoffs fixed before scoring.

- [ ] **S002 · P0 · Specify economic effect and power.** Register smallest useful net excess return after costs, realistic dependence and enough future observations to discriminate from zero.

- [ ] **S003 · P1 · Verify Lo/HAC Sharpe numerics.** Independent oracle with positive/negative serial dependence, degenerate returns, bandwidth sensitivity and irregular-clock refusal.

- [ ] **S004 · P1 · Audit annualization decisions.** Duration-aware vs fixed-period returns, multi-day gaps, 24/7 vs closed-market sessions and out-of-order marks must not overstate annual Sharpe.

- [ ] **S005 · P1 · Calibrate PSR/DSR/MinTRL.** Skew/kurtosis, multiple tried candidates, effective sample counts and small-sample refusal tested against known examples.

- [ ] **S006 · P1 · Account for cross-asset/date dependence.** Same-date correlated coins and overlapping forward labels cannot inflate independent observation count.

- [ ] **S007 · P1 · Validate block bootstrap sensitivity.** Mean block length, seed, extreme volatility, missing gaps, selected outcome windows and confidence stability are exposed.

- [ ] **S008 · P1 · Provide matched baseline uplift intervals.** Strategy minus investable cash/passive model on identical dates/costs, bootstrapped by defensible paired market-date units.

- [ ] **S009 · P1 · Separate no evidence from evidence of no edge.** Below-threshold, underpowered, stale and unknown-data outcomes have explicit distinct status codes.

- [ ] **S010 · P1 · Validate existing SPA-style scope.** Confirm only 2–8 matched candidates, common bootstrap indices and finite Monte Carlo upper bound; no full-Hansen label.

- [ ] **S011 · P1 · Calibrate SPA-style null rejection.** Correlated candidates, serial dependence, true null, positive control, heavy tails and unbalanced sample refusal.

- [ ] **S012 · OPT · Implement Hansen-consistent SPA.** Define full test family, studentization, consistent/liberal/conservative recentering and external reference calibration before replacing current label.

- [ ] **S013 · OPT · Expand candidate family capacity.** Do so only for a preregistered comparison needing more than eight strategies and with verified memory/simulation budget.

- [ ] **S014 · OPT · Implement true label-purged CPCV.** Split by label information interval, correct embargo and causally trained candidates; verify all known leakage fixtures.

- [ ] **S015 · OPT · Compute PBO/rank-logit diagnostics.** Rank winners on train, evaluate disjoint OOS and report below-median OOS rank with split-dependence limitations.

- [ ] **S016 · OPT · Define sequential e-process null and bound.** Spot/credit/FX return support, actual lower bound and past-measurable bet sizes must be proved before constructing an e-value.

- [ ] **S017 · OPT · Calibrate optional stopping.** Random peeks/stopping, correlated strategies and heavy tails should control false discovery under the declared betting/null contract.

- [ ] **S018 · P1 · Enforce registered selection-family count.** No hidden alternative lookback, threshold, asset subset, cost assumption or journal read omitted from selection adjustment.

- [ ] **S019 · P1 · Audit model fit chronology.** Fit/feature/label timestamps, training window, embargo, seed, hyperparameter count and actual data digests are reproducible.

- [ ] **S020 · P1 · Add negative controls.** Lagged/shuffled factors and non-causal placebos must lose purported predictive ability; otherwise investigate leakage before full replay.

- [ ] **S021 · P2 · Show statistical interpretation in product.** Distinguish descriptive Sharpe, model-family-adjusted exploratory evidence, independently released future result and unsupported inference.

- [ ] **S022 · P1 · Define study refusal conditions.** Inadequate observations, zero variance, stale prices, bad sample duration, mismatched calendar, unknown benchmark or missing costs yield no promotion score.

- [ ] **S023 · P2 · Document method lineage.** Every advanced score links to formula/reference version, sample/denominator, code hash, random seed, assumption gate and tested null cases.

# C. Margin, financing, FX routing and tokenized-asset semantics

- [ ] **C001 · P1 · Define full debt balance identities.** Collateral, quote cash, base holding, borrowed principal, interest, extension fee, repayment and residual claim in exact currency.

- [ ] **C002 · P1 · Version historical margin terms.** Actual loan ratio, account-level bounds, fee period, reopen schedule, collateral maintenance and liquidation threshold need dated source evidence.

- [ ] **C003 · P1 · Model margin event lifecycle.** Origination, additional margin, partial position close, margin call, forced sale, liquidation failure and residual liability are discrete states.

- [ ] **C004 · P1 · Test 4-hour financing and boundary clocks.** No double interest at reopen/time boundary, missing fee data does not mean free credit, and liabilities survive stop/crash.

- [ ] **C005 · P1 · Compare 1x margin long to 1x spot.** Define where fees/loan differ and reconcile the economic ledger on the same prices and exact currency.

- [ ] **C006 · P1 · Test delayed/partial liquidation.** Gaps, no depth, unavailable venue, changing collateral or surviving debt never silently close at the stop threshold.

- [ ] **C007 · P1 · Separate trading credit subaccount from position margin.** Different balance, fee and liquidation semantics use separate workflow and risk accounting.

- [ ] **C008 · P1 · Capture missing public margin ratio where useful.** Date, symbol mapping, source limits and outages; don't claim it gives current account-level borrow eligibility.

- [ ] **C009 · P1 · Maintain known/unknown account credit eligibility.** Read-only observation isn't an authorization to open debt, and private missing fields must not be guessed.

- [ ] **C010 · P1 · Prevent wrong-currency margin aggregation.** Accrued TMN quote debt and USDT collateral are never netted without a dated conversion route.

- [ ] **C011 · P1 · Define executable FX route model.** Direct and bridge legs, fees, bid/ask, depth, size, timestamps and availability; uncertainty propagates to the final amount.

- [ ] **C012 · P1 · Compare FX direction carefully.** Converting TMN to USDT and back uses distinct fees/spreads and available book sides; reject mid-based round-trip profit claims.

- [ ] **C013 · P1 · Evaluate token-specific tradability.** Listing, symbol/contract, market hours, halt/delisting, actual premiums, min order and independent exit depth.

- [ ] **C014 · P1 · Model token corporate actions and tracking.** Reference equity/commodity price, dividend/distribution, split, issuer and currency are explicit proxy limits.

- [ ] **C015 · P1 · Verify passive mix on authentic venue quotes.** Wallex paper journal is separate from 3,591-day stand-in study; show missing and untradeable tokens without backfilling.

- [ ] **C016 · P1 · Define token mix investable benchmark.** Cash/USDT and same eligible token universe with matched fees and time-of-day, not reference ETF returns.

- [ ] **C017 · P2 · Give UX distinct asset/FX labels.** Actual Wallex quote, external market proxy, estimated route, unsellable token, unknown FX and verified venue observation never share one metric.

- [ ] **C018 · OPT · Compare alternate currency/portfolio constructions.** New registration and economic feasibility gate before extra routing, derivatives, shorting or leveraged allocations.

---

# U. Evidence-first product, guided research, accessibility and operator UX

- [ ] **U001 · P1 · Design truthful Overview checkpoint.** Show latest actual feed/forward/independent-evidence/backup/host state and the next honest operator action with dated source.

- [ ] **U002 · P2 · Separate evidence-stage badges.** Synthetic demo, observed public data, paper modeled, exploratory, registered, released future outcome, authenticated account and qualified HOST use distinct copy.

- [ ] **U003 · P2 · Build feed readiness panel.** Actual covered day fraction, last qualified tick, maximum raw gap, rule freshness and per-asset warning counts; no decorative healthy label.

- [ ] **U004 · P2 · Build trial readiness panel.** Family count, registration receipt, sampling criterion, consumed/withheld status, independent custodian and next date.

- [ ] **U005 · P2 · Build journal continuity panel.** Last completed day versus mere process heartbeat, failure/missing-day reason, eligible next day and immutable strategy identity.

- [ ] **U006 · P2 · Build risk/authority headline.** Research-only and protected DISARMED/NOT CERTIFIED shown before any control or preview that might resemble a trade button.

- [ ] **U007 · P2 · Add chronological evidence timeline.** Filter feed gaps, experiment attempts, backup restores, signed receipts and operator safety; each entry has source/time.

- [ ] **U008 · P2 · Show attention/next-action ranking.** Prioritize actual user actions from severity and dependence, not static “green checks.”

- [ ] **U009 · P2 · Build eligible markets watchlist.** Search, pin, sort by recorded exchange/quote, retain keyboard focus/selection on updates and expose data-quality state.

- [ ] **U010 · P2 · Present price, spread and depth with exact units.** Distinguish bid/ask, bps, base size, quote notional, timestamp, source age and stale/unknown status.

- [ ] **U011 · P2 · Show historical rule vintages.** Effective tick/lot/minimum, market-order flag, halt and changed account fee; unknown historical windows are visible.

- [ ] **U012 · P2 · Build quality calendar.** Missing periods, crossed book, source gap and archive availability for each market, not smooth imputed continuity.

- [ ] **U013 · P2 · Build time-of-day liquidity diagnostics.** Time-aligned spread, real touch depth and available prints, with time zone and actual qualifying sample counts.

- [ ] **U014 · P2 · Build size-sensitive order preview.** Realistically partial/not executable vs touch-only, with fee and depth assumption; no order transport.

- [ ] **U015 · P2 · Build direct/bridge FX inspector.** Read-only route, direction, quote amounts, fee/spread, depth, source freshness and unknown crossings.

- [ ] **U016 · P2 · Guide hypothesis registration.** Idea, chosen asset/universe, benchmark, target effect, allowed evidence use and prospective state before launching run.

- [ ] **U017 · P2 · Add data eligibility preflight.** Actual coverage, future-data horizon, venue vintage unknowns, price age and required indicator prehistory before research.

- [ ] **U018 · P2 · Build strategy/cost/risk review.** Explain modeled latency, fee source, queue/fill assumption, inventory model, currency, margin debt and qualified baseline.

- [ ] **U019 · P2 · Bind forms to server action registry.** Field units, valid enum, permissions, output type and side effects must match actual authoritative API handlers.

- [ ] **U020 · P2 · Preserve advanced input mode.** Expert JSON remains possible with bounded schema validation and no arbitrary subprocess, local path or funded authority.

- [ ] **U021 · P2 · Display job lifecycle receipts.** Accepted, running, complete, failed, interrupted, cancel requested and saved output are distinct; stale processes not shown alive.

- [ ] **U022 · P2 · Build filterable saved-run catalog.** Asset, strategy, date, model version, cost, evidence stage, benchmark, data gaps, saved identity and status.

- [ ] **U023 · P2 · Build synchronized decision explorer.** Recorded quote, bar, signal, account balances, modeled order, fee, no-fill and later mark on one causal time axis.

- [ ] **U024 · P2 · Explain why a decision was rejected.** Warmup, missing volume/reference, stale quote, unknown fee, lot/minimum, pending order and risk constraint.

- [ ] **U025 · P2 · Build Run Cost Lab.** Compare paired cost/depth/latency scenarios, turnover, equity, failed exits and uncertainty without confusing them with registered hypotheses.

- [ ] **U026 · P2 · Add maker-order timeline.** Queue activation, ahead quantity, qualifying observed prints, potential duplicate capacity, cancellation and partial fill.

- [ ] **U027 · P2 · Build portfolio holdings timeline.** Owned base, sellable under modeled minimum, exit_check, dust, reserved cash, working orders and risk latch.

- [ ] **U028 · P2 · Explain portfolio valuation bases.** Mark-to-bid, net-after-modeled fee, size/depth-limited liquidation and actual booked cash must remain distinguishable.

- [ ] **U029 · P2 · Display margin debt explicitly.** Collateral, borrowed currency, fee periods, missed liquidations, liabilities and read-only account eligibility.

- [ ] **U030 · P2 · Make evidence governance inspectable.** What has been selected/released/consumed and who verified it, including all failed attempts and limitations.

- [ ] **U031 · P2 · Make backup scope understandable.** Inventory complete vs sampled decrypt vs full local restore vs actual independent copy; show the owner exception.

- [ ] **U032 · P2 · Keep offline ticket review separate from money.** Three-stage intent/evidence/preview, explicit acknowledgment and blocked reason with no implicit executor arm.

- [ ] **U033 · P2 · Add every dynamic English/Persian string.** Stable semantic keys, plural/count interpolation parity and complete errors/missing-data labels.

- [ ] **U034 · P2 · Preserve RTL number/time semantics.** Tick size, negative P&L, currency, symbol ticker, scientific notation and ISO/Tehran clock do not reverse in Persian.

- [ ] **U035 · P2 · Make charts keyboard and screen-reader usable.** Semantic headings, accessible tables, focus order, text alternatives, contrast and reduced-motion updates.

- [ ] **U036 · P2 · Test desktop/mobile/light/dark combinations.** Windows Edge/Linux Chrome, narrow screens, keyboard-only form submission, live refresh and EN/FA switching without state loss.

- [ ] **U037 · P2 · Measure UI render and update cost.** On hundreds of markets, track DOM churn, focus stability, CPU/memory, route payload and time-to-usefulness before framework changes.

# O. Backups, operational diagnostics, local API and accepted-risk controls

- [ ] **O001 · P0 · Verify latest actual backup/restore state.** On the operator data root confirm destination, last valid backup, trusted manifest receipt, last full restore, source segments and actual recovery age.

- [ ] **O002 · P0 · Keep the owner cancellation decision visible.** Do not auto-enable off-machine schedules; show that loss since last manually copied backup is accepted and unprotected.

- [ ] **O003 · P1 · Test the current full local restore.** Restore a pinned older snapshot to an isolated empty root, run SQLite integrity/doctor and verify frozen artifacts while all privileged paths remain DISARMED.

- [ ] **O004 · P1 · Test sampled vs full integrity labels.** Segment inventory COMPLETE, SAMPLED_DRILL and FULL_RESTORE can be combined without claiming cross-host survival.

- [ ] **O005 · P1 · Test missing closed segment refusal.** Absent archive object, digest mismatch or invalid container header yields INCOMPLETE/ERROR with exact segment ID.

- [ ] **O006 · P1 · Test open segment cutoff.** A raw segment closed after SQLite snapshot is excluded from older cut; it appears only in the correct later snapshot.

- [ ] **O007 · P1 · Test pinned historical manifest selection.** Correct retained ID+digest works; stale/modified/invalid expected digest or deleted cut fails closed.

- [ ] **O008 · P1 · Test encrypted container version compatibility.** Legacy v1 decryptable, v2 validated fields/KDF, malformed compression/cipher/nonce/size refused without corrupt output.

- [ ] **O009 · P1 · Test nested SQLite WAL backup.** Writers active during copy do not silently lose committed rows or append-only triggers.

- [ ] **O010 · P1 · Test archive/link/tar traversal.** Untrusted filenames, symlinks, wrong device and raw archive references cannot escape the bounded restore root.

- [ ] **O011 · P1 · Test disk-full and interrupted restore.** Incomplete outputs are non-authoritative, old valid snapshot remains, and status files never claim success prematurely.

- [ ] **O012 · P2 · Measure storage runway.** Live DB/WAL, raw segments, archives, temp export, backup rotation and scheduled growth with emergency thresholds.

- [ ] **O013 · P2 · Audit backup receipt chronology.** Show actual oldest/newest copy, changed validation status and unverifiable off-host age as UNKNOWN rather than zero.

- [ ] **O014 · OPT · Reconsider independent backup policy only with approval.** A new owner choice specifies external destination, credential escrow, encryption, retention, RPO/RTO and cross-host drill; no silent opt-in.

- [ ] **O015 · P1 · Review current loopback route matrix.** Public local paper records are intentional; test exact Host, Origin, method, token, CSRF and DNS-rebinding constraints before changing policy.

- [ ] **O016 · P1 · Verify private account isolation.** Browser tokens, per-run session credentials, exported HTML/CSV, logs and errors contain no authenticated account secrets.

- [ ] **O017 · P1 · Confirm API has no implicit order authority.** Fixed allowlisted paper actions cannot run subprocesses, call native arm/send or supply arbitrary filesystem paths.

- [ ] **O018 · P1 · Test query and input bounds.** Large saved-run reads, malformed decimals, duplicate jobs, client disconnect and cancel requests must not starve collector or half-mutate research.

- [ ] **O019 · P2 · Make CLI installed layout portable.** Wheel/resource paths, UTF-8, command aliases, explicit data root and safe path/exit codes work outside an editable checkout.

- [ ] **O020 · P2 · Audit CSV/spreadsheet export safety.** Preserve exact values and labels while preventing formula injection, unsafe filenames and misleading default currency.

- [ ] **O021 · P2 · Publish 24h reliability scorecard.** Feed last qualified observation, per-symbol gaps, jobs, backup age, disk runway and operational error timeline.

- [ ] **O022 · P2 · Add escalation on severity/duration.** A gap increasing in age, affected markets or data loss triggers a new actionable alert despite unchanged status string.

- [ ] **O023 · P1 · Define incident safe behavior.** Full disk, corrupt archive, suspect account, unknown order, stale venue and failed checkpoint all stop unsafe claims/authority.

- [ ] **O024 · P2 · Document operator recovery runbook.** Concrete local commands, expected receipts, backup-policy limitation, manual restoration and DISARMED post-restore state.

---

# H. Protected Rust/Windows execution acceptance — separate future HOST lane

**All H tasks require a future funded-path authorization decision.** The existing in-source LIMIT transport and source fault tests do **not** mean the installed Windows system can trade. Keep the service DISARMED; no public API, UI, Python model or AI workflow receives funded submission authority. An explicit owner checkpoint and independent installed-host/venue reviewer are required.

- [ ] **H001 · HOST · Freeze the funded qualification contract.** Bind 2027-02-08 owner go/no-go, exact Windows build, service principal, venue capability, loss budget and explicit excluded order types.

- [ ] **H002 · HOST · Verify installed signed bundle identity.** Match SHA, manifest and signer to reviewed source for service/helper/scripts; do not use development binaries.

- [ ] **H003 · HOST · Qualify update trust pinning.** Missing/rotated signing key, modified manifest, downgraded helper and interrupted update must fail closed and leave service disarmed.

- [ ] **H004 · HOST · Verify real service SID and Windows identity.** Test LocalService/T2 and operator logon SID as installed, not temporary runner identities.

- [ ] **H005 · HOST · Verify DPAPI and vault ACL.** Service-owned trade keys stay out of Python/UI, browser, logs and wrong-user profile after service restart.

- [ ] **H006 · HOST · Verify named-pipe authorization.** T0 STOP-only and privileged review channel ACLs reject nonowners, other logon SIDs and sandboxed client tokens.

- [ ] **H007 · HOST · Benchmark independent STOP.** Deliberately hung network worker, failed UI, rate pressure and crashed observer cannot block the protected STOP acknowledgment contract.

- [ ] **H008 · HOST · Check WinHTTP/vault lock separation.** Network send and slow response never retain secret-vault mutex across an unbounded interval; disarm/send ordering remains sound.

- [ ] **H009 · HOST · Establish send/STOP linearization.** Define exact first-byte boundary: STOP before admission forbids send; after ambiguous delivery forces durable unknown and reconciliation.

- [ ] **H010 · HOST · Reject old-revision sends.** Disarm and later re-arm cannot transmit a plan authorized under the earlier arm/policy revision.

- [ ] **H011 · HOST · Validate approval/intent consumption.** Native operator intent, spend ceiling, order fields, one-shot token and review v2 receipt are consistent and impossible to duplicate.

- [ ] **H012 · HOST · Verify price/lot/size admission.** Actual venue symbol, tick, minimum, latest two balance observations and conservative held cash gate orders without relying on a stale UI preview.

- [ ] **H013 · HOST · Audit reservation accounting across overlapping holds.** A terminal order never frees another still-working order's locked funds or debt.

- [ ] **H014 · HOST · Test two simultaneous order interleavings.** Overlapping quotes, partials, late fees, changed balance snapshot, out-of-order observation and cancel must conserve available balance.

- [ ] **H015 · HOST · Retain conservative one-open-order limit until proof.** If actual multi-order settlement cannot be reconciled, retain/reinstate a hard bounded concurrency policy.

- [ ] **H016 · HOST · Qualify authenticated venue read pages.** Actual account balance, locked/available, orders/open/history, fees, account scope, pagination and source age.

- [ ] **H017 · HOST · Persist unknown delivery correctly.** Timeout after request's first byte is an uncertain venue state, not automatically a failed order; retain holds.

- [ ] **H018 · HOST · Prove safe retry/idempotency.** Venue client/order IDs and GET history reconcile ambiguous sends without duplicate funded orders.

- [ ] **H019 · HOST · Specify actual native cancellation transport.** Request→acknowledgment→unknown→late fill→terminal states with durable account/fee reconciliation.

- [ ] **H020 · HOST · Test cancel-vs-fill races.** A fill during cancellation affects inventory/reservations and cannot vanish after a successful cancel acknowledgment.

- [ ] **H021 · HOST · Specify ExitOnly authority.** Exposure-reducing orders must be separately scoped, bounded by actual held inventory and protected from accidental new exposure.

- [ ] **H022 · HOST · Design finite protective execution.** Stop/profit/time exit attempts with partial/no-fill, market halt and irreducible exposure states; no promise of guaranteed stop fill.

- [ ] **H023 · HOST · Fault-inject every crash transition.** Before intent, after durable reservation, before/after first byte, during partial fill, during cancellation and after receipt but before settlement.

- [ ] **H024 · HOST · Verify startup conservative replay.** Signed ledger/anchor chain, interrupted journal, unknown remote order and stale credential always restart disarmed/unresolved until proven.

- [ ] **H025 · HOST · Rehearse torn multi-store commitments.** A service/credential journal and executor ledger cannot infer coherent settlement across independently failed writes.

- [ ] **H026 · HOST · Qualify vault snapshot/retention recovery.** Secure pruning, signed anchors, key rotation and cold restored artifacts preserve all uncertain financially material order states.

- [ ] **H027 · HOST · Validate actual Windows SCM/service recovery.** Upgrade, user logout, service restart, crash, network outage and machine reboot never auto-arm or bypass STOP.

- [ ] **H028 · HOST · Verify a permitted real read-only/manual order lifecycle.** Use a separately authorized non-withdrawal key and an externally placed manual order only if the owner and account rules permit; never test a funded POST as an unapproved diagnostic.

- [ ] **H029 · HOST · Publish installed-host qualification bundle.** Date, Windows build, machine/service identity, exact binary hashes, negative authorization tests, authenticated Wallex receipts, known skips, reviewer and owner approval.

# I. Engineering, measured performance, optional architecture and source hygiene

- [ ] **I001 · P1 · Pin representative performance baselines.** Real workload, hardware/OS, market count, rows, query/replay duration, disk, CPU, event-loop lag and memory with cold/warm distinction.

- [ ] **I002 · P1 · Benchmark raw/SQL publication pressure.** Long-running collector with rollover hashing, WAL checkpoint, DB reads, reconnect and full disk; protect archival correctness.

- [ ] **I003 · P1 · Profile limit settlement queries.** Count repeated trade scans per order, identical timestamp ties and first/last event cursor; identify real growth bottlenecks.

- [ ] **I004 · P2 · Add incremental limit scan only if faster.** Preserve exact late-print semantics, same-time ordering, queue state and versioned replay parity.

- [ ] **I005 · P2 · Profile portfolio compute.** Isolate redundant optimizer/covariance/counterfactual calculations, checkpoint costs and memory at realistic 500-market bounds.

- [ ] **I006 · OPT · Prototype a bounded single writer.** Durable ordered messages, one SQLite/raw owner, backpressure and watermark, only if loop-lag measurements demand it.

- [ ] **I007 · OPT · Prove writer crash and overload safety.** Bounded queue, fatal worker, disk full, WAL lock, partial batch and restart preserve raw↔SQL correspondence.

- [ ] **I008 · OPT · Evaluate Parquet/Arrow/DuckDB cold catalog.** Existing real multi-year scan/query benchmark first; keep raw and canonical SQL/receipt truth unchanged.

- [ ] **I009 · OPT · Test exact cold-catalog types.** Decimal scale/range, UTC event/availability, source digest, closed partition and SQLite tail stitching preserve replay order.

- [ ] **I010 · OPT · Check partition crash/re-export parity.** Failed export or missing file cannot return an apparently complete model, and repair is idempotent.

- [ ] **I011 · OPT · Evaluate multi-database consolidation.** Only after measured contention/backup gain and a migration plan with independent executor ledger untouched.

- [ ] **I012 · P1 · Rehearse large-store schema upgrade.** Online snapshot, temp disk runway, WAL consistency, old reader, wrong future schema, interrupted index and full rollback.

- [ ] **I013 · P2 · Measure backend API read contention.** Slow sqlite/file results or client disconnect cannot starve collector heartbeat; offload bounded snapshots only if measured.

- [ ] **I014 · P2 · Measure full-market frontend churn.** Stable sort/focus, render interval, long watchlist memory and keyboard interaction, before adopting a framework.

- [ ] **I015 · OPT · Phase native ES module cleanup.** A small owner view first, preserve CSP/deep links/local privacy/EN-FA, and prove improved import coupling or measured loading.

- [ ] **I016 · P1 · Strengthen financial/custody mutation fixtures.** Target source-causal timestamps, exact money, risk latches, holdout refusal and protected state transitions with dated mutation receipts.

- [ ] **I017 · P1 · Keep CI qualification labels honest.** Full Python/Rust/Windows/API/UI, SBOM and secret audit recorded; skipped HOST suites remain NOT QUALIFIED.

- [ ] **I018 · P2 · Classify scripts before deletion.** Operational tool, current registered study, immutable historical negative reproducer, or verified unused; check scheduled and documented callers.

- [ ] **I019 · P2 · Verify docs/action drift.** CLI help, README, API action registry, capability claims, forward dates, source schemas and expected exceptions agree on current master.

- [ ] **I020 · P2 · Review licensing and supply chain.** Root redistribution license, binary/data provenance, dependency lockfiles, signed release, third-party notices and CVE/secret scanning.

- [ ] **I021 · P2 · Maintain safe complexity ownership.** Characterization tests before splitting huge Python/Rust/frontend modules; preserve old wire/checkpoint adapters and actual authority semantics.

# R. Conditional research and peer-system task menu

**Every R task is a hypothesis/technology option, not a proven missing correctness feature.** Choose no more than the available registered trial capacity. Document a decisive benchmark or experimental pass/fail rule *before* implementing, and archive rejected ideas.

- [ ] **R001 · OPT · Continuous multi-horizon EWMAC prototype.** Causal 16/64, 32/128, 64/256 forecasts; externally motivated scalars are starting hypotheses, not fitted future information.

- [ ] **R002 · OPT · Volatility targeting and forecast diversification.** Prior-only variance, zero-vol abstention, risk caps and cost-of-speed gate, compared with an investable cash baseline.

- [ ] **R003 · OPT · Edge-of-band rebalancing.** No action within band, trade only to nearer edge outside band, exact min lots/dust and full fee/turnover reporting.

- [ ] **R004 · OPT · Factor-level IC/Rank-IC laboratory.** Forward label horizons, overlapping-label purge, per-date cross-sectional dependence, calibration and negative controls before full execution.

- [ ] **R005 · OPT · New maker USDTTMN imbalance trial.** Register 1bp spread market context, queue activation, conservative cancellations, clip size and genuine postfill markout; no assumed maker edge.

- [ ] **R006 · OPT · Time-of-day execution hypothesis.** Test Tehran-hour spread/depth/receipt coverage against same-day matched fillable size and fees.

- [ ] **R007 · OPT · Slow trend prospective comparison.** BTC and breadth model can only use future unseen days; no new optimization on already consumed 2024–26 windows.

- [ ] **R008 · OPT · Token passive-mix robustness.** Actual Wallex token premium, spread, opening hours, missing listings and size-aware rebalance against same-currency cash/hold.

- [ ] **R009 · OPT · Funding/carry alternative.** Genuine new funding days and loan terms, bounded short exposure, financing and liquidation; distinct from failed old short-trend family.

- [ ] **R010 · OPT · Compare LEAN/Nautilus/hftbacktest contracts.** Differential fee/fill, event/queue and latency oracles on fixed Wallex data; no replacement of custody.

- [ ] **R011 · OPT · Compare pysystemtrade/Hummingbot patterns.** Causal EWMAC and finite maker controller design only under clear safe paper boundaries.

- [ ] **R012 · OPT · Compare Qlib/Freqtrade/Zipline/vectorbt diagnostics.** Use feature lineage, lookahead bias, historical universe and exploratory screening with license review, not automatic source port.

- [ ] **R013 · OPT · Compare PyPortfolioOpt/skfolio/Riskfolio-Lib.** Risk-tail and covariance/cluster oracles on fixed samples with measured net decision improvement; reject otherwise.

---

# Suggested execution bundles

These are groupings of **existing tasks**, not extra work. They give the lead engineer a way to create manageable issues without losing the baseline's cross-cutting contracts.

| Bundle | Task IDs | Independent outcome |
| - | - | - |
| **Baseline and current source acceptance** | G001–G012, I017 | Current exact SHA and CI/host claims reconciled; no reintroduced finished issue |
| **Independent evidence and forward continuity** | E001–E022, S018–S019 | Future study has custody, complete attempts, verified journal readiness and no outcome leakage |
| **Market and economic qualification** | M001–M022, X001–X022 | Source/provenance/fee/queue/latency coverage and honest executable-net refusal |
| **Money and portfolio financial truth** | F001–F025, C001–C017 | Posting equivalence, shared cash/risk, debt/FX/token meaning and actual eligibility |
| **Statistical credibility** | S001–S023 | Calibrated dependence and candidate-selection diagnostics, power and clearly labeled limits |
| **Evidence-first product** | U001–U037 | Guided screens, valid state copy, EN/FA, RTL, accessible real workflows |
| **Recovery and local security** | O001–O024 | Honest policy exception, full local recovery, bounded private/public API and actual reliability |
| **Measured architecture and maintenance** | I001–I021 | Baselines and safe rollback before any optional database or frontend rewrite |
| **Future protected HOST qualification** | H001–H029 | Only with owner approval: installed signed host, authenticated reads, finite order lifecycle and conservative recovery |
| **Optional scientific/peer investigations** | R001–R013 | Newly registered measurable hypotheses and explicit adoption/non-adoption decisions |

## Recommended first sprint — 12 concrete IDs

**G002, G006, G007, G009, E001, E003, E011, E012, E013, M001, F002, O003.**

This is a **recommendation**, not a claim each action is unfinished in the actual private installation. It prioritizes one pinned engineering baseline, independent science, forward day continuity, feed qualification, ledger proof and recovery truth. Keep optional library, storage and funded work outside the critical path.

## Standard implementation issue template

**ID and source:** Stable task ID; current code ref; related roadmap requirement; technical/risk owner; P0/P1/P2/OPT/HOST class.

**Evidence before:** Exact reproducer or reason a new feature is needed, observed data and machine state, source identifiers, relevant current tests, distinction between missing proof and failing behavior.

**Contract:** Input/output schema, units/currency/clock, allowed caller, persisted model identity, possible error/unknown states, actor/privilege separation and old-run semantics.

**Tests and acceptance:** Gold fixture and specific positive/negative/boundary tests; property/metamorphic/reference oracle where relevant; commands and actual outputs; dates, seeds, observed counts and explicit skipped scenarios. For inference record the null and power; for performance record baseline; for HOST use actual host.

**Risk and recovery:** Historical-run compatibility, run IDs, database schema, signed evidence, migration size, interrupted-write behavior, restore/rollback, disarmed startup and user-visible copy.

**Close:** Accepted/declined/deferred and rationale; reviewer/date; evidence links. Code compile and green CI alone do not satisfy genuine independent custody, funded-host qualification or off-machine disaster recovery.

**Final rule:** Do not turn paper research success, a completed checklist line or a future calendar date into funded authority. Any unqualified empirical result stays explicitly unqualified.
