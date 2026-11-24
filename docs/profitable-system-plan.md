# Profitable System Master Specification — Wallex Core Engine First, Multi-Venue Plug-In Later

**Date:** 2026-11-24 (Status updated 2026-11-25) · **Scope:** Canonical architecture, financial-engine, trading-framework, and quantitative-modeling specification for reaching an independently verified net-profitable trading system.

> [!NOTE]
> **Implementation & Empirical Status (2026-11-25):** Phase A0/A1 financial engine, ADMM convex optimizer, Yang–Zhang/asymmetric volatility, causal multi-sleeve framework, pure-NumPy `EnsembleGRU`, and Nobitex 20-symbol live observation (`record_multi_venue_quotes.py` + `SIDE_ASYMMETRIC_ROUTER`) are **implemented and CI-verified**. The frozen v1 Champion (`70% BASE_13_S1_S5 (XAUT) + 30% 2h GRU-Ignition`) is actively journaling untouched forward observations on Windows Task Scheduler (`DISARMED`). See [evidence/README.md](../evidence/README.md) and [roadmap.md](../gym-core/docs/roadmap.md) for current empirical verdicts and v2 candidates.

**Hard Authority Boundary:** `TradingGYMExecutor` remains **`DISARMED / NOT CERTIFIED`** with a **`$0` funded-loss budget**. Phase A stays **100% paper** through the `2027-02-08` checkpoint. Passing the checkpoint authorizes entering Stage 6 installed-host qualification only — never automatic live arming or pre-checkpoint real-money probes ([2027-02-08-checkpoint-protocol.md](2027-02-08-checkpoint-protocol.md)).

---

## 1. Verified Baseline & Empirical Diagnosis (2026-11-24)

### 1.1 Current Status Against the Profitable-System Gate (`2027-02-08`)

| Gate | Requirement | Verified State on Disk (2026-11-24) | Verdict |
| --- | --- | --- | --- |
| **G1 — 30-day feed reliability** | `<= 10%` failed UTC days (`<= 3/30`) and max raw archive gap `<= 24.0h` over `2027-01-09..2027-02-08` | Live 40-market Wallex collector (`core-40-wallex`, watchlist `5078e0c5a62155c6`, `--depth-levels 5`) streams across **2 WebSocket shards** at `0s` lag (`*.ir` bypassed from VPN). Historical span (`2026-10-30..2026-11-23`) had 3 raw gaps `> 24h` (`49.0h`, `41.0h`, `35.0h`) and 17 unclosed segments. | **Stabilized live; 30-day qualification window starts 2027-01-09** |
| **G2 — Independently validated net edge** | Evaluated against **both** v1 (`2026-11-21`, `8fba0b1`: validation + independently consumed holdout `DSR >= 0.95`) and v2 (`2026-11-24`: Track A high-$N$ `DSR >= 0.95` or Track B multi-year OOS `DSR >= 0.95` + completed 90-day live-paper shortfall audit) | `data/live/research_protocol.sqlite3` has `0` evaluations and `0` outcomes. `trials()` parses **21 registered hypotheses** in [trial-log.md](../gym-core/docs/trial-log.md) (`17 FAIL`, `1 NARROW_PASS`, `1 PASS` on stand-in proxies, `2 OPEN` background forward monitors), plus `98,161` exploratory rows in `trial_ledger.sqlite3`. | **NOT MET** |
| **G3 — Authority & admission** | Automated ADR 0006/0007/0008 checks green; `DISARMED` invariant intact | Source Rust/Python/browser suites pass; installed Windows service `TradingGYMExecutor` is `Stopped` / `Disabled` (`2026-11-06` binaries, `custody_requalified: false`, `funded_authority: false`, `capital_quanta: "0"`). | **In source only** |
| **G4 — Owner sign-off** | Written decision in `evidence/2027-02-08-checkpoint-decision.md` | Default **NO-GO** until `2027-02-08`. | **Open** |

### 1.2 Economic Constraints Established by Empirical Evidence

1. **Wallex Published Fee Asymmetry ([structured_fees.json](../data/live/structured_fees.json)):**
   - **USDT spot pairs (Level 1):** `0.10%` (`10.0 bps`) maker / `0.13%` (`13.0 bps`) taker → **`20.0–26.0 bps` round trip**.
   - **TMN spot pairs (Level 1):** `0.25%` (`25.0 bps`) maker / `0.30%` (`30.0 bps`) taker → **`50.0–60.0 bps` round trip** (**2.3×–2.5× more expensive** than USDT pairs).
   - **Explicit Maker Burden:** On a `25 bps` USDT spread at `10 bps` maker fee per side, completing **both** passive sides around a stationary mid earns ~`+5 bps` before adverse selection, queue non-fills, and inventory unwind — whereas crossing both sides at `13 bps` taker costs ~`-51 bps`. Because `thin-market-quoting` lost after fees in 12/13 candidates and `book-imbalance` moved the 5-minute mid by only `0.7–4.4 bps`, passive quoting must prove positive net incremental proceeds under conservative fill and unwind bounds (**Experiment 0**, §7.1) before building complex signal layers.
2. **Order-Book Depth & Residual Inventory ([2026-11-22-historical-replay-financial-audit.md](../evidence/2026-11-22-historical-replay-financial-audit.md), [whole-market-research-plan.md](whole-market-research-plan.md)):**
   - Hourly `ema-trend 8/21` lost quote capital in **320 of 337 traded markets** (median `-9.73%` TMN, `-11.15%` USDT).
   - In the 45-minute post-cutoff exit replay at `25%` participation, 131 of 137 positions reduced size and **only 2 of 137 fully closed**, demonstrating severe residual-inventory tail risk outside top liquid pairs.
3. **Currency Denomination of Margin Borrowing (`~33%/yr`):**
   - **Shorting `BTCUSDT` (BTC debt, USDT collateral):** Pays `0.015%` every 4 hours (`~32.85%/yr`) + `0.25%` open / `0.10%` close + forced 21-day reopening **in USDT terms**, losing in 60/60 cells in `trend-with-short-side` (29/60 liquidated) vs. holding `USDT` cash at `0%` borrow cost.
   - **Long `USDTTMN` or `XAUTTMN` using TMN-denominated debt:** Borrows **TMN** against assets historically appreciating in TMN (treated as an explicit scenario input, never an assumed constant), subject to 6–9 month flat-Toman carry bleed, rejected renewal, and pullback liquidation risk (`<= 1.5x–2.0x` cap).
