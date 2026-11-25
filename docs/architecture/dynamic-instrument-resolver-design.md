# v3 Dynamic Per-Moment Instrument & Action Resolver — Design Specification

**Status:** Approved for Historical Head-to-Head Research (`PAPER_ONLY`, `TradingGYMExecutor DISARMED`)  
**Scope:** Local venues now (**Nobitex** + **Wallex**: Spot, `تعهدی` Isolated Margin Long/Short up to `5×`, Idle USDT Liquidity Pool) with a pluggable `PERP_FUTURE` (`FUNDING_RATE`) offer interface reserved for **Hyperliquid** later. Frozen v1 and v2 forward shadow journals remain strictly untouched.

---

## 1. Core Design Principle

Instrument choice (`Spot` vs. `تعهدی Margin Long` vs. `تعهدی Margin Short` vs. `Perp Future`), leverage (`1.0×..5.0×`), and position action (`OPEN`, `HOLD`, `REDUCE/SELL`, `FLIP`, `SWITCH_INSTRUMENT`, `PARK_POOL`) are **never pre-determined per strategy sleeve**. Instead, they are resolved **at decision time `t` for each specific `(symbol, current_position)`** based on live expected edge, holding horizon, stop width, liquidity/spread, carry/borrow/funding, pool capacity, and portfolio drawdown state.

### Why Local `تعهدی` Differs from Perpetual Futures
- **Local `تعهدی` (Nobitex & Wallex):** Isolated collateralized borrowing executed directly on the spot orderbook. Both longs and shorts pay positive borrow (`Nobitex`: `0.05%/day` EOD UTC, `$0` intraday; `Wallex`: `0.015%/4h`), and short/long capacity is bounded by liquidity pool inventory.
- **Perpetual Futures (Future Hyperliquid Plug-In):** Separate synthetic contract with two-way funding (`FUNDING_RATE`) where positive funding *pays* shorts, continuous leverage, and mark-price liquidation.

---

## 2. Shared Venue-Agnostic Domain Contracts (`gym/domain/instrument_resolver.py`)

- **`MarketView`**: Venue-agnostic per-symbol forecast `(expected_return_bps, horizon_hours, stop_distance_bps, realized_vol_ann, confidence, regime_breadth, source_tag)`.
- **`InstrumentOffer`**: Live feasible instrument at time `t` (`venue`, `symbol`, `instrument_type ∈ {IDLE_POOL, SPOT, ISOLATED_MARGIN, PERP_FUTURE}`, `direction`, `allowed_leverages`, `entry_cost_bps`, `exit_cost_bps`, `carry_model`, `carry_rate_per_period`, `maintenance_margin_rate`, `available_capacity_usdt`).
- **`PositionState`**: Active per-symbol holding state (`venue`, `instrument_type`, `direction`, `leverage`, `collateral_usdt`, `notional_usdt`, `entry_price`, `stop_price`, `liquidation_price`, `held_hours`, `unrealized_pnl_bps`).
- **`ResolvedAction`**: Executable paper decision (`action`, `venue`, `instrument_type`, `direction`, `leverage`, `target_collateral_usdt`, `target_notional_usdt`, `stop_distance_bps`, `expected_net_edge_bps`, `rationale`).

---

## 3. Survival & Asymmetric `5×` Leverage Physics

1. **Zero-Liquidation Stop Barrier:** Leverage `L ∈ {1.0, 1.5, ..., 5.0}` is feasible only if:
   `stop_distance_bps + worst_slippage_bps <= liquidation_distance_bps(L) * safety_factor (0.75)`.
   On Nobitex isolated margin (`marginRatio = 1.1`), `5×` has a `1,200 bps` long / `1,000 bps` short liquidation distance, so `5×` is unlocked **only** on tight-stop, short-horizon, top-conviction setups while wide-stop `1d` trends automatically stay at `1.0×–1.5×`.
2. **Equal Risk-to-Stop Sizing:** `collateral * L * stop_distance <= max_trade_risk_pct * equity` (`1.2%` default), preventing high-leverage positions from dominating portfolio risk.
3. **Portfolio Trailing-DD Governor:** Smoothly throttles maximum allowed leverage from `5.0×` (`DD < 3%`) down to `2.5× → 1.0×` (`3% <= DD < 6%`) and `1.0×` spot-only (`DD >= 6%`).
4. **Anti-Churn Switching Hurdle:** Changing instruments or resizing an active position must beat round-trip switching costs plus `min_switch_edge_gain_bps` (`18 bps`).

---

## 4. Four Competing Resolvers (Head-to-Head Evaluation)

All four resolvers consume identical `MarketView` and `InstrumentOffer` streams and execute through the same strictly causal bar-by-bar ledger (`gym/domain/dynamic_resolver_ledger.py`):

1. **`A1_UTILITY_SOLVER`**: Direct per-moment net-utility maximizer across all feasible `(offer, leverage)` pairs with Equal Risk-to-Stop collateral allocation.
2. **`A2_SIGNED_ADMM_ROUTER`**: Continuous signed covariance/turnover-penalized portfolio optimizer (`w_i ∈ [-w_max, +w_max]`) followed by post-solve cheapest-instrument routing.
3. **`A3_STATE_MACHINE`**: Explicit discrete per-position state machine (`FLAT_POOL ↔ SPOT ↔ MARGIN_LONG ↔ MARGIN_SHORT`) with conformal confidence & ATR stop tiers and hysteresis bands.
4. **`H12_HYBRID_UTILITY_ADMM`**: Uses `A1` per-moment instrument pre-pricing (`L*_i`, live carry/cost hurdle `c*_i`, net edge `μ*_i`), feeds those instrument-aware parameters into `A2`'s joint covariance/sector-cap signed optimizer, and enforces `A3`'s anti-churn hysteresis & Equal Risk-to-Stop bounds.

---

## 5. Evaluation & Promotion Gates

- **Historical Comparison:** Single shared-ledger replay (`2024–2026` `2h` twin-phase `0h` + `+1h`) against frozen `V2_CHAMPION` (`NBX16`) with paired stationary-bootstrap CI (`bps/d`), Bear Stress (`>= 2025-11-24`), MaxDD, liquidation count (`0` required), and `+1h` clock-shift robustness.
- **Ceiling Ablation:** Compare `max_leverage = 2.0×` vs `max_leverage = 5.0×` across all 4 resolvers.
- **Hyperliquid Plug-In Verification:** Verify the exact same resolver automatically routes qualified shorts to `PERP_FUTURE` when positive funding pays shorts (`carry < 0`), requiring zero solver modifications.
- **Safety Invariant:** Zero mutation of v1/v2 forward journals; `TradingGYMExecutor` remains `DISARMED`.
