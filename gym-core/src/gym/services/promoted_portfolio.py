"""Canonical paper-only runner for the promoted Slow S1+S5 Reference Portfolio.

Unifies the promoted research winners (Slow S1+S5 + Cost-Aware No-Trade Band + matched
CASH and 40%-Slow+Cash controls) on one snapshot-consistent SelfFinancingLedger path.
Strictly read-only against market.db; TradingGYMExecutor remains DISARMED ($0 funded budget).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean, stdev

from ..adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ..domain.multi_asset_research import BASE_13_SYMBOLS
from ..domain.paper_ledger import SelfFinancingLedger
from ..domain.promoted_strategies import (
    PROMOTED_STRATEGY_MANIFEST,
    SlowCorePolicy,
    apply_cost_aware_band,
    enforce_spot_only_strategy,
)
from ..domain.quant_v3_gates import (
    assert_irr_tmn_denomination_sane,
    bayesian_fractional_kelly_size,
    compute_deflated_sharpe_ratio,
    compute_leave_k_out_fragility,
    compute_ofi_toxicity,
    consensus_kalman_fx_rate,
    decompose_dual_factor_fx_return,
    pre_trade_implementation_shortfall_gate,
)
from .experiments.ensemble_study import portfolio_metrics
from .experiments.io_utils import readonly_snapshot
from .experiments.strategy_promotion_and_revival_study import _build_frozen_slow_targets
from .experiments.unified_book_helpers import resolve_bar_prices


def compute_dual_factor_fx_attribution(
    *,
    local_tmn_ret: float,
    global_usdt_ret: float,
    usdt_tmn_ret: float,
    venue_usdt_quotes: list[tuple[float, float]] | None = None,
) -> dict:
    """Separate local TMN return into global crypto alpha, FX depreciation, and local venue basis."""
    g_ret, fx_ret, basis_ret = decompose_dual_factor_fx_return(local_tmn_ret, usdt_tmn_ret, global_usdt_ret)
    kalman_fx = consensus_kalman_fx_rate(venue_usdt_quotes or [])
    return {
        "global_crypto_ret": g_ret,
        "fx_ret": fx_ret,
        "venue_basis_ret": basis_ret,
        "consensus_usdt_tmn": kalman_fx,
    }


def _apply_v3_admission_gates(
    raw_targets: dict[str, float],
    cur_w: dict[str, float],
    bar_map: dict,
    *,
    leg_fee_rate: float,
    spread_bps: float,
    expected_edge_bps: float,
    max_ofi_toxicity: float,
    kelly_scale: float,
    observed_trades: dict[str, list[tuple[str, float]]] | None = None,
) -> tuple[dict[str, float], int, int]:
    """Filter non-exit entries via Pre-Trade IS Gate, observed OFI (or labeled bar-imbalance proxy), and Kelly scaling."""
    gated: dict[str, float] = {}
    is_blocked = 0
    imbalance_vetoed = 0
    admitted, _, _ = pre_trade_implementation_shortfall_gate(
        expected_edge_bps,
        spread_bps=spread_bps,
        fee_bps=leg_fee_rate * 10_000.0,
        margin_multiple=1.5,
    )
    for sym, tgt_w in raw_targets.items():
        scaled_w = tgt_w * kelly_scale
        cur = cur_w.get(sym, 0.0)
        if scaled_w <= cur + 1e-6:
            # Always allow exits and reductions unconditionally
            gated[sym] = scaled_w
            continue
        if not admitted:
            gated[sym] = cur
            is_blocked += 1
            continue
        trades = (observed_trades or {}).get(sym)
        if trades:
            ofi, toxicity = compute_ofi_toxicity(trades)
            if toxicity >= max_ofi_toxicity and ofi < 0.0:
                gated[sym] = cur
                imbalance_vetoed += 1
                continue
        else:
            bar = bar_map.get(sym)
            if bar is not None and bar.high > bar.low and bar.volume > 0:
                # Bar-range volume-imbalance proxy (used only when tick-level aggressor trades are unavailable)
                buy_frac = max(0.0, min(1.0, (bar.close - bar.low) / (bar.high - bar.low)))
                proxy_ofi, proxy_tox = compute_ofi_toxicity([("BUY", bar.volume * buy_frac), ("SELL", bar.volume * (1.0 - buy_frac))])
                if proxy_tox >= max_ofi_toxicity and proxy_ofi < 0.0:
                    gated[sym] = cur
                    imbalance_vetoed += 1
                    continue
        gated[sym] = scaled_w
    return gated, is_blocked, imbalance_vetoed


def _filter_bar_denomination(ef: dict[str, float], prev_snapshot: dict[str, float], tradable: set[str]) -> int:
    rejects = 0
    for sym in list(tradable):
        if sym in prev_snapshot and sym in ef:
            try:
                assert_irr_tmn_denomination_sane(ef[sym], prev_snapshot[sym], max_ratio=2.5)
            except ValueError:
                tradable.discard(sym)
                ef[sym] = prev_snapshot[sym]
                rejects += 1
    return rejects


def _kelly_exposure_scale(daily_rets: list[float], drawdown: float) -> float:
    if len(daily_rets) < 20:
        return 1.0
    window = daily_rets[-60:]
    mu = mean(window)
    sd = stdev(window)
    if mu <= 0.0:
        return max(0.25, 1.0 - drawdown / 0.15)
    var = max(1e-6, sd * sd)
    mu_se = sd / (len(window) ** 0.5)
    k_frac = bayesian_fractional_kelly_size(
        mu, var, mu_se, kappa=0.5, max_fraction=1.0, drawdown=drawdown, max_drawdown=0.15,
    )
    return max(0.25, min(1.0, k_frac / 0.30))


def _simulate_reference_arm(
    panel_1d: dict,
    slow_targets: dict[datetime, dict[str, float]],
    win_ts: list[datetime],
    *,
    arm_name: str,
    policy: SlowCorePolicy,
    exposure_scale: float = 1.0,
    use_cost_aware_band: bool = True,
    starting_cash: Decimal = Decimal("1000"),
    enable_v3_gates: bool = False,
    estimated_spread_bps: float = 12.0,
    expected_edge_bps: float = 65.0,
    max_ofi_toxicity: float = 0.85,
) -> dict:
    enforce_spot_only_strategy(arm_name, leverage=1.0, short_allowed=False)
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    ledger = SelfFinancingLedger(
        starting_cash,
        fee_rate=Decimal(str(policy.leg_fee_rate)),
        fee_in_received_asset=True,
    )
    nav_by_date: dict[str, float] = {}
    last_px: dict[str, float] = {}
    daily_rets: list[float] = []
    peak_nav = float(starting_cash)
    prev_nav = float(starting_cash)
    is_blocked_total = 0
    ofi_vetoed_total = 0
    denom_rejects = 0

    for ts in win_ts:
        prev_snapshot = dict(last_px)
        ef, tradable = resolve_bar_prices(BASE_13_SYMBOLS, by_start, by_avail, ts, last_px)
        if enable_v3_gates:
            denom_rejects += _filter_bar_denomination(ef, prev_snapshot, tradable)
        ep = {s: Decimal(str(p)) for s, p in ef.items()}
        nav_now = float(ledger.mark_nav(ep))
        peak_nav = max(peak_nav, nav_now)
        drawdown = max(0.0, (peak_nav - nav_now) / max(1e-9, peak_nav))
        cur_w = {
            s: float(ledger.units.get(s, Decimal("0"))) * ef.get(s, 0.0) / max(1e-9, nav_now)
            for s in BASE_13_SYMBOLS
        }
        raw_t = {s: w * exposure_scale for s, w in slow_targets[ts].items()}
        if enable_v3_gates:
            bar_map = {s: by_avail[s].get(ts) for s in BASE_13_SYMBOLS}
            raw_t, b_cnt, o_cnt = _apply_v3_admission_gates(
                raw_t,
                cur_w,
                bar_map,
                leg_fee_rate=policy.leg_fee_rate,
                spread_bps=estimated_spread_bps,
                expected_edge_bps=expected_edge_bps,
                max_ofi_toxicity=max_ofi_toxicity,
                kelly_scale=_kelly_exposure_scale(daily_rets, drawdown),
            )
            is_blocked_total += b_cnt
            ofi_vetoed_total += o_cnt
        if use_cost_aware_band:
            targets = apply_cost_aware_band(
                raw_t,
                cur_w,
                leg_fee_rate=policy.leg_fee_rate,
                min_band=policy.min_no_trade_band,
                fee_multiplier=policy.fee_band_multiplier,
                max_gross=policy.max_gross_weight,
            )
        else:
            targets = {s: w for s, w in raw_t.items() if w > 1e-6}
        ledger.rebalance_to_targets(ts, targets, ep, tradable_symbols=tradable)
        nav_after = float(ledger.mark_nav(ep))
        nav_by_date[ts.date().isoformat()] = nav_after
        if prev_nav > 0.0:
            daily_rets.append((nav_after - prev_nav) / prev_nav)
        prev_nav = nav_after

    metrics = portfolio_metrics(nav_by_date, starting_nav=float(starting_cash))
    daily_sr = (mean(daily_rets) / stdev(daily_rets)) if len(daily_rets) >= 3 and stdev(daily_rets) > 1e-12 else 0.0
    out = {
        "arm": arm_name,
        "ending_nav": metrics["ending_nav"],
        "ret_pct": metrics["ret_pct"],
        "ann_sharpe": metrics["ann_sharpe"],
        "max_dd_pct": metrics["max_dd_pct"],
        "fills": len(ledger.fills),
        "fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "days": len(nav_by_date),
        "deflated_sharpe_ratio": compute_deflated_sharpe_ratio(daily_sr, len(daily_rets), n_trials=18),
        "leave_k_out": compute_leave_k_out_fragility([r * 10_000.0 for r in daily_rets], max_k=3),
    }
    if enable_v3_gates:
        out["v3_gates"] = {
            "is_blocked_entries": is_blocked_total,
            "bar_imbalance_proxy_vetoes": ofi_vetoed_total,
            "imbalance_source": "bar_range_proxy",
            "denomination_rejects": denom_rejects,
            "spot_only_enforced": True,
        }
    return out


def run_promoted_reference_portfolio(
    db_path: Path,
    *,
    policy: SlowCorePolicy | None = None,
    lookback_days: int | None = None,
    as_of: datetime | None = None,
    starting_cash: Decimal = Decimal("1000"),
) -> dict:
    """Evaluate the promoted Slow S1+S5 Reference Portfolio plus matched Cash & 40%-Slow controls."""
    policy = policy or SlowCorePolicy()
    con = open_readonly_market_db(db_path)
    try:
        with readonly_snapshot(con):
            panel_1d = {s: load_keyed_candles(con, s, "1d", as_of=as_of) for s in BASE_13_SYMBOLS}
    finally:
        con.close()

    slow_targets, _, _ = _build_frozen_slow_targets(panel_1d)
    all_ts = sorted(slow_targets)
    if not all_ts:
        return {
            "status": "INSUFFICIENT_CANDLES",
            "mode": "PAPER_ONLY",
            "executor_state": "DISARMED",
            "arms": [],
        }
    if lookback_days is not None and lookback_days > 0:
        cutoff = all_ts[-1] - timedelta(days=lookback_days)
        win_ts = [t for t in all_ts if t >= cutoff]
    else:
        win_ts = all_ts

    ref_band = _simulate_reference_arm(
        panel_1d, slow_targets, win_ts,
        arm_name="PROMOTED_SLOW_S1_S5_COST_AWARE", policy=policy,
        exposure_scale=1.0, use_cost_aware_band=True, starting_cash=starting_cash,
    )
    ref_raw = _simulate_reference_arm(
        panel_1d, slow_targets, win_ts,
        arm_name="SLOW_S1_S5_IMMEDIATE_CONTROL", policy=policy,
        exposure_scale=1.0, use_cost_aware_band=False, starting_cash=starting_cash,
    )
    slow_40 = _simulate_reference_arm(
        panel_1d, slow_targets, win_ts,
        arm_name="SLOW_40PCT_PLUS_CASH_CONTROL", policy=policy,
        exposure_scale=0.40, use_cost_aware_band=True, starting_cash=starting_cash,
    )
    ref_v3_gated = _simulate_reference_arm(
        panel_1d, slow_targets, win_ts,
        arm_name="PROMOTED_SLOW_S1_S5_V3_GATED", policy=policy,
        exposure_scale=1.0, use_cost_aware_band=True, starting_cash=starting_cash,
        enable_v3_gates=True,
    )
    cash_ctrl = {
        "arm": "CASH_100PCT_CONTROL",
        "ending_nav": round(float(starting_cash), 2),
        "ret_pct": 0.0,
        "ann_sharpe": 0.0,
        "max_dd_pct": 0.0,
        "fills": 0,
        "fees_usdt": 0.0,
        "days": len(win_ts),
    }
    return {
        "status": "OK",
        "generated_at_utc": (as_of or datetime.now(UTC)).isoformat(),
        "mode": "PAPER_ONLY",
        "executor_state": "DISARMED",
        "window_start": win_ts[0].date().isoformat(),
        "window_end": win_ts[-1].date().isoformat(),
        "policy": {
            "leg_fee_rate": policy.leg_fee_rate,
            "min_no_trade_band": policy.min_no_trade_band,
            "fee_band_multiplier": policy.fee_band_multiplier,
            "max_gross_weight": policy.max_gross_weight,
        },
        "manifest_tiers": {k: v["tier"] for k, v in PROMOTED_STRATEGY_MANIFEST.items()},
        "arms": [ref_band, ref_raw, slow_40, cash_ctrl],
        "v3_gated_arm": ref_v3_gated,
    }
