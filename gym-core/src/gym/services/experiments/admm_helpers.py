"""Shared ADMM portfolio optimization, shrunk covariance, and daily breadth helpers for study & journal services."""
from __future__ import annotations

import math
from bisect import bisect_right
from datetime import datetime

from ...domain.async_covariance import coarse_bar_shrunk_covariance_aligned
from ...domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    solve_convex_portfolio,
)
from ...domain.strategy_sleeves import SleeveSignal
from ...domain.timeframe_panel import BarPoint


def build_dated_returns_index(
    panel_1d: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
) -> dict[str, tuple[list[datetime], list[float]]]:
    """Build bisect-searchable (ts_avail_list, close_return_list) per symbol for O(log N) covariance windowing."""
    dated_rets: dict[str, tuple[list[datetime], list[float]]] = {}
    for sym in symbols:
        bars = panel_1d.get(sym, [])
        dts: list[datetime] = []
        rts: list[float] = []
        for i in range(1, len(bars)):
            c0 = bars[i - 1].close
            if c0 > 0:
                dts.append(bars[i].ts_avail)
                rts.append((bars[i].close - c0) / c0)
        dated_rets[sym] = (dts, rts)
    return dated_rets


def extract_daily_breadth(sigs_1d: dict[datetime, dict[str, SleeveSignal]]) -> dict[str, float]:
    """Extract causal ISO-date -> crypto_breadth map from computed daily sleeve signals."""
    breadth: dict[str, float] = {}
    for ts, day_map in sigs_1d.items():
        br = next((s.crypto_breadth for s in day_map.values() if s.crypto_breadth is not None), None)
        if br is not None:
            breadth[ts.date().isoformat()] = br
    return breadth


def build_shrunk_horizon_cov(
    dated_rets: dict[str, tuple[list[datetime], list[float]]],
    active_syms: tuple[str, ...],
    t_avail: datetime,
    *,
    window: int = 60,
    holding_horizon_days: float = 20.0,
    shrinkage: float = 0.25,
) -> tuple[tuple[float, ...], ...]:
    """Compute strictly causal trailing shrunk covariance scaled to holding_horizon_days."""
    win: dict[str, dict[datetime, float]] = {}
    for sym in active_syms:
        dts, rts = dated_rets[sym]
        hi = bisect_right(dts, t_avail)
        lo = max(0, hi - window)
        win[sym] = dict(zip(dts[lo:hi], rts[lo:hi], strict=True))
    cov_d = coarse_bar_shrunk_covariance_aligned(win, active_syms, shrinkage=shrinkage)
    return tuple(tuple(v * holding_horizon_days for v in row) for row in cov_d)


def solve_s1_s5_admm_weights(
    active_syms: tuple[str, ...],
    day_sigs: dict[str, SleeveSignal],
    current_weights: tuple[float, ...],
    cov_h: tuple[tuple[float, ...], ...],
    *,
    fee_rate: float = 0.0013,
    l2_impact: float = 0.0020,
    risk_aversion: float = 2.0,
    max_weight: float = 0.30,
    cash_buffer: float = 0.05,
    holding_horizon_days: float = 20.0,
    s1_override: dict[str, float | None] | None = None,
) -> tuple[float, ...]:
    """Solve canonical S1+S5 (DROP_S2) convex ADMM target weights for active symbols."""
    sqrt_h = math.sqrt(holding_horizon_days)
    mu_gross: list[float] = []
    for sym in active_syms:
        sig = day_sigs[sym]
        s1_v = s1_override[sym] if (s1_override is not None and sym in s1_override) else sig.s1_trend
        parts = [v for v in (s1_v, sig.s5_defensive_gold) if v is not None]
        raw = sum(parts) / len(parts) if parts else 0.0
        vol_h_bps = sig.yang_zhang_vol * sqrt_h * 10000.0
        mu_gross.append(forecast_to_expected_return_bps(raw * 20.0, ic_prior=0.08, horizon_vol_bps=vol_h_bps) / 10000.0)
    prob = OptimizationProblem(
        symbols=active_syms,
        expected_returns=tuple(mu_gross),
        current_weights=current_weights,
        covariance=cov_h,
        l1_fee_costs=(fee_rate,) * len(active_syms),
        l2_impact_costs=(l2_impact,) * len(active_syms),
        risk_aversion=risk_aversion,
        max_weight=max_weight,
        cash_buffer=cash_buffer,
    )
    return solve_convex_portfolio(prob).weights
