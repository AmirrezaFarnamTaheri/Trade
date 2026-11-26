# Design Specification: Uncorrelated Multi-Timeframe Strategy Ensemble & Calibrated ML Meta-Gateway (v2 — Review Integrated)

**Date:** 2026-11-24 · **Baseline Commit:** `c2eec08` · **Status:** Approved Revision Integrating [ensemble-gateway-design-review.md](ensemble-gateway-design-review.md)

**Hard Authority Boundary:** `TradingGYMExecutor` remains **`DISARMED / NOT CERTIFIED`** with **`$0` funded-loss budget**. This specification governs paper research, engine repairs, and reproducible evaluation only. Margin, shorts, derivatives, cross-venue real-inventory transfers, funded probes, and automatic arming are explicitly outside scope ([PRODUCT.md](../../PRODUCT.md)).

---

## 1. Prerequisites: Engine, Accounting & Bottleneck Repairs (Must Land Before Any Model Race)

No gateway comparison is valid until the five verified codebase defects and five measured performance bottlenecks are repaired and independently checked:

1. **Constrained Convex Solver Repair ([convex_optimizer.py](../../gym-core/src/gym/domain/convex_optimizer.py)):**
   - Replace single-coordinate descent under a binding budget hyperplane ($\sum w_i = M$) with a **FISTA / projected proximal-gradient solver with exact Euclidean simplex/box/group projection (Dykstra / dual bisection)** + true primal-dual KKT optimality residual.
   - Verify exact objective and feasibility agreement (`tol <= 1e-6`) against `scipy.optimize.minimize` (SLSQP / trust-constr) across binding-budget, asset-order permutation, fee-zone boundary, frozen-inventory, and infeasible-starting-holding fixtures.
   - Re-verify the exact diagnostic counterexample (`w0=(0.5, 0.5), mu=(0.02, 0.06), cov=diag(0.01, 0.01), ra=1, tau=0.001, max_w=1, cash_buf=0`) reaches `(0.0, 1.0)` with objective `0.0540` (not stuck at `(0.5, 0.5)` / `0.0375`).
2. **Explicit Covariance Axis Alignment & Timestamp-Joined Returns ([async_covariance.py](../../gym-core/src/gym/domain/async_covariance.py), [evaluate_candidates.py](../../gym-core/scripts/evaluate_candidates.py)):**
   - Add `align_covariance_to_symbols(symbols, cov_symbols, cov_matrix)` and timestamp-joined return pairing (`coarse_bar_shrunk_covariance_aligned(dated_returns_by_symbol)`), guaranteeing identical target weights under any input symbol permutation (fixing the `XRPUSDT`/`XAUTUSDT` axis swap).
3. **End-to-End Causality Perturbation & Self-Financing Portfolio Ledger ([instant_gate_check.py](../../gym-core/scripts/instant_gate_check.py)):**
   - Fix the broken EWMAC lambda bug (stateful single-instance pass) and enforce **full future-input perturbation** across all symbols, features, and quotes after cutoff `t_c`, asserting byte-equivalent earlier eligibility, forecasts, intents, fills, and NAV alongside a mandatory positive-control future-peeking feature that MUST fail.
   - Track actual drifting portfolio holdings, cash, reservations, and received-asset fees at event times (never carrying target weights forward without price drift or crediting close-to-close returns across an unexecuted open gap).
4. **VPIN Arithmetic Batching & Strict Side Validation ([microstructure.py](../../gym-core/src/gym/domain/microstructure.py)):**
   - Replace unit-by-unit `while rem > 0:` bucket loop with exact arithmetic `divmod` batching for complete same-side buckets (eliminating the `417M`-iteration PEPE print hang), validate canonical `"BUY"` / `"SELL"` aggressor strictly (raising or counting `"UNKNOWN"` separately, never defaulting to `"SELL"`), and support quote/asset-scaled bucket sizing.
5. **Measured Performance Repairs (§11 of Review):**
   - Keyed `instrument_id` candle query (`WHERE instrument_id=? AND resolution=?`) + shared immutable trailing-window risk cache (`~11.5×` speedup).
   - `set`-backed test-index membership in `purged_cpcv_splits` ([statistical_inference.py](../../gym-core/src/gym/domain/statistical_inference.py), `~8×` speedup).
   - `bisect` availability-time indexing in `simulate_passive_orders` ([passive_execution.py](../../gym-core/src/gym/domain/passive_execution.py), `~6×` speedup) with exact parity verification on fill records and shared print capacity.

---

## 2. Data Provenance, Bar Parity & Eligibility Contract (`timeframe_panel.py`)

Directly reflecting the database audit (`20` named USDT pairs: `BTC` hourly from `2023-01-01`, 17 pairs from `2025-01-01`, `SUI` from `2025-08-19`, `ZEC` from `2025-10-01`, all hourly ending `2026-11-17`; `AAVEUSDT` had `9,458/16,389` zero-volume flat hours and `185/321` days with native `1d` vs `00:00` `1h` open disagreement up to `917.43 bps`):

