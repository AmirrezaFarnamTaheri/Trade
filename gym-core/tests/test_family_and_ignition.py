"""Tests for 3h bar resampling, asset-family differentiation, intraday crash breakers, and rare ignition."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.family_and_ignition import (
    MACRO_18_SYMBOLS,
    compute_family_differentiated_sleeves,
    family_of_symbol,
    simulate_rare_momentum_ignition,
)
from gym.domain.timeframe_panel import BarPoint, resample_hourly_to_bucket

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def test_resample_hourly_supports_3h_and_4h_with_offset() -> None:
    hourly = [
        BarPoint(
            "BTCUSDT",
            T0 + timedelta(hours=i),
            T0 + timedelta(hours=i + 1),
            100.0 + i,
            101.0 + i,
            99.0 + i,
            100.5 + i,
            10.0,
            "NATIVE_1H",
            True,
            1.0,
            0,
            True,
            "FRESH",
        )
        for i in range(12)
    ]
    bars_3h = resample_hourly_to_bucket(hourly, 3, offset_hours=0)
    bars_3h_shift = resample_hourly_to_bucket(hourly, 3, offset_hours=1)
    bars_4h = resample_hourly_to_bucket(hourly, 4, offset_hours=0)
    assert len(bars_3h) == 4
    assert all(b.clock_complete and b.volume == 30.0 for b in bars_3h)
    assert len(bars_4h) == 3
    assert any(b.ts_start.hour == 1 for b in bars_3h_shift)


def test_family_classification_separates_metals_commodities_core_and_satellites() -> None:
    assert len(MACRO_18_SYMBOLS) == 18
    assert family_of_symbol("BTCUSDT") == "CRYPTO_CORE"
    assert family_of_symbol("PAXGUSDT") == "PRECIOUS_METALS"
    assert family_of_symbol("XAUTUSDT") == "PRECIOUS_METALS"
    assert family_of_symbol("SLVONUSDT") == "COMMODITY_ETFS"
    assert family_of_symbol("AVAXUSDT") == "ALT_SATELLITES"


def test_family_sleeves_smart_gold_dedup_selects_single_preferred_gold_twin() -> None:
    syms = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "PAXGUSDT", "XAUTUSDT")
    panel = {}
    for sym in syms:
        bars = []
        for i in range(140):
            ts0 = T0 + timedelta(days=i)
            px = (100.0 + i * 1.2) if sym == "PAXGUSDT" else (100.0 + i * 0.5) if sym == "XAUTUSDT" else max(10.0, 200.0 - i)
            bars.append(BarPoint(sym, ts0, ts0 + timedelta(days=1), px, px * 1.01, px * 0.99, px, 100.0, "NATIVE_1D", True, 1.0, 0, True, "FRESH"))
        panel[sym] = bars

    sigs = compute_family_differentiated_sleeves(panel, syms)
    last = sigs[max(sigs)]
    assert last["PAXGUSDT"].s5_defensive_gold is not None and last["PAXGUSDT"].s5_defensive_gold > 0.5
    assert last["XAUTUSDT"].s5_defensive_gold is None


def test_rare_momentum_ignition_triggers_only_on_extreme_impulse_and_volume() -> None:
    bars = []
    px = 100.0
    for i in range(90):
        ts0 = T0 + timedelta(hours=i * 3)
        if i == 65:
            # Extreme >4sigma breakout with 6x volume spike
            nxt_px = px * 1.12
            vol = 600.0
        elif i > 65:
            nxt_px = px * 1.01
            vol = 120.0
        else:
            nxt_px = px * (1.002 if i % 2 == 0 else 0.998)
            vol = 100.0
        bars.append(BarPoint("BTCUSDT", ts0, ts0 + timedelta(hours=3), px, max(px, nxt_px), min(px, nxt_px), nxt_px, vol, "RESAMPLED_1H", True, 1.0, 0, True, "FRESH"))
        px = nxt_px

    breadth = {(T0 + timedelta(days=d)).date().isoformat(): 0.80 for d in range(20)}
    res = simulate_rare_momentum_ignition({"BTCUSDT": bars}, ("BTCUSDT",), breadth, label="TEST_3H", bucket_hours=3)
    assert res.entries >= 1
    assert res.ending_nav > 1000.0


def test_intraday_crash_exit_has_zero_same_day_lookahead() -> None:
    from gym.domain.family_and_ignition import compute_intraday_crash_exit_dates

    syms = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    # Build 400 3h bars (50 days); crash happens ONLY at 15:00Z on day 49 -> must NOT flag day 49's 00:00Z!
    panel = {}
    crash_day = (T0 + timedelta(days=49)).date().isoformat()
    next_day = (T0 + timedelta(days=50)).date().isoformat()
    for sym in syms:
        bars = []
        for i in range(400):
            ts0 = T0 + timedelta(hours=i * 3)
            ts1 = ts0 + timedelta(hours=3)
            # Gentle uptrend then sudden crash at day 49 12:00..15:00Z
            if ts1.date().isoformat() == crash_day and ts1.hour >= 15:
                px = 40.0
            else:
                px = 100.0 + i * 0.1
            bars.append(BarPoint(sym, ts0, ts1, px, px * 1.005, px * 0.995, px, 100.0, "RESAMPLED_1H", True, 1.0, 0, True, "FRESH"))
        panel[sym] = bars

    flagged = compute_intraday_crash_exit_dates(panel, syms, bucket_hours=3)
    assert crash_day not in flagged
    assert next_day in flagged
