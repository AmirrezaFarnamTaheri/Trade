# Profitable System Master Specification — Wallex Core Engine First, Multi-Venue Plug-In Later

**Date:** 2026-11-24 · **Scope:** Canonical architecture, financial-engine, trading-framework, and quantitative-modeling specification for reaching an independently verified net-profitable trading system.

**Hard Authority Boundary:** `TradingGYMExecutor` remains **`DISARMED / NOT CERTIFIED`** with a **`$0` funded-loss budget**. Nothing in this plan arms live order execution or relaxes the pre-committed [2027-02-08-checkpoint-protocol.md](2027-02-08-checkpoint-protocol.md).

---

## 1. Verified Baseline & Empirical Diagnosis (2026-11-24)

### 1.1 Current Status Against the Profitable-System Gate (`2027-02-08`)

| Gate | Requirement | Verified State on Disk (2026-11-24) | Verdict |
| --- | --- | --- | --- |
| **G1 — 30-day feed reliability** | `<= 10%` failed UTC days (`<= 3/30`) and max raw archive gap `<= 24.0h` over `2027-01-09..2027-02-08` | Live 40-market Wallex collector (`core-40-wallex`, watchlist `5078e0c5a62155c6`) is streaming across **2 WebSocket shards** at `0s` lag (`*.ir` bypassed from VPN). Historical span (`2026-10-30..2026-11-23`) had 3 raw gaps `> 24h` (`49.0h`, `41.0h`, `35.0h`) and 17 unclosed segments. | **Stabilized live; 30-day qualification window starts 2027-01-09** |
| **G2 — Independently validated net edge** | Track A (`DSR >= 0.95` + sequential `e-value >= 20` on unseen holdout/forward data) **or** Track B (multi-year OOS `DSR >= 0.95` + 90-day live-paper implementation-shortfall check) | `data/live/research_protocol.sqlite3` has `0` evaluations and `0` outcomes. Out of 18 trials in [trial-log.md](../gym-core/docs/trial-log.md), 14 failed, 2 passed narrowly on non-live/proxy benchmarks, and 2 background forward monitors remain open. | **NOT MET** |
| **G3 — Authority & admission** | Automated ADR 0006/0007/0008 checks green; `DISARMED` invariant intact | Source Rust/Python/browser suites pass; installed Windows service `TradingGYMExecutor` is `Stopped` / `Disabled` (`2026-11-06` binaries, `custody_requalified: false`, `funded_authority: false`, `capital_quanta: "0"`). | **In source only** |
| **G4 — Owner sign-off** | Written decision in `evidence/2027-02-08-checkpoint-decision.md` | Default **NO-GO** until `2027-02-08`. | **Open** |

### 1.2 Economic Constraints Established by Empirical Evidence

1. **Wallex Published Fee Asymmetry ([structured_fees.json](../data/live/structured_fees.json)):**
   - **USDT spot pairs (Level 1):** `0.10%` (`10.0 bps`) maker / `0.13%` (`13.0 bps`) taker → **`20.0–26.0 bps` round trip**.
   - **TMN spot pairs (Level 1):** `0.25%` (`25.0 bps`) maker / `0.30%` (`30.0 bps`) taker → **`50.0–60.0 bps` round trip** (**2.3×–2.5× more expensive** than USDT pairs).
   - **Operator read-only account fee (`/v1/account/fee`):** `0.10%` per side where applicable.
   - **Implication:** Active high-turnover strategies on Wallex **must prioritize USDT pairs and passive maker execution**. Crossing a `25 bps` spread as a taker starts `-38 to -55 bps` underwater; capturing that spread passively with maker execution flips execution economics by **`+50 bps` per round trip**.
2. **Order-Book Depth & Exit Capacity ([2026-11-22-historical-replay-financial-audit.md](../evidence/2026-11-22-historical-replay-financial-audit.md)):**
   - Hourly `ema-trend 8/21` lost quote capital in **320 of 337 traded markets** (median `-9.73%` TMN, `-11.15%` USDT; median spread debit `4.87%` TMN / `7.53%` USDT).
   - In a 45-minute post-cutoff exit replay at a `25%` displayed-size participation cap, only **2 of 137** positions could fully close. ~330 tail pairs on Wallex lack executable depth.
3. **Currency Denomination of Margin Borrowing (`~33%/yr`):**
   - **Shorting `BTCUSDT` (BTC debt, USDT collateral):** Pays `0.015%` every 4 hours (`~32.85%/yr`) + `0.25%` open / `0.10%` close + forced 21-day reopening **in USDT terms**, losing in 60/60 cells in `trend-with-short-side` (29/60 liquidated) vs. simply holding `USDT` cash at `0%` borrow cost.
   - **Long `USDTTMN` or `XAUTTMN` using TMN-denominated debt:** Borrows **TMN** at `~33%/yr` against assets appreciating `~50%+/yr` in TMN (**negative real interest rate carry**), subject to two explicit risks that must be modeled: (a) 6–9 month flat-Toman carry bleed, and (b) sudden `-10%` to `-15%` Toman appreciation spikes triggering liquidation if over-levered (`> 1.5x–2.0x`).
4. **Statistical Power vs. Horizon ([2026-11-18-detectable-edge.md](../evidence/2026-11-18-detectable-edge.md)):**
   - Daily-bar rules had a minimum detectable edge (`MDE`) of `10–20 bps/day` (`44%–107%/yr`) vs. realistic net edges of `1–5 bps/day`. Active high-sample strategies (Track A) and slow macro/multi-asset allocations (Track B) require separate validation protocols.

### 1.3 Baseline Upgrades Already Delivered on 2026-11-24

- **Collector cut to 40 curated markets (`core-40-wallex`, 2 WS shards):** 7 core TMN pairs (`USDTTMN, BTCTMN, ETHTMN, SOLTMN, XRPTMN, XAUTTMN, PEPETMN`) + 33 core USDT pairs covering 100% of `btc-daily-trend`, `passive-multi-asset-mix`, and `breadth-trend-forward` ([Install-Collector.ps1](../scripts/windows/Install-Collector.ps1)).
- **Losing hourly EMA jobs paused:** All 5 scheduled `ema-trend 8/21` jobs in `data/live/research.sqlite3` paused (`enabled = 0`).
- **Live `/v2/structured-fee` ingestion & quote-aware published fees:** Added in [collector.py](../gym-core/src/gym/services/collector.py), [market_quality.py](../gym-core/src/gym/services/market_quality.py), and [cost_defaults.py](../gym-core/src/gym/services/cost_defaults.py).
- **Standalone causal passive cancel/replace simulator:** `simulate_passive_cancel_replace` added in [execution_qualification.py](../gym-core/src/gym/domain/execution_qualification.py).
- **Governance & sequential e-values:** Background forward monitors (`funding-confirmed-trend-forward`, `breadth-trend-forward`) separated from the 2 active hypothesis seats (`remaining: 2`) while staying in the BH/DSR denominator; `sequential_e_process` wired into all three forward journals ([trial_governance.py](../gym-core/src/gym/services/trial_governance.py), [evidence.py](../gym-core/src/gym/services/evidence.py)).

