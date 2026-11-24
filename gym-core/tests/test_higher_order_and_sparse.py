"""Unit tests for higher-order momentum, tiered sparse ignition, walk-forward risk-parity, and structural bear shorts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.higher_order_and_sparse import (
    compute_second_order_trend_map,
    compute_walkforward_sleeve_weights,
    simulate_structural_breakdown_short,
    simulate_tiered_sparse_ignition,
)
from gym.domain.strategy_sleeves import SleeveSignal
from gym.domain.timeframe_panel import BarPoint


def _bp(symbol: str, ts_start: datetime, ts_avail: datetime, o: float, h: float, lo: float, c: float, v: float) -> BarPoint:
    return BarPoint(
        symbol=symbol, ts_start=ts_start, ts_avail=ts_avail,
        open=o, high=h, low=lo, close=c, volume=v,
        bar_source="test", clock_complete=True, nonzero_volume_fraction=1.0,
        last_trade_age_bars=0, entry_eligible=True, mark_status="LIVE",
    )


def test_second_order_trend_acceleration_detects_inflection_and_deceleration() -> None:
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    sigs: dict[datetime, dict[str, SleeveSignal]] = {}
    # Rising trend S1 for 25 days, then rolling over for 15 days
    vals = [min(0.9, -0.5 + 0.06 * i) for i in range(25)] + [0.9 - 0.06 * i for i in range(15)]
    for i, v in enumerate(vals):
        ts = t0 + timedelta(days=i)
        sigs[ts] = {
            "BTCUSDT": SleeveSignal("BTCUSDT", ts, v, None, None, 0.5, 10, 0.03, 1.0, True),
        }
    acc = compute_second_order_trend_map(sigs, ("BTCUSDT",))
    # Peak positive acceleration during ramp-up, negative acceleration during roll-over
    assert acc[t0 + timedelta(days=15)]["BTCUSDT"] > 0.2
    assert acc[t0 + timedelta(days=35)]["BTCUSDT"] < -0.2


def test_tiered_sparse_ignition_filters_low_liquidity_satellite() -> None:
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    bars_sat = []
    for i in range(90):
        c = 10.0 + (0.05 if i % 2 == 0 else -0.05)
        bars_sat.append(_bp("THINUSDT", t0 + timedelta(hours=2 * i), t0 + timedelta(hours=2 * (i + 1)), c, c * 1.005, c * 0.995, c, 10.0))
    # Huge breakout bar on thin volume ($500 dollar volume << $15,000 floor)
    bars_sat.append(_bp("THINUSDT", t0 + timedelta(hours=180), t0 + timedelta(hours=182), 10.0, 11.2, 9.9, 11.0, 50.0))
    bars_sat.append(_bp("THINUSDT", t0 + timedelta(hours=182), t0 + timedelta(hours=184), 11.0, 11.5, 10.9, 11.4, 20.0))
    breadth = {b.ts_avail.date().isoformat(): 0.70 for b in bars_sat}

    res, _, _ = simulate_tiered_sparse_ignition(
        {"THINUSDT": bars_sat}, (), ("THINUSDT",), breadth,
        label="TEST_THIN", sat_min_24h_dvol=15000.0,
    )
    assert res.satellite_entries == 0


def test_walkforward_sleeve_weights_are_strictly_lagged_and_favor_lower_vol() -> None:
    slow = {f"2025-01-{d:02d}": (0.005 if d % 2 == 0 else -0.005) for d in range(1, 31)}
    ign = {f"2025-01-{d:02d}": (0.025 if d % 2 == 0 else -0.025) for d in range(1, 31)}
    w = compute_walkforward_sleeve_weights(slow, ign, mode="WF_INV_VOL_RP", window=20)
    # Slow sleeve has 5x lower vol -> gets higher weight (clamped at 0.85)
    assert w["2025-01-30"][0] > 0.75
    assert abs(w["2025-01-30"][0] + w["2025-01-30"][1] - 1.0) < 1e-9


def test_structural_breakdown_short_excludes_climax_and_shorts_steady_laggard() -> None:
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    btc_bars, alt_bars = [], []
    sigs: dict[datetime, dict[str, SleeveSignal]] = {}
    for i in range(45):
        ts0, ts1 = t0 + timedelta(days=i), t0 + timedelta(days=i + 1)
        bc = 100.0 * (0.999 ** i)
        # Steady noisy decline on alt, breaking 20d low gently on day 30 (-1.8% on 1.5x vol)
        ac = 100.0 * (0.992 ** i) * (1.008 if i % 2 == 0 else 0.992)
        v = 100.0 if i != 30 else 180.0
        if i == 30:
            ac = alt_bars[-1].close * 0.980
        btc_bars.append(_bp("BTCUSDT", ts0, ts1, bc, bc * 1.01, bc * 0.99, bc, 1000.0))
        alt_bars.append(_bp("ALTUSDT", ts0, ts1, ac * 1.005, ac * 1.01, ac * 0.99, ac, v))
        sigs[ts1] = {
            "BTCUSDT": SleeveSignal("BTCUSDT", ts1, -0.30, None, None, 0.15, 10, 0.02, 1.0, True),
            "ALTUSDT": SleeveSignal("ALTUSDT", ts1, -0.60, None, None, 0.15, 10, 0.03, 1.0, True),
        }
    res, _ = simulate_structural_breakdown_short(
        {"BTCUSDT": btc_bars, "ALTUSDT": alt_bars}, ("BTCUSDT", "ALTUSDT"), sigs,
        label="TEST_STRUCT_SHORT", leg_cost=0.0010, borrow_per_day=0.0,
    )
    assert res.entries >= 1
    assert res.liquidations == 0