4. **Statistical Power & Sequential Betting Calibration ([2026-11-18-detectable-edge.md](../evidence/2026-11-18-detectable-edge.md), [statistical_inference.py](../gym-core/src/gym/domain/statistical_inference.py)):**
   - Daily rules had `MDE >= 10 bps/day`. Furthermore, `sequential_e_process` with default `lower_bound = 0.5` caps bet fraction `lambda <= 1.0`, yielding only `e ≈ 1.0126` over 30 consecutive `+5 bps` days against `threshold = 20.0`. Sequential e-processes must set `lower_bound` to a **proven per-decision/per-clip loss bound** and pass a pre-registration Monte Carlo power check (`>= 80%` detection probability over the declared window) before serving as a gate.

### 1.3 Baseline Upgrades Delivered on 2026-11-24

- **Collector cut to 40 curated markets with 5-level depth (`core-40-wallex`, watchlist `5078e0c5a62155c6`, `--depth-levels 5`, 2 WS shards):** Covers 6 dual-quoted TMN/USDT triangles (`BTC, ETH, SOL, XRP, XAUT, PEPE`), `USDTTMN`, and 27 additional liquid USDT pairs (100% of active forward-journal USDT symbols except halted `AAPLXUSDT`).
- **Losing hourly EMA jobs paused:** All 5 scheduled `ema-trend 8/21` jobs in `data/live/research.sqlite3` paused (`enabled = 0`).
- **Live `/v2/structured-fee` ingestion & quote-aware published fees:** Implemented in [collector.py](../gym-core/src/gym/services/collector.py), [market_quality.py](../gym-core/src/gym/services/market_quality.py), and [cost_defaults.py](../gym-core/src/gym/services/cost_defaults.py) (retaining undiscounted fallback whenever volume-tier eligibility is unverified).
- **Standalone causal passive cancel/replace simulator:** `simulate_passive_cancel_replace` added in [execution_qualification.py](../gym-core/src/gym/domain/execution_qualification.py).
- **Governance & sequential e-values:** Background forward monitors (`funding-confirmed-trend-forward`, `breadth-trend-forward`) separated from the 2 active hypothesis seats (`remaining: 2`) while remaining in the multiplicity denominator ([trial_governance.py](../gym-core/src/gym/services/trial_governance.py), [evidence.py](../gym-core/src/gym/services/evidence.py)).

---

## 2. Strategic Sequencing & Permanent Scope Freeze

### 2.1 Experiment-First Phased Sequencing

1. **Phase A0 (WEEK 1 GATE — Feasibility & Execution Economics First):**
   Before building the multi-module forecast stack, run **Experiment 0** (§7.1) on already-accessed `BTCUSDT` and 6-triangle development data: (a) constrained hindsight dynamic-programming ceiling, (b) fixed-size, fixed-offset passive maker replay vs. immediate execution vs. cash under an **$O(1)$ adversarial ambiguous-print lower bound**, and (c) microstructure execution-timing overlay on already-required slow rebalances. Advance only mechanisms with positive net incremental USDT after unwinding.
2. **Phase A1 (Wallex 40-Market Core Engine):**
   Upgrade the **financial engine**, **multi-signal trading framework**, and **quantitative modeling** stack for mechanisms passing Phase A0, parameterized cleanly by `venue`, `FeeSchedule`, `OrderSpec`, `QuoteSnapshot`, and `NavReference`.
3. **Phase B (Post-Core Iranian Multi-Venue Plug-In):**
   Plug **Nobitex** (permanent **`-30%`** discount: `7.0/9.1 bps` USDT, `14.0/17.5 bps` IRT; deep books) and **AbanTether** (`0.558%` flat round-trip OTC across tokenized US equities, US Treasury bonds, and commodities) into Phase A's adapters (§8).
4. **Phase C (Optional Future — Global Perpetuals):**
   Optional perpetual adapter (e.g., Hyperliquid) with explicit collateral, mark/index basis, funding reversal, and liquidation contracts.

### 2.2 Strict Engineering Freeze (Until Gate G2 Passes)

- **FROZEN:** 373-market whole-catalogue replay expansions, new EN/FA Web UI views, Rust `executor/` feature additions (`DISARMED`), single-venue price-only TA sweeps, and BTC/USDT-denominated margin shorting.

---

## 3. Code-Level Audit of the 12 Structural Flaws in `gym-core`