---

## 2. Strategic Sequencing & Permanent Scope Freeze

### 2.1 Three-Phase Sequencing

1. **Phase A (ACTIVE NOW — Wallex 40-Market Core Only):**
   Upgrade the **financial engine**, **multi-signal trading framework**, and **quantitative modeling** stack exclusively against the 40-market Wallex store, designing every domain interface with explicit `venue` and `FeeSchedule` abstractions so zero math is rewritten later.
2. **Phase B (NEXT — Iranian Multi-Venue Plug-In):**
   Plug **Nobitex** (permanent **`-30%`** fee discount: `7.0/9.1 bps` USDT, `14.0/17.5 bps` IRT; deep books) and **AbanTether** (`0.558%` flat round-trip OTC across tokenized US equities, US Treasury bonds, and commodities) into Phase A's venue-agnostic adapters (complete specs in §8).
3. **Phase C (OPTIONAL LATER — Global Perpetuals):**
   Optional Hyperliquid adapter for delta-neutral perpetual funding carry and low-cost asymmetric shorting (`< 120d` MA).

### 2.2 Strict Engineering Freeze (Effective Immediately Until Gate G2 Passes)

- **FROZEN:** 373-market whole-catalogue replay micro-optimizations, new EN/FA Web UI views/charts, Rust `executor/` feature additions (`DISARMED`), single-venue price-only TA sweeps, and BTC/USDT-denominated margin shorting.

---

## 3. Code-Level Audit of the 12 Structural Flaws in `gym-core`

Direct inspection of `gym-core/src/gym/domain/` and `gym-core/src/gym/services/` identified 12 internal flaws that prevent TradingGYM from expressing or executing profitable strategies even on clean data:

