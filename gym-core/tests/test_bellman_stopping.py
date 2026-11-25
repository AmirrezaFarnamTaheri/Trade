"""Unit tests for Nonlinear Bellman Stopping V2, 1d Slow Bellman, and resurrected entry detectors."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from gym.domain.bellman_stopping import (
    NonlinearBellmanModel,
    SlowCoreBellmanModel,
    SlowCoreStoppingState,
    compute_bellman_path_target_bps,
    detect_breakdown_short_trigger,
    detect_flush_rebound_trigger,
    detect_uncensored_early_ignition,
    expand_bellman_interactions,
)
from gym.domain.optimal_exits import OptimalStoppingState
from gym.domain.timeframe_panel import BarPoint


def _bar(ts: datetime, o: float, h: float, low: float, c: float, v: float = 100.0) -> BarPoint:
    return BarPoint("BTCUSDT", ts, ts + timedelta(hours=2), o, h, low, c, v, "test", True, 1.0, 0, True, "LIVE")


def test_nonlinear_bellman_captures_interaction_curvature() -> None:
    rng = np.random.default_rng(19)
    x = rng.normal(size=(240, 10))
    # Pure nonlinear interaction: mfe (col 2) * wick (col 4) hurts continuation
    y = -180.0 * (x[:, 2] * x[:, 4]) + 90.0 * x[:, 1] + rng.normal(0.0, 10.0, size=240)
    m = NonlinearBellmanModel(l2_ridge=15.0, hidden_dim=10).fit(x, y, epochs=40, lr=5e-3)

    assert len(expand_bellman_interactions([0.0] * 10)) == 16
    exhausted = OptimalStoppingState(3, 0.02, 0.15, 0.4, 0.90, 0.8, -0.5, 0.0, 4.0, 0.02)
    clean_runner = OptimalStoppingState(2, 0.08, 0.09, 0.05, 0.05, 2.2, 1.5, 0.02, 18.0, 0.03)
    assert m.predict_wait_value_bps(clean_runner) > m.predict_wait_value_bps(exhausted) + 50.0


def test_slow_core_bellman_and_path_target_accounting() -> None:
    rng = np.random.default_rng(23)
    x = rng.normal(size=(160, 10))
    y = 140.0 * x[:, 4] - 120.0 * x[:, 3] + rng.normal(0.0, 10.0, size=160)
    sm = SlowCoreBellmanModel(l2_alpha=15.0).fit(x, y)
    weak = SlowCoreStoppingState(25, 0.10, 0.25, 0.14, -0.2, -0.5, 0.15, 0.05, -2.0)
    strong = SlowCoreStoppingState(10, 0.12, 0.13, 0.01, 0.8, 0.4, 0.75, 0.04, 1.2)
    assert sm.predict_wait_5d_bps(strong) > sm.predict_wait_5d_bps(weak) + 100.0

    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(hours=2 * i), 100.0 + i, 101.0 + i, 99.5 + i, 100.5 + i) for i in range(12)]
    val_long = compute_bellman_path_target_bps(bars, 2, direction=1, peak_px=103.0, b_vol=0.02, max_lookahead=6)
    val_short = compute_bellman_path_target_bps(bars, 2, direction=-1, peak_px=103.0, b_vol=0.02, max_lookahead=6)
    assert val_long is not None and val_short is not None and val_long > 0.0 and val_short < 0.0


def test_resurrection_entry_detectors_fire_on_exact_patterns() -> None:
    t0 = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(hours=2 * i), 100.0, 100.8, 99.2, 100.0 + (0.2 if i % 2 else -0.2), 100.0) for i in range(80)]
    # Bar 75: panic flush with lower wick absorption
    bars[75] = _bar(t0 + timedelta(hours=150), 100.0, 100.2, 94.0, 96.5, 250.0)
    # Bar 76: breakdown short below 72-bar low
    bars[76] = _bar(t0 + timedelta(hours=152), 96.5, 96.8, 92.0, 92.2, 220.0)
    # Bar 78: uncensored early ignition (modest z ~ 1.8 above 36-bar high)
    bars[78] = _bar(t0 + timedelta(hours=156), 99.0, 102.5, 98.8, 102.2, 180.0)

    rets = [0.0] + [(bars[i].close - bars[i - 1].close) / bars[i - 1].close for i in range(1, len(bars))]
    vols = [b.volume for b in bars]
    lows = [b.low for b in bars]

    assert detect_flush_rebound_trigger(bars, rets, vols, 75)[0]
    assert detect_breakdown_short_trigger(bars, rets, vols, lows, 76, breadth=0.30)[0]
    assert not detect_breakdown_short_trigger(bars, rets, vols, lows, 76, breadth=0.75)[0]

    # Clean separate series for uncensored early ignition (1.5 <= z < 2.2 above 36-bar high)
    clean = [_bar(t0 + timedelta(hours=2 * i), 100.0, 100.6, 99.4, 100.0 + (0.4 if i % 2 else -0.4), 100.0) for i in range(45)]
    clean[40] = _bar(t0 + timedelta(hours=80), 100.4, 102.0, 100.2, 101.85, 175.0)
    c_rets = [0.0] + [(clean[i].close - clean[i - 1].close) / clean[i - 1].close for i in range(1, len(clean))]
    c_vols = [b.volume for b in clean]
    c_highs = [b.high for b in clean]
    assert detect_uncensored_early_ignition(clean, c_rets, c_vols, c_highs, 40)[0]
