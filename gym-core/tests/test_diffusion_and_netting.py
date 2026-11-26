"""Unit tests for Track III lead-lag diffusion and joint ADMM sector-cluster netting."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.diffusion_and_netting import (
    _build_cluster_groups,
    simulate_lead_lag_diffusion,
)
from gym.domain.timeframe_panel import BarPoint


def _bp(sym: str, i: int, c: float, v: float = 10.0) -> BarPoint:
    t0 = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=2 * i)
    return BarPoint(
        symbol=sym, ts_start=t0, ts_avail=t0 + timedelta(hours=2),
        open=c, high=c * 1.005, low=c * 0.995, close=c, volume=v,
        bar_source="test", clock_complete=True, nonzero_volume_fraction=1.0,
        last_trade_age_bars=0, entry_eligible=True, mark_status="LIVE",
    )


def test_lead_lag_diffusion_buys_lagging_follower_and_exits_on_catchup() -> None:
    btc, sol = [], []
    bc, sc = 100.0, 50.0
    for i in range(45):
        m = 1.004 if i % 2 == 0 else 0.996
        bc *= m
        sc *= m
        btc.append(_bp("BTCUSDT", i, bc, v=10.0))
        sol.append(_bp("SOLUSDT", i, sc, v=10.0))
    # Bar 45: BTC impulses +4% on 3x vol while SOL stays flat (gap = ~4% >= 1.5%)
    btc.append(_bp("BTCUSDT", 45, bc * 1.04, v=35.0))
    sol.append(_bp("SOLUSDT", 45, sc, v=10.0))
    # Bars 46-50: SOL catches up +4.5%
    for k in range(1, 6):
        btc.append(_bp("BTCUSDT", 45 + k, bc * 1.04, v=10.0))
        sol.append(_bp("SOLUSDT", 45 + k, sc * (1.0 + 0.011 * k), v=15.0))

    breadth = {b.ts_avail.date().isoformat(): 0.70 for b in btc}
    s1_map = {b.ts_avail.date().isoformat(): {"BTCUSDT": 0.5, "SOLUSDT": 0.4} for b in btc}
    res, _ = simulate_lead_lag_diffusion(
        {"BTCUSDT": btc, "SOLUSDT": sol}, ("BTCUSDT", "SOLUSDT"), breadth, s1_map,
        label="TEST_DIFFUSION", leg_cost=0.0016,
    )
    assert res.entries >= 1
    assert res.ret_pct > 0.0


def test_cluster_group_builder_maps_sector_indices() -> None:
    groups = _build_cluster_groups(("BTCUSDT", "ETHUSDT", "AAVEUSDT", "SOLUSDT", "AVAXUSDT", "XAUTUSDT"))
    assert groups["ETH_DEFI"] == (1, 2)
    assert groups["ALT_L1"] == (3, 4)
    assert "BTC_MAJOR" not in groups  # single asset doesn't need multi-asset group cap