| # | Pillar | File & Lines | Exact Defect in Current Code | Architectural Replacement |
| --- | --- | --- | --- | --- |
| **F1** | Financial Engine | [session.py#L391-L486](../gym-core/src/gym/services/session.py#L391-L486) | `settle_limit` freezes `pending.limit = top.bid` once for the entire `max_wait` (never re-pegs or cancels on toxic flow) and when `top.ask <= pending.limit` stamps `order["maker"] = True` (charging maker fee even on a marketable crossing order that arrived after the ask dropped!). | Arrival-state maker/taker/post-only classifier + stateful dynamic pegged child orders (`PeggedMakerPolicy`, `ReservationPricePolicy`) (§4.2). |
| **F2** | Financial Engine | [portfolio_policy.py#L89-L218](../gym-core/src/gym/domain/portfolio_policy.py#L89-L218) | `PortfolioPolicy.weights(observations)` takes past prices only (**zero signal forecast $\hat{\mu}_i$**) and checks rebalance bands per coin independently, paying double fees to swap highly correlated coins (`corr(BTC, ETH) = 0.85`). | Joint convex trade optimizer with L1 exact fee-zone & quadratic depth-impact penalty (§4.3). |
| **F3** | Financial Engine | [session.py#L290-L300](../gym-core/src/gym/services/session.py#L290-L300) | Submits orders immediately at bar close regardless of intraday spread seasonality (missing the measured `32%` spread reduction at `15:00 Tehran`). | Decoupled signal clock vs. opportunistic liquidity-window execution slicer (§4.4). |
| **F4** | Financial Engine | [sim.py#L523-L533](../gym-core/src/gym/domain/sim.py#L523-L533) | Stops cost attribution at the instant of fill (`spread + fees + latency_drift`), hiding post-fill adverse selection (`+5s..+1h` toxic markouts). | Multi-horizon post-fill TCA markout engine (§4.5). |
| **F5** | Trading Framework | [strategy.py#L107-L129](../gym-core/src/gym/domain/strategy.py#L107-L129), [session.py#L231-L232](../gym-core/src/gym/services/session.py#L231-L232) | Binary `0%` / `100%` `decide(snap, holding)` contract; holding `> 1%` equity sets `holding = True`, blocking scale-ins when conviction triples and blocking partial scale-outs. | Continuous target-weight protocol (`TargetIntent`) trading $\Delta w_t = w^*_t - w_{\text{held},t}$ (§5.3). |
| **F6** | Trading Framework | [blend_strategies.py#L21-L72](../gym-core/src/gym/domain/blend_strategies.py#L21-L72) | Hardcodes single-market price-only members and crushes continuous signals to `1-bit` votes (`True`/`False`), destroying signal magnitude and banning cross-market/book signals from blends. | Multi-modal continuous `[-20, +20]` forecast graph with shrinkage combiner & capped `FDM` (§5.4). |
| **F7** | Trading Framework | [bars.py#L200-L206](../gym-core/src/gym/domain/bars.py#L200-L206), [session.py#L127-L128](../gym-core/src/gym/services/session.py#L127-L128) | `Consolidator.update_quote` sets `qty = 0` (`bar.volume == 0`) on naive `(bid + ask)/2` midpoints (corrupted by 1-lot stub orders), and `Snapshot` strips `bid_qty`, `ask_qty`, `depth`, and signed trade flow. | `MicrostructureConsolidator` + `RichSnapshot` exposing Stoikov `microprice`, 5-level book imbalance, `OFI`, `VWAP`, and `VPIN` (§5.1). |
| **F8** | Trading Framework | [session.py#L101](../gym-core/src/gym/services/session.py#L101) | Fixed wall-clock bar closes only; misses fast between-bar liquidity dislocations and oversamples dead hours. | Dual-clock event, dollar-volume, `OFI`-bar, and dislocation-threshold triggers (§5.2). |
| **F9** | Quantitative Modeling | [cross_market_strategies.py#L42-L45](../gym-core/src/gym/domain/cross_market_strategies.py#L42-L45), [L128-L139](../gym-core/src/gym/domain/cross_market_strategies.py#L128-L139), [portfolio_policy.py#L131-L132](../gym-core/src/gym/domain/portfolio_policy.py#L131-L132) | Single-bar gap calls `.clear()`/`.reset()` (wiping 20–129 bars of warmup) and `PortfolioPolicy._history` raises `GAPPED_HISTORY` on any irregular interval across markets. | Continuous-time irregular decay ($\alpha(\Delta t) = 1 - e^{-\Delta t/\tau}$) + Hayashi–Yoshida nonsynchronous overlap covariance (§6.1, §6.2). |
| **F10** | Quantitative Modeling | [cross_market_strategies.py#L61-L75](../gym-core/src/gym/domain/cross_market_strategies.py#L61-L75) | `TomanPremium` assumes stationary mean basis; fades structural multi-day Iranian FX level shifts. | 2-state Linear-Gaussian Kalman Filter separating slow structural level $\mu_t$ from tradable residual $\epsilon_t$ (§6.1). |
| **F11** | Quantitative Modeling | [sim.py#L159-L165](../gym-core/src/gym/domain/sim.py#L159-L165), [volatility.py](../gym-core/src/gym/domain/volatility.py) | 20-bar close-to-close std / basic Parkinson `H/L` ignores overnight/closure jumps and symmetric-weights crashes vs. rallies. | Yang–Zhang jump-safe OHLC variance + asymmetric downside GJR-EWMA volatility (§6.3). |
| **F12** | Quantitative Modeling | *(Absent in repo)* | Passive limit orders have no model for optimal quote depth $\delta^*$ vs. fill probability and toxic markout. | Empirical monotone fill-hazard & expected-surplus quote optimizer (§6.5). |

---

## 4. Workstream 1 — Financial Engine Specification

### 4.1 Venue-Agnostic Domain Contracts (`gym-core/src/gym/domain/venue_contracts.py`)

All new financial, execution, and modeling components consume these immutable exact-Decimal structures so Phase A runs on `venue="wallex"` and Phase B plugs in `venue="nobitex"` and `venue="abantether"` without altering downstream code:

```python
@dataclass(frozen=True)
class FeeTier:
    level: str
    min_30d_quote_volume: Decimal
    maker_rate: Decimal          # e.g. Decimal("0.0010") for Wallex USDT L1, Decimal("0.0025") for Wallex TMN L1
    taker_rate: Decimal          # e.g. Decimal("0.0013") for Wallex USDT L1, Decimal("0.0030") for Wallex TMN L1

@dataclass(frozen=True)
class FeeSchedule:
    venue: str                   # "wallex" | "nobitex" | "abantether"
    quote_asset: str             # "USDT" | "TMN"
    tiers: tuple[FeeTier, ...]
    permanent_discount: Decimal  # Decimal("0") on Wallex; Decimal("0.30") on Nobitex in Phase B
    fee_in_received_asset: bool  # True on Wallex spot
    observed_at: datetime
    source: str                  # "PUBLIC_STRUCTURED_FEE_VINTAGE" | "READ_ONLY_ACCOUNT_GET" | "PUBLISHED_L1"

    def effective_rates(self, rolling_30d_volume: Decimal = Decimal(0), *, zero_fee: bool = False) -> tuple[Decimal, Decimal]:
        if zero_fee:
            return Decimal(0), Decimal(0)
        selected = self.tiers[0]
        for tier in self.tiers:
            if rolling_30d_volume >= tier.min_30d_quote_volume:
                selected = tier
        mult = Decimal(1) - self.permanent_discount
        return selected.maker_rate * mult, selected.taker_rate * mult

@dataclass(frozen=True)
class OrderSpec:
    venue: str
    symbol: str
    base_asset: str
    quote_asset: str
    price_decimals: int
    qty_decimals: int
    min_qty: Decimal
    min_notional: Decimal
    market_order_enabled: bool
    post_only_supported: bool

@dataclass(frozen=True)
class QuoteSnapshot:
    venue: str
    symbol: str
    ts_event: datetime
    ts_avail: datetime
    bid: Decimal
    ask: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    bid_levels: tuple[tuple[Decimal, Decimal], ...]  # ordered best-bid-first (price, qty) pairs
    ask_levels: tuple[tuple[Decimal, Decimal], ...]  # ordered best-ask-first (price, qty) pairs
    flags: frozenset[str]

@dataclass(frozen=True)
class NavReference:
    symbol: str
    underlying_ticker: str       # e.g. "GC=F" / "SPY" / "TLT"
    underlying_usd_price: Decimal
    fx_usdt_to_quote: Decimal    # Decimal(1) for USDT pairs; live USDTTMN mid for TMN pairs
    share_ratio: Decimal         # underlying shares per 1.0 token
    observed_at: datetime
    market_open: bool
```

### 4.2 Arrival-State Passive Matching & Dynamic Pegged Child Orders (`gym-core/src/gym/domain/passive_execution.py`)

Replace static touch resting in `PaperSession.settle_limit` with a causal child-order state machine (`PassiveOrderWorkingState`):

1. **Arrival Classification at `t_arr = t_send + send_latency`:**
   Let `top_arr` be the latest qualified `BookTop` with `ts_avail <= t_arr`.
   - For `BUY` with `limit_price`:
     - If `limit_price >= top_arr.ask`:
       - If `post_only=True`: transition immediately to `POST_ONLY_REJECTED` (`filled_qty = 0`, `fee = 0`).
       - If `post_only=False`: execute immediately against `top_arr.ask` (or walk `ask_levels` when `walk_depth=True`) capped by `limit_price`, setting `liquidity_role = "TAKER"` and charging `taker_rate`.
     - If `limit_price < top_arr.ask`: enter `RESTING_MAKER` with `queue_ahead = top_arr.bid_qty` when `limit_price == top_arr.bid`, `Decimal(0)` when `top_arr.bid < limit_price < top_arr.ask` (price-improving inside spread), or summed depth strictly at/above `limit_price` when deeper in `bid_levels`.
2. **Dynamic Re-Peg & Toxicity Cancel Policy (`PeggedMakerPolicy`):**
   At each subsequent quote `top` (`ts_avail > last_checked`):
   - Trigger cancel/replace (`cancel_sent_at = top.ts_avail`) if **any** holds:
     1. **Stranded drift:** `(top.bid - limit_price) / limit_price * 10000 > chase_bps` (for `BUY`) and `repeg_count < max_repegs`.
     2. **Toxic imbalance flip:** top-of-book imbalance `I = (top.bid_qty - top.ask_qty) / (top.bid_qty + top.ask_qty)` drops below `cancel_imbalance_threshold` (e.g. `-0.65` while resting a `BUY`).
     3. **Spread blowout:** `top.spread_bps > max_safe_spread_bps`.
   - **Cancel-in-flight race window `[cancel_sent_at, cancel_sent_at + cancel_latency)`:** The prior resting order **remains exposed** to opposing trade prints (`aggressor == "SELL"` for `BUY`) during the entire `cancel_latency` interval. Fills occurring inside this window are settled at the old `limit_price` (`maker_rate`) and tagged `adverse_race_fill = True`.
   - Only unfilled `remaining_qty > 0` after `cancel_effective_at = cancel_sent_at + cancel_latency` is re-submitted at the new reservation/pegged limit price (`active_at = cancel_effective_at + send_latency`).

### 4.3 Convex Single-Period Portfolio Trade Optimizer (`gym-core/src/gym/domain/convex_optimizer.py`)

Given $N$ assets, current weights $\mathbf{w}^0 \in \mathbb{R}_{\ge 0}^N$, expected net alpha forecast vector $\hat{\boldsymbol{\mu}} \in \mathbb{R}^N$ (in return units per horizon), positive-definite covariance matrix $\boldsymbol{\Sigma} \in \mathbb{R}^{N \times N}$, linear one-way transaction cost $\tau_i = f_i + \frac{1}{2}s_i$, quadratic depth-impact coefficient $\kappa_i = \frac{\text{account\_equity}}{2 \cdot \text{depth\_quote}_i}$, risk aversion $\lambda > 0$, per-asset cap $w_{\max}$, and cash buffer $c_{\text{buf}} \in [0, 1)$:

$$\min_{\mathbf{w} \in \mathbb{R}^N} \; J(\mathbf{w}) = \frac{\lambda}{2}\mathbf{w}^\top \boldsymbol{\Sigma}\mathbf{w} - \hat{\boldsymbol{\mu}}^\top \mathbf{w} + \sum_{i=1}^{N} \tau_i |w_i - w_i^0| + \frac{1}{2}\sum_{i=1}^{N} \kappa_i (w_i - w_i^0)^2$$
$$\text{s.t.} \quad 0 \le w_i \le w_{\max} \;\;\forall i, \qquad \sum_{i=1}^{N} w_i \le 1 - c_{\text{buf}}.$$

**Exact Coordinate-Descent + Dual Simplex Projection Algorithm (`solve_cost_aware_weights`):**
1. For outer dual multiplier $\nu \ge 0$ enforcing $\sum_i w_i \le 1 - c_{\text{buf}}$ (solved by bisection when $\sum_i w_i(\nu=0) > 1 - c_{\text{buf}}$):
2. Sweep coordinates $i = 1, \dots, N$ cyclically for up to `max_iter = 200` (stopping when $\max_i |w_i^{(k)} - w_i^{(k-1)}| < 10^{-9}$):
   - Compute partial gradient excluding coordinate $i$ at $w_i = w_i^0$:
     $$g_i = \hat{\mu}_i - \nu - \lambda \sum_{j \ne i} \Sigma_{ij} w_j - \lambda \Sigma_{ii} w_i^0$$
   - Apply exact **L1 soft-thresholding** (creating the analytical correlation-aware no-trade band $|g_i| \le \tau_i$):
     $$\Delta_i = \begin{cases} \dfrac{g_i - \tau_i}{\lambda \Sigma_{ii} + \kappa_i} & \text{if } g_i > \tau_i \\[6pt] \dfrac{g_i + \tau_i}{\lambda \Sigma_{ii} + \kappa_i} & \text{if } g_i < -\tau_i \\[6pt] 0 & \text{if } |g_i| \le \tau_i \end{cases}$$
   - Project onto box bounds: $w_i \leftarrow \min(w_{\max}, \max(0, w_i^0 + \Delta_i))$.
3. Convert final target deltas $\Delta w_i = w_i - w_i^0$ to exact `Decimal` quantities floored to `spec.qty_decimals`, dropping legs below `spec.min_notional`.

### 4.4 Opportunistic Liquidity-Window Execution Slicer (`gym-core/src/gym/domain/execution_schedule.py`)

For slow horizons (`>= 1h` or `1day`), decouple signal generation from order submission via `OpportunisticWindowPolicy(max_delay: timedelta, target_spread_quantile: Decimal = Decimal("0.35"), adverse_drift_limit_bps: Decimal = Decimal("40"))`:
- Record `decision_mid` at `decision_time`.
- Over `[decision_time, decision_time + max_delay]`, submit the passive/child order as soon as **either**:
  1. `current_spread_bps <= rolling_pair_spread_quantile(target_spread_quantile)` (capturing Wallex's `15:00 Tehran` tight-spread regime), **or**
  2. Adverse price drift `side_sign * (current_mid - decision_mid) / decision_mid * 10000 >= adverse_drift_limit_bps` (prevents missing a fast breakout), **or**
  3. `now >= decision_time + max_delay` (deadline reached; execute if still cost-positive, else abstain).

### 4.5 Transaction Cost Analysis & Post-Fill Markout Engine (`gym-core/src/gym/domain/tca_markout.py`)

Define `compute_fill_markouts(fills: list[dict], quotes_by_symbol: dict[str, list[BookTop]], horizons_s: tuple[int, ...] = (5, 30, 300, 3600)) -> dict`:
- For each settled fill `(symbol, side, fill_time, fill_price, mid_at_fill, fee_rate, liquidity_role)` with `sign = +1` (`BUY`) or `-1` (`SELL`):
  - `spread_capture_bps = sign * (mid_at_fill - fill_price) / mid_at_fill * 10000` (positive for passive maker fills inside/at touch, negative for taker fills).
  - For each horizon $h \in \{5, 30, 300, 3600\}$ seconds, locate via `bisect_right` the latest qualified `BookTop` at or before `fill_time + timedelta(seconds=h)` (within staleness bound `max(60s, h // 2)`, else `None`):
    $$\text{markout\_pnl\_bps}(h) = \text{sign} \cdot \frac{\text{mid}_{t+h} - \text{fill\_price}}{\text{mid\_at\_fill}} \cdot 10^4 - \text{fee\_bps}$$
    $$\text{adverse\_selection\_bps}(h) = -\text{sign} \cdot \frac{\text{mid}_{t+h} - \text{mid\_at\_fill}}{\text{mid\_at\_fill}} \cdot 10^4$$
- Emit summary percentiles (`p10`, `median`, `mean`, `p90`) stratified by `liquidity_role` (`MAKER` vs. `TAKER`), `symbol`, and Tehran hour `0..23`.

### 4.6 Dual-Numeraire Accounting & Separated TMN-Borrow Carry (`gym-core/src/gym/domain/dual_numeraire.py`, `tmn_carry.py`)

1. **`DualNumeraireReport`:** Every replay and forward journal computes exact starting and ending wealth in:
   - `usdt_equity`: consolidated in `USDT` using causal `USDTTMN` bid (for `TMN` holdings),
   - `tmn_equity`: consolidated in `TMN` using causal `USDTTMN` bid (for `USDT` holdings),
   - `excess_vs_usdt_cash_pct`, `excess_vs_tmn_cash_pct`, and `excess_vs_equal_weight_benchmark_pct`.
2. **`simulate_tmn_borrow_carry` (`tmn_carry.py`):**
   Dedicated simulator for borrowing **TMN** against `USDTTMN` or `XAUTTMN`:
   - State: `(collateral_tmn, borrowed_tmn_principal, accrued_interest_tmn, asset_units, opened_at, cycle_count)`.
   - Every `4 hours` (`14,400s`): `accrued_interest_tmn += borrowed_tmn_principal * Decimal("0.00015")`.
   - Intra-bar liquidation check on `bar.low`: `equity_at_low = asset_units * bar.low * (1 - taker_fee_tmn) - borrowed_tmn_principal - accrued_interest_tmn`; liquidate if `equity_at_low <= maintenance_margin_ratio * (asset_units * bar.low)` (default `0.15`).
   - Every `21 days`: settle accrued interest, pay forced roll/reopening cost (`reopen_fee_bps`), and re-check leverage cap (`<= max_leverage`, e.g. `1.5x`).

---

## 5. Workstream 2 — Trading Framework Specification (Multi-Signal Vector Pipeline)

### 5.1 Microstructure-Complete Consolidator & Snapshot (`gym-core/src/gym/domain/microstructure.py`)

Extend bar consolidation with `MicrostructureConsolidator` consuming **both** `BookTop` quotes and `TradeTick` prints in causal `ts_avail` order, producing `MicrostructureBar` and `RichSnapshot`:

```python
@dataclass(frozen=True)
class MicrostructureBar:
    symbol: str
    start: datetime
    end: datetime
    avail: datetime
    # Midpoint & Stoikov Microprice OHLC
    open_mid: Decimal
    high_mid: Decimal
    low_mid: Decimal
    close_mid: Decimal
    close_microprice: Decimal          # (bid * ask_qty + ask * bid_qty) / (bid_qty + ask_qty)
    # Trade & Order-Flow Metrics (exact Decimal, never 0-stubbed when prints exist)
    trade_volume_base: Decimal
    trade_volume_quote: Decimal
    vwap: Decimal | None
    buy_aggressor_vol: Decimal
    sell_aggressor_vol: Decimal
    net_trade_delta: Decimal           # buy_aggressor_vol - sell_aggressor_vol
    order_flow_imbalance: Decimal      # Cont-Kukanov-Stoikov OFI summed across book updates in bar
    # Liquidity & Toxicity Metrics
    tw_spread_bps: Decimal             # time-weighted average spread in bps
    tw_top_imbalance: Decimal          # time-weighted (bid_qty - ask_qty) / (bid_qty + ask_qty)
    depth5_imbalance: Decimal | None   # top-5 level notional imbalance when depth is stored
    quote_count: int
    trade_count: int
```

- **Cont–Kukanov–Stoikov Order Flow Imbalance (`OFI`) update per quote step $k$:**
  $$\text{OFI}_k = \mathbb{I}_{b_k \ge b_{k-1}} q^b_k - \mathbb{I}_{b_k \le b_{k-1}} q^b_{k-1} - \mathbb{I}_{a_k \le a_{k-1}} q^a_k + \mathbb{I}_{a_k \ge a_{k-1}} q^a_{k-1}$$
- **Volume-Synchronized Probability of Informed Trading (`VPIN`):** Rolling bucket estimator over equal-quote-volume buckets $V_{\text{bucket}}$ measuring $|V_{\text{buy}} - V_{\text{sell}}| / V_{\text{bucket}} \in [0, 1]$.

### 5.2 Dual-Clock Event, Dollar-Volume & Dislocation Triggers (`services/session.py`)

Add `TriggerPolicy` to `PaperSession`:
1. `FixedBarTrigger(resolution)` — existing closed-bar schedule (`15min`, `1h`, `1day`).
2. `QuoteVolumeTrigger(quote_volume_threshold: Decimal)` — fires whenever cumulative traded quote notional since last decision reaches `quote_volume_threshold` (e.g. `10,000 USDT` on `BTCUSDT`), sampling fast during active bursts and sleeping during dead hours.
3. `DislocationTrigger(min_dislocation_bps: Decimal, cooldown: timedelta)` — fires immediately between bar closes when `|KalmanBasisResidual_bps| >= min_dislocation_bps` or `|Microprice - Mid|_bps >= min_dislocation_bps`, bounded by `cooldown` to prevent order spam.

### 5.3 Continuous Target-Position Protocol (`gym-core/src/gym/domain/target_protocol.py`)

```python
@dataclass(frozen=True)
class TargetIntent:
    target_weight: Decimal             # desired portfolio/account weight in [0, 1] on spot
    expected_alpha_bps: Decimal        # expected net horizon return in bps before this trade's fee
    urgency: str                       # "PASSIVE_MAKER" | "OPPORTUNISTIC" | "URGENT_TAKER" | "ABSTAIN"
    limit_offset_bps: Decimal | None   # passive offset deeper than near touch (>= 0), or None for hazard-optimal
    confidence: Decimal                # in [0, 1]
    reasons: tuple[str, ...]
    feature_values: dict[str, str | float | int | bool | None]
```

- **Backward Compatibility:** Legacy strategies implementing `decide(snap, holding)` are wrapped automatically via `LegacyStrategyAdapter` (`BUY_REQUEST -> target_weight=1`, `SELL_REQUEST -> target_weight=0`, `HOLD -> keep current weight`), keeping all 2,070+ existing tests unchanged.

### 5.4 Multi-Modal Continuous Forecast Graph (`gym-core/src/gym/domain/forecast_graph.py`)

Replace 1-bit `SignalBlend` with `ForecastGraph`:

1. **`ForecastNode` Interface:** `observe(rich_snap: RichSnapshot) -> float | None`, returning a continuous forecast normalized via trailing causal EWMA mean-absolute-deviation so $\mathbb{E}[|f_{i,t}|] = 10.0$, clipped to **`[-20.0, +20.0]`**.
2. **Four Orthogonal Built-In Wallex-Core Node Families (Pairwise Target `|corr| < 0.30`):**
   - **`MultiHorizonEwmacNode` (Group 1 — Price Trend):** Continuous volatility-normalized EWMAC across `(8, 32)`, `(16, 64)`, `(32, 128)`, `(64, 256)` using microprice closes and Yang–Zhang volatility $\hat{\sigma}_{\text{YZ},t}$:
     $$f_{\text{ewmac},k,t} = \text{clip}\!\left(s_k \cdot \frac{\text{EMA}_{\text{fast},t} - \text{EMA}_{\text{slow},t}}{\hat{\sigma}_{\text{YZ},t} \cdot P_t},\; -20,\; +20\right)$$
   - **`MicropriceOfiNode` (Group 2 — Order-Book & Flow Microstructure):** Combines microprice-to-mid skew $(P_{\text{micro}} - P_{\text{mid}})/\text{half\_spread}$, normalized `OFI`, and 5-level book slope, gated off when `VPIN > 0.75` (toxic informed flow).
   - **`KalmanTomanBasisNode` (Group 3 — Cross-Pair FX Basis):** Consumes primary `Coin/USDT` (or `Coin/TMN`), paired `Coin/TMN` (or `Coin/USDT`), and `USDTTMN`, returning the negative standardized Kalman residual $-z_t \cdot 10$ (§6.1) when local coin basis deviates from structural equilibrium.
   - **`CrossMarketBreadthRegimeNode` (Group 4 — Cross-Sectional Regime):** Consumes the 40-market cross-section state (`breadth_50d`, aggregate spread Z-score, 3-state regime probabilities $P(S_t)$ from §6.4) to modulate directional vs. mean-reverting node weights.
3. **Causal Shrinkage Forecast Combiner:**
   Given active node vector $\mathbf{f}_t \in [-20, 20]^K$, prior/equal weights $\mathbf{w}_0$ ($w_{0,i} = 1/K$), and shrunk trailing forecast correlation matrix $\hat{\mathbf{C}}_t = (1 - \lambda_c)\mathbf{C}_{\text{ewma},t} + \lambda_c \mathbf{I}$ ($\lambda_c = 0.30$):
   $$\text{FDM}_t = \min\!\left(\frac{1}{\sqrt{\mathbf{w}^\top \hat{\mathbf{C}}_t \mathbf{w}}},\; 1.75\right), \qquad F_t = \text{clip}\!\left(\text{FDM}_t \sum_{i=1}^{K} w_i f_{i,t},\; -20.0,\; +20.0\right)$$
   On long-only spot, negative combined forecasts map to `target_weight = Decimal(0)` (cash), while positive forecasts map linearly via volatility targeting:
   $$w^*_t = \text{clip}\!\left(\frac{\max(0, F_t)}{10.0} \cdot \frac{\sigma_{\text{target}}}{\hat{\sigma}_{\text{YZ},t}},\; 0,\; w_{\max}\right).$$

### 5.5 Inventory-Skewed Quoting & Hard Kill-Switches (`gym-core/src/gym/domain/quoting_policy.py`)

1. **Avellaneda–Stoikov Lite Reservation Price:**
   For passive maker execution around fair price $P_{\text{fair},t} = P_{\text{micro},t} \cdot (1 + \hat{\alpha}_{\text{short},t})$ with normalized inventory deviation $q_t = (w_{\text{held},t} - w^*_t) / w_{\max} \in [-1, 1]$:
   $$r_t = P_{\text{fair},t} \cdot \Big(1 - \gamma \cdot q_t \cdot \hat{\sigma}_t^2 \cdot \tau_{\text{horizon}}\Big)$$
   Bid and ask offsets are placed around $r_t$ by optimal depth $\delta^*$ (§6.5), naturally skewing bids lower when long inventory builds and asks lower to unwind inventory for spread profit.
2. **Hard Fail-Closed Circuit Breakers (`KillSwitchEvaluator`):**
   Immediately cancel resting orders and output `ABSTAIN` when any condition triggers:
   - `quote_age_s > 10.0` or collector shard disconnected,
   - `USDTTMN` spread `> 100 bps` or pair spread `> max(150 bps, 3.0 * median_7d_spread_bps)`,
   - `VPIN > 0.85` (extreme toxic flow spike),
   - Portfolio drawdown latch or accounting conservation violation,
   - *(Phase B ready)* `not nav_ref.market_open` or `abs(token_usdt - nav_ref.underlying_usd_price) / nav_ref.underlying_usd_price > Decimal("0.015")`.

---

## 6. Workstream 3 — Quantitative Modeling & Statistical Governance Specification

### 6.1 Irregular-Time Decay & 2-State Kalman Basis Filter (`gym-core/src/gym/domain/kalman_models.py`)

1. **Irregular-Time Exponential Decay (`IrregularEWMA`):**
   Replaces fixed-step `deque`s that call `.clear()` on gaps. Given elapsed seconds $\Delta t = t_k - t_{k-1} > 0$ and characteristic half-life $\tau_{1/2}$ ($\lambda = \ln(2) / \tau_{1/2}$):
   $$\alpha(\Delta t) = 1 - e^{-\lambda \Delta t}, \qquad m_k = (1 - \alpha(\Delta t)) m_{k-1} + \alpha(\Delta t) x_k.$$
   History is **never** wiped on a gap; stale state smoothly down-weights proportional to elapsed time.
2. **2-State Linear-Gaussian Kalman Basis Filter (`KalmanBasisFilter`):**
   Let $y_k = \ln(P_{\text{CoinTMN},k}) - \ln(P_{\text{CoinUSDT},k}) - \ln(P_{\text{USDTTMN},k})$ (in bps, $\times 10^4$) at irregular timestamps $t_k$ ($\Delta t_k = t_k - t_{k-1}$ in seconds).
   - **State vector:** $\mathbf{x}_k = [\mu_k,\; \epsilon_k]^\top$, where $\mu_k$ is the slow structural Iranian FX/coin equilibrium basis and $\epsilon_k$ is the fast mean-reverting microstructure dislocation with mean-reversion rate $\kappa > 0$:
     $$\mathbf{A}(\Delta t) = \begin{bmatrix} 1 & 0 \\ 0 & e^{-\kappa \Delta t} \end{bmatrix}, \qquad \mathbf{Q}(\Delta t) = \begin{bmatrix} q_\mu \Delta t & 0 \\ 0 & \frac{q_\epsilon}{2\kappa}(1 - e^{-2\kappa \Delta t}) \end{bmatrix}, \qquad \mathbf{H} = \begin{bmatrix} 1 & 1 \end{bmatrix}.$$
   - **Predict (strictly prior to observing $y_k$):**
     $$\hat{\mathbf{x}}_{k|k-1} = \mathbf{A}(\Delta t_k)\hat{\mathbf{x}}_{k-1|k-1}, \qquad \mathbf{P}_{k|k-1} = \mathbf{A}(\Delta t_k)\mathbf{P}_{k-1|k-1}\mathbf{A}(\Delta t_k)^\top + \mathbf{Q}(\Delta t_k).$$
   - **Standardized causal innovation (used for signal before update!):**
     $$\nu_k = y_k - \mathbf{H}\hat{\mathbf{x}}_{k|k-1}, \qquad F_k = \mathbf{H}\mathbf{P}_{k|k-1}\mathbf{H}^\top + R, \qquad z_k = \frac{\nu_k}{\sqrt{F_k}}, \qquad \hat{\epsilon}_{k|k} \text{ after Gain } \mathbf{K}_k = \mathbf{P}_{k|k-1}\mathbf{H}^\top / F_k.$$
   - Note: Across a multi-hour outage ($\Delta t_k \gg 1$), $\mathbf{P}_{k|k-1}$ automatically expands, shrinking $|z_k|$ naturally until fresh post-outage observations re-lock the structural level $\mu_k$ — zero manual `.reset()` required!

### 6.2 Hayashi–Yoshida Nonsynchronous Overlap Covariance (`gym-core/src/gym/domain/async_covariance.py`)

Replaces `PortfolioPolicy._history`'s synchronous-grid requirement (eliminating `GAPPED_HISTORY` shutdowns and intraday Epps-effect bias).
Given asynchronous price observations $\{(t^{(i)}_m, P^{(i)}_m)\}_{m=0}^{M_i}$ for each asset $i \in \{1, \dots, N\}$ over lookback window $[T - W, T]$ with log/simple returns $\Delta r^{(i)}_m$ over intervals $I^{(i)}_m = (t^{(i)}_{m-1}, t^{(i)}_m]$:

$$\hat{\Sigma}^{\text{HY}}_{ii} = \sum_{m=1}^{M_i} \big(\Delta r^{(i)}_m\big)^2, \qquad \hat{\Sigma}^{\text{HY}}_{ij} = \sum_{m=1}^{M_i} \sum_{l=1}^{M_j} \Delta r^{(i)}_m \Delta r^{(j)}_l \, \mathbb{I}\!\left(\min(t^{(i)}_m, t^{(j)}_l) > \max(t^{(i)}_{m-1}, t^{(j)}_{l-1})\right).$$

- Normalize per unit time (`/ W_seconds * target_horizon_seconds`), symmetrize, clip any small negative finite-sample eigenvalues at $\epsilon = 10^{-10} \cdot \text{tr}(\hat{\boldsymbol{\Sigma}})/N$ (`project_psd`), and apply constant-correlation shrinkage (`shrinkage_intensity = 0.25`). Computed in $O(M_i + M_j)$ per pair via two-pointer interval sweep!

### 6.3 Yang–Zhang Jump-Safe Volatility & Asymmetric Downside GJR-EWMA (`gym-core/src/gym/domain/volatility_models.py`)

1. **Yang–Zhang Estimator (`yang_zhang_volatility`):**
   Over $n \ge 10$ bars with log overnight jumps $o_t = \ln(O_t / C_{t-1})$, open-to-close $c_t = \ln(C_t / O_t)$, highs $u_t = \ln(H_t / O_t)$, and lows $d_t = \ln(L_t / O_t)$:
   $$\sigma_{\text{YZ}}^2 = \sigma_o^2 + k \sigma_c^2 + (1 - k)\sigma_{\text{RS}}^2, \quad k = \frac{0.34}{1.34 + \frac{n + 1}{n - 1}}, \quad \sigma_{\text{RS}}^2 = \frac{1}{n}\sum_{t=1}^{n}\big(u_t(u_t - c_t) + d_t(d_t - c_t)\big).$$
2. **Asymmetric Downside GJR-EWMA (`asymmetric_ewma_volatility`):**
   $$\sigma_t^2 = \left(1 - \alpha - \frac{\gamma}{2}\right)\sigma_{t-1}^2 + \big(\alpha + \gamma \mathbb{I}_{r_{t-1} < 0}\big) r_{t-1}^2 \qquad (\alpha = 0.06,\; \gamma = 0.08)$$
   Composite risk scale $\hat{\sigma}_t = \max(\sigma_{\text{YZ},t},\; \sigma_{\text{GJR},t})$ guarantees fast downside de-risking on crashes and jump-awareness across Wallex `USDTTMN` closures.

### 6.4 Online 3-State Filtered Regime Model (`gym-core/src/gym/domain/regime_filter.py`)

Define discrete latent states $S_t \in \{\text{MARKUP}=0,\; \text{CHOP}=1,\; \text{PANIC\_ILLIQUID}=2\}$ updated causally on 3 cross-sectional observables $\mathbf{z}_t = [\text{breadth\_50d}_t,\; \text{vol\_zscore}_t,\; \text{spread\_zscore}_t]^\top$ with fixed Markov transition matrix $\mathbf{\Pi}$ and diagonal Gaussian emission densities $\phi_k(\mathbf{z}_t)$:
$$\tilde{\mathbf{p}}_t = \mathbf{\Pi}^\top \mathbf{p}_{t-1}, \qquad p_{t,k} = \frac{\tilde{p}_{t,k} \phi_k(\mathbf{z}_t)}{\sum_{j=0}^{2} \tilde{p}_{t,j} \phi_j(\mathbf{z}_t)}.$$
- Output continuous state probabilities $(p_{\text{markup}}, p_{\text{chop}}, p_{\text{panic}})$ used by `ForecastGraph` to smoothly scale trend vs. passive-microstructure weights and shrink gross exposure toward `0` as $p_{\text{panic}} \to 1$.

### 6.5 Empirical Passive Quote-Placement Hazard Optimizer (`gym-core/src/gym/domain/quote_hazard.py`)

Calibrate on strictly prior historical windows `[t_train_start, t_train_end)` across candidate quote offsets $\delta \in \{0, 2, 5, 10, 15, 25, 40, 60\}\text{ bps}$ deeper than near touch:
- Measure empirical fill rate $\hat{p}_{\text{fill}}(\delta, b)$ (monotone PAVA isotonic-smoothed so $\hat{p}_{\text{fill}}$ is guaranteed non-increasing in $\delta$) and mean 5-minute adverse markout $\hat{m}(\delta, b)$ conditioned on coarse `(spread_bucket, ofi_tercile)` bin $b$ (with shrinkage toward global curve when bin count `< 50`).
- Choose at runtime:
  $$\delta^*(b) = \arg\max_{\delta} \; \hat{p}_{\text{fill}}(\delta, b) \cdot \left(\frac{\text{spread\_bps}}{2} + \delta - \text{maker\_fee\_bps} - \hat{m}(\delta, b)\right).$$
  If the maximum expected surplus is `<= min_edge_bps` (default `2.0 bps`), abstain (`URGENCY = "ABSTAIN"`).

### 6.6 Orthogonal Signal Gatekeeper & Surrogate Null Calibration (`gym-core/src/gym/domain/signal_gatekeeper.py`)

No candidate node enters `ForecastGraph` unless `evaluate_candidate_signal` passes all four checks on purged training/validation splits:
1. **Date-Clustered OOS Rank-IC:** `mean_ic > 0` and `t_stat_clustered >= 2.0`.
2. **Orthogonality:** $\max_{j \in \text{existing}} |\text{corr}(f_{\text{new}}, f_j)| < 0.70$ (or strictly higher net Sharpe when replacing $f_j$).
3. **Marginal Net Sharpe Uplift:** $\text{Sharpe}_{\text{net}}(\text{existing} \cup \{f_{\text{new}}\}) - \text{Sharpe}_{\text{net}}(\text{existing}) > 0.05$ after exact Wallex fees and cancel latency.
4. **Stationary Block-Bootstrap Surrogate Sanity Check:** Run the complete pipeline on `100` stationary-block-bootstrapped / random-sign return surrogates; confirm median surrogate Sharpe `<= 0` and `95th` percentile matches theoretical null (zero lookahead / sizing-bug leakage).

---

## 7. Sprint-by-Sprint Execution Plan (Phase A Wallex Core → `2027-02-08` Gate)

| Sprint | Target Window | Exact Code Deliverables | Verification & Acceptance Gate |
| --- | --- | --- | --- |
| **Sprint 1 — Financial Engine & TCA Core** | Nov 24 – Dec 7 | `domain/venue_contracts.py`, `domain/passive_execution.py`, `domain/tca_markout.py`, `domain/dual_numeraire.py`, `domain/execution_schedule.py`; wire arrival-state maker/taker classification & `structured_fees.json` into `services/session.py`; remove dead `AAPLXUSDT` & add `10%` band option in `services/mix_journal.py`. | Unit + property conservation tests (`Decimal` balance parity `== 0` error); markout decomposition identity holds to `1e-9`; 0 regressions across existing 2,070+ tests; 14 straight days of clean 40-market Wallex feed. |
| **Sprint 2 — Multi-Signal Vector Framework & Quant Models** | Dec 8 – Dec 22 | `domain/microstructure.py` (`MicrostructureBar`, `microprice`, `OFI`, `VPIN`), `domain/target_protocol.py`, `domain/forecast_graph.py`, `domain/convex_optimizer.py`, `domain/kalman_models.py`, `domain/async_covariance.py`, `domain/volatility_models.py`, `domain/regime_filter.py`, `domain/quote_hazard.py`, `domain/signal_gatekeeper.py`, `domain/quoting_policy.py`, `domain/tmn_carry.py`. | Hayashi–Yoshida passes asynchronous gap fixtures with zero `GAPPED_HISTORY`; Kalman innovation matches analytical variance; convex L1 optimizer matches brute-force grid on 4-asset fixtures; surrogate null test confirms zero lookahead. |
| **Sprint 3 — Pre-Registered Wallex Trials (2 Active Slots)** | Dec 23 – Jan 8 | **Active Trial #1 (Track A):** Wallex USDT Multi-Signal Passive Quoting (`MicropriceOfi + KalmanTomanBasis + Regime + QuoteHazard + InventorySkew`) on top liquid USDT pairs at `10 bps` maker with `250/500/1000ms` cancel-race stress.<br>**Active Trial #2 (Track B):** Multi-Asset Continuous-Vector Risk-Parity (`XAUTUSDT, SLVONUSDT, USOONUSDT, COPXONUSDT, BTCUSDT, ETHUSDT, USDT`) + separate `simulate_tmn_borrow_carry` study on `USDTTMN`/`XAUTTMN`. | Pre-registered in `trial-log.md` with pre-computed `MDE` before holdout scoring; all attempts logged in `trial_ledger.sqlite3`. |
| **Sprint 4 — Gate G1 Window, Calibration & Checkpoint** | Jan 9 – Feb 8, 2027 | Unbroken 30-day G1 feed window (`2027-01-09..2027-02-08`); live prospective shadow run with `sequential_e_process`; optional owner-approved `$50–$100` live calibration probe if Sprint 3 clears Track A/B; decision receipt `evidence/2027-02-08-checkpoint-decision.md`. | **Pass G1–G4** → unlock Stage 6 installed-host qualification & controlled capital ladder (`$200–$500` Tranche 1 → `$1k–$2.5k` Tranche 2 → depth-capped target), **and/or** trigger Phase B multi-venue plug-in. |

---

## 8. Phase B Multi-Venue Plug-In Specification (Preserved for Post-Core Expansion)

Because §4.1–§6.6 are strictly parameterized by `venue`, `FeeSchedule`, `QuoteSnapshot`, and `NavReference`, expanding beyond Wallex requires **only** thin venue adapters:

### 8.1 Nobitex Adapter (`gym-core/src/gym/adapters/nobitex.py` — Phase B)
- **Endpoints verified live (`200 OK` on 2026-11-24):** `GET https://apiv2.nobitex.ir/market/stats` (all `rls` + `usdt` tops; note `1 TMN = 10 RLS` unit conversion via `CurrencyUnit`) and `GET https://apiv2.nobitex.ir/v3/orderbook/{SYMBOL}`.
- **Exact `FeeSchedule` with permanent `-30%` discount (`permanent_discount = Decimal("0.30")`):**
  - `USDT` L1 (`0.10%` / `0.13%` base) → **`0.070%` (`7.0 bps`) maker / `0.091%` (`9.1 bps`) taker**.
  - `TMN/IRT` L1 (`0.20%` / `0.25%` base) → **`0.140%` (`14.0 bps`) maker / `0.175%` (`17.5 bps`) taker**.
- **Unlocked strategies using the exact Phase A engine:**
  1. **Nobitex ↔ Wallex Pre-Funded USDT Inventory Arb & Lead-Lag Passive Quoting** (`17.0–19.1 bps` combined fee hurdle; `+25–41 bps` gaps already observed live on `BTCUSDT`),
  2. **Nobitex Implied-FX Passive Basis** (`21.0–35.0 bps` fee hurdle against `+40–150 bps` observed `Coin/IRT ÷ Coin/USDT` vs. `USDT/IRT` gaps),
  3. **Cheaper Primary Crypto Execution** for Track B (`BTC`, `ETH`, `SOL`, `XRP` at `7.0 bps` maker and `~3–16 bps` spreads).

### 8.2 AbanTether RWA Adapter & NAV Guard (`gym-core/src/gym/adapters/abantether.py` — Phase B)
- **Measured OTC economics (2026-11-24):** Flat **`0.558%`** (`~27.9 bps`/side) round-trip buy/sell spread across Ondo (`*ON`) and Backed (`*B`) tokenized ETFs, bonds, and commodities (`https://api.abantether.ir/` authenticated KYC read/trade API).
- **Unlocked 5-Pillar Institutional All-Weather Track B Universe:**
  - *Global Equities:* `SPYON` (S&P 500), `QQQON` (Nasdaq-100), `IEFAON` (Developed ex-US)
  - *US Treasury & Aggregate Bonds (deflationary crisis hedge):* `TLTON` (20Y+ US Treasuries), `AGGON` (US Aggregate Bonds)
  - *Commodities (inflation hedge):* `IAUON` (Gold), `SLVON` (Silver), `USOON` (Oil), `COPXON` (Copper) — last three cross-routed against Wallex Ondo books
  - *Crypto:* `BTC`, `ETH` (routed to Nobitex `7.0 bps` maker)
  - *Safe Cash:* `USDT`
- **Five Mandatory Hardcoded Guards in `KillSwitchEvaluator` for AbanTether RWA:**
  1. **Live NAV-Premium Check (`NavReference`):** Reconcile `(Token_Quote_TMN ÷ USDTTMN)` against live US ETF price × `share_ratio`; hard refuse when `|nav_premium| > 1.5%` (prevents anomalies like the `14.7%` `SNDKON` vs. `SNDKB` discrepancy).
  2. **Zero-Volume & Duplicate-Issuer Filter:** Refuse `0`-volume listings (`NFLXON`, `SKHYB`) and prefer canonical liquid Ondo ETF tickers (`SPYON`, `QQQON`, `TLTON`, `AGGON`, `IAUON`, `IEFAON`).
  3. **Leveraged-ETF Exclusion:** Hard block 3× daily-reset ETFs (`TQQQB`, `SOXLB`, `KORUB`, `MUUB`) from Track B multi-day holds.
  4. **US Regular Market-Hours Gate:** Allow RWA execution strictly within `14:30–21:00 UTC` (`18:00–00:30 Tehran` standard time) on NYSE trading days.
  5. **Per-Issuer & Per-Venue Custody Caps:** Enforce `max_venue_share` and `max_issuer_share` in `solve_cost_aware_weights`.
