"""Unit tests for Nobitex pay-as-you-go margin, EOD borrow, isolated liquidation, and Wallex 5x credit."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.timeframe_panel import BarPoint
from gym.domain.venue_leverage_models import (
    NOBITEX_MARGIN_ELIGIBLE_USDT,
    _step_venue_margin_2h_exit,
    nobitex_long_liquidation_price,
    simulate_bull_levered_1d_core,
    simulate_wallex_trade_credit_contract,
)


def _bar(ts_start: datetime, o: float, h: float, lo: float, c: float, hours: int = 24) -> BarPoint:
    return BarPoint(
        symbol="BTCUSDT",
        ts_start=ts_start,
        ts_avail=ts_start + timedelta(hours=hours),
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=1000.0,
        bar_source="venue_candles",
        clock_complete=True,
        nonzero_volume_fraction=1.0,
        last_trade_age_bars=0,
        mark_status="FRESH",
        entry_eligible=True,
    )


def test_nobitex_eod_borrow_is_zero_intraday_and_charges_overnight() -> None:
    t0 = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    t1_same_day = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    t2_next_day = datetime(2026, 5, 2, 0, 0, tzinfo=UTC)

    pos = {
        "collateral": 200.0, "notional": 400.0, "qty": 4.0, "entry_px": 100.0,
        "entry_fee": 0.64, "extreme": 100.0, "b_vol": 0.02, "liq_price": 57.5, "age": 0, "lev": 2.0,
    }
    cur_same = _bar(t0, 100.0, 101.0, 99.5, 100.5, hours=2)
    nxt_same = _bar(t1_same_day, 100.5, 101.0, 100.0, 101.0, hours=2)
    _, _, _, brw_intraday, _ = _step_venue_margin_2h_exit(
        pos, cur_same, nxt_same, cur_ts=t1_same_day, prev_ts=t0,
        leg_cost=0.0016, borrow_mode="eod_utc", borrow_rate=0.0005,
    )
    assert brw_intraday == 0.0

    cur_over = _bar(datetime(2026, 5, 1, 22, 0, tzinfo=UTC), 100.5, 101.5, 100.0, 101.0, hours=2)
    _, _, _, brw_overnight, _ = _step_venue_margin_2h_exit(
        pos, cur_over, None, cur_ts=t2_next_day, prev_ts=datetime(2026, 5, 1, 22, 0, tzinfo=UTC),
        leg_cost=0.0016, borrow_mode="eod_utc", borrow_rate=0.0005,
    )
    assert abs(brw_overnight - (200.0 * 0.0005)) < 1e-9


def test_nobitex_isolated_liquidation_price_monotone_in_leverage() -> None:
    assert nobitex_long_liquidation_price(100.0, 1.0) == 0.0
    p15 = nobitex_long_liquidation_price(100.0, 1.5)
    p20 = nobitex_long_liquidation_price(100.0, 2.0)
    assert 35.0 < p15 < p20 < 60.0
    assert "XAUTUSDT" in NOBITEX_MARGIN_ELIGIBLE_USDT
    assert "TONUSDT" not in NOBITEX_MARGIN_ELIGIBLE_USDT


def test_bull_levered_core_earns_pool_yield_when_flat_and_charges_borrow_when_levered() -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(days=i), 100.0, 101.0, 99.0, 100.0) for i in range(40)]
    panel = {"BTCUSDT": bars}
    targets_flat = {b.ts_avail: {"BTCUSDT": 0.0} for b in bars[:-1]}
    breadth_low = {b.ts_avail.date().isoformat(): 0.1 for b in bars}

    res_flat, _ = simulate_bull_levered_1d_core(
        panel, ("BTCUSDT",), targets_flat, breadth_low,
        label="FLAT_POOL", bull_leverage=1.5, idle_usdt_apr=0.0264,
    )
    assert res_flat.total_pool_yield_usdt > 2.0
    assert res_flat.total_borrow_usdt == 0.0
    assert res_flat.ending_nav > 1002.0

    targets_full = {b.ts_avail: {"BTCUSDT": 0.90} for b in bars[:-1]}
    breadth_bull = {b.ts_avail.date().isoformat(): 0.80 for b in bars}
    res_bull, _ = simulate_bull_levered_1d_core(
        panel, ("BTCUSDT",), targets_full, breadth_bull,
        label="BULL_1.5X", bull_leverage=1.5, borrow_per_day=0.0005, leg_cost=0.0016,
    )
    assert res_bull.levered_days >= 30
    assert res_bull.total_borrow_usdt > 5.0


def test_wallex_trade_credit_bleeds_in_cash_and_stops_out_at_13pct_drop() -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    # 95 flat days (100% cash) -> 3 cycles, each bleeds $15 on $1,000 credit (7.5%/mo of equity)
    flat_nav = {(t0 + timedelta(days=i)).date().isoformat(): 1000.0 for i in range(95)}
    res_flat = simulate_wallex_trade_credit_contract(flat_nav, label="FLAT_CASH")
    assert res_flat.total_30d_cycles == 3
    assert res_flat.cash_bleed_cycles == 3
    assert res_flat.profitable_cycles == 0
    assert res_flat.single_life_ending_equity_usdt < 160.0
    assert res_flat.unlevered_ending_equity_usdt == 200.0

    # 15% drawdown inside cycle 1 -> triggers 13% sub-account stop-out immediately!
    crash_nav = {}
    for i in range(40):
        px = 1000.0 if i < 10 else 850.0
        crash_nav[(t0 + timedelta(days=i)).date().isoformat()] = px
    res_crash = simulate_wallex_trade_credit_contract(crash_nav, label="CRASH_15PCT")
    assert res_crash.stop_out_cycles == 1
    assert res_crash.single_life_survived is False
    assert res_crash.first_stop_out_date == (t0 + timedelta(days=10)).date().isoformat()
    assert res_crash.single_life_ending_equity_usdt < 5.0
