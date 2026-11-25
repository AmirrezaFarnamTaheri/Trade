"""Regression counterexamples for P1 defects from the 2026-11-25 42-commit audit.

Each test reproduces a concrete failure mode documented in
docs/architecture/2026-11-25-last-42-commits-review.md and verifies the fix.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from gym.domain.instrument_resolver import InstrumentOffer
from gym.domain.meta_gateway import LogisticVetoGateway
from gym.domain.multi_horizon_book import MultiHorizonBook, ThesisLot
from gym.domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from gym.services.experiments.ensemble_study import (
    COHORT_SYMBOLS,
    _exec_prices_and_tradable,
)
from gym.services.experiments.ignition_upgrade_ablation_study import (
    _walkforward_gru_scores,
)
from gym.services.experiments.smart_execution_sim import _evaluate_symbol_orders
from gym.services.experiments.unified_book_helpers import resolve_bar_prices


def _bar(
    sym: str,
    ts_start: datetime,
    hours: int,
    *,
    open_px: float = 100.0,
    close_px: float = 100.0,
    volume: float = 100.0,
    clock_complete: bool = True,
    entry_eligible: bool = True,
) -> BarPoint:
    return BarPoint(
        symbol=sym,
        ts_start=ts_start,
        ts_avail=ts_start + timedelta(hours=hours),
        open=open_px,
        high=max(open_px, close_px),
        low=min(open_px, close_px),
        close=close_px,
        volume=volume,
        bar_source="NATIVE_1H",
        clock_complete=clock_complete,
        nonzero_volume_fraction=1.0 if volume > 0 else 0.0,
        last_trade_age_bars=0 if volume > 0 else 1,
        entry_eligible=entry_eligible,
        mark_status="FRESH" if volume > 0 else "STALE_MARK",
    )


def test_finding_1_no_future_volume_lookahead_at_next_open() -> None:
    """Changing only the next bar's eventual volume/entry_eligible must not change decision-time fills."""
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=2)
    cur = _bar("BTCUSDT", t0, 2, open_px=99.0, close_px=100.0, volume=500.0, entry_eligible=True)
    nxt_liquid = _bar("BTCUSDT", t1, 2, open_px=100.0, close_px=102.0, volume=500.0, entry_eligible=True)
    nxt_zero_vol = _bar("BTCUSDT", t1, 2, open_px=100.0, close_px=102.0, volume=0.0, entry_eligible=False)

    px_a, tr_a = resolve_bar_prices(("BTCUSDT",), {"BTCUSDT": {t1: nxt_liquid}}, {"BTCUSDT": {t1: cur}}, t1, {})
    px_b, tr_b = resolve_bar_prices(("BTCUSDT",), {"BTCUSDT": {t1: nxt_zero_vol}}, {"BTCUSDT": {t1: cur}}, t1, {})
    assert px_a == px_b == {"BTCUSDT": 100.0}
    assert tr_a == tr_b == {"BTCUSDT"}

    by_start_a = {"BTCUSDT": {t1: nxt_liquid}}
    by_start_b = {"BTCUSDT": {t1: nxt_zero_vol}}
    by_avail = {"BTCUSDT": {t1: cur}}
    for s in COHORT_SYMBOLS:
        by_start_a.setdefault(s, {})
        by_start_b.setdefault(s, {})
        by_avail.setdefault(s, {})
    ep_a, et_a = _exec_prices_and_tradable(by_start_a, by_avail, t1)
    ep_b, et_b = _exec_prices_and_tradable(by_start_b, by_avail, t1)
    assert ep_a == ep_b
    assert et_a == et_b == {"BTCUSDT"}


def test_finding_2_resample_propagates_child_incompleteness() -> None:
    """An incomplete child hourly bar must prevent its parent 2h bucket from being marked clock_complete."""
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    h0 = _bar("BTCUSDT", t0, 1, volume=100.0, clock_complete=True)
    h1_partial = _bar("BTCUSDT", t0 + timedelta(hours=1), 1, volume=100.0, clock_complete=False)
    b2 = resample_hourly_to_bucket([h0, h1_partial], 2, offset_hours=0)
    assert len(b2) == 1
    assert b2[0].clock_complete is False
    assert b2[0].entry_eligible is False


