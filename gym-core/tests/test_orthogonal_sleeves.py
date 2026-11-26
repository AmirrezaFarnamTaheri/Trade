"""Unit tests for orthogonal strategy sleeves (capitulation-flush rebound, dead-cat short, macro risk-parity)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.orthogonal_sleeves import (
    simulate_capitulation_flush_rebound,
    simulate_dead_cat_exhaustion_short,
    simulate_macro_risk_parity_sleeve,
)
from gym.domain.timeframe_panel import BarPoint


def _bp(symbol: str, ts_start: datetime, ts_avail: datetime, o: float, h: float, lo: float, c: float, v: float) -> BarPoint:
    return BarPoint(
        symbol=symbol,
        ts_start=ts_start,
        ts_avail=ts_avail,
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=v,
        bar_source="test",
        clock_complete=True,
        nonzero_volume_fraction=1.0,
        last_trade_age_bars=0,
        entry_eligible=True,
        mark_status="LIVE",
    )


def _make_2h_bars(symbol: str, closes: list[float], vols: list[float], highs: list[float] | None = None, lows: list[float] | None = None) -> list[BarPoint]:
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    bars = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = highs[i] if highs is not None else max(o, c) * 1.005
        lo = lows[i] if lows is not None else min(o, c) * 0.995
        bars.append(_bp(symbol, t0 + timedelta(hours=2 * i), t0 + timedelta(hours=2 * (i + 1)), o, h, lo, c, vols[i]))
    return bars


def test_capitulation_flush_rebound_triggers_on_volume_crash_and_profits_on_snapback() -> None:
    closes = [100.0 + (0.2 if i % 2 == 0 else -0.2) for i in range(90)]
    vols = [10.0] * 90
    # Bar 90: violent -8% flush on 4x volume breaking all 72 prior lows
    closes.append(92.0)
    vols.append(45.0)
    # Next 15 bars: sharp snapback to 98.0
    for k in range(1, 16):
        closes.append(92.0 + 0.4 * k)
        vols.append(12.0)
    bars = _make_2h_bars("BTCUSDT", closes, vols)
    breadth = {b.ts_avail.date().isoformat(): 0.30 for b in bars}
    res, nav, _ = simulate_capitulation_flush_rebound(
        {"BTCUSDT": bars}, ("BTCUSDT",), breadth, label="TEST_FLUSH", leg_cost=0.0016,
    )
    assert res.entries >= 1
    assert res.ret_pct > 0.0
    assert res.liquidations == 0
    assert len(nav) > 0


def test_dead_cat_exhaustion_short_enters_only_in_bear_low_volume_bounce() -> None:
    # Realistic noisy downtrend from 120 down to ~90 over 85 bars
    closes = [120.0 - 0.35 * i + (0.6 if i % 2 == 0 else -0.6) for i in range(85)]
    vols = [20.0] * 85
    # Bar 85: weak low-volume bounce (+1.8% on 0.5x median vol, still well below 72-bar SMA)
    closes.append(closes[-1] * 1.018)
    vols.append(9.0)
    # Continuation downward
    for _k in range(1, 20):
        closes.append(closes[-1] * 0.994)
        vols.append(18.0)
    bars = _make_2h_bars("ETHUSDT", closes, vols)
    breadth = {b.ts_avail.date().isoformat(): 0.20 for b in bars}
    res, _ = simulate_dead_cat_exhaustion_short(
        {"ETHUSDT": bars}, ("ETHUSDT",), breadth, label="TEST_DEADCAT", leg_cost=0.0016,
    )
    assert res.entries >= 1
    assert res.total_borrow_usdt > 0.0


def test_macro_risk_parity_sleeve_allocates_into_uptrending_commodity() -> None:
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    bars_up = []
    bars_down = []
    for i in range(120):
        cu = 100.0 * (1.003 ** i)
        cd = 100.0 * (0.997 ** i)
        ts0 = t0 + timedelta(days=i)
        ts1 = t0 + timedelta(days=i + 1)
        bars_up.append(_bp("PAXGUSDT", ts0, ts1, cu * 0.999, cu * 1.005, cu * 0.995, cu, 100.0))
        bars_down.append(_bp("USOONUSDT", ts0, ts1, cd * 1.001, cd * 1.005, cd * 0.995, cd, 100.0))
    res, nav, targets = simulate_macro_risk_parity_sleeve(
        {"PAXGUSDT": bars_up, "USOONUSDT": bars_down},
        symbols=("PAXGUSDT", "USOONUSDT"),
        label="TEST_MACRO",
    )
    assert res.ret_pct > 0.0
    last_t = targets[max(targets)]
    assert last_t["PAXGUSDT"] > 0.0
    assert last_t["USOONUSDT"] == 0.0
    assert len(nav) > 50
