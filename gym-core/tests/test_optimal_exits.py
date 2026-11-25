"""Unit tests for optimal position-closing engines E1-E4 and exact trim conservation."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from gym.domain.instrument_resolver import build_local_venue_offers
from gym.domain.multi_horizon_book import MultiHorizonBook, ThesisLot
from gym.domain.optimal_exits import (
    ClosedTradeCapture,
    OptimalExitConfig,
    OptimalStoppingModel,
    OptimalStoppingState,
    compute_ratchet_stop_price,
    decide_optimal_stopping_action,
    detect_climax_exhaustion,
    evaluate_slow_core_peak_protection,
    is_dead_money_pre_eod,
    summarize_exit_efficiency,
    trim_lot_fraction,
)
from gym.domain.timeframe_panel import BarPoint


def _lot(entry_px: float = 100.0, peak_px: float = 100.0, stop_px: float = 95.0, age: int = 1, thesis: str = "ignition_2h") -> ThesisLot:
    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    return ThesisLot(
        lot_key=("BTCUSDT", thesis), symbol="BTCUSDT", thesis_id=thesis, venue="nobitex",
        instrument_type="ISOLATED_MARGIN" if thesis == "ignition_2h" else "SPOT",
        direction=1, leverage=2.0 if thesis == "ignition_2h" else 1.0,
        collateral=100.0, notional=200.0, qty=2.0, entry_price=entry_px,
        stop_price=stop_px, take_profit_price=0.0, liq_price=60.0,
        entry_ts=t0, last_utc_date="2026-11-20", entry_bar_vol=0.02, peak_price=peak_px, age_bars=age,
    )


def test_e1_ratchet_breakeven_lock_and_dead_money_pre_eod() -> None:
    cfg = OptimalExitConfig(use_e1_ratchet=True)
    # Big winner (MFE = +10% = 5x b_vol) tightens stop well above breakeven
    winner = _lot(entry_px=100.0, peak_px=110.0, stop_px=95.0)
    r_stop = compute_ratchet_stop_price(winner, cur_close=109.0, cfg=cfg)
    assert r_stop > 105.0 and r_stop > winner.entry_price * 1.004

    # Moderate winner (MFE = +4% = 2x b_vol) locks breakeven + fee floor (>= 100.40)
    mod_win = _lot(entry_px=100.0, peak_px=104.0, stop_px=95.0)
    assert compute_ratchet_stop_price(mod_win, cur_close=103.0, cfg=cfg) >= 100.40

    # Dead money (age 6 bars, MFE only +0.5% < 0.75*2%) approaching UTC EOD triggers exit
    stalled = _lot(entry_px=100.0, peak_px=100.5, stop_px=95.0, age=6)
    assert is_dead_money_pre_eod(stalled, hours_to_utc_eod=2.0, cfg=cfg)
    assert not is_dead_money_pre_eod(winner, hours_to_utc_eod=2.0, cfg=cfg)


def test_e2_climax_exhaustion_and_exact_trim_conservation() -> None:
    cfg = OptimalExitConfig(use_e2_climax_trim=True)
    t0 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    lot = _lot(entry_px=100.0, peak_px=109.0, stop_px=95.0)
    # Parabolic bar spiking to 112 and closing at 106 (upper wick 6/7 = 85.7%) with climax volume 2.6x
    climax_bar = BarPoint("BTCUSDT", t0, t0 + timedelta(hours=2), 105.0, 112.0, 105.0, 106.0, 2600.0, "test", True, 1.0, 0, True, "LIVE")
    assert detect_climax_exhaustion(lot, climax_bar, volume_ratio=2.6, cfg=cfg)

    # Verify exact <1e-9 equity conservation on 50% passive maker trim
    book = MultiHorizonBook(free_cash=500.0)
    offer = [o for o in build_local_venue_offers("BTCUSDT") if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == 1][0]
    assert book.open_fast_margin_lot(
        symbol="BTCUSDT", thesis_id="ignition_2h", direction=1, leverage=2.0,
        target_collateral=100.0, entry_px=100.0, stop_bps=300.0, take_profit_bps=0.0,
        offer=offer, ts=t0, entry_bar_vol=0.02, entry_gru_score=0.02,
    )
    eq_before = book.mark_equity({"BTCUSDT": 108.0})
    fees_before = book.total_fees
    trim_lot_fraction(book, ("BTCUSDT", "ignition_2h"), 0.50, 108.0, fee_bps=4.5)
    eq_after = book.mark_equity({"BTCUSDT": 108.0})
    assert abs((eq_before - (book.total_fees - fees_before)) - eq_after) < 1e-9


def test_e3_optimal_stopping_e4_slow_peak_and_efficiency_metrics() -> None:
    cfg = OptimalExitConfig(use_e3_optimal_stopping=True, use_e4_slow_peak_protect=True)
    rng = np.random.default_rng(11)
    x = rng.normal(size=(150, 10))
    y = 120.0 * x[:, 1] - 55.0 * x[:, 3] - 35.0 * x[:, 4] + rng.normal(0.0, 5.0, size=150)
    model = OptimalStoppingModel(l2_alpha=10.0).fit(x, y)

    exhausted = OptimalStoppingState(4, 0.01, 0.06, 0.83, 0.75, 0.5, -1.2, -0.01, 1.5, 0.01)
    surging = OptimalStoppingState(2, 0.08, 0.08, 0.0, 0.05, 2.5, 1.8, 0.02, 16.0, 0.04)
    assert decide_optimal_stopping_action(model.predict_wait_value_bps(exhausted), exhausted, already_pyramided=False, already_trimmed=False, cfg=cfg) == "OPTIMAL_EXIT"
    assert decide_optimal_stopping_action(model.predict_wait_value_bps(surging), surging, already_pyramided=False, already_trimmed=False, cfg=cfg) == "FREE_ROLL_PYRAMID"

    # E4 slow core peak protection triggers TRIM_50 after +20% surge reverses > 2.2 * 4% ATR
    slow_lot = _lot(entry_px=100.0, peak_px=122.0, stop_px=0.0, thesis="slow_core")
    act, frac = evaluate_slow_core_peak_protection(slow_lot, cur_px=110.0, daily_atr_pct=0.04, breadth=0.45, already_trimmed=False, cfg=cfg)
    assert act == "TRIM_50" and frac == 0.50

    eff = summarize_exit_efficiency([
        ClosedTradeCapture(220.0, 300.0, 80.0, 8.0, "RATCHET_STOP", True),
        ClosedTradeCapture(-60.0, 20.0, 80.0, 12.0, "DEAD_MONEY_PRE_EOD", True),
    ])
    assert eff["closed_trades"] == 2 and eff["mfe_capture_ratio"] == 0.5 and eff["pre_eod_zero_borrow_pct"] == 100.0