- **Separate Eligibility & Provenance Fields:** Every symbol-bar emits:
  1. `clock_complete: bool` (100% constituent sub-bars present for resampled `2h`/`6h`/`12h`),
  2. `nonzero_volume_fraction: float` and `last_actual_trade_age_bars: int`,
  3. `bar_source: str` (`"NATIVE_1D"` vs `"RESAMPLED_1H"`),
  4. `entry_eligible: bool` (requires `clock_complete`, positive volume on signal bar and execution bar, warmup complete, and active listing),
  5. `mark_status: str` (`"FRESH"` vs `"STALE_MARK"` — stale bars preserve inventory valuation with disclosed haircut/uncertainty while strictly **suppressing fresh entry fills**).
- **Declared Source Convention & Sensitivity:** Predeclare `"NATIVE_1D"` as the primary source for the First Experiment slow daily panel and run a mandatory paired sensitivity report against `"RESAMPLED_1H"` on common complete dates (`2025-01-01..2026-11-17`). A reversal of the research verdict between sources is classified `INCONCLUSIVE / UNRESOLVED_PRICE_PROVENANCE`.
- **Retrospective Cohort Labeling:** Where historical Wallex catalogue snapshots cannot establish point-in-time listing membership, label the estimand explicitly as performance on the named retrospective cohort rather than claiming survivorship-free universe selection.

---

## 3. Scoped Delivery Order (First Experiment vs. Independent Follow-On Studies)

### 3.1 First Paper Experiment (Veto-Only Logistic Challenger on Slow Wallex Spot Sleeves)
**Primary Question:** *For the exact same eligible Wallex spot entry proposals, opening holdings, position-sizing rule, and execution cost model, does a frozen, chronologically sigmoid-calibrated `L2 LogisticRegression` veto improve ending USDT liquidation wealth per unit of equal starting capital over the fixed rule at the declared risk budget?*

- **Universe & Account:** Single self-financing Wallex spot long/flat account in `USDT` (reporting executable `TMN` dual-numeraire translation separately), curated liquid USDT cohort with dynamic listing & warmup eligibility (`XAUTUSDT` enters strictly after `2024-08-06` + warmup; `USDT` cash is the defensive action before gold eligibility).
- **Slow Sleeves Supported by Multi-Year Daily History:**
  - **S1 — Time-Series Trend (`1d`):** Multi-horizon EWMAC (`8/32`, `16/64`, `32/128`), explicit `128`-bar warmup mask, normalized to `[-1, +1]`.
  - **S2 — Cross-Sectional Residual Momentum (`1d`):** Rolling 30-day BTC-beta-neutral residual return ($r_i - \hat{\beta}_{i,\text{BTC}} r_{\text{BTC}}$) computed strictly on active eligible crypto symbols (excluding cash and gold from crypto breadth/ranking, deterministic tie-breaking, minimum active cross-section `>= 4`).
  - **S5 — Defensive Gold / Cash Regime Rotation (`1d`):** Portfolio-wide defensive signal rotating into `XAUTUSDT` (when eligible) and `USDT` cash when crypto breadth `< 0.35` or downside GJR-EWMA vol is in its trailing top decile.
- **Zero Fee Double-Charging (Gross Forecast + Incremental Cost Separation):**
  - The allocator receives conditional **gross** horizon expected returns $\hat{\mu}^{\text{gross}}_{i,t}$ (decimal units, explicitly stamped with horizon & numeraire) and applies incremental L1 execution costs **once** only on actual inventory changes $|w_i - w_i^0|$ (zero cost on unchanged holdings; single joint portfolio sizing rule via the repaired convex solver).
- **Arms Compared on Identical Eligible Timestamps, Starting Wealth & Ledger:**
  1. `CASH_USDT`: 100% `USDT` cash control.
  2. `STATIC_GOLD_AND_CRYPTO`: Passive equal-weight buy-and-hold + static gold/crypto benchmark on common dates.
  3. `FIXED_S1`: Prespecified slow trend baseline (Candidate B recomputed on the repaired self-financing ledger).
  4. `FIXED_ENSEMBLE_S1_S2_S5`: Equal-risk fixed combination of slow sleeves `S1 + S2 + S5` (plus leave-one-sleeve-out marginal contribution, BTC/gold beta attribution, and preservation of negative correlation — never pruning a sleeve solely for negative correlation!).
  5. `ADAPTIVE_VOTE`: Online decayed-Sharpe voting control with explicit normalized capped weights and sparse-coverage abstention remainder.
  6. `LOGISTIC_VETO`: **Veto-only** `L2 LogisticRegression` (`Pipeline([SimpleImputer, RobustScaler, LogisticRegression])`, chronological sigmoid calibration on inner purged validation folds) accepting or rejecting proposals from the identical `FIXED_ENSEMBLE_S1_S2_S5` stream.
     - **Expected-Value Gating (No Fixed `52%` Floor):** Accept proposal iff $\hat{p}_{i,t} \cdot \hat{W}_{\text{train}} - (1 - \hat{p}_{i,t}) \cdot \hat{L}_{\text{train}} > c_{\text{incremental}} + \text{margin}$, where $\hat{W}_{\text{train}}, \hat{L}_{\text{train}}$ are training-fold conditional win/loss magnitudes.
     - **Shadow Scoring of Rejected Proposals:** Every vetoed proposal is scored in shadow on the identical ledger to report avoided losses, foregone winners, and net uplift over the common candidate stream.

