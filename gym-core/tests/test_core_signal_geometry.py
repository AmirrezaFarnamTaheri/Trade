"""Unit tests for Track I core signal geometry (Path Efficiency IC, Savitzky-Golay, HRP anchor, defensive metals)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.core_signal_geometry import (
    compute_defensive_metals_reserve,
    compute_hrp_trend_target_weights,
    compute_path_efficiency_ic_map,
    compute_savgol_velocity_curvature,
)
from gym.domain.strategy_sleeves import SleeveSignal
from gym.domain.timeframe_panel import BarPoint


def _bp(sym: str, i: int, close: float) -> BarPoint:
    t0 = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=i)
    return BarPoint(
        symbol=sym, ts_start=t0, ts_avail=t0 + timedelta(days=1),
        open=close, high=close * 1.01, low=close * 0.99, close=close, volume=100.0,
        bar_source="test", clock_complete=True, nonzero_volume_fraction=1.0,
        last_trade_age_bars=0, entry_eligible=True, mark_status="LIVE",
    )


def test_path_efficiency_ic_separates_straight_trend_from_chop() -> None:
    trend = [_bp("TREND", i, 100.0 + 1.5 * i) for i in range(30)]
    chop = [_bp("CHOP", i, 100.0 + (2.0 if i % 2 == 0 else -2.0)) for i in range(30)]
    ic_map = compute_path_efficiency_ic_map({"TREND": trend, "CHOP": chop}, ("TREND", "CHOP"))
    t_last = trend[-1].ts_avail
    assert ic_map[t_last]["TREND"] > 0.08 * 1.2
    assert ic_map[t_last]["CHOP"] <= 0.08 * 0.30


def test_savgol_detects_positive_velocity_and_acceleration_turn() -> None:
    # Accelerating exponential curve: positive velocity & positive curvature
    bars = [_bp("BTCUSDT", i, 100.0 * (1.002 ** (i * i / 40.0))) for i in range(75)]
    sg = compute_savgol_velocity_curvature({"BTCUSDT": bars}, ("BTCUSDT",))
    vel, curv = sg[bars[-1].ts_avail]["BTCUSDT"]
    assert vel > 0.3
    assert curv > 0.1


def test_hrp_anchor_allocates_only_positive_trends_within_caps() -> None:
    t0 = datetime(2025, 2, 1, tzinfo=UTC)
    sigs = {
        "BTCUSDT": SleeveSignal("BTCUSDT", t0, 0.8, None, None, 0.6, 3, 0.02, 1.0, True),
        "ETHUSDT": SleeveSignal("ETHUSDT", t0, 0.6, None, None, 0.6, 3, 0.03, 1.0, True),
        "BADUSDT": SleeveSignal("BADUSDT", t0, -0.5, None, None, 0.6, 3, 0.04, 1.0, True),
    }
    cov = ((0.0004, 0.0002, 0.0001), (0.0002, 0.0009, 0.0001), (0.0001, 0.0001, 0.0016))
    w = compute_hrp_trend_target_weights(("BTCUSDT", "ETHUSDT", "BADUSDT"), sigs, cov)
    assert w["BADUSDT"] == 0.0
    assert w["BTCUSDT"] > w["ETHUSDT"] > 0.0
    assert sum(w.values()) <= 0.9501


def test_defensive_metals_reserve_respects_issuer_caps_and_breadth_gate() -> None:
    t0 = datetime(2025, 2, 1, tzinfo=UTC)
    sigs = {
        "XAUTUSDT": SleeveSignal("XAUTUSDT", t0, 0.7, None, None, 0.1, 3, 0.01, 1.0, True),
        "PAXGUSDT": SleeveSignal("PAXGUSDT", t0, 0.7, None, None, 0.1, 3, 0.01, 1.0, True),
        "SLVONUSDT": SleeveSignal("SLVONUSDT", t0, -0.2, None, None, 0.1, 3, 0.02, 1.0, True),
    }
    bull_w = compute_defensive_metals_reserve(sigs, crypto_breadth=0.60)
    assert sum(bull_w.values()) == 0.0

    bear_w = compute_defensive_metals_reserve(sigs, crypto_breadth=0.10)
    assert 0.20 <= bear_w["XAUTUSDT"] <= 0.25
    assert 0.10 <= bear_w["PAXGUSDT"] <= 0.15
    assert bear_w["SLVONUSDT"] == 0.0
