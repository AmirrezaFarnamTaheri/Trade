"""Unit tests for shared ADMM portfolio optimization, shrunk covariance, and breadth helpers."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.strategy_sleeves import SleeveSignal
from gym.domain.timeframe_panel import BarPoint
from gym.services.experiments.admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    extract_daily_breadth,
    solve_s1_s5_admm_weights,
)


def _bp(sym: str, i: int, close: float) -> BarPoint:
    t0 = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=i)
    return BarPoint(
        symbol=sym, ts_start=t0, ts_avail=t0 + timedelta(days=1),
        open=close, high=close * 1.01, low=close * 0.99, close=close, volume=100.0,
        bar_source="test", clock_complete=True, nonzero_volume_fraction=1.0,
        last_trade_age_bars=0, entry_eligible=True, mark_status="LIVE",
    )


def test_admm_helpers_produce_valid_causal_weights_and_breadth() -> None:
    panel = {
        "BTCUSDT": [_bp("BTCUSDT", i, 100.0 * (1.004 ** i) * (1.01 if i % 2 == 0 else 0.99)) for i in range(40)],
        "ETHUSDT": [_bp("ETHUSDT", i, 50.0 * (0.998 ** i) * (1.01 if i % 3 == 0 else 0.99)) for i in range(40)],
    }
    idx = build_dated_returns_index(panel, ("BTCUSDT", "ETHUSDT"))
    t_last = panel["BTCUSDT"][-1].ts_avail
    cov_h = build_shrunk_horizon_cov(idx, ("BTCUSDT", "ETHUSDT"), t_last)
    assert len(cov_h) == 2 and cov_h[0][0] > 0

    sigs = {
        t_last: {
            "BTCUSDT": SleeveSignal("BTCUSDT", t_last, 0.85, None, None, 0.50, 2, 0.025, 1.0, True),
            "ETHUSDT": SleeveSignal("ETHUSDT", t_last, -0.40, None, None, 0.50, 2, 0.030, 1.0, True),
        }
    }
    br = extract_daily_breadth(sigs)
    assert br[t_last.date().isoformat()] == 0.50

    weights = solve_s1_s5_admm_weights(("BTCUSDT", "ETHUSDT"), sigs[t_last], (0.0, 0.0), cov_h)
    assert weights[0] > weights[1]
    assert sum(weights) <= 0.9501