| # | Pillar | File & Lines | Exact Defect in Current Code | Architectural Replacement |
| --- | --- | --- | --- | --- |
| **F1** | Financial Engine | [session.py#L391-L486](../gym-core/src/gym/services/session.py#L391-L486) | `settle_limit` freezes `pending.limit = top.bid` once for the entire `max_wait`, credits crossing-quote capacity without prints (`lines 451-459`), counts ambiguous duplicate prints optimistically, and stamps `order["maker"] = True` unconditionally without arrival-state post-only/taker classification. | Arrival-state maker/taker/post-only classifier + dynamic pegged child orders + $O(1)$ adversarial duplicate-print bound (§4.2). |
| **F2** | Financial Engine | [portfolio_policy.py#L89-L218](../gym-core/src/gym/domain/portfolio_policy.py#L89-L218) | `PortfolioPolicy.weights(observations)` takes past prices only (**zero expected-return forecast $\hat{\mu}_i$**) and applies rebalance thresholds per coin independently, paying double fees to swap correlated assets (`corr(BTC, ETH) = 0.85`). | Joint convex trade optimizer with L1 exact fee-zone, quadratic depth penalty, and post-rounding cash/cap verification (§4.3). |
| **F3** | Financial Engine | [session.py#L290-L300](../gym-core/src/gym/services/session.py#L290-L300) | Submits orders immediately at bar close, ignoring spread compression windows and book-recovery timing. | Decoupled signal clock vs. bounded-wait execution overlay scored on total implementation shortfall (§4.4). |
| **F4** | Financial Engine | [sim.py#L523-L533](../gym-core/src/gym/domain/sim.py#L523-L533) | Stops cost attribution at fill instant (`spread + fees + latency_drift`), hiding post-fill adverse selection and unliquidated deadline inventory. | Strictly post-fill multi-horizon TCA markout & deadline-liquidation engine (§4.5). |
| **F5** | Trading Framework | [strategy.py#L107-L129](../gym-core/src/gym/domain/strategy.py#L107-L129), [session.py#L231-L232](../gym-core/src/gym/services/session.py#L231-L232) | Binary `0%`/`100%` `decide(snap, holding)` contract; holding `> 1%` equity sets `holding = True`, blocking scale-ins and partial trims. | Continuous target-weight protocol (`TargetIntent`) with exact free-cash-preserving `LegacyStrategyAdapter` (§5.3). |
| **F6** | Trading Framework | [blend_strategies.py#L21-L72](../gym-core/src/gym/domain/blend_strategies.py#L21-L72) | Restricts blends to single-market price-only rules and quantizes signals to `1-bit` votes, destroying signal magnitude and excluding book/cross-pair inputs. | Multi-modal continuous `[-20, +20]` forecast graph mapped explicitly to horizon expected gross bps (§5.4). |
| **F7** | Trading Framework | [bars.py#L200-L206](../gym-core/src/gym/domain/bars.py#L200-L206), [session.py#L127-L128](../gym-core/src/gym/services/session.py#L127-L128) | Quote bars pass `qty = 0` on naive `(bid+ask)/2` midpoints and `Snapshot` drops `bid_qty`, `ask_qty`, `depth`, and signed trade flow. | `MicrostructureConsolidator` + `RichSnapshot` exposing Stoikov `microprice`, L1 `OFI`, 5-level book slope (`--depth-levels 5`), `VWAP`, and `VPIN` (§5.1). |
| **F8** | Trading Framework | [session.py#L101](../gym-core/src/gym/services/session.py#L101) | Fixed wall-clock closes only; misses fast intra-bar dislocations and lacks deterministic tie/cooldown precedence. | Deterministic dual-clock triggers (`FixedBar`, `QuoteVolume`, `Dislocation`) with frozen priority & cooldown rules (§5.2). |
| **F9** | Quantitative Modeling | [cross_market_strategies.py#L42-L45](../gym-core/src/gym/domain/cross_market_strategies.py#L42-L45), [L128-L139](../gym-core/src/gym/domain/cross_market_strategies.py#L128-L139), [portfolio_policy.py#L131-L132](../gym-core/src/gym/domain/portfolio_policy.py#L131-L132) | Single-bar gap calls `.clear()`/`.reset()` and `PortfolioPolicy._history` raises `GAPPED_HISTORY` on any irregular interval across markets. | Explicit gap taxonomy (quiet vs. scheduled closure vs. outage) + continuous-time irregular decay + Hayashi–Yoshida overlap covariance (§6.1, §6.2). |
| **F10** | Quantitative Modeling | [cross_market_strategies.py#L61-L75](../gym-core/src/gym/domain/cross_market_strategies.py#L61-L75) | `TomanPremium` uses static moments on a single triangle, conflating market-wide Toman repricing with coin-specific staleness. | Leave-one-coin-out common FX reference + 2-state Kalman basis filter with explicit traded-leg sign convention (§6.1). |
| **F11** | Quantitative Modeling | [sim.py#L159-L165](../gym-core/src/gym/domain/sim.py#L159-L165), [volatility.py](../gym-core/src/gym/domain/volatility.py) | 20-bar close-to-close std / basic Parkinson ignores session-closure jumps and weights crashes identically to rallies. | Yang–Zhang jump-safe OHLC variance + asymmetric downside GJR-EWMA volatility (§6.3). |
| **F12** | Quantitative Modeling | *(Absent in repo)* | Passive limit orders lack calibrated offset selection and confuse simulator-assumed fills with true fill hazard. | Fixed-offset baseline first, followed by empirical PAVA fill-hazard & conditional-payoff optimizer with optimistic/adversarial queue bounds (§6.5). |

---

## 4. Workstream 1 — Financial Engine Specification

### 4.1 Venue-Agnostic Domain Contracts & Instrument Master (`gym-core/src/gym/domain/venue_contracts.py`)

```python
@dataclass(frozen=True)
class FeeTier:
    level: str
    min_30d_quote_volume: Decimal | None  # None when threshold is unverified -> force Level-1 undiscounted fallback
    maker_rate: Decimal
    taker_rate: Decimal

@dataclass(frozen=True)
class FeeSchedule:
    venue: str                            # "wallex" | "nobitex" | "abantether"
    venue_kind: str                       # "SPOT_BOOK" | "OTC_QUOTE" | "PERPETUAL_BOOK"
    quote_asset: str                      # "USDT" | "TMN"
    tiers: tuple[FeeTier, ...]
    permanent_discount: Decimal           # Decimal("0") unless verified by account receipt
    discount_expires_at: datetime | None
    fee_in_received_asset: bool           # True on Wallex spot (base debited on BUY, quote debited on SELL)
    observed_at: datetime
    source: str

    def effective_rates(self, as_of: datetime, rolling_30d_volume: Decimal = Decimal(0), *, zero_fee: bool = False) -> tuple[Decimal, Decimal]:
        if zero_fee:
            return Decimal(0), Decimal(0)
        selected = self.tiers[0]
        for tier in self.tiers:
            if tier.min_30d_quote_volume is not None and rolling_30d_volume >= tier.min_30d_quote_volume:
                selected = tier
        disc = self.permanent_discount if (self.discount_expires_at is None or as_of < self.discount_expires_at) else Decimal(0)
        mult = Decimal(1) - disc
        return selected.maker_rate * mult, selected.taker_rate * mult

@dataclass(frozen=True)
class InstrumentMaster:
    venue: str
    symbol: str
    underlying_id: str                    # e.g. "BTC", "SPY", "SLV_ETF", "COPX_EQUITY_ETF", "XAUT_GOLD"
    issuer: str | None                    # None for native crypto; "ondo" | "backed" | "tether" for tokenized assets
    product_kind: str                     # "CRYPTO_SPOT" | "TOKENIZED_ETF" | "TOKENIZED_COMMODITY" | "FIAT_FX"
    trading_calendar: str                 # "24X7" | "TEHRAN_FX_SESSION" | "NYSE_CORE"
    price_decimals: int
    qty_decimals: int
    min_qty: Decimal
    min_notional: Decimal
    market_order_enabled: bool
    post_only_supported: bool
    custody_eligible: bool                # False excludes asset from funded proposals while keeping research visibility

@dataclass(frozen=True)
class QuoteSnapshot:
    venue: str
    symbol: str
    ts_event: datetime | None             # None when venue REST omits event clock; never fabricated from ts_avail
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
    underlying_ticker: str                # e.g. "SPY", "TLT", "SLV", "USO", "COPX"
    underlying_usd_price: Decimal
    usdt_usd_basis: Decimal               # USDT price in USD (e.g. Decimal("1.0000"))
    fx_usdt_to_quote: Decimal             # Decimal(1) for USDT pairs; executable USDTTMN ask/bid for TMN pairs
    share_ratio: Decimal                  # point-in-time underlying shares per 1.0 token (tracks splits/distributions)
    observed_at: datetime
    session_open: bool                    # evaluated from exchange calendar (handles EDT/EST DST & early closes)
```

### 4.2 Arrival-State Passive Matching, Pegged Child Orders & $O(1)$ Adversarial Print Bound (`gym-core/src/gym/domain/passive_execution.py`)

1. **Arrival Classification (`t_arr = t_send + send_latency`):**
   Evaluate against latest qualified `top_arr` (`ts_avail <= t_arr`):
   - `BUY` with `limit_price >= top_arr.ask`: transition to `POST_ONLY_REJECTED` when `post_only=True`, else execute immediately at `top_arr.ask` with `liquidity_role = "TAKER"`, `taker_rate`, and received-asset fee debit (base debited on `BUY`, quote debited on `SELL`).
   - `BUY` with `limit_price < top_arr.ask`: enter `RESTING_MAKER` with cash reserved immediately in `CashBook`. Never credit crossing-quote capacity without qualifying trade prints unless `allow_quote_cross_fill=True` is explicitly enabled as an optimistic sensitivity bound.
2. **Cancel-in-Flight Race & Uncertain Cancel State:**
   - When re-pegging or canceling at `cancel_sent_at`, the prior resting order stays exposed to opposing prints over `[cancel_sent_at, cancel_sent_at + cancel_latency)`.
   - Shared print capacity is conserved across simultaneous child orders on the same symbol (`remaining_print_qty` decremented in deterministic priority order).
   - If a feed gap occurs before `cancel_effective_at`, enter `UNCERTAIN_CANCEL`, block new risk on that symbol, and reconcile before resuming.
3. **$O(1)$ Adversarial Ambiguous-Print Lower Bound (`duplicate_print_mode`):**
   Instead of branching $2^K$ account trees on indistinguishable trade prints (Wallex REST/WS omits trade IDs), run three linear-time passes on identical inputs:
   - `"optimistic"`: all observed prints drain queue and fill.
   - `"deduplicated"`: identical `(ts_event, price, qty, aggressor)` prints count once (`unambiguous_filled_qty`).
   - `"adversarial_lower_bound"`: an ambiguous duplicate print fills the resting order **if and only if** the 5-minute post-fill markout (or realized exit) is **negative**, and is treated as a transport duplicate (no fill) whenever profitable. Any passive strategy positive under `"adversarial_lower_bound"` is provably robust to print-duplication ambiguity without combinatorial state forking.

### 4.3 Ownership Chain & Convex Single-Period Trade Optimizer (`gym-core/src/gym/domain/convex_optimizer.py`)

Enforce a single strictly ordered decision chain:
`Normalized Forecast f_i in [-20, +20]` → `Horizon Expected Gross Return mu_i (bps)` → `Convex Portfolio Target w*` → `Lot-Rounded Executable Child Order`.

- **Forecast-to-Return Mapping:** $\hat{\mu}_{i,t} = \frac{f_{i,t}}{10.0} \cdot \text{IC}_{\text{prior}} \cdot \hat{\sigma}_{i,t}$, where $\text{IC}_{\text{prior}}$ is a conservative fixed scaling constant (e.g. `0.05`, or training-fold shrunk `Rank-IC`) and $\hat{\sigma}_{i,t}$ is expressed at the portfolio's rebalance horizon.
- **Optimization Problem:**
  $$\min_{\mathbf{w} \in \mathbb{R}^N} \; \frac{\lambda}{2}\mathbf{w}^\top \boldsymbol{\Sigma}\mathbf{w} - \hat{\boldsymbol{\mu}}^\top \mathbf{w} + \sum_{i=1}^{N} \tau_i |w_i - w_i^0| + \frac{1}{2}\sum_{i=1}^{N} \kappa_i (w_i - w_i^0)^2$$
  subject to $0 \le w_i \le w_{\max}$, $\sum_{i \in G_u} w_i \le w_{\text{underlying\_max}}$ (linking `BTCTMN` + `BTCUSDT`), $\sum_{i \in G_{\text{issuer}}} w_i \le w_{\text{issuer\_max}}$, and $\sum_i w_i \le 1 - c_{\text{buf}} - w_{\text{reserved\_open\_orders}}$.
- **Post-Solve Exact Verification:** Solve via cyclical coordinate descent with L1 soft-thresholding (`max_iter = 200`, KKT optimality residual `< 1e-7`), convert $\Delta w_i$ to floored `Decimal` lots, and re-verify exact native-currency cash sufficiency, `min_notional`, and displayed exit depth. Always benchmark against a simple fixed `10%` no-trade-band allocator on identical forecasts.

### 4.4 Turnover-Saving Execution-Timing Overlay (`gym-core/src/gym/domain/execution_schedule.py`)

Isolate execution timing value on **already-required parent trades** (`OpportunisticWindowPolicy`):
- Given a parent rebalance delta $\Delta Q$ decided at `t_0` with completion deadline `t_0 + T_max`:
  - Compare three matched account paths starting from identical inventory and ending with identical target exposure (forcing completion at `t_0 + T_max` at executable touch/depth if still unfilled):
    1. `IMMEDIATE`: cross/place at `t_0`,
    2. `FIXED_PASSIVE`: rest passive limit for `T_max`,
    3. `OPPORTUNISTIC_RECOVERY`: wait inside `[t_0, t_0 + T_max]` until `spread_bps <= p35_spread_bps` or post-burst depth recovers (verified by distinct source receipt references, not repeated heartbeat rows), with `adverse_drift_limit_bps` stop-chase guard.
- Report implementation shortfall (`decision_mid` to realized all-in VWAP including deadline completion cost), delay exposure time, and missed size across multiple weeks.

### 4.5 Strictly Post-Fill TCA Markout & Exit-Liquidity Stress (`gym-core/src/gym/domain/tca_markout.py`)

1. **Strictly Post-Fill Markout Lookup (`compute_fill_markouts`):**
   For each fill at `t_fill` and each horizon $h \in \{5, 30, 300, 3600\}$ seconds:
   - Select the **first** qualified `BookTop` satisfying `t_fill + timedelta(seconds=h) <= quote.ts_avail <= t_fill + timedelta(seconds=h + max_post_tolerance(h))` where `max_post_tolerance(h) = min(h, 60)` seconds (so `t_quote > t_fill` holds **strictly** — a pre-fill quote is **never** admitted!).
   - When no quote falls in that post-fill window, record `MISSING_POST_FILL_QUOTE` stratified by `(symbol, side, market_state)` rather than imputing zero adverse selection.
   - Single-ledger shortfall waterfall (every leg counted once with consistent sign):
     `Decision Mid -> Arrival Delay Drift -> Spread Capture / Crossing Cost -> Venue Fee (in actual debited asset) -> 5m Adverse Markout -> Post-5m Signal Drift -> Unfilled Opportunity / Deadline Unwind`.
2. **Value-Weighted Exit Risk Metrics:**
   Report minutes required to liquidate `50%`, `90%`, and `100%` of **held USDT-equivalent value**, cash recovered by deadline under three depth-replenishment assumptions (`no_replenishment`, `distinct_source_ref_only`, `full_displayed`), residual dust, and unpriced exposure.

### 4.6 Corrected Executable Dual-Numeraire Accounting & TMN-Borrow Carry (`gym-core/src/gym/domain/dual_numeraire.py`, `tmn_carry.py`)

1. **Executable FX Side Rules (`USDTTMN` quoted in TMN per 1 USDT, `bid < ask`):**
   - **Positive TMN balance → executable USDT estimate:** divide by **`USDTTMN.ask`** (`tmn_amount / ask * (1 - fx_taker_fee)`).
   - **Positive USDT balance → executable TMN estimate:** multiply by **`USDTTMN.bid`** (`usdt_amount * bid * (1 - fx_taker_fee)`).
   - **TMN liability → USDT cost to cover:** divide by **`USDTTMN.bid`**.
   - **USDT liability → TMN cost to cover:** multiply by **`USDTTMN.ask`**.
   - Report (a) booked native currency balances, (b) executable liquidation proceeds within declared depth by deadline, (c) unliquidated residual inventory, (d) **absolute net dollar/TMN profit after incremental operating costs** (alongside Sharpe), and (e) exact TMN return decomposition: `R_TMN = (1 + R_USDT)(1 + R_FX) - 1 = R_USDT + R_FX + R_USDT * R_FX`.
2. **Preview-Reconciled `simulate_tmn_borrow_carry` (`tmn_carry.py`):**
   Bind TMN loan currency, pledged guarantee collateral, `0.015%` 4-hourly extension fee, warning/liquidation prices, and 21-day expiry directly to saved Wallex margin preview schemas ([wallex-margin.md](../gym-core/docs/wallex-margin.md)). Explicitly test: (a) rejected renewal at day 21, (b) price gap below liquidation price on thin depth, (c) simultaneous 4h fee + 21d roll events, and (d) head-to-head comparison against **unlevered `1x` ownership of `USDTTMN` / `XAUTTMN`** over identical dates across multiple FX appreciation scenarios (`0%`, `25%`, `50%`).

---

## 5. Workstream 2 — Trading Framework Specification (Multi-Signal Vector Pipeline)

### 5.1 Microstructure-Complete Consolidator & Snapshot (`gym-core/src/gym/domain/microstructure.py`)

With `--depth-levels 5` enabled on the 40-market collector, `MicrostructureConsolidator` consumes `BookTop` and `TradeTick` streams in causal `ts_avail` order (preserving `ts_event=None` as unknown when absent, and separating observed aggressor prints from unknown gap intervals):
- **Stoikov Microprice:** $P_{\text{micro}} = \frac{P_{\text{bid}} Q_{\text{ask}} + P_{\text{ask}} Q_{\text{bid}}}{Q_{\text{bid}} + Q_{\text{ask}}}$.
- **L1 Event-Driven Cont–Kukanov–Stoikov `OFI`:** Computed on each published L1 `BookTop` transition (`bid`, `ask`, `bid_qty`, `ask_qty`), accompanied by `top_age_ms` and `l2_depth5_imbalance` (flagged as top-triggered snapshot when deeper levels only update alongside L1 or 60s heartbeats).
- **Signed Trade Flow & `VPIN`:** Tracks `buy_aggressor_vol`, `sell_aggressor_vol`, `vwap`, and volume-bucketed `VPIN` strictly from verified prints.

### 5.2 Deterministic Multi-Trigger Precedence (`services/session.py`)

When multiple triggers (`FixedBarTrigger`, `QuoteVolumeTrigger`, `DislocationTrigger`) fire on the same observation `ts_avail`:
1. Settle/advance any open child order or cancel-in-flight **first**.
2. Evaluate `KillSwitchEvaluator` **second** (an active circuit breaker preempts all entry triggers).
3. Coalesce simultaneous triggers into **one** decision evaluation at `ts_avail` with deterministic reason ordering `("DISLOCATION", "QUOTE_VOLUME", "FIXED_BAR")`, enforcing `cooldown` before the next non-bar trigger and never emitting duplicate orders while a parent target is already working.

### 5.3 Fraction-Preserving Target-Position Protocol & Expiry (`gym-core/src/gym/domain/target_protocol.py`)

```python
@dataclass(frozen=True)
class TargetIntent:
    version_id: int
    predecessor_version_id: int | None
    decided_at: datetime
    expires_at: datetime               # entry intent expires if unfilled; held exit follows inventory policy
    target_weight: Decimal             # desired account weight in [0, 1] on spot
    expected_gross_bps: Decimal        # horizon expected gross return in common currency
    urgency: str                       # "PASSIVE_MAKER" | "OPPORTUNISTIC" | "URGENT_TAKER" | "ABSTAIN"
    limit_offset_bps: Decimal | None
    reasons: tuple[str, ...]
    feature_values: dict[str, str | float | int | bool | None]
```

- **Exact `LegacyStrategyAdapter` Mapping:** Given current held weight $w_{\text{held}} = \frac{Q_{\text{base}} \cdot P_{\text{bid}}}{E}$ and free-cash share $w_{\text{free}} = \frac{C_{\text{free\_quote}}}{E}$:
  - `BUY_REQUEST(fraction)` $\mapsto w^* = \min\!\big(1,\; w_{\text{held}} + \text{fraction} \cdot w_{\text{free}}\big)$ (so `20%` held + `25%` of `80%` free cash maps to **`40%`**, never `100%`!).
  - `SELL_REQUEST(fraction)` $\mapsto w^* = w_{\text{held}} \cdot (1 - \text{fraction})$.
  - `HOLD` $\mapsto w^* = w_{\text{held}}$; `ABSTAIN_*` preserves abstention reason and leaves working orders governed by their `expires_at` contract.
- **Target Revision With Working Remainder:** Required child delta is always `target_units - held_units - working_uncanceled_units`, verified across restart checkpoints.

### 5.4 Multi-Modal Continuous Forecast Graph & 2×2 Attribution (`gym-core/src/gym/domain/forecast_graph.py`)

1. **Multi-Horizon Alignment:** Fast microstructure nodes (`MicropriceOfiNode`, 1–5m horizon) are **not** summed naively into slow daily forecasts (`MultiHorizonEwmacNode`). Instead:
   - Slow nodes (`G1: MultiHorizonEwmacNode`, `G4: CrossMarketBreadthRegimeNode`) set the **parent target weight $w^*_t$**.
   - Fast nodes (`G2: MicropriceOfiNode`, `G3: LeaveOneOutKalmanBasisNode`) act first as **execution-timing / quote-skew / toxicity-veto overlays** (§4.4, §5.5), and only enter standalone Track A directional forecasts at their matched short horizon after passing §6.6.
   - Regime state $P(S_t)$ acts strictly as a **conditioning multiplier** on node weights — never double-counted as an additive forecast alongside the nodes it conditions.
2. **Mandatory 2×2 Attribution Matrix:** Every combined candidate replays four matched arms on identical development dates — `A: (Baseline Signal, Baseline Exec)`, `B: (New Signal, Baseline Exec)`, `C: (Baseline Signal, New Exec)`, `D: (New Signal, New Exec)` — reporting `Signal = B - A`, `Execution = C - A`, and `Interaction = D - B - C + A` (summing to `D - A` identically).

### 5.5 Inventory-Skewed Quoting & Calendar-Aware Kill-Switches (`gym-core/src/gym/domain/quoting_policy.py`)

1. **Stepwise Quoting Progression:** Start with **one fixed quote offset $\delta_0$ and one hard inventory cap $w_{\max}$** as the baseline control; enable Avellaneda–Stoikov reservation skew $r_t = P_{\text{micro},t}(1 - \gamma q_t \hat{\sigma}_t^2 \tau)$ only if it beats the fixed-offset control on development data.
2. **Hard Fail-Closed Circuit Breakers (`KillSwitchEvaluator`):**
   - `quote_age_s > 10.0`, collector shard disconnected, or `UNCERTAIN_CANCEL` state active,
   - `USDTTMN` spread `> 100 bps` or pair spread `> max(150 bps, 3.0 * median_7d_spread_bps)`,
   - `VPIN > 0.85` (tested against an exposure-matched constant-cash control to verify selective crash avoidance),
   - *(Phase B RWA Guard — Share-Ratio & Calendar Exact):*
     $$\text{fair\_quote} = \text{nav\_ref.underlying\_usd\_price} \times \text{nav\_ref.share\_ratio} \times \text{nav\_ref.usdt\_usd\_basis} \times \text{nav\_ref.fx\_usdt\_to\_quote}$$
     Refuse immediately if `not nav_ref.session_open` (evaluated from NYSE holiday/early-close/DST calendar, e.g. `18:00 UTC` early close on Nov 27) or `abs(token_mid - fair_quote) / fair_quote > Decimal("0.015")`.

---

## 6. Workstream 3 — Quantitative Modeling & Statistical Governance Specification

### 6.1 Gap Taxonomy, Leave-One-Coin-Out FX Factor & Traded-Leg Kalman Basis (`gym-core/src/gym/domain/kalman_models.py`)

1. **Explicit Gap Classification:** Classify every interval $\Delta t_k$ into `ROUTINE_QUIET` (connected shard, zero book change), `SCHEDULED_CLOSURE` (known venue rule window), `CAPTURE_OUTAGE` (collector/WS disconnect — cannot fill orders), or `STRUCTURAL_BREAK` (halt/re-denomination). Irregular decay $\alpha(\Delta t) = 1 - e^{-\lambda \Delta t}$ carries feature state across quiet/closure intervals while never fabricating fills during outages.
2. **Leave-One-Coin-Out Common FX Factor (`leave_one_out_fx_interval`):**
   Across the 6 dual-quoted pairs $j \in \{\text{BTC, ETH, SOL, XRP, XAUT, PEPE}\} \setminus \{i\}$, compute each peer's executable implied-FX interval:
   $$\Big[\frac{\text{bid}_{j,\text{TMN}}(1 - f_{\text{TMN}})}{\text{ask}_{j,\text{USDT}}(1 + f_{\text{USDT}})},\; \frac{\text{ask}_{j,\text{TMN}}(1 + f_{\text{TMN}})}{\text{bid}_{j,\text{USDT}}(1 - f_{\text{USDT}})}\Big]$$
   Take the trimmed median center $\hat{F}_{-i,t}$ (requiring $\ge 4$ fresh peers within `max_skew_seconds = 5s`; a shock isolated to coin $i$ has **zero** influence on $\hat{F}_{-i,t}$).
3. **Explicit Traded-Leg Sign Convention in `KalmanBasisFilter`:**
   Define $y_{i,t} = \big(\ln(P_{i,\text{TMN}} / P_{i,\text{USDT}}) - \ln(\hat{F}_{-i,t})\big) \times 10^4$ (positive $y_{i,t} \implies$ coin $i$'s **TMN leg is rich** relative to its **USDT leg** and peer FX):
   - **Trading the USDT leg (`Coin/USDT`):** $+z_{i,t} > z_{\text{entry}} \implies$ `Coin/USDT` is relatively cheap $\implies$ **positive (`BUY`) forecast on `Coin/USDT`** (only if expected convergence fraction $\hat{\beta}_{\text{USDT}} \cdot |\hat{\epsilon}_{i,t}|$ exceeds round-trip USDT maker cost).
   - **Trading the TMN leg (`Coin/TMN`):** $+z_{i,t} > z_{\text{entry}} \implies$ `Coin/TMN` is relatively rich $\implies$ **negative (`SELL` held inventory / skip buy) on `Coin/TMN`**.

### 6.2 Hayashi–Yoshida Overlap Covariance With Coarser-Grid Benchmark (`gym-core/src/gym/domain/async_covariance.py`)

Compute $O(M_i + M_j)$ overlap covariance $\hat{\boldsymbol{\Sigma}}^{\text{HY}}$ alongside a simple **synchronized coarse-bar (e.g. `1h`/`1d`) shrunk sample covariance** control, reporting joint timestamp coverage, effective overlap ratio, stale-mark share, and trace norm of any PSD eigenvalue repair. Retain `Hayashi–Yoshida` only where it improves out-of-sample risk calibration across Wallex quiet/closure gaps.

### 6.3 Yang–Zhang & Downside GJR-EWMA Volatility (`gym-core/src/gym/domain/volatility_models.py`)

Evaluate `yang_zhang_volatility` and `asymmetric_ewma_volatility` at matched target horizons with an explicit volatility floor $\sigma_{\min}$, testing jump recovery across `USDTTMN` closures, sparse prints, and bid-ask bounce on thin pairs.

### 6.4 Constrained Hindsight Ceiling & Joint Outcome-Payoff Quote Model (`gym-core/src/gym/domain/quote_hazard.py`)

1. **Constrained Hindsight DP Ceiling (`hindsight_dp_ceiling`):**
   On development data, compute by dynamic programming the exact maximum self-financing terminal cash reachable by a 1-lot cash-or-long policy with compulsory flat finish, crossing recorded executable quotes within displayed depth and paying exact received-asset fees on both legs. Any market/cadence whose **perfect-foresight ceiling** fails to beat cash + minimum hurdle is retired immediately before feature engineering.
2. **Mutually Exclusive Execution-Outcome Payoff Model:**
   Classify every passive order attempt of lifetime $\tau$ into four mutually exclusive outcomes $o \in \{\text{FILLED\_BENIGN},\; \text{FILLED\_ADVERSE},\; \text{CANCELED\_UNFILLED},\; \text{EXPIRED\_UNFILLED}\}$ and estimate expected net value per submitted order $\sum_o \hat{p}(o \mid \delta, \text{spread}, \text{OFI}) \cdot \hat{V}(o, \delta)$ (charging completion cost on unfilled mandatory rebalances and `0` on unfilled optional entries), reporting probability calibration separately from simulated profit.

### 6.5 Power-Calibrated Validation, Path-Preserving Nulls & Sealed Custody (`gym-core/src/gym/domain/signal_gatekeeper.py`)

1. **Pre-Registration Joint-Gate Power Simulation:** Before allocating one of the 2 active trial slots, simulate date-clustered joint cross-market blocks (all 40 markets + cash + costs together) to verify `>= 80%` probability of clearing `DSR >= 0.95` within the declared window under realistic edge and fill bounds.
2. **Path-Preserving Placebo & Planted-Leak Controls:**
   - Keep the real market quote/print path intact and circularly shift / permute signal timestamps across days (`500+` replications, reporting Monte Carlo SE) so zero-edge nulls retain exact spreads, depth, and cross-asset correlation.
   - Include two mandatory unit-test controls: (a) a **planted synthetic alpha** that must pass, and (b) a **deliberately future-peeking signal** (`close[t+1]`) that the causality perturbation gate (`E004`) must catch and refuse.
3. **Versioned Track B Shortfall Audit & Sealed Forward Custody:**
   - Preserve original `mix-journal.jsonl` untouched as the baseline control; write any modified multi-asset journal (`AAPLXUSDT` removed, `10%` band, depth check) to a versioned `mix-journal-v2.jsonl` recording intended size, displayed depth, fee vintage, missed quantity, tracking error vs. underlying basket, and `earliest_release = start + 90d` (declaring minimum substantive rebalance count up front).
   - While a registered forward scoring window is still open (`breadth-trend-forward` before `2027-05-19`), routine health checks inspect operational continuity (`recorded_days`, `missing_days`, `status`) without using interim PnL or `e_process` to alter parameters.

---

## 7. Reconciled Execution Sequence to `2027-02-08`

### 7.1 Sprint 0 (Nov 24 – Dec 7) — Reconcile Foundations & Run Experiment 0 (Go/Stop Gate)

1. **Data & Accounting Hygiene:**
   - Keep `--depth-levels 5` live on the 40-market Wallex collector (`core-40-wallex`); publish a per-symbol coverage matrix (two-sided quote uptime, L2 depth presence, print/aggressor rate, triangle alignment across the 6 dual-quoted pairs).
   - Implement corrected FX bid/ask oracle (§4.6), fraction-preserving `LegacyStrategyAdapter` (§5.3), strictly post-fill markout calculator (§4.5), and `hindsight_dp_ceiling` (§6.4).
2. **Experiment 0 (First Funded-By-Time Research Deliverable on `BTCUSDT` + 6 Paired Triangles):**
   - Replay on existing development data: (a) `hindsight_dp_ceiling`, (b) fixed-size, fixed-offset passive maker vs. immediate taker vs. cash across `"optimistic"`, `"deduplicated"`, and `"adversarial_lower_bound"` print modes with forced flat unwind at deadline, and (c) execution-timing overlay (`OpportunisticWindowPolicy`) on existing `btc-daily-trend` / `mix` rebalance intents.
   - **Hard Gate:** Deliver one table of intended size, filled size, ambiguous-fill share, fees, 5m post-fill markout coverage, deadline residual inventory, conservative exit proceeds, and net incremental USDT. **Retire any mechanism whose net benefit vanishes under `"adversarial_lower_bound"` or flat unwind.**

### 7.2 Sprint 1 (Dec 8 – Dec 22) — Build Only Proven High-Value Engine & Vector Components

1. Implement `venue_contracts.py`, `passive_execution.py` (arrival-state classification + dynamic pegging), and `execution_schedule.py` for mechanisms surviving Sprint 0.
2. Implement `microstructure.py` (`MicrostructureBar`, `microprice`, L1 `OFI`, `VPIN`), `forecast_graph.py` (with 2×2 `A/B/C/D` attribution), `kalman_models.py` (leave-one-out FX factor + traded-leg Kalman basis), `volatility_models.py` (`Yang–Zhang` + `GJR-EWMA`), and `convex_optimizer.py` (benchmarked against simple `10%` band).
3. Run joint-block power simulations and 500-run path-preserving placebo checks (§6.5).

### 7.3 Sprint 2 (Dec 23 – Jan 8) — Formal Preregistration (Up to 2 Active Slots; Leaving a Slot Unused Is Valid)

1. **Slot #1 (Track A — Only If Sprint 0 & Sprint 1 Clear Adversarial Bounds & Power):** Register the strongest surviving Wallex USDT passive/execution-overlay or leave-one-out FX-basis policy with pinned SHA, fee schedule, custodian, and primary metric.
2. **Slot #2 (Track B — Separately Versioned Slow Allocation / Carry Study):** Launch `mix-journal-v2.jsonl` (`earliest_release >= start + 90d`, preserving v1 `mix-journal.jsonl` as control) and/or pre-register the `simulate_tmn_borrow_carry` vs. `1x` unlevered `USDTTMN`/`XAUTTMN` comparison.

### 7.4 Instant On-Demand Gate Verification (Zero Calendar Waits — Owner-Directed 2026-11-24)

All multi-week / 30-day / 90-day calendar-wait gates are replaced by immediate, reproducible counterparts executed on demand via `gym-core/scripts/instant_gate_check.py`:
1. **G1-Instant:** Immediate live `/api/health` verification (`connected=true`, `40` markets, `2` shards, `0s` lag, `--depth-levels 5` active in `book_top.depth`) plus live Nobitex rows in `multi_venue_quotes.sqlite3`.
2. **G2-Instant:** Strict chronological **Development (`<= 2025-11-23`) vs. 365-Day Sealed Historical Holdout (`2025-11-24..2026-11-23`)** + **Purged CPCV/PBO (`< 0.50`)** + **500-run path-preserving placebo (`p < 0.05`)** + **Causality perturbation (`True`)** + **`DSR >= 0.95`** (`N=21`) under exact Wallex L1 / Nobitex `-30%` executable fees.
3. **Post-Gate Path:** Passing G1–G4 immediately opens **Stage 6 installed-host qualification (`H001–H029`)** without waiting for `2027-02-08`; `TradingGYMExecutor` remains `DISARMED` until explicit owner sign-off.

---

## 8. Phase B Multi-Venue Plug-In Specification (Post-Core Expansion)

### 8.1 Nobitex Spot Book Adapter (`gym-core/src/gym/adapters/nobitex.py`)
- **Endpoints (`200 OK` verified 2026-11-24):** `GET https://apiv2.nobitex.ir/market/stats` (`1 TMN = 10 RLS` via `CurrencyUnit`) and `GET https://apiv2.nobitex.ir/v3/orderbook/{SYMBOL}`.
- **FeeSchedule (`permanent_discount = Decimal("0.30")` when verified by account receipt; undiscounted L1 reported alongside):**
  - `USDT` L1: **`7.0 bps` maker / `9.1 bps` taker** (`10.0 / 13.0 bps` undiscounted).
  - `TMN/IRT` L1: **`14.0 bps` maker / `17.5 bps` taker** (`20.0 / 25.0 bps` undiscounted).
- **Round-Trip Pre-Funded Arb Accounting:** Track venue-by-currency balances (`Nobitex` vs. `Wallex`), charging inventory replenishment / rebalance costs, partial second-leg residuals, and repeatable net proceeds per **capital-day** (never extrapolating a one-shot gap without inventory reset).

### 8.2 AbanTether OTC RWA Adapter & Instrument Master (`gym-core/src/gym/adapters/abantether.py`)
- **OTC Contract (`venue_kind = "OTC_QUOTE"`):** All-in quoted buy/sell spread (**`0.558%`** round trip observed 2026-11-24; never double-charged as a separate commission), explicit quote TTL/expiry, and size limits.
- **Underlying Mapping Accuracy:** Map each token in `InstrumentMaster` to its **actual** underlying (`SPYON -> SPY`, `QQQON -> QQQ`, `IEFAON -> IEFA`, `TLTON -> TLT`, `AGGON -> AGG`, `IAUON -> IAU`, `SLVON -> SLV`, `USOON -> USO` oil futures fund, `COPXON -> COPX` copper miners equity ETF — never conflated with spot crude or spot copper).
- **Five Hardcoded Guards:** (1) `share_ratio` + `usdt_usd_basis` NAV check (`|premium| <= 1.5%`), (2) `0`-volume exclusion (`NFLXON`, `SKHYB`), (3) 3× leveraged-ETF exclusion (`TQQQB`, `SOXLB`, `KORUB`, `MUUB`), (4) NYSE exchange-calendar session gate (handling DST & early closes), and (5) per-issuer (`Ondo`/`Backed`/`Tether`) and per-venue custody caps.

---

## 9. Deferred Post-Edge Backlog (Build Only After Experiment 0 Clears Net Hurdle)

To prevent infrastructure bloat before establishing a positive net Wallex mechanism, the following valid extensions are **explicitly deferred** until at least one candidate passes §7.1 Experiment 0:

1. **Cross-Sleeve Internal Order Netting:** Net opposing signed base deltas across independent profitable sleeves in one account before venue submission (only useful once `>= 2` sleeves have proven net edge).
2. **Maturity-Laddered Multi-Currency Obligation Stress Solver:** Deadline-by-deadline liquidity/FX stress sizing across simultaneous multi-currency margin loans (only needed if `simulate_tmn_borrow_carry` beats unlevered `1x` spot in Sprint 2).
3. **Full Out-of-Order Same-Timestamp Permutation Replay:** Enumerating alternative tie-break orderings for simultaneous same-microsecond multi-source events beyond deterministic sequence checkpointing.
4. **Hierarchical Partial-Pooling Shrinkage Across Markets:** Fitting mixed-effects / partially pooled parameters across tick-size groups (only warranted after a single-market `BTCUSDT` / 6-triangle baseline succeeds).
5. **Multi-Period / Two-Decision Dynamic Programming Allocator:** Extending single-period convex L1 optimization (§4.3) + bounded execution overlay (§4.4) to multi-step stochastic control.
6. **Full Combinatorial Ambiguous-Print Account-Tree Branching:** Forking exponential $2^K$ replay trees on duplicate trade prints (superseded in Phase A by the $O(1)$ `"adversarial_lower_bound"` mode in §4.2).