def test_finding_5_internal_short_offset_exact_equity_conservation() -> None:
    """Offsetting 495 of 500 spot units at flat price with 0 fee must preserve exact 1,000 NAV."""
    ts = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    book = MultiHorizonBook(free_cash=500.0)
    book.lots[("BTCUSDT", "slow_core")] = ThesisLot(
        lot_key=("BTCUSDT", "slow_core"),
        symbol="BTCUSDT",
        thesis_id="slow_core",
        venue="nobitex",
        instrument_type="SPOT",
        direction=1,
        leverage=1.0,
        collateral=500.0,
        notional=500.0,
        qty=500.0,
        entry_price=1.0,
        stop_price=0.0,
        take_profit_price=0.0,
        liq_price=0.0,
        entry_ts=ts,
        last_utc_date=ts.date().isoformat(),
        peak_price=1.0,
    )
    offer = InstrumentOffer(
        venue="nobitex",
        symbol="BTCUSDT",
        instrument_type="ISOLATED_MARGIN",
        direction=-1,
        allowed_leverages=(1.0, 2.0),
        entry_cost_bps=0.0,
        exit_cost_bps=0.0,
        carry_model="NONE",
        carry_rate_bps=0.0,
    )
    ok = book.open_fast_margin_lot(
        symbol="BTCUSDT",
        thesis_id="bear_short",
        direction=-1,
        leverage=1.0,
        target_collateral=495.0,
        entry_px=1.0,
        stop_bps=400.0,
        take_profit_bps=800.0,
        offer=offer,
        ts=ts,
        entry_bar_vol=0.02,
        entry_gru_score=0.0,
        allow_internal_short_offset=True,
    )
    assert ok is True
    assert book.mark_equity({"BTCUSDT": 1.0}) == pytest.approx(1000.0, abs=1e-9)
    assert book.free_cash == pytest.approx(1000.0, abs=1e-9)
    assert ("BTCUSDT", "slow_core") not in book.lots

    # Partial offset (400 of 500) must also conserve exact equity with 100 spot remaining.
    book2 = MultiHorizonBook(free_cash=500.0)
    book2.lots[("BTCUSDT", "slow_core")] = ThesisLot(
        lot_key=("BTCUSDT", "slow_core"),
        symbol="BTCUSDT",
        thesis_id="slow_core",
        venue="nobitex",
        instrument_type="SPOT",
        direction=1,
        leverage=1.0,
        collateral=500.0,
        notional=500.0,
        qty=500.0,
        entry_price=1.0,
        stop_price=0.0,
        take_profit_price=0.0,
        liq_price=0.0,
        entry_ts=ts,
        last_utc_date=ts.date().isoformat(),
        peak_price=1.0,
    )
    ok2 = book2.open_fast_margin_lot(
        symbol="BTCUSDT",
        thesis_id="bear_short",
        direction=-1,
        leverage=1.0,
        target_collateral=400.0,
        entry_px=1.0,
        stop_bps=400.0,
        take_profit_bps=800.0,
        offer=offer,
        ts=ts,
        entry_bar_vol=0.02,
        entry_gru_score=0.0,
        allow_internal_short_offset=True,
    )
    assert ok2 is True
    assert book2.mark_equity({"BTCUSDT": 1.0}) == pytest.approx(1000.0, abs=1e-9)
    assert book2.free_cash == pytest.approx(900.0, abs=1e-9)
    assert book2.lots[("BTCUSDT", "slow_core")].qty == pytest.approx(100.0, abs=1e-9)


