# Design Specification: Uncorrelated Multi-Timeframe Strategy Ensemble & Calibrated ML Meta-Gateway

**Date:** 2026-11-24 · **Baseline Commit:** `25df193` · **Status:** Draft Design for External Review (GPT Astra) & Owner Sign-Off

**Hard Authority Boundary:** `TradingGYMExecutor` remains **`DISARMED / NOT CERTIFIED`** with **`$0` funded-loss budget**. This specification governs research, paper simulation, and instant zero-wait gate verification only.

---

## 1. Problem Statement & Verified Data Foundation

### 1.1 Why Prior Single-Strategy Tests Failed `G2-Instant`
Our mirage-proof verification harness ([instant-gate-report.md](../../../evidence/instant-gate-report.md), commit `25df193`) established three hard empirical facts on real Wallex data:
1. **Single-family intraday rules die on Wallex fees:** Hourly `ema-trend 8/21` lost in 320/337 markets; blind `0 bps`-offset passive quoting lost on 6/6 USDT pairs; causal next-bar hourly 6-triangle FX basis lost `-54,773 bps` on Wallex and `-27,513 bps` on Nobitex after fees.
2. **Single-family long-only crypto allocation lacks bear-market return streams:** Our horizon-matched Convex L1 allocator (`Candidate B`) protected capital well during the 2025–2026 crypto bear market (`-2.19%` vs. Buy & Hold `-47.29%`, 4-year `MaxDD 19.45%` vs. `64.09%`), **but** long-only trend alone could not clear `DSR >= 0.95` across `N = 21` trials (`DSR = 0.367` full, `CPCV PBO = 0.533`).
3. **Portfolio math demands genuinely uncorrelated sleeves + calibrated bet sizing:** If $K$ strategy sleeves have modest standalone Sharpe $S_0$ and average pairwise correlation $\bar{\rho}$, the combined Sharpe scales as:
   $$S_{\text{ensemble}} = S_0 \sqrt{\frac{K}{1 + (K - 1)\bar{\rho}}}$$
   Moving from $K = 1$ to $K = 5$ sleeves with $\bar{\rho} = 0.20$ multiplies Sharpe by **$1.67\times$** — turning a borderline `0.75` Sharpe into `~1.25`, while a **Meta-Gateway** that filters low-probability setups and scales position size by calibrated post-fee win probability cuts turnover and adverse-regime bleed.

### 1.2 Verified On-Disk Dataset & ML Environment (`2026-11-24`)
Verified directly against `data/live/market.db`, `data/live/multi_venue_quotes.sqlite3`, and `gym-core/.venv`:
- **Daily candles (`1d`):** `373` symbols (`2019-01-01 .. 2026-11-24`, `338,238` rows); `175` symbols have `>= 730` daily bars (`2–7` years).
- **Hourly candles (`1h`):** `366` symbols (`2023-01-01 .. 2026-11-17`, `4,346,201` rows); `358` symbols have `>= 4,000` hourly bars — supporting **lossless UTC-aligned resampling into `2h`, `6h`, and `12h` bars** across `2–4` years.
- **Minute candles (`1min`) & L1/L2 Book Archive:** `339` symbols (`5,876,596` `1min` rows, `~25` days on liquid altcoins, `2023–2026` on `USDTTMN`) + `27.87M` `book_top` rows (`106,558+` with 5-level `depth`) + live Nobitex quotes in `multi_venue_quotes.sqlite3`.
- **Installed ML Runtime (`gym-core/.venv`):** `numpy 2.4.6`, `scipy 1.17.1`, `scikit-learn 1.9.1` (no external cloud dependencies or GPU required).

---

## 2. Architecture Options Evaluated & Recommended Design

We evaluated three architectures combining **multi-timeframe uncorrelated sleeves (`1d / 12h / 6h / 2h` + `30m` tactical layer)** with a **Meta-Gateway**:

| Approach | Mechanism | Strengths | Risks / Trade-Offs | Verdict |
| --- | --- | --- | --- | --- |
| **1. Hybrid Rule Sleeves → Calibrated ML Meta-Labeling Gateway (Mix of A + C)** | 6 interpretable, orthogonal rule sleeves generate candidate direction/conviction across `1d / 12h / 6h / 2h`; a purged walk-forward ML Meta-Gateway (`LogisticRegression` + regularized `HistGradientBoosting` + out-of-fold probability calibration) sees the full sleeve vector + volatility/breadth/`30m` exhaustion context and outputs calibrated $P(\text{net profit} > 0 \mid \mathbf{s}_t, \mathbf{x}_t) \in [0, 1]$ to veto or size into `solve_convex_portfolio`. | Separates **direction** (simple, low-DOF economic rules) from **filtering & sizing** (ML trained directly on post-fee net triple-barrier outcomes); naturally integrates voting, probability aggregation, and regime conditioning without black-box direction chasing. | Requires strict triple-barrier purging/embargoing and fold-local calibration to prevent subtle leakage; must prove OOS lift over non-ML voting. | **Recommended Primary** |
| **2. Online Voting / Bayesian Probability Gateway (Non-ML)** | Same 6 orthogonal sleeves cast continuous votes weighted by rolling OOS exponential-regret / inverse-variance skill weights (Hedge / Bayesian Model Averaging), mapped to calibrated consensus probability requiring quorum agreement. | Zero supervised ML overfitting surface; ultra-fast; trivially auditable; works even on short history (`30m`). | Cannot learn nonlinear interactions (e.g., "Mean-Reversion works in normal vol but dies when breadth `< 20%` and `VPIN > 0.75`"). | **Mandatory Non-ML Control Benchmark** |
| **3. Direct End-to-End ML Alpha Sleeve + Rule Sleeves in Probability Aggregator** | Train a supervised regressor/classifier directly on multi-timeframe price/vol features to predict raw forward returns, and add it as peer sleeve `S7` alongside rule sleeves inside a voting/probability gateway. | Can discover raw nonlinear cross-sectional patterns not captured by hand-crafted rules. | Highest `CPCV PBO` overfitting risk on crypto regime shifts; sensitive to non-stationary feature distributions. | **Optional Challenger Arm (Must Beat Approach 1 & 2 on PBO & Holdout)** |

**Core Design Rule:** Approach 2 (Non-ML Bayesian Voting) is **always** executed alongside Approach 1 (ML Meta-Labeling) on identical sleeves, dates, and fees. The ML Meta-Gateway earns promotion **only** if it beats both Equal-Weight Sleeves and Non-ML Bayesian Voting on the sealed 365-day holdout while maintaining `CPCV PBO < 0.45` and calibrated out-of-sample Brier/ECE metrics.

---

## 3. Component Design

### 3.1 Multi-Timeframe Causal Resampling Panel (`gym-core/src/gym/domain/timeframe_panel.py`)
- **Universe:** Curated liquid USDT pairs from `core-40-wallex` with multi-year `1h` and `1d` history (`20–25` symbols: `BTC, ETH, SOL, XRP, BNB, DOGE, LTC, BCH, DASH, TRX, ADA, LINK, AAVE, UNI, SUI, ARB, FIL, CAKE, ZEC, XAUT`, plus `USDT` cash).
- **Dynamic Listing Mask (No Survivorship Fabrication):** Each symbol enters the active cross-section **strictly after** its own `warmup_bars` (`128` bars on native timeframe) following its first valid recorded bar in `venue_candles`. Missing/halted bars never forward-fill fake trades; open positions during missing bars cannot trade until the next valid bar.
- **Lossless UTC Resampling:**
  - `1d`: native `venue_candles(resolution='1d')`.
  - `12h`, `6h`, `2h`: exact UTC-aligned aggregation from `venue_candles(resolution='1h')` (`open=first`, `high=max`, `low=min`, `close=last`, `volume=sum`, requiring **100% constituent hourly bars present** — partial buckets are marked `INCOMPLETE_BAR` and excluded from signal generation).
  - `30m`: exact UTC-aligned aggregation from `venue_candles(resolution='1min')` where available (`~25` days on altcoins, live-streaming forward). Because `30m` lacks 2–4 year altcoin depth, `30m` is strictly an **optional fast veto/execution-timing feature** (gracefully `None` on pre-`2026-10-30` historical backtest dates, never imputed with future data).