### 3.2 Independent Follow-On Attribution Studies (Gated Behind First Experiment)
Each addition below is built and scored strictly as a **separate attribution experiment** after the First Experiment completes:
- **Fast Sleeves (`S3` Panic Reversion `2h/6h`, `S4` Vol-Compression Breakout `6h/12h`):**
  - `S3` enforces strict **no-averaging-down / no-martingale** episode identity (`PRODUCT.md`): one entry from flat per episode, hard `-2.5 * sigma` stop, `36h` max hold matching a `36h` label horizon, cooldown before re-entry, and explicit cross-sleeve add-on cap when `S1` and `S3` target the same underlying.
  - `S4` compares close strictly against the *previous* 20 highs (`high[t-20:t]`) and computes pre-breakout compression strictly prior to release, plus UTC bucket-offset sensitivity (`+1h` shift test).
- **Nonlinear Model Challenger (`HistGradientBoostingClassifier`):** Admitted only if `LOGISTIC_VETO` reveals repeatable residual structure across development folds; uses explicit purged chronological early stopping or fixed iteration budget (never default random internal validation).
- **`S6` (`30m` Execution & Toxicity Overlay):** Strictly excluded from multi-year historical alpha features, voting denominators, and sleeve correlations; shadow-scored on identical accepted directional intents on live/recent data measuring paired shortfall saved per **intended** unit.
- **Venue Separation (Wallex vs. Nobitex):** Always reported as three explicitly labeled streams: (a) **Wallex-native replay**, (b) **Wallex paths under hypothetical Nobitex `-30%` fee counterfactual**, and (c) **Nobitex-native execution evidence** (once multi-venue recorder builds sufficient native coverage).

---

## 4. Evidence Classification, Synthetic Falsification & Statistical Protocol

1. **Contaminated Bear Year Reclassification:**
   - **`2025-11-24 .. 2026-11-23`** is permanently classified as **`BEAR_STRESS_REPLAY_SEEN`** (previously inspected during Candidate B evaluation). It is reported transparently as a stress replay and **never** counted as an untouched final holdout.
   - Outer evaluation uses **past-only expanding chronological walk-forward** with whole-UTC-date splits and wall-clock span purging `[t_entry, t_exit]` + embargo (`H` bars). Independent final confirmation requires either an untouched historical block certified by `holdout_ledger.py` or a pre-registered forward paper journal with a predeclared minimum independent active-block count.
2. **Two Mandatory Pre-Race Synthetic Falsification Tests:**
   - **Synthetic Null Panel:** Common market shocks + realistic missingness + **zero conditional edge** → verify the full selector/gateway rejects noise (false-promotion rate calibrated).
   - **Synthetic Planted-Edge Panel:** Identical panel + planted feasible net edge of known sign/magnitude → verify the selector recovers the planted effect after costs.
3. **Primary Economic Endpoint & Calibration Diagnostics:**
   - **Primary Metric:** Paired difference in ending USDT liquidation wealth per unit of equal starting capital (with open/unpriceable inventory bounded), plus aligned daily NAV paired differences with **stationary/contiguous date-block bootstrap** 95% CIs, active-risk/exposure-matched comparison, drawdown duration, expected shortfall, and turnover.
   - **Calibration Metrics:** Training-only base-rate **Brier Skill Score (`BSS`)**, log loss, reliability slope/intercept, and calibration specifically near the trade decision threshold.
   - **Multiplicity & PBO/Placebo Precision:** Log every selectable fit, threshold, pruning pass, and abandoned attempt in the trial ledger (`N_total` reconciled against `21` inherited records); compute empirical `skew` and `kurt` in DSR; report exact PBO split counts/ties (recognizing 15-split discreteness: `6/15 = 0.400`, `7/15 = 0.467`) and Monte Carlo SE on `500`-run portfolio placebos shifting the joint intent stream across eligible regimes.
4. **Four Valid Verdicts:**
   - `INVALID_RUN`: Any causal, unit, price-source, covariance-axis, or ledger invariant fails → quarantine and fix.
   - `INCONCLUSIVE`: Paired CI spans zero or bar-source/execution bounds reverse the winner.
   - `RETIRE_INCREMENT`: Adequate evidence rejects economically useful uplift or breaches risk budget → retain simplest qualified comparator (including `CASH_USDT`).
   - `ADVANCE_TO_INDEPENDENT_EVAL`: Clears all development criteria, synthetic falsifications, stress replay, and ledger reconciliation → freeze for independent custody/prospective evaluation.