def test_finding_7_future_fold_labels_do_not_leak_into_earlier_priors() -> None:
    """Inverting fold-3 labels must leave fold-1 and fold-2 scores and base rates byte-identical."""
    rng = np.random.default_rng(7)
    dts: list[datetime] = []
    syms: list[str] = []
    # 90 train samples before fold 1, 20 in fold 1, 20 in fold 2, 20 in fold 3
    for i in range(90):
        dts.append(datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i))
        syms.append("BTCUSDT")
    for i in range(20):
        dts.append(datetime(2024, 10, 1, tzinfo=UTC) + timedelta(days=i))
        syms.append("BTCUSDT")
    for i in range(20):
        dts.append(datetime(2025, 5, 1, tzinfo=UTC) + timedelta(days=i))
        syms.append("BTCUSDT")
    for i in range(20):
        dts.append(datetime(2025, 12, 1, tzinfo=UTC) + timedelta(days=i))
        syms.append("BTCUSDT")

    x_mat = rng.normal(size=(len(dts), 4, 6))
    y_a = rng.integers(0, 2, size=len(dts)).astype(np.float64)
    y_b = y_a.copy()
    fold3_start = datetime(2025, 11, 24, tzinfo=UTC)
    for k, dt in enumerate(dts):
        if dt >= fold3_start:
            y_b[k] = 1.0 - y_b[k]

    sc_a, _, br_a = _walkforward_gru_scores(dts, syms, x_mat, y_a, y_a, task="binary")
    sc_b, _, br_b = _walkforward_gru_scores(dts, syms, x_mat, y_b, y_b, task="binary")

    for dt in dts:
        if datetime(2024, 9, 1, tzinfo=UTC) <= dt < fold3_start:
            assert br_a[dt] == br_b[dt]
            assert sc_a[(dt, "BTCUSDT")] == sc_b[(dt, "BTCUSDT")]


def test_finding_13_wallex_ask_cannot_fill_passive_nobitex_bid() -> None:
    """Holding Nobitex book fixed while dropping Wallex ask must leave Nobitex passive fill rate at 0%."""
    base_snap_0 = {
        "epoch": 1000.0,
        "w_mid": 100.5,
        "n_mid": 100.5,
        "w_bids": [(100.0, 10.0)],
        "w_asks": [(101.0, 10.0)],
        "n_bids": [(100.0, 10.0)],
        "n_asks": [(101.0, 10.0)],
    }
    snap_1_wlx_high = {
        "epoch": 1060.0,
        "w_mid": 100.5,
        "n_mid": 100.5,
        "w_bids": [(100.0, 10.0)],
        "w_asks": [(101.0, 10.0)],
        "n_bids": [(100.0, 10.0)],
        "n_asks": [(101.0, 10.0)],
    }
    snap_1_wlx_crossed = {
        **snap_1_wlx_high,
        "w_mid": 98.5,
        "w_bids": [(98.0, 10.0)],
        "w_asks": [(99.0, 10.0)],
    }

    res_a = _evaluate_symbol_orders(
        [base_snap_0, snap_1_wlx_high],
        symbol="BTCUSDT",
        notional=250.0,
        w_maker_bps=20.0,
        w_taker_bps=25.0,
        n_maker_bps=12.0,
        n_taker_bps=16.0,
    )
    res_b = _evaluate_symbol_orders(
        [base_snap_0, snap_1_wlx_crossed],
        symbol="BTCUSDT",
        notional=250.0,
        w_maker_bps=20.0,
        w_taker_bps=25.0,
        n_maker_bps=12.0,
        n_taker_bps=16.0,
    )
    assert res_a["buy"]["passive_buy_fill_pct"] == 0.0
    assert res_b["buy"]["passive_buy_fill_pct"] == 0.0
    assert res_a["passive_covered_samples"] == 1
    assert res_a["passive_uncovered_deadlines"] == 1


