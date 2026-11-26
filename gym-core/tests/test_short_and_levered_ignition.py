"""Tests for 2h short-ignition, event-scoped levered long-ignition, borrow fees, and intra-bar liquidations."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.short_and_levered_ignition import simulate_levered_ignition
from gym.domain.timeframe_panel import BarPoint

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def test_short_ignition_triggers_on_extreme_breakdown_and_pays_borrow() -> None:
    bars = []
    px = 100.0
    for i in range(110):
        ts0 = T0 + timedelta(hours=i * 2)
        if i == 80:
            nxt_px = px * 0.88  # violent -12% downward capitulation bar
            vol = 600.0
        elif i > 80:
            nxt_px = px * 0.99  # continued cascade follow-through
            vol = 120.0
        else:
            nxt_px = px * (1.002 if i % 2 == 0 else 0.998)
            vol = 100.0
        bars.append(BarPoint("BTCUSDT", ts0, ts0 + timedelta(hours=2), px, max(px, nxt_px), min(px, nxt_px), nxt_px, vol, "RESAMPLED_1H", True, 1.0, 0, True, "FRESH"))
        px = nxt_px

    breadth = {(T0 + timedelta(days=d)).date().isoformat(): 0.20 for d in range(20)}
    res, _ = simulate_levered_ignition({"BTCUSDT": bars}, ("BTCUSDT",), breadth, label="TEST_SHORT", side="SHORT", leverage=1.5)
    assert res.entries >= 1
    assert res.total_borrow_usdt > 0.0
    assert res.liquidations == 0
    assert res.ending_nav > 1000.0


def test_short_ignition_liquidates_on_violent_bar_high_squeeze() -> None:
    bars = []
    px = 100.0
    for i in range(110):
        ts0 = T0 + timedelta(hours=i * 2)
        hi = px * 1.005
        if i == 80:
            nxt_px = px * 0.88
            vol = 600.0
        elif i == 82:
            nxt_px = px * 1.02
            hi = px * 1.80  # violent +80% short squeeze bar-high liquidation!
            vol = 200.0
        else:
            nxt_px = px * (1.002 if i % 2 == 0 else 0.998)
            vol = 100.0
        bars.append(BarPoint("BTCUSDT", ts0, ts0 + timedelta(hours=2), px, max(hi, nxt_px), min(px, nxt_px), nxt_px, vol, "RESAMPLED_1H", True, 1.0, 0, True, "FRESH"))
        px = nxt_px

    breadth = {(T0 + timedelta(days=d)).date().isoformat(): 0.20 for d in range(20)}
    res, _ = simulate_levered_ignition({"BTCUSDT": bars}, ("BTCUSDT",), breadth, label="TEST_LIQ", side="SHORT", leverage=2.0)
    assert res.entries >= 1
    assert res.liquidations >= 1
    assert res.ending_nav < 1000.0
