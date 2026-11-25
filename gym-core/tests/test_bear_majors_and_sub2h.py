"""Unit tests for BearMajors sleeve, sub-2h resampler/detectors, and shared unified-book helpers."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.bear_majors_sleeve import (
    BearMajorsConfig,
    compute_calm_bear_majors_targets,
    rebalance_slow_short_lots,
)
from gym.domain.instrument_resolver import build_local_venue_offers
from gym.domain.multi_horizon_book import MultiHorizonBook
from gym.domain.strategy_sleeves import SleeveSignal
from gym.domain.sub_2h_signals import (
    IntradaySignal,
    Sub2hSimConfig,
    compute_ema_series,
    detect_n1_pullback_rejection_short,
    detect_n4_coiled_down_short,
    detect_sub2h_ignition_long,
    is_deep_bear_cascade_active,
    rank_deep_bear_short_targets,
    resample_1min_to_minutes,
    simulate_sub2h_signal_strategy,
)
from gym.domain.timeframe_panel import BarPoint
from gym.services.experiments.unified_book_helpers import (
    latest_signal_date,
    nav_ts_to_daily,
    window_return_pct,
    year_returns_pct,
)


def _bar(sym: str, ts: datetime, mins: int, o: float, h: float, low: float, c: float, v: float = 100.0) -> BarPoint:
    return BarPoint(sym, ts, ts + timedelta(minutes=mins), o, h, low, c, v, "test", True, 1.0, 0, True, "LIVE")


def test_resample_1min_to_30m_and_240m_preserves_ohlcv_and_alignment() -> None:
    t0 = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    bars_1m = [_bar("BTCUSDT", t0 + timedelta(minutes=i), 1, 100.0 + i * 0.1, 101.0 + i * 0.1, 99.5, 100.05 + i * 0.1, 10.0) for i in range(240)]
    b30 = resample_1min_to_minutes(bars_1m, 30, min_bars_per_bucket=20)
    assert len(b30) == 8
    assert b30[0].ts_start == t0 and b30[0].ts_avail == t0 + timedelta(minutes=30)
    assert b30[0].open == 100.0 and abs(b30[0].volume - 300.0) < 1e-9
    b240 = resample_1min_to_minutes(bars_1m, 240, min_bars_per_bucket=180)
    assert len(b240) == 1
    assert b240[0].ts_start == t0 and b240[0].ts_avail == t0 + timedelta(minutes=240)
    assert abs(b240[0].volume - 2400.0) < 1e-9


def test_n1_pullback_short_n2_cascade_and_n4_coiled_down_detectors() -> None:
    t0 = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    bars = [
        _bar("SOLUSDT", t0 + timedelta(hours=i), 60, 100.0 - 0.35 * i + 0.1, 100.0 - 0.35 * i + 0.25, 100.0 - 0.35 * i - 0.25, 100.0 - 0.35 * i, 100.0)
        for i in range(50)
    ]
    closes = [b.close for b in bars]
    ef = compute_ema_series(closes, 10)
    bars[45] = _bar("SOLUSDT", t0 + timedelta(hours=45), 60, ef[45] - 0.2, ef[45] + 0.6, ef[45] - 1.1, ef[45] - 0.9, 180.0)
    closes = [b.close for b in bars]
    rets = [0.0] + [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    vols = [b.volume for b in bars]
    ef, es = compute_ema_series(closes, 10), compute_ema_series(closes, 30)

    sig_n1 = detect_n1_pullback_rejection_short(bars, ef, es, vols, rets, 45, breadth=0.10, s1_daily=-0.50)
    assert sig_n1 is not None and sig_n1.direction == -1 and sig_n1.stop_bps <= 420.0
    assert detect_n1_pullback_rejection_short(bars, ef, es, vols, rets, 45, breadth=0.60, s1_daily=-0.50) is None

    assert is_deep_bear_cascade_active(58000, 60000, 62000, 60500, breadth=0.05)
    assert not is_deep_bear_cascade_active(61000, 60000, 62000, 60500, breadth=0.05)
    sigs_d = {
        "NEARUSDT": SleeveSignal("NEARUSDT", t0, -0.80, 0.0, None, 0.0, 12, 0.04, 1.0, True),
        "AAVEUSDT": SleeveSignal("AAVEUSDT", t0, -0.70, 0.0, None, 0.0, 12, 0.04, 1.0, True),
        "XAUTUSDT": SleeveSignal("XAUTUSDT", t0, -0.50, 0.0, None, 0.0, 12, 0.02, 1.0, True),
    }
    ranked = rank_deep_bear_short_targets(
        ("NEARUSDT", "AAVEUSDT", "XAUTUSDT"), sigs_d,
        {"NEARUSDT": -0.06, "AAVEUSDT": -0.04, "XAUTUSDT": -0.02},
        {"NEARUSDT": 3.0, "AAVEUSDT": 100.0, "XAUTUSDT": 3500.0},
        {"NEARUSDT": 3.5, "AAVEUSDT": 110.0, "XAUTUSDT": 3600.0},
        {"NEARUSDT": 2.8, "AAVEUSDT": 95.0, "XAUTUSDT": 3480.0},
    )
    assert [s for s, _ in ranked] == ["NEARUSDT", "AAVEUSDT"]

    bars_c = [_bar("AVAXUSDT", t0 + timedelta(hours=i), 60, 100.0 - 0.2 * i, 101.0 - 0.2 * i, 99.0 - 0.2 * i, 100.0 - 0.2 * i, 100.0) for i in range(52)]
    for j in range(42, 48):
        px = bars_c[41].close
        bars_c[j] = _bar("AVAXUSDT", t0 + timedelta(hours=j), 60, px, px + 0.25, px - 0.25, px - 0.05, 90.0)
    px48 = bars_c[47].close
    bars_c[48] = _bar("AVAXUSDT", t0 + timedelta(hours=48), 60, px48, px48 + 0.1, px48 - 3.5, px48 - 3.2, 240.0)
    cc = [b.close for b in bars_c]
    cr = [0.0] + [(cc[i] - cc[i - 1]) / cc[i - 1] for i in range(1, len(cc))]
    cv = [b.volume for b in bars_c]
    sig_n4 = detect_n4_coiled_down_short(bars_c, compute_ema_series(cc, 30), cv, cr, 48, breadth=0.10, s1_daily=-0.50)
    assert sig_n4 is not None and sig_n4.direction == -1


def test_sub2h_simulator_profits_on_bear_short_and_kills_on_btc_reclaim() -> None:
    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    prices = [100.0, 100.0, 96.0, 93.0, 94.0, 98.0]
    bars = [_bar("SOLUSDT", t0 + timedelta(hours=i), 60, px, px * 1.005, px * 0.995, px) for i, px in enumerate(prices)]
    assert detect_sub2h_ignition_long(bars, [100.0] * 6, [0.0] * 6, 0) is None
    sig_map = {
        bars[0].ts_avail: [IntradaySignal("SOLUSDT", bars[0].ts_avail, -1, 0.015, 300.0, 1.0, "n2_deep_bear_cascade")]
    }
    btc_bear = {b.ts_avail: (i < 3) for i, b in enumerate(bars)}
    meta, nav_ts = simulate_sub2h_signal_strategy(
        {"SOLUSDT": bars}, sig_map, btc_bear,
        cfg=Sub2hSimConfig(label="TEST_30M_SHORT", bar_hours=1.0, max_leverage=2.0, kill_shorts_on_btc_reclaim=True),
    )
    assert meta["entries"] == 1 and meta["liqs"] == 0
    assert nav_ts[bars[-1].ts_avail] > 1005.0
    assert meta["eff"]["reasons"].get("BTC_RECLAIM_KILL", 0) == 1


def test_calm_bear_majors_targets_and_exact_short_ledger_conservation() -> None:
    t0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    cfg = BearMajorsConfig(breadth_max=0.30, s1_max=-0.25, gross_short_budget=1.0, leg_fee_bps=16.0, rebal_band=0.05)
    sigs = {
        "BTCUSDT": SleeveSignal("BTCUSDT", t0, -0.60, 0.0, None, 0.0, 12, 0.02, 0.0, True),
        "ETHUSDT": SleeveSignal("ETHUSDT", t0, -0.60, 0.0, None, 0.0, 12, 0.04, 0.0, True),
        "SOLUSDT": SleeveSignal("SOLUSDT", t0, -0.60, 0.0, None, 0.0, 12, 0.06, 0.0, True),
        "BNBUSDT": SleeveSignal("BNBUSDT", t0, -0.60, 0.0, None, 0.0, 12, 0.03, 0.0, True),
    }
    assert compute_calm_bear_majors_targets(sigs, {}, 0.45, cfg) == {}
    tgts = compute_calm_bear_majors_targets(sigs, {"SOLUSDT": 0.20}, 0.0, cfg)
    assert "SOLUSDT" not in tgts and len(tgts) == 3
    assert abs(tgts["BTCUSDT"]) > abs(tgts["ETHUSDT"])
    assert abs(sum(tgts.values()) + 1.0) < 1e-9

    book = MultiHorizonBook(free_cash=1000.0)
    offers = {s: build_local_venue_offers(s, nobitex_leg_bps=16.0) for s in ("BTCUSDT", "ETHUSDT")}
    px1 = {"BTCUSDT": 100.0, "ETHUSDT": 50.0}
    rebalance_slow_short_lots(book, {"BTCUSDT": -0.60}, px1, {"BTCUSDT", "ETHUSDT"}, offers, t0, cfg=cfg)
    assert abs(book.mark_equity(px1) - (1000.0 - book.total_fees)) < 1e-9

    px2 = {"BTCUSDT": 90.0, "ETHUSDT": 50.0}
    eq_before_trim, fees_before_trim = book.mark_equity(px2), book.total_fees
    rebalance_slow_short_lots(book, {"BTCUSDT": -0.30}, px2, {"BTCUSDT", "ETHUSDT"}, offers, t0 + timedelta(days=1), cfg=cfg)
    assert abs(book.mark_equity(px2) - (eq_before_trim - (book.total_fees - fees_before_trim))) < 1e-9

    px3 = {"BTCUSDT": 85.0, "ETHUSDT": 50.0}
    eq_before_add, fees_before_add = book.mark_equity(px3), book.total_fees
    rebalance_slow_short_lots(book, {"BTCUSDT": -0.70}, px3, {"BTCUSDT", "ETHUSDT"}, offers, t0 + timedelta(days=2), cfg=cfg)
    assert abs(book.mark_equity(px3) - (eq_before_add - (book.total_fees - fees_before_add))) < 1e-9

    eq_before_close, fees_before_close = book.mark_equity(px3), book.total_fees
    rebalance_slow_short_lots(book, {}, px3, {"BTCUSDT", "ETHUSDT"}, offers, t0 + timedelta(days=3), cfg=cfg)
    assert not book.lots
    assert abs(book.free_cash - (eq_before_close - (book.total_fees - fees_before_close))) < 1e-9


def test_unified_book_helpers_handle_odd_1h_phase_and_window_returns() -> None:
    d0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
    d1 = datetime(2026, 11, 21, 0, 0, tzinfo=UTC)
    # Odd 1h-offset bar (01:00 UTC) causally resolves to 00:00 UTC daily signal without lookahead
    assert latest_signal_date([d0, d1], datetime(2026, 11, 20, 1, 0, tzinfo=UTC)) == d0
    assert latest_signal_date([d0, d1], datetime(2026, 11, 21, 1, 0, tzinfo=UTC)) == d1
    nav_ts = {d0: 1000.0, d1: 1050.0}
    assert window_return_pct(nav_ts, 24.0) == 5.0
    daily = nav_ts_to_daily(nav_ts)
    assert year_returns_pct(daily, years=("2026",)) == {"2026": 5.0}