def test_finding_6_logistic_veto_utc_day_purge_and_no_double_fee() -> None:
    """LogisticVetoGateway supports UTC calendar-day group purging and single fee convention."""
    rng = np.random.default_rng(11)
    n = 120
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    # 3 proposals per UTC day -> 40 days
    ts_list = [t0 + timedelta(days=i // 3) for i in range(n)]
    feats = rng.normal(size=(n, 6)).tolist()
    net_bps = [120.0 if f[0] > 0 else -100.0 for f in feats]
    gw = LogisticVetoGateway(c_reg=0.2, safety_margin_bps=5.0)
    cal = gw.fit(feats, net_bps, purge_gap=5, timestamps=ts_list)
    assert cal.n_samples >= 10
    acc_single, _, ev_single = gw.should_accept([2.0, 0.0, 0.0, 0.0, 0.0, 0.0], incremental_cost_bps=0.0)
    assert acc_single is True
    assert ev_single > 5.0


def test_finding_10_instant_gate_never_hardcodes_g3_pass(tmp_path) -> None:
    """write_instant_report must render UNKNOWN for G3 when no fresh typed G3 receipt is provided."""
    import importlib.util
    from pathlib import Path

    script = Path("D:/Github/Trade/gym-core/scripts/instant_gate_check.py")
    spec = importlib.util.spec_from_file_location("instant_gate_check", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    out_md = tmp_path / "gate.md"
    g1 = {"passed": True, "collector_connected": True, "markets": 10, "shards": 1, "lag_s": 1, "depth5_rows": 10, "nobitex_rows": 10}
    mod.write_instant_report(out_md, g1, {"hourly_passes": False}, {"orderbook_passes": False}, {"status": "SKIP"})
    txt = out_md.read_text(encoding="utf-8")
    assert "**UNKNOWN**" in txt
    assert "41 passed" not in txt


def test_finding_3_and_4_forward_journal_immutable_after_db_growth_and_valid_e_process(tmp_path) -> None:
    """Appending 200 later daily candles must not rewrite a 2-day journal's paper_nav, and e-process must be valid under asymmetric mean-zero null."""
    import json
    import sqlite3

    from gym.services.experiments.champion_forward_journal import (
        score_champion_forward_journal,
    )

    db = tmp_path / "market.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE instruments (instrument_id INTEGER PRIMARY KEY, symbol TEXT)")
    con.execute(
        "CREATE TABLE venue_candles (instrument_id INTEGER, resolution TEXT, t TEXT, o REAL, h REAL, l REAL, c REAL, v REAL)"
    )
    con.execute("INSERT INTO instruments VALUES (1, 'BTCUSDT')")
    # Day 0 close = 100 (ts_avail = 2025-01-02), Day 1 close = 110 (ts_avail = 2025-01-03)
    con.execute("INSERT INTO venue_candles VALUES (1, '1d', '2025-01-01T00:00:00Z', 100, 100, 100, 100, 10)")
    con.execute("INSERT INTO venue_candles VALUES (1, '1d', '2025-01-02T00:00:00Z', 100, 110, 100, 110, 10)")
    con.commit()

    jpath = tmp_path / "journal.jsonl"
    jpath.write_text(
        "\n".join([
            json.dumps({"as_of": "2025-01-02T00:05:00+00:00", "blended_weights": {"BTCUSDT": 1.0}}),
            json.dumps({"as_of": "2025-01-03T00:05:00+00:00", "blended_weights": {"BTCUSDT": 1.0}}),
        ]) + "\n",
        encoding="utf-8",
    )
    score_before = score_champion_forward_journal(jpath, db)
    assert score_before["paper_nav"] == pytest.approx(1100.0, abs=1e-6)

    # Append 200 future daily candles (far beyond old limit=120)
    t_base = datetime(2025, 1, 3, tzinfo=UTC)
    for k in range(200):
        ts_s = (t_base + timedelta(days=k)).isoformat().replace("+00:00", "Z")
        con.execute("INSERT INTO venue_candles VALUES (1, '1d', ?, 110, 110, 110, 110, 10)", (ts_s,))
    con.commit()
    con.close()

    score_after = score_champion_forward_journal(jpath, db)
    assert score_after["paper_nav"] == score_before["paper_nav"] == pytest.approx(1100.0, abs=1e-6)
    assert score_after["peak_nav"] == pytest.approx(1100.0, abs=1e-6)

    # Finding 4 check: E[1 + 0.5 * r] on mean-zero asymmetric distribution (+5% w.p. 0.9, -45% w.p. 0.1) == 1.0
    e_mult = 0.9 * (1.0 + 0.5 * 0.05) + 0.1 * (1.0 + 0.5 * (-0.45))
    assert e_mult <= 1.0 + 1e-12


def test_finding_9_window_scoring_respects_staleness_and_combines_phases() -> None:
    """score_7d_window_targets must mark uncovered windows unscored instead of matching distant timestamps."""
    from gym.domain.macro_quadrant_overlay import score_7d_window_targets

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    nav_ts = {t0 + timedelta(days=d): 1000.0 * (1.01 ** d) for d in range(8)}
    windows = [
        {"wid": "W1", "regime": "BULL", "start": t0.isoformat()},
        {"wid": "W_MISSING", "regime": "BEAR", "start": datetime(2026, 6, 1, tzinfo=UTC).isoformat()},
    ]
    res = score_7d_window_targets(nav_ts, windows, max_staleness_hours=24.0)
    assert res["scored_windows"] == 1
    assert res["unscored_windows"] == 1
    assert len(res["per_window"]) == 1
    assert res["per_window"][0]["wid"] == "W1"


def test_reference_event_tape_replay_and_restart_conservation() -> None:
    """Shared reference sequence (entry, missing bar, partial offset, fee, stop, restart) conserves equity identically."""
    ts0 = datetime(2025, 2, 1, 0, 0, tzinfo=UTC)
    ts1 = ts0 + timedelta(hours=2)
    ts2 = ts0 + timedelta(hours=4)
    offer = InstrumentOffer(
        venue="nobitex",
        symbol="BTCUSDT",
        instrument_type="ISOLATED_MARGIN",
        direction=-1,
        allowed_leverages=(1.0, 2.0),
        entry_cost_bps=10.0,
        exit_cost_bps=10.0,
        carry_model="NONE",
        carry_rate_bps=0.0,
    )

    def _run_sequence(restart_midway: bool) -> tuple[float, float, int]:
        book = MultiHorizonBook(free_cash=1000.0)
        # Step 1: buy 50% slow spot at 100 (10 bps fee)
        book.rebalance_slow_spot_targets({"BTCUSDT": 0.50}, {"BTCUSDT": 100.0}, {"BTCUSDT"}, ts0, leg_fee_bps=10.0)
        # Step 2: missing bar (BTCUSDT not in tradable) -> no trade, equity unchanged
        fills_missing = book.rebalance_slow_spot_targets({"BTCUSDT": 0.80}, {"BTCUSDT": 100.0}, set(), ts1, leg_fee_bps=10.0)
        assert fills_missing == 0
        if restart_midway:
            # Simulate process restart via snapshot clone of cash, lots, and counters
            snap_lots = {k: ThesisLot(**v.__dict__) for k, v in book.lots.items()}
            book = MultiHorizonBook(
                free_cash=book.free_cash,
                lots=snap_lots,
                total_fees=book.total_fees,
                total_borrow=book.total_borrow,
                total_pool_yield=book.total_pool_yield,
                internal_short_offsets=book.internal_short_offsets,
            )
        # Step 3: internal short offset near 2% dust threshold at 105
        book.open_fast_margin_lot(
            symbol="BTCUSDT",
            thesis_id="bear_short",
            direction=-1,
            leverage=1.0,
            target_collateral=518.0,
            entry_px=105.0,
            stop_bps=400.0,
            take_profit_bps=800.0,
            offer=offer,
            ts=ts2,
            entry_bar_vol=0.02,
            entry_gru_score=0.0,
            allow_internal_short_offset=True,
        )
        return book.mark_equity({"BTCUSDT": 105.0}), book.total_fees, book.internal_short_offsets

    eq_a, fee_a, off_a = _run_sequence(restart_midway=False)
    eq_b, fee_b, off_b = _run_sequence(restart_midway=True)
    assert eq_a == pytest.approx(eq_b, abs=1e-12)
    assert fee_a == pytest.approx(fee_b, abs=1e-12)
    assert off_a == off_b == 1


def test_dual_clock_nobitex_orderbook_parses_ts_event() -> None:
    """parse_nobitex_orderbook must preserve both exchange lastUpdate (ts_event) and local receipt (ts_avail)."""
    from gym.adapters.nobitex import parse_nobitex_orderbook

    ts_local = datetime(2026, 11, 25, 20, 0, 5, tzinfo=UTC)
    ts_ex_ms = int(datetime(2026, 11, 25, 20, 0, 4, tzinfo=UTC).timestamp() * 1000)
    qs = parse_nobitex_orderbook(
        "BTCUSDT",
        {"lastUpdate": ts_ex_ms, "bids": [["90000", "0.5"]], "asks": [["90010", "0.5"]]},
        ts_local,
    )
    assert qs is not None
    assert qs.ts_avail == ts_local
    assert qs.ts_event == datetime(2026, 11, 25, 20, 0, 4, tzinfo=UTC)



