"""Unit tests for F1-F6: Multi-Horizon Lot Book, Online IC, In-Position ML, Tehran Clock, TMN Triangles, RV Hedge."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from gym.domain.in_position_and_execution import (
    InPositionContinuationModel,
    InPositionSnapshot,
    decide_in_position_action,
    evaluate_synthetic_triangle_route,
    select_borrow_currency,
    tehran_execution_cost_bps,
)
from gym.domain.instrument_resolver import build_local_venue_offers
from gym.domain.multi_horizon_book import (
    MultiHorizonBook,
    OnlineICTracker,
    capital_velocity_score,
    check_lot_intrabar_exit,
    select_rv_laggard_hedge,
)
from gym.domain.strategy_sleeves import SleeveSignal
from gym.domain.timeframe_panel import BarPoint


def test_lot_book_isolates_slow_spot_and_conserves_equity_on_internal_short_and_pyramid() -> None:
    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    book = MultiHorizonBook(free_cash=1000.0)
    prices = {"BTCUSDT": 100.0, "SOLUSDT": 50.0}

    # 1) Open slow Spot BTC lot (40% = $400)
    fills = book.rebalance_slow_spot_targets({"BTCUSDT": 0.40}, prices, {"BTCUSDT"}, t0, leg_fee_bps=16.0)
    assert fills == 1 and ("BTCUSDT", "slow_core") in book.lots
    eq_after_slow = book.mark_equity(prices)
    assert abs((1000.0 - book.total_fees) - eq_after_slow) < 1e-9

    # 2) Open fast 3x isolated Margin SOL lot from remaining free cash WITHOUT touching slow BTC lot!
    sol_offer = [o for o in build_local_venue_offers("SOLUSDT") if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == 1][0]
    btc_qty_before = book.lots[("BTCUSDT", "slow_core")].qty
    assert book.open_fast_margin_lot(
        symbol="SOLUSDT", thesis_id="ignition_2h", direction=1, leverage=3.0,
        target_collateral=100.0, entry_px=50.0, stop_bps=300.0, take_profit_bps=700.0,
        offer=sol_offer, ts=t0, entry_bar_vol=0.02, entry_gru_score=0.02,
    )
    assert book.lots[("BTCUSDT", "slow_core")].qty == btc_qty_before  # Zero cannibalization!

    # 3) Pyramid SOL on house money when SOL rallies +4% -> exact conservation!
    prices_up = {"BTCUSDT": 100.0, "SOLUSDT": 52.0}
    eq_pre_pyr = book.mark_equity(prices_up)
    fees_pre_pyr = book.total_fees
    assert book.pyramid_lot_on_house_money(("SOLUSDT", "ignition_2h"), 52.0, add_fraction=0.50, entry_fee_bps=16.0)
    eq_post_pyr = book.mark_equity(prices_up)
    assert abs((eq_pre_pyr - (book.total_fees - fees_pre_pyr)) - eq_post_pyr) < 1e-9

    # 4) Internal zero-borrow short on BTCUSDT trims slow Spot BTC instead of borrowing!
    btc_sh = [o for o in build_local_venue_offers("BTCUSDT") if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == -1][0]
    eq_pre_sh = book.mark_equity(prices_up)
    fees_pre_sh = book.total_fees
    assert book.open_fast_margin_lot(
        symbol="BTCUSDT", thesis_id="rv_hedge", direction=-1, leverage=1.5,
        target_collateral=100.0, entry_px=100.0, stop_bps=300.0, take_profit_bps=0.0,
        offer=btc_sh, ts=t0, entry_bar_vol=0.02, entry_gru_score=0.0, allow_internal_short_offset=True,
    )
    assert book.internal_short_offsets == 1
    assert ("BTCUSDT", "rv_hedge") not in book.lots  # Fully absorbed internally with 0 borrow!
    assert abs((eq_pre_sh - (book.total_fees - fees_pre_sh)) - book.mark_equity(prices_up)) < 1e-9


def test_online_ic_tracker_and_capital_velocity() -> None:
    ic = OnlineICTracker(prior_ic=0.06, prior_weight=10.0, decay=0.95)
    for _ in range(40):
        ic.update(1.0, -0.02)
        ic.update(-1.0, 0.02)
    assert ic.realized_ic < 0.0
    assert ic.shrunk_ic <= 0.025  # Decays sharply during anti-correlated chop!
    assert capital_velocity_score(80.0, 14.0, 0.50) > capital_velocity_score(100.0, 240.0, 0.50)


def test_in_position_continuation_model_and_oco_exit() -> None:
    rng = np.random.default_rng(7)
    x = rng.normal(size=(120, 8))
    y = 0.02 * x[:, 1] - 0.03 * x[:, 3] + rng.normal(0.0, 0.002, size=120)
    m = InPositionContinuationModel(l2_alpha=5.0).fit(x, y)

    bad_snap = InPositionSnapshot(age_bars=3, unrealized_ret=-0.01, peak_mfe=0.02, giveback_from_peak=0.03, last_bar_ret_z=-1.5, volume_follow_ratio=0.4, rel_btc_ret=-0.01, entry_gru_score=0.01)
    good_snap = InPositionSnapshot(age_bars=2, unrealized_ret=0.06, peak_mfe=0.06, giveback_from_peak=0.0, last_bar_ret_z=1.5, volume_follow_ratio=2.2, rel_btc_ret=0.02, entry_gru_score=0.03)
    assert decide_in_position_action(m.predict_remaining_return(bad_snap), bad_snap, already_pyramided=False) == "EARLY_SELL"
    assert decide_in_position_action(m.predict_remaining_return(good_snap), good_snap, already_pyramided=False) == "FREE_ROLL_PYRAMID"

    # OCO maker profit target exit check
    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    book = MultiHorizonBook(free_cash=1000.0)
    offer = [o for o in build_local_venue_offers("BTCUSDT") if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == 1][0]
    book.open_fast_margin_lot(
        symbol="BTCUSDT", thesis_id="ignition_2h", direction=1, leverage=2.0,
        target_collateral=100.0, entry_px=100.0, stop_bps=300.0, take_profit_bps=500.0,
        offer=offer, ts=t0, entry_bar_vol=0.02, entry_gru_score=0.02,
    )
    bar_tp = BarPoint("BTCUSDT", t0, t0 + timedelta(hours=2), 101.0, 106.0, 100.5, 104.0, 500.0, "test", True, 1.0, 0, True, "LIVE")
    evt, px, fee_bps = check_lot_intrabar_exit(book.lots[("BTCUSDT", "ignition_2h")], bar_tp, taker_exit_bps=16.0, oco_maker_exit_bps=4.5, use_oco_maker_tp=True)
    assert evt == "OCO_TP" and abs(px - 105.0) < 1e-6 and fee_bps == 4.5


def test_tehran_clock_triangle_router_borrow_currency_and_rv_hedge() -> None:
    assert tehran_execution_cost_bps(10) < tehran_execution_cost_bps(3)
    assert tehran_execution_cost_bps(10, use_passive_maker=True) < tehran_execution_cost_bps(10)

    # Dislocated TMN leg beats direct USDT buy
    route = evaluate_synthetic_triangle_route(
        "BTCUSDT", "BUY", direct_usdt_bid=90000.0, direct_usdt_ask=90500.0,
        tmn_bid=5_800_000_000.0, tmn_ask=5_820_000_000.0,
        usdttmn_bid=65_500.0, usdttmn_ask=65_600.0, usdt_fee_bps=13.0, tmn_fee_bps=25.0,
    )
    assert route.chosen_route == "SYNTHETIC_TMN" and route.saving_bps > 100.0

    # Dynamic borrow currency selects TMN during sharp USDTTMN depreciation, USDT when flat
    assert select_borrow_currency(expected_usdttmn_drift_bps_per_day=12.0, usdttmn_trend_score=0.70).chosen_currency == "TMN"
    assert select_borrow_currency(expected_usdttmn_drift_bps_per_day=1.0, usdttmn_trend_score=0.10).chosen_currency == "USDT"

    # RV laggard hedge selects weakest negative-trend crypto when breadth < 0.45
    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    sigs = {
        "SOLUSDT": SleeveSignal("SOLUSDT", t0, 0.6, 0.2, None, 0.30, 12, 0.03, 1.0, True),
        "ADAUSDT": SleeveSignal("ADAUSDT", t0, -0.75, -0.4, None, 0.30, 12, 0.03, 1.0, True),
    }
    hed = select_rv_laggard_hedge("SOLUSDT", sigs, {"SOLUSDT": 0.05, "ADAUSDT": -0.04}, breadth=0.30)
    assert hed is not None and hed[0] == "ADAUSDT"
    assert select_rv_laggard_hedge("SOLUSDT", sigs, {"SOLUSDT": 0.05, "ADAUSDT": -0.04}, breadth=0.65) is None
