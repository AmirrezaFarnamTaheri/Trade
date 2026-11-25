"""Unit tests for 4-Quadrant Macro Bidirectional Overlay, 4h Supertrend, bidirectional ledger conservation, and 20-window scorer."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gym.domain.instrument_resolver import build_local_venue_offers
from gym.domain.macro_quadrant_overlay import (
    MacroQuadrantConfig,
    compute_4h_supertrend_direction,
    compute_macro_quadrant_targets,
    rebalance_bidirectional_margin_lots,
    score_7d_window_targets,
)
from gym.domain.multi_horizon_book import MultiHorizonBook
from gym.domain.strategy_sleeves import SleeveSignal
from gym.domain.timeframe_panel import BarPoint


def _bar(sym: str, ts: datetime, mins: int, o: float, h: float, low: float, c: float) -> BarPoint:
    return BarPoint(sym, ts, ts + timedelta(minutes=mins), o, h, low, c, 100.0, "test", True, 1.0, 0, True, "LIVE")


def test_4h_supertrend_flips_direction_causally() -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    bars = []
    # Steady uptrend for 20 bars, then sharp breakdown for 15 bars, then breakout
    for i in range(45):
        px = 100.0 + i * 1.2 if i < 20 else (124.0 - (i - 19) * 2.5 if i < 35 else 85.0 + (i - 34) * 3.0)
        bars.append(_bar("BTCUSDT", t0 + timedelta(hours=4 * i), 240, px, px + 0.8, px - 0.8, px))
    dirs = compute_4h_supertrend_direction(bars, atr_window=10, atr_mult=2.2)
    assert dirs[bars[18].ts_avail] == 1
    assert dirs[bars[33].ts_avail] == -1
    assert dirs[bars[44].ts_avail] == 1


def test_macro_quadrant_targets_all_four_quadrants_and_4h_agreement_gate() -> None:
    t0 = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
    cfg = MacroQuadrantConfig(use_4h_agreement_gate=True, disagree_retain_frac=0.35)
    vols = {"BTCUSDT": 0.55, "ETHUSDT": 0.65, "SOLUSDT": 0.80, "BNBUSDT": 0.55, "XAUTUSDT": 0.18}
    # Q3 Flight-to-Safety: Crypto Bear + Gold Bull
    sigs_q3 = {
        "BTCUSDT": SleeveSignal("BTCUSDT", t0, -0.60, 0.0, None, 0.0, 12, 0.02, 0.0, True),
        "ETHUSDT": SleeveSignal("ETHUSDT", t0, -0.60, 0.0, None, 0.0, 12, 0.03, 0.0, True),
        "SOLUSDT": SleeveSignal("SOLUSDT", t0, -0.60, 0.0, None, 0.0, 12, 0.04, 0.0, True),
        "BNBUSDT": SleeveSignal("BNBUSDT", t0, -0.60, 0.0, None, 0.0, 12, 0.03, 0.0, True),
        "XAUTUSDT": SleeveSignal("XAUTUSDT", t0, +0.65, 0.0, None, 0.0, 12, 0.01, 0.0, True),
    }
    st_agree = {"BTCUSDT": -1, "ETHUSDT": -1, "SOLUSDT": -1, "BNBUSDT": -1, "XAUTUSDT": 1}
    st_disagree = {"BTCUSDT": 1, "ETHUSDT": 1, "SOLUSDT": 1, "BNBUSDT": 1, "XAUTUSDT": -1}
    t_agree = compute_macro_quadrant_targets(sigs_q3, {}, 0.05, vols, st_agree, cfg)
    t_dis = compute_macro_quadrant_targets(sigs_q3, {}, 0.05, vols, st_disagree, cfg)
    assert t_agree["BTCUSDT"] < 0 and t_agree["XAUTUSDT"] > 1.5
    assert abs(t_dis["BTCUSDT"] - t_agree["BTCUSDT"] * 0.35) < 1e-6
    assert abs(t_dis["XAUTUSDT"] - t_agree["XAUTUSDT"] * 0.35) < 1e-6


def test_bidirectional_rebalancer_exact_equity_conservation_across_long_to_short_flip() -> None:
    t0 = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    cfg = MacroQuadrantConfig(leg_fee_bps=16.0, rebal_band=0.05, margin_leverage=3.0, stop_bps=1150.0)
    book = MultiHorizonBook(free_cash=1000.0)
    offers = {s: build_local_venue_offers(s, nobitex_leg_bps=16.0) for s in ("BTCUSDT", "XAUTUSDT")}
    px1 = {"BTCUSDT": 100.0, "XAUTUSDT": 3000.0}
    rebalance_bidirectional_margin_lots(book, {"BTCUSDT": 0.90, "XAUTUSDT": 0.80}, px1, {"BTCUSDT", "XAUTUSDT"}, offers, t0, cfg=cfg)
    assert abs(book.mark_equity(px1) - (1000.0 - book.total_fees)) < 1e-9

    # Price rallies -> trim Long, then directly flip Long -> Short
    px2 = {"BTCUSDT": 110.0, "XAUTUSDT": 3100.0}
    eq2, f2 = book.mark_equity(px2), book.total_fees
    rebalance_bidirectional_margin_lots(book, {"BTCUSDT": -0.80, "XAUTUSDT": 0.40}, px2, {"BTCUSDT", "XAUTUSDT"}, offers, t0 + timedelta(days=1), cfg=cfg)
    assert abs(book.mark_equity(px2) - (eq2 - (book.total_fees - f2))) < 1e-9
    assert book.lots[("BTCUSDT", "macro_4quad")].direction == -1

    # Add to Short then close everything cleanly
    px3 = {"BTCUSDT": 102.0, "XAUTUSDT": 3050.0}
    eq3, f3 = book.mark_equity(px3), book.total_fees
    rebalance_bidirectional_margin_lots(book, {"BTCUSDT": -1.20, "XAUTUSDT": 0.0}, px3, {"BTCUSDT", "XAUTUSDT"}, offers, t0 + timedelta(days=2), cfg=cfg)
    assert abs(book.mark_equity(px3) - (eq3 - (book.total_fees - f3))) < 1e-9

    eq4, f4 = book.mark_equity(px3), book.total_fees
    rebalance_bidirectional_margin_lots(book, {}, px3, {"BTCUSDT", "XAUTUSDT"}, offers, t0 + timedelta(days=3), cfg=cfg)
    assert not book.lots
    assert abs(book.free_cash - (eq4 - (book.total_fees - f4))) < 1e-9


def test_score_7d_window_targets_exact_5_criteria() -> None:
    t0 = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
    # Daily growth: +4%, +3%, +2%, +3%, +3%, +2%, +2% -> 7d = +20.5% (meets all 5 criteria!)
    mults = [1.0, 1.04, 1.0712, 1.0926, 1.1254, 1.1592, 1.1824, 1.2060]
    nav_ts = {t0 + timedelta(days=d): 1000.0 * mults[d] for d in range(8)}
    w = [{"wid": "W01", "regime": "TEST", "start": t0.isoformat()}]
    sc = score_7d_window_targets(nav_ts, w)
    assert sc["c1_3pct_1d"] == 1 and sc["c2_2pct_2d"] == 1 and sc["c3_1pct_3d"] == 1
    assert sc["c4_8pct_3d"] == 1 and sc["c5_18pct_7d"] == 1 and sc["full_5of5_hits"] == 1
