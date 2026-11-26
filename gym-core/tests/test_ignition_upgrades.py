"""Unit tests for Track II ignition upgrades (Absorption Ratio, Two-Tranche Exit, Conformal DD Governor, Path P&L)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.ignition_upgrades import (
    _select_lev_and_col,
    compute_absorption_ratio_map,
    simulate_episode_path_pnl,
    simulate_upgraded_ignition,
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


def test_absorption_ratio_approaches_one_when_all_coins_move_in_lockstep() -> None:
    syms = ("A", "B", "C", "D")
    panel = {}
    for s in syms:
        bars = []
        px = 100.0
        for i in range(45):
            px *= 1.02 if i % 2 == 0 else 0.985
            bars.append(_bp(s, i, px))
        panel[s] = bars
    ar = compute_absorption_ratio_map(panel, syms, window=36)
    assert ar[panel["A"][-1].ts_avail] > 0.95


def test_conformal_and_dd_governor_clamps_leverage_during_drawdown() -> None:
    recent = [0.40 + 0.002 * i for i in range(60)]
    lev_ok, _ = _select_lev_and_col(0.58, score_is_return=False, base_prob=0.45, use_conformal=True, recent_scores=recent, in_dd_throttle=False)
    lev_dd, _ = _select_lev_and_col(0.58, score_is_return=False, base_prob=0.45, use_conformal=True, recent_scores=recent, in_dd_throttle=True)
    assert lev_ok == 1.5
    assert lev_dd == 1.0


def test_two_tranche_exit_locks_half_on_rally_and_protects_remaining_at_breakeven() -> None:
    bars = [_bp("BTCUSDT", i, 100.0 + (0.15 if i % 2 == 0 else -0.15), v=10.0) for i in range(80)]
    # Bar 80: huge +5% breakout on 4x volume
    bars.append(_bp("BTCUSDT", 80, 105.0, v=45.0))
    # Rally to +5% above entry (bar 82 triggers partial lock -> fills at bar 83 open = 110.0), then reverses
    bars.append(_bp("BTCUSDT", 81, 105.0, v=15.0))
    bars.append(_bp("BTCUSDT", 82, 110.0, v=15.0))
    bars.append(_bp("BTCUSDT", 83, 110.0, v=15.0))
    for k in range(84, 95):
        bars.append(_bp("BTCUSDT", k, 104.8, v=12.0))
    breadth = {b.ts_avail.date().isoformat(): 0.70 for b in bars}
    res, _ = simulate_upgraded_ignition(
        {"BTCUSDT": bars}, ("BTCUSDT",), breadth,
        label="TEST_TWO_TRANCHE", use_two_tranche_exit=True,
    )
    assert res.entries >= 1
    assert res.ret_pct > 0.0
    pnl = simulate_episode_path_pnl(bars, 80, 0.01)
    assert -0.06 <= pnl <= 0.14
