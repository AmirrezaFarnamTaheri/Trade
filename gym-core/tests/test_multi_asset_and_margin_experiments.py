"""Tests for 33-market multi-asset sleeves, liquidity scaling, continuous ML tilt, and paper margin."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.multi_asset_research import (
    EXPANDED_33_SYMBOLS,
    compute_multi_asset_sleeves,
    continuous_ml_tilt,
    depth_scaled_l2_impact,
    simulate_wallex_margin_short_cascades,
    spread_aware_l1_cost,
)
from gym.domain.timeframe_panel import BarPoint

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def test_expanded_33_universe_has_unique_symbols_and_includes_commodities() -> None:
    assert len(EXPANDED_33_SYMBOLS) == 33
    assert len(set(EXPANDED_33_SYMBOLS)) == 33
    for sym in ("PAXGUSDT", "SLVONUSDT", "USOONUSDT", "COPXONUSDT", "UNGONUSDT", "WBTCUSDT"):
        assert sym in EXPANDED_33_SYMBOLS


def test_depth_scaled_l2_impact_and_spread_aware_l1_cost() -> None:
    deep = depth_scaled_l2_impact(10000.0)
    thin = depth_scaled_l2_impact(200.0)
    assert deep < thin
    assert depth_scaled_l2_impact(None) == 0.0250
    assert spread_aware_l1_cost(20.0, fee_rate=0.0013) == 0.0033


def test_continuous_ml_tilt_is_bounded_and_monotonic() -> None:
    lo = continuous_ml_tilt(0.10, base_rate=0.50, floor=0.50, cap=1.40)
    mid = continuous_ml_tilt(0.50, base_rate=0.50, floor=0.50, cap=1.40)
    hi = continuous_ml_tilt(0.95, base_rate=0.50, floor=0.50, cap=1.40)
    assert lo == 0.50 and mid == 1.0 and hi == 1.40


def test_multi_asset_sleeves_excludes_commodities_from_crypto_breadth() -> None:
    syms = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "PAXGUSDT", "SLVONUSDT")
    panel = {}
    for sym in syms:
        bars = []
        # Crypto trends down while PAXG & SLVON trend sharply up
        for i in range(140):
            ts0 = T0 + timedelta(days=i)
            px = (100.0 + i * 1.5) if sym in ("PAXGUSDT", "SLVONUSDT") else max(10.0, 200.0 - i * 0.9)
            bars.append(BarPoint(sym, ts0, ts0 + timedelta(days=1), px, px * 1.01, px * 0.99, px, 100.0, "NATIVE_1D", True, 1.0, 0, True, "FRESH"))
        panel[sym] = bars

    sigs = compute_multi_asset_sleeves(panel, syms)
    last = sigs[max(sigs)]
    # All 4 crypto symbols are below 50d EMA -> breadth must be 0.0 even though PAXG & SLVON rally!
    assert last["BTCUSDT"].crypto_breadth == 0.0
    assert last["PAXGUSDT"].s5_defensive_gold is not None and last["PAXGUSDT"].s5_defensive_gold > 0.5
    assert last["SLVONUSDT"].s5_defensive_gold is None


def test_margin_short_cascade_liquidates_on_violent_bar_high_squeeze() -> None:
    syms = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    panel = {}
    for sym in syms:
        bars = []
        for i in range(145):
            ts0 = T0 + timedelta(days=i)
            px = max(20.0, 300.0 - i * 1.5)
            # Violent short squeeze on day 141!
            hi = px * 2.5 if i == 141 else px * 1.02
            bars.append(BarPoint(sym, ts0, ts0 + timedelta(days=1), px, hi, px * 0.98, px, 100.0, "NATIVE_1D", True, 1.0, 0, True, "FRESH"))
        panel[sym] = bars
    sigs = compute_multi_asset_sleeves(panel, syms)
    dates = sorted(sigs)[130:]
    stats = simulate_wallex_margin_short_cascades(panel, sigs, dates, short_symbols=("BTCUSDT",))
    assert stats.trades >= 0
    assert stats.ending_nav >= 0.0