- **Strict Causality Contract:** A bar covering `[t_start, t_end)` becomes observable at `ts_avail = t_end`. Any order triggered from `ts_avail = t_end` executes **strictly at `bar[t_end].open` (the next bar's open)** on candle backtests, or at real `book_top` at `t_end + send_latency_ms` on order-book replays.

### 3.2 Six Orthogonal Strategy Sleeves (`gym-core/src/gym/domain/strategy_sleeves.py`)
Every sleeve implements a uniform, stateless-or-checkpointable contract returning a bounded continuous conviction score $s_{k,i,t} \in [-1, +1]$ (spot long-only mapping: `> 0` = long conviction, `<= 0` = flat / exit pressure), plus its native horizon $H_k$ and explicit economic rationale:

| ID | Sleeve Name | Native Timeframes | Core Economic Signal | Why Low-Correlation With Other Sleeves |
| --- | --- | --- | --- | --- |
| **S1** | **Time-Series Trend (`EWMAC`)** | `12h`, `1d` | Volatility-standardized multi-horizon EWMAC (`8/32`, `16/64`, `32/128`) divided by Yang–Zhang vol. | Captures sustained directional trends (positive convexity in big rallies/crashes). |
| **S2** | **Cross-Sectional Residual Momentum** | `12h`, `1d` | Rolling 14-day/30-day **BTC-beta-neutral residual return** $r_i - \hat{\beta}_{i,\text{BTC}} r_{\text{BTC}}$, cross-sectionally z-scored; long top quartile only when coin's own 30d vol-adjusted return is non-negative. | Strips out common BTC market beta — captures idiosyncratic sector/narrative leaders even when BTC chops sideways. |
| **S3** | **Panic / Oversold Mean-Reversion** | `2h`, `6h` | Enters after sharp downward washouts: `6h` log-return z-score `< -2.2` AND `RSI(4) < 20` AND current bar closes in upper `40%` of its range (exhaustion wick), with mandatory `max_hold = 36h` and `-2.5 * sigma` stop. | **Negatively correlated with S1 Trend** during short-term overreactions — earns positive alpha in choppy/mean-reverting regimes where trend bleeds. |
| **S4** | **Volatility-Compression Breakout** | `6h`, `12h` | Enters when short-to-long Yang–Zhang vol ratio `< 0.65` (compression squeeze) releases above the 20-bar Donchian high with confirming volume z-score `> 1.5`. | Fires selectively at regime transitions out of quiet consolidations rather than continuous trend following. |
| **S5** | **Defensive Gold / Safe-Haven Rotation** | `12h`, `1d` | Allocates positive conviction to `XAUTUSDT` (and `USDT` cash via reduced risk budget) when cross-market crypto breadth (`%` of coins above 50-bar EMA) drops `< 0.35` or cross-sectional downside GJR-EWMA vol enters top decile. | Explicitly generates **positive carry / defensive convexity during crypto bear markets** (directly addressing Candidate B's 2025–2026 bear-year gap). |
| **S6** | **Tactical Micro-Exhaustion & Cross-Venue Overlay** | `30m`, `2h` | On live/recent data: (a) `30m` overextension veto (blocks buying immediately after a `> +3.0 * sigma` 30-minute vertical spike), (b) live Wallex ↔ Nobitex executable spread score from `multi_venue_quotes.sqlite3` (`USDTTMN` / `BTCUSDT`), and (c) `VPIN > 0.85` toxicity veto from `microstructure.py`. | Pure microstructure/venue-structure signal orthogonal to daily/6h candle prices. |

**Orthogonality Enforcement Gate:** Before feeding sleeves into the Meta-Gateway, compute the development-fold pairwise correlation matrix of standalone sleeve returns. Any sleeve pair with $|\rho_{ab}| > 0.60$ must either be orthogonalized (residualize sleeve `b` against `a`) or pruned so the ensemble does not double-count one factor.

### 3.3 The Meta-Gateway (`gym-core/src/gym/domain/meta_gateway.py`)
The Meta-Gateway sits strictly between the 6 strategy sleeves and our existing horizon-matched **Convex L1 Portfolio Optimizer** ([convex_optimizer.py](../../../gym-core/src/gym/domain/convex_optimizer.py)):

```
[1d / 12h / 6h / 2h / 30m Causal Bars]
                │
                ▼
  ┌──────────────────────────────────┐
  │ 6 Orthogonal Strategy Sleeves    │  ──► s_{i,t} in [-1, +1]^6
  │ (S1 Trend, S2 X-Mom, S3 Rev,     │      + sleeve agreement & entropy
  │  S4 Squeeze, S5 Gold, S6 Micro)  │
  └──────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────┐
  │ Meta-Gateway (3 Ablation Modes)  │
  │  • Mode A: Bayesian Voting       │  ──► Calibrated P(net win | s, x) in [0, 1]
  │  • Mode B: ML Meta-Labeling      │      + expected net bps + veto reasons
  │  • Mode C: Direct ML Peer (S7)   │
  └──────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────┐
  │ Probability-to-Return & Sizing   │  ──► mu_hat_i = E[net_bps | P_i]
  │ (Hard P_min gate + Frac. Kelly)  │      (P_i < P_min  ==>  veto = 0)
  └──────────────────────────────────┘
                │
                ▼
  ┌──────────────────────────────────┐
  │ Existing Convex L1 Optimizer     │  ──► TargetIntent + lot/depth verified
  │ + KillSwitch + Execution Overlay │      orders (Wallex L1 / Nobitex -30%)
  └──────────────────────────────────┘
```

#### 3.3.1 Mode A — Non-ML Bayesian / Voting Probability Gateway (Control)
- Maintains causal exponentially-decayed OOS performance weights $w_{k,t} = \frac{\exp(\eta \cdot \text{SR}_{k,t-1})}{\sum_j \exp(\eta \cdot \text{SR}_{j,t-1})}$ (capped to `[0.05, 0.40]` per sleeve to prevent winner-take-all collapse).
- Computes consensus score $c_{i,t} = \sum_k w_{k,t} s_{k,i,t}$ and active-sleeve quorum count $q_{i,t} = \sum_k \mathbb{I}(s_{k,i,t} > 0.25)$.
- Maps $(c_{i,t}, q_{i,t})$ via a strictly monotonic 1D logistic calibrator fit **only on training folds** to calibrated probability $p^{\text{vote}}_{i,t} \in [0, 1]$.

#### 3.3.2 Mode B — Supervised ML Meta-Labeling Gateway (Primary)
- **Trigger Condition:** Evaluates whenever at least one sleeve emits positive candidate conviction ($\max_k s_{k,i,t} > 0.20$ or weighted consensus $c_{i,t} > 0.10$).
- **Exact Feature Vector $\mathbf{z}_{i,t}$ (Compact, Low-DOF — 16 Features Total):**
  1. Individual sleeve scores: `s1_trend`, `s2_xmom`, `s3_reversion`, `s4_breakout`, `s5_gold_regime`, `s6_tactical` (6 features),
  2. Ensemble consensus & disagreement: `weighted_mean_s`, `active_bullish_count`, `sleeve_std` (3 features),
  3. Asset & cross-market regime context: `yang_zhang_vol_20`, `vol_ratio_10_60`, `downside_gjr_vol_ratio`, `cross_market_breadth`, `btc_trend_state`, `asset_relative_volume_z` (6 features),
  4. Fee-to-vol feasibility ratio: `round_trip_fee_bps / (yang_zhang_vol_horizon_bps + 1e-6)` (1 feature — directly teaches the gateway to abstain when volatility is too compressed to clear Wallex/Nobitex fees!).
- **Triple-Barrier Net-of-Fee Label Construction (`build_triple_barrier_labels`):**
  For each candidate entry at `bar[t+1].open` with holding horizon $H$ bars (`H = 12` bars on `6h` = 3 days, or `H = 5` bars on `1d` = 5 days) and local volatility $\hat{\sigma}_{i,t}$:
  - Upper profit barrier: $U = \text{entry\_px} \cdot (1 + k_{\text{up}} \hat{\sigma}_{i,t} \sqrt{H})$ (`k_up = 1.5`),
  - Lower stop barrier: $L = \text{entry\_px} \cdot (1 - k_{\text{dn}} \hat{\sigma}_{i,t} \sqrt{H})$ (`k_dn = 1.0`),
  - Realized net return $r_{\text{net}} = r_{\text{gross}} - c_{\text{RT}}$ where $c_{\text{RT}}$ is the **exact executable round-trip cost** (`30 bps` Wallex USDT maker + drift / `51 bps` Wallex taker + spread, evaluated separately alongside `18 bps` Nobitex `-30%` maker + drift),
  - Binary target: $y_{i,t} = 1$ **if and only if** $r_{\text{net}} > 0$ at first barrier touch or vertical expiry $H$, storing exact label span $[t_{\text{entry}}, t_{\text{exit}}]$ for purging!
- **Sample Weighting (Uniqueness Weighting, López de Prado Ch. 4):**
  Because overlapping positions across `20–25` correlated crypto assets are **not** independent IID draws, weight each training sample inversely by concurrent active label overlap $u_{i,t} = \frac{1}{N_{\text{concurrent}}(t)}$ (and optionally cross-sectional date cluster weight `1 / active_symbols_on_date`) so correlated market-wide crashes cannot dominate the fit.
- **Model Family (Strictly Regularized, Pure `scikit-learn`):**
  1. `LogisticRegression(penalty="l2", C=0.2)` inside a fold-local `Pipeline([SimpleImputer, RobustScaler, LogisticRegression])` — linear interpretable anchor.
  2. `HistGradientBoostingClassifier(max_depth=3, min_samples_leaf=100, l2_regularization=5.0, learning_rate=0.05, max_iter=150, early_stopping=True)` — captures nonlinear sleeve × regime interactions without memorizing noise.
  3. **Out-of-Fold Probability Calibration:** Fit isotonic / sigmoid calibration strictly on purged inner validation folds; report out-of-sample **Brier score** and **Expected Calibration Error (`ECE`)** separately from portfolio PnL.
- **Probability-to-Trade Gate & Sizing:**
  - Break-even probability given average win $W$ and average loss $L$ (estimated strictly on training folds): $p_{\text{BE}} = \frac{L}{W + L}$.
  - Hard veto whenever $\hat{p}_{i,t} < \max(0.52,\; p_{\text{BE}} + 0.03)$ (margin of safety above break-even).
  - For surviving trades, compute expected net horizon return:
    $$\hat{\mu}^{\text{net}}_{i,t} = \hat{p}_{i,t} \cdot \hat{W}_{\text{train}} - (1 - \hat{p}_{i,t}) \cdot \hat{L}_{\text{train}}$$
    and pass $\hat{\mu}^{\text{net}}_{i,t}$ directly into `solve_convex_portfolio` (`convex_optimizer.py`) with exact L1 fee zone, `max_weight = 0.30`, `cash_buffer = 0.05`, and correlation-aware shrinkage covariance.

---

## 4. Anti-Leakage, Statistical Governance & Instant Zero-Wait Validation

Every single experiment in this design runs **instantly on existing disk data (zero 30-day or 90-day calendar wait)** while preserving full statistical rigor:

1. **Chronological Sealed Historical Holdout (Zero Peeking):**
   - **Development & Purged CV Split:** All data `<= 2025-11-23` (`~3–6` years on `1d`, `~1–3` years on `2h/6h/12h`). All feature selection, sleeve correlation pruning, model fitting, and probability calibration happen **strictly** inside this window using **Purged & Embargoed CPCV** (`purged_cpcv_splits` with exact triple-barrier span `[t_entry, t_exit]` purging and `embargo = H` bars!).
   - **Sealed Historical Holdout:** `2025-11-24 .. 2026-11-23` (**365 full calendar days** covering a harsh crypto bear market + gold rally — evaluated **once** per frozen configuration).
2. **Effective Sample Size & Date-Clustered Inference:**
   - Pooled panel rows (`35,000–180,000`) are used for regularized ML fitting with overlap uniqueness weights, **never** to artificially inflate Sharpe `N` or `DSR`!
   - All portfolio `Sharpe`, `DSR`, `500`-run path-preserving placebo (`run_path_preserving_placebo`), and `CPCV PBO` (`pbo_rank_logit`) are computed strictly on **aggregated daily portfolio net returns** (`1` observation per UTC calendar day), eliminating cross-sectional correlation inflation.
3. **Full Multiplicity Denominator:**
   - `DSR` uses $N_{\text{total}} = 21 + N_{\text{new\_configs}}$ (counting every tested sleeve/gateway/timeframe configuration in the trial ledger, never hiding failed runs).
4. **Mandatory 5-Way Ablation Matrix (Reported on Both Wallex L1 and Nobitex `-30%` Fees):**
   1. Equal-Weight Buy & Hold (passive benchmark),
   2. Best Single Sleeve (`S1` Trend alone),
   3. Equal-Weight 6-Sleeve Ensemble (`S1–S6`, no gateway),
   4. **Mode A:** Non-ML Bayesian Voting Gateway (`S1–S6`),
   5. **Mode B:** Calibrated ML Meta-Labeling Gateway (`Logistic` and `HistGradientBoosting`, `S1–S6`).
5. **Real Order-Book Execution Sanity Check (Live Archive):**
   - Replay the winning gateway's signals on the archived 25-day live `book_top` + `trades` database (`27.87M` rows, including `--depth-levels 5` depth) using `simulate_passive_orders(..., duplicate_print_mode="adversarial_lower_bound")` and verify realized implementation shortfall matches or beats the modeled fee/spread assumption used in the multi-year backtest.

### Instant Promotion Criteria (`G2-Instant` Pass Bar)
A candidate clears `G2-Instant` **only** if ALL of the following hold simultaneously:
- **Sealed 365-day Holdout (`2025-11-24..2026-11-23`):** Net return `> 0%`, `Ann. Sharpe >= 0.75`, `MaxDD <= 20%`.
- **Full Multi-Year OOS / Walk-Forward:** `DSR >= 0.95` under full $N_{\text{total}}$ multiplicity.
- **Overfitting & Causality Guards:** `CPCV PBO < 0.45`, `500`-run path-preserving placebo `p < 0.05`, `check_causality_perturbation == True`.
- **Calibration Integrity (for ML Mode B):** Out-of-sample `Brier < 0.25`, `ECE < 0.05`, AND Mode B beats Mode A (Non-ML Voting) on sealed holdout risk-adjusted net return (otherwise adopt simpler Mode A!).
- **Order-Book Execution Check:** Live archive replay confirms realized execution drag does not exceed the modeled cost hurdle.

---

## 5. Planned Module & File Layout (Clean Domain Names, Zero Code Written Yet)

| File | Single Responsibility |
| --- | --- |
| `gym-core/src/gym/domain/timeframe_panel.py` | Lossless UTC-aligned `2h/6h/12h/30m` resampler from `market.db` candles with dynamic listing masks and strict `ts_avail` next-bar-open contracts. |
| `gym-core/src/gym/domain/strategy_sleeves.py` | Six orthogonal sleeves (`S1–S6`) returning bounded `[-1, +1]` convictions + development-fold sleeve correlation orthogonality audit. |
| `gym-core/src/gym/domain/triple_barrier.py` | Net-of-fee triple-barrier labeler, label-span overlap tracker, and López de Prado uniqueness sample weights. |
| `gym-core/src/gym/domain/meta_gateway.py` | Mode A (Non-ML Bayesian Voting), Mode B (Purged Walk-Forward ML Meta-Labeling with fold-local `Pipeline` & calibration), Mode C (Optional ML Peer), and probability-to-expected-return sizing bridge into `convex_optimizer.py`. |
| `gym-core/scripts/evaluate_ensemble_gateway.py` | Runs the full 5-way ablation matrix, orthogonality report, calibration audit (Brier/ECE), purged CPCV/PBO, 500-run placebo, live order-book execution check, and writes `evidence/ensemble-gateway-evaluation.md`. |
| `gym-core/tests/test_ensemble_and_meta_gateway.py` | Unit & causality tests: lossless resampling, zero future leak (`check_causality_perturbation`), triple-barrier overlap purging, probability calibration monotonicity, and Mode A vs Mode B parity. |

---

## 6. Specific Adversarial Review Questions for GPT Astra

To make Astra's critique maximally actionable before writing any implementation plan or code, we explicitly invite review on six high-risk design points:
1. **Effective Sample Size vs. Pooled ML Training:** Does training `HistGradientBoosting` (`max_depth=3, min_samples_leaf=100`) on `~25` correlated crypto assets with inverse-concurrency uniqueness weights (`u_{i,t} = 1 / N_concurrent`) still risk overfitting 2023–2025 bull beta when evaluated on the 2025–2026 bear holdout, or should we restrict Mode B initially to `L2 LogisticRegression` only?
2. **Triple-Barrier Horizon Alignment Across Timeframes:** Mixing `2h/6h` reversion (`S3`) with `12h/1d` trend (`S1`) means one fixed vertical barrier `H` may be too slow for `S3` and too fast for `S1`. Should we train **two horizon-matched Meta-Gateways** (Fast `2h/6h` Gateway for `S3/S4/S6` and Slow `12h/1d` Gateway for `S1/S2/S5`) and combine their outputs at the portfolio optimizer level instead of one monolithic gateway?
3. **`30m` Data Asymmetry (`25` Days vs. `2–4` Years):** Since `1min -> 30m` exists for only `~25` days on most altcoins, is treating `30m` (`S6`) strictly as a live-archive execution/veto overlay (excluded from multi-year `2021–2026` ML feature vectors to avoid train/serve skew) the cleanest boundary?
4. **Defensive Gold Sleeve (`S5: XAUTUSDT`) Availability:** `XAUTUSDT` daily history in `market.db` starts `2024-08-06` (`841` days). Should the multi-year 2021–2026 panel allow `S5` to rotate into `USDT` cash before `2024-08-06` and `XAUTUSDT + USDT` after `2024-08-06` via the dynamic listing mask?
5. **Wallex vs. Nobitex Execution Realism:** Given Nobitex's `7.5×` tighter `BTCUSDT` spread (`4.2 bps` vs. Wallex `31.5 bps`) and `-30%` fee discount (`14–18.2 bps` RT vs. Wallex `20–26 bps` RT), should `G2-Instant` report separate Wallex-only and Nobitex-only net outcomes so a strategy that clears Nobitex costs isn't masked by Wallex spread drag?
6. **Multiplicity Accounting (`N_total`):** Should every ablation arm (`Mode A`, `Mode B Logistic`, `Mode B HGBT`, `Mode C`) and sleeve pruning pass increment `N_total` in `DSR` on top of the existing `21` registered trials?
