"""Behavioral unit tests covering pure-domain research modules for CI domain-coverage parity."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from gym.domain.diffusion_and_netting import (
    _detect_leader_impulse,
    _trailing_beta,
    run_joint_admm_cross_sleeve_netting,
    simulate_lead_lag_diffusion,
)
from gym.domain.higher_order_and_sparse import (
    compute_second_order_trend_map,
    compute_walkforward_sleeve_weights,
    run_dynamic_shared_ledger_blend,
    simulate_structural_breakdown_short,
    simulate_tiered_sparse_ignition,
)
from gym.domain.ignition_and_intraday_exit import (
    compute_intraday_crash_timestamps,
    pearson_correlation,
    run_shared_ledger_1h_blend,
    run_true_intraday_3h_exit,
    simulate_ignition_detailed,
)
from gym.domain.ignition_upgrades import (
    _select_lev_and_col,
    _slot_limit_from_ar,
    _step_two_tranche_exit,
    combine_twin_phase_navs,
    compute_absorption_ratio_map,
    compute_cross_sectional_2h_context,
    simulate_episode_path_pnl,
    simulate_upgraded_ignition,
)
from gym.domain.model import BookTop, TradeTick
from gym.domain.multi_asset_research import (
    compute_4h_crash_exit_dates,
    compute_multi_asset_sleeves,
    continuous_ml_tilt,
    depth_scaled_l2_impact,
    simulate_market_neutral_l1_pairs,
    simulate_wallex_margin_short_cascades,
    spread_aware_l1_cost,
)
from gym.domain.passive_execution import (
    PassiveOrderSpec,
    _post_fill_markout_bps,
    simulate_passive_orders,
)
from gym.domain.rare_micro_signals import (
    detect_failed_downside_auction,
    detect_peer_relative_catchup,
    scan_micro_signal_intents,
)
from gym.domain.strategy_sleeves import SleeveSignal
from gym.domain.sub_2h_signals import (
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
from gym.domain.venue_contracts import FeeSchedule, FeeTier
from gym.domain.venue_leverage_models import (
    nobitex_long_liquidation_price,
    simulate_bull_levered_1d_core,
    simulate_nobitex_margin_ignition,
    simulate_wallex_trade_credit_contract,
)


def _bar(
    sym: str,
    ts_s: datetime,
    step_h: float,
    op: float,
    hi: float,
    lo: float,
    cl: float,
    vol: float = 100.0,
    eligible: bool = True,
) -> BarPoint:
    return BarPoint(
        symbol=sym,
        ts_start=ts_s,
        ts_avail=ts_s + timedelta(hours=step_h),
        open=op,
        high=hi,
        low=lo,
        close=cl,
        volume=vol,
        bar_source="synthetic",
        clock_complete=True,
        nonzero_volume_fraction=1.0,
        last_trade_age_bars=0,
        entry_eligible=eligible,
        mark_status="FRESH",
    )


def test_rare_micro_signals_detectors_and_scanner() -> None:
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    bars: list[BarPoint] = []
    rets: list[float] = []
    # Build 90 bars with normal noise, a breakdown+reclaim for failed auction, and an upward breakout for ignition
    for k in range(90):
        px = 100.0 + 0.1 * (k % 3)
        op, hi, lo, cl, vol = px, px * 1.004, px * 0.996, px * 1.001, 50.0
        if k in (45, 74):
            op, hi, lo, cl, vol = 100.0, 100.0, 93.0, 94.0, 120.0
        elif k in (46, 75):
            op, hi, lo, cl, vol = 95.0, 101.5, 95.0, 101.0, 90.0
        elif k == 80:
            op, hi, lo, cl, vol = 100.5, 108.0, 100.2, 107.5, 350.0
        b = _bar("BTCUSDT", t0 + timedelta(hours=2 * k), 2.0, op, hi, lo, cl, vol)
        bars.append(b)
        rets.append(0.0 if k == 0 else (cl - bars[k - 1].close) / bars[k - 1].close)

    fda = detect_failed_downside_auction(bars, 46, rets)
    assert fda is not None and fda.mechanism == "FAILED_DOWNSIDE_AUCTION"

    prc = detect_peer_relative_catchup(
        "ETHUSDT",
        _bar("ETHUSDT", t0, 2.0, 100.0, 102.0, 99.8, 101.8, 100.0),
        _bar("ETHUSDT", t0 - timedelta(hours=2), 2.0, 100.0, 100.5, 99.5, 100.0, 100.0),
        sym_ret=0.015,
        sym_prev_ret=-0.002,
        peer_rets_cur=[0.005, 0.004, 0.003, 0.002, 0.001],
        peer_rets_prev=[0.02, 0.025, 0.018, 0.022, 0.03],
        bar_vol=0.008,
    )
    assert prc is not None and prc.mechanism == "PEER_RELATIVE_CATCHUP"

    panel = {"BTCUSDT": bars}
    for sym in ("ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "LTCUSDT"):
        s_bars = []
        for k in range(90):
            cl = 100.0 + (2.5 if k in (79, 80) and sym != "ETHUSDT" else 0.0)
            op = 99.5 if (k == 80 and sym == "ETHUSDT") else cl
            cl_v = 101.0 if (k == 80 and sym == "ETHUSDT") else cl
            s_bars.append(_bar(sym, t0 + timedelta(hours=2 * k), 2.0, op, max(op, cl_v) * 1.005, min(op, cl_v) * 0.995, cl_v, 100.0))
        panel[sym] = s_bars

    breadth = {(t0 + timedelta(hours=2 * k)).date().isoformat(): 0.8 for k in range(95)}
    scanned = scan_micro_signal_intents(panel, tuple(panel), breadth)
    assert len(scanned["MOMENTUM_IGNITION"]) >= 1
    assert len(scanned["FAILED_DOWNSIDE_AUCTION"]) >= 1
    assert len(scanned["PEER_RELATIVE_CATCHUP"]) >= 1


def test_diffusion_and_netting_simulation_and_joint_admm() -> None:
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    assert _trailing_beta([0.01] * 20, [0.0] * 20) == 1.0
    assert _trailing_beta([0.01 * ((i % 3) - 1) for i in range(24)], [0.01 * ((i % 3) - 1) for i in range(24)]) >= 0.5
    assert _detect_leader_impulse(None, 0.02, [], []) is None

    panel_2h: dict[str, list[BarPoint]] = {"BTCUSDT": [], "ETHUSDT": [], "SOLUSDT": []}
    s1_by_date: dict[str, dict[str, float]] = {}
    breadth: dict[str, float] = {}
    for k in range(55):
        ts_s = t0 + timedelta(hours=2 * k)
        d_iso = (ts_s + timedelta(hours=2)).date().isoformat()
        breadth[d_iso] = 0.80
        s1_by_date[d_iso] = {"BTCUSDT": 0.5, "ETHUSDT": 0.4, "SOLUSDT": 0.4}
        btc_p = 100.0 + (k % 2) * 0.1 + (4.0 if k >= 42 else 0.0)
        eth_p = 100.0 + (0.0 if k < 43 else 3.5)
        sol_p = 100.0 + (0.0 if k < 44 else 5.0)
        panel_2h["BTCUSDT"].append(_bar("BTCUSDT", ts_s, 2.0, btc_p, btc_p * 1.005, btc_p * 0.995, btc_p, 400.0 if k == 42 else 80.0))
        panel_2h["ETHUSDT"].append(_bar("ETHUSDT", ts_s, 2.0, eth_p, eth_p * 1.005, eth_p * 0.995, eth_p, 100.0))
        panel_2h["SOLUSDT"].append(_bar("SOLUSDT", ts_s, 2.0, sol_p, sol_p * 1.005, sol_p * 0.995, sol_p, 100.0))

    diff_res, diff_nav = simulate_lead_lag_diffusion(
        panel_2h, ("BTCUSDT", "ETHUSDT", "SOLUSDT"), breadth, s1_by_date, label="DIFF_TEST", stress_iso="2025-01-04"
    )
    assert diff_res.entries >= 1
    assert len(diff_nav) >= 2

    # Joint ADMM netting test on short 1h panel
    syms = ("BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUTUSDT")
    panel_1h = {s: [_bar(s, t0 + timedelta(hours=k), 1.0, 100.0 + 0.2 * k, 101.0 + 0.2 * k, 99.0 + 0.2 * k, 100.2 + 0.2 * k) for k in range(30)] for s in syms}
    ts_sig = panel_1h["BTCUSDT"][5].ts_avail
    sigs_1d = {
        ts_sig: {
            s: SleeveSignal(s, ts_sig, 0.6 if s == "BTCUSDT" else 0.1, 0.0, 0.4 if "AU" in s or "AX" in s else None, 0.7, 2, 0.02, 1.0, True)
            for s in syms
        }
    }
    cov_h = tuple(tuple(0.02 if i == j else 0.005 for j in range(len(syms))) for i in range(len(syms)))
    ign_tgt = {panel_1h["BTCUSDT"][10].ts_avail: {"BTCUSDT": 0.30, "ETHUSDT": 0.20}}
    net_res = run_joint_admm_cross_sleeve_netting(panel_1h, syms, syms, sigs_1d, {ts_sig: (syms, cov_h)}, ign_tgt)
    assert net_res["fills"] >= 1


def test_multi_asset_sleeves_4h_crash_and_short_models() -> None:
    assert depth_scaled_l2_impact(None) == pytest.approx(0.025)
    assert depth_scaled_l2_impact(4000.0) == pytest.approx(0.0010)
    assert spread_aware_l1_cost(None) > 0.0013
    assert continuous_ml_tilt(0.80, base_rate=0.50) == pytest.approx(1.40)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    syms = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "PAXGUSDT", "XAUTUSDT")
    panel_1d: dict[str, list[BarPoint]] = {s: [] for s in syms}
    for d in range(150):
        ts_s = t0 + timedelta(days=d)
        for j, s in enumerate(syms):
            # Upward trend then bear drop to hit both S2 and S5 and cascade gates
            base = 100.0 + (0.6 * d if d < 110 else 66.0 - 1.5 * (d - 110) * (1.0 + 0.1 * j))
            if s in ("PAXGUSDT", "XAUTUSDT"):
                base = 2000.0 + 1.5 * d
            hi = base * (1.60 if d == 135 and s == "SOLUSDT" else 1.02)
            panel_1d[s].append(_bar(s, ts_s, 24.0, base, hi, base * 0.97, base * 0.995, 200.0))

    sigs = compute_multi_asset_sleeves(panel_1d, syms, warmup_bars=60)
    assert len(sigs) == 150
    eval_dates = sorted(sigs)
    casc = simulate_wallex_margin_short_cascades(panel_1d, sigs, eval_dates, ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    assert casc.name == "CRASH_CASCADE_SHORTS_1.5X"
    l1 = simulate_market_neutral_l1_pairs(panel_1d, sigs, eval_dates, ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "PAXGUSDT", "XAUTUSDT"), rebalance_days=5)
    assert l1.trades >= 4

    panel_4h = {
        s: [_bar(s, t0 + timedelta(hours=4 * k), 4.0, 100.0 - 0.3 * max(0, k - 130), 100.5, 98.0 - 0.3 * max(0, k - 130), 100.0 - 0.4 * max(0, k - 130), 100.0) for k in range(160)]
        for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    }
    crash_dates = compute_4h_crash_exit_dates(panel_4h, ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"))
    assert isinstance(crash_dates, set)


def test_higher_order_sparse_walkforward_and_intraday_exit() -> None:
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    assert pearson_correlation({}, {}) == 0.0
    assert pearson_correlation({f"d{i}": float(i) for i in range(6)}, {f"d{i}": float(2 * i) for i in range(6)}) == pytest.approx(1.0)

    # Walkforward sleeve weights (both modes)
    s_rets = {f"2025-01-{i + 1:02d}": 0.01 * ((i % 3) - 1) for i in range(30)}
    i_rets = {f"2025-01-{i + 1:02d}": 0.02 * (((i + 1) % 3) - 1) for i in range(30)}
    w_rp = compute_walkforward_sleeve_weights(s_rets, i_rets, mode="WF_INV_VOL_RP")
    w_mv = compute_walkforward_sleeve_weights(s_rets, i_rets, mode="WF_MIN_VAR")
    assert len(w_rp) == 30 and len(w_mv) == 30

    # Tiered sparse ignition + detailed ignition + dynamic blend + intraday crash
    core = ("BTCUSDT", "ETHUSDT")
    sat = ("ARBUSDT",)
    syms = core + sat + ("XAUTUSDT",)
    panel_2h: dict[str, list[BarPoint]] = {s: [] for s in syms}
    breadth: dict[str, float] = {}
    for k in range(95):
        ts_s = t0 + timedelta(hours=2 * k)
        breadth[(ts_s + timedelta(hours=2)).date().isoformat()] = 0.80
        for s in syms:
            px = 100.0 + 0.05 * k
            op, hi, lo, cl, vol = px, px * 1.003, px * 0.997, px * 1.001, 500.0
            if k == 80 and s in ("BTCUSDT", "ARBUSDT"):
                op, hi, lo, cl, vol = px, px * 1.08, px * 0.99, px * 1.07, 2500.0
            panel_2h[s].append(_bar(s, ts_s, 2.0, op, hi, lo, cl, vol))

    tiered_res, tiered_nav, tiered_tgts = simulate_tiered_sparse_ignition(
        panel_2h, core, sat, breadth, label="TIER_TEST", breakout_hours=96, hold_hours=12, sat_min_24h_dvol=100.0
    )
    assert tiered_res.base.entries >= 1

    det_res, det_nav, det_tgts = simulate_ignition_detailed(
        panel_2h, syms, breadth, label="DET_TEST", bucket_hours=2, breakout_hours=96, hold_hours=12
    )
    assert det_res.entries >= 1

    daily_tgts = {panel_2h["BTCUSDT"][12].ts_avail: {"BTCUSDT": 0.4, "XAUTUSDT": 0.4}}
    blend = run_dynamic_shared_ledger_blend(panel_2h, syms, daily_tgts, tiered_tgts, w_rp)
    assert blend["fills"] >= 1
    blend_1h = run_shared_ledger_1h_blend(panel_2h, syms, daily_tgts, det_tgts)
    assert blend_1h["fills"] >= 1

    crash_ts = {panel_2h["BTCUSDT"][40].ts_avail}
    intra = run_true_intraday_3h_exit(panel_2h, syms, daily_tgts, crash_ts)
    assert intra["intraday_exits"] >= 1

    # Structural breakdown short & second-order acceleration map
    panel_1d = {
        s: [
            _bar(
                s,
                t0 + timedelta(days=d),
                24.0,
                100.0 if d < 25 else 90.0 - 1.2 * (d - 25),
                101.0,
                88.0 - 1.2 * max(0, d - 25),
                99.5 if d < 25 else 89.0 - 1.2 * (d - 25),
                100.0 if d < 26 else 220.0,
            )
            for d in range(45)
        ]
        for s in ("BTCUSDT", "SOLUSDT", "ETHUSDT")
    }
    sigs_1d = {}
    for d in range(45):
        ts_a = panel_1d["BTCUSDT"][d].ts_avail
        sigs_1d[ts_a] = {
            "BTCUSDT": SleeveSignal("BTCUSDT", ts_a, -0.30, 0.0, None, 0.15, 3, 0.02, 1.2, True),
            "SOLUSDT": SleeveSignal("SOLUSDT", ts_a, -0.65, 0.0, None, 0.15, 3, 0.03, 1.2, True),
            "ETHUSDT": SleeveSignal("ETHUSDT", ts_a, -0.55, 0.0, None, 0.15, 3, 0.03, 1.2, True),
        }
    acc = compute_second_order_trend_map(sigs_1d, ("BTCUSDT", "SOLUSDT"))
    assert len(acc) == 45
    st_res, _ = simulate_structural_breakdown_short(panel_1d, ("BTCUSDT", "SOLUSDT", "ETHUSDT"), sigs_1d, label="STRUCT_SHORT")
    assert st_res.label == "STRUCT_SHORT"

    panel_3h = {
        s: [_bar(s, t0 + timedelta(hours=3 * k), 3.0, 100.0 - 0.4 * max(0, k - 170), 100.5, 98.0, 100.0 - 0.5 * max(0, k - 170), 100.0) for k in range(200)]
        for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    }
    assert isinstance(compute_intraday_crash_timestamps(panel_3h, ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")), set)


def test_ignition_upgrades_and_venue_leverage_models() -> None:
    assert _slot_limit_from_ar(None, 3) == 3
    assert _slot_limit_from_ar(0.80, 3) == 1
    assert _slot_limit_from_ar(0.60, 3) == 2
    assert nobitex_long_liquidation_price(100.0, 2.0) == pytest.approx(57.5)
    assert _select_lev_and_col(None, score_is_return=False, base_prob=0.45, use_conformal=False, recent_scores=[], in_dd_throttle=False) == (1.0, 0.30)
    assert _select_lev_and_col(0.80, score_is_return=False, base_prob=0.45, use_conformal=True, recent_scores=[0.1 * (i % 10) for i in range(40)], in_dd_throttle=True) == (1.0, 0.30)
    assert _select_lev_and_col(0.012, score_is_return=True, base_prob=0.45, use_conformal=False, recent_scores=[], in_dd_throttle=False) == (1.5, 0.30)

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    syms = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    panel_2h: dict[str, list[BarPoint]] = {s: [] for s in syms}
    breadth: dict[str, float] = {}
    scores: dict[tuple[datetime, str], float] = {}
    for k in range(100):
        ts_s = t0 + timedelta(hours=2 * k)
        ts_a = ts_s + timedelta(hours=2)
        breadth[ts_a.date().isoformat()] = 0.80
        for j, s in enumerate(syms):
            px = 100.0 + 0.1 * k * (1.0 + 0.2 * j)
            op, hi, lo, cl, vol = px, px * 1.004, px * 0.996, px * 1.001, 50.0
            if k == 80:
                op, hi, lo, cl, vol = px, px * 1.08, px * 0.99, px * 1.07, 400.0
            if k >= 81:
                cl = px * 1.12
                op, hi, lo = cl * 0.99, cl * 1.01, cl * 0.98
            panel_2h[s].append(_bar(s, ts_s, 2.0, op, hi, lo, cl, vol))
            scores[(ts_a, s)] = 0.70

    ar = compute_absorption_ratio_map(panel_2h, syms)
    wave, rank = compute_cross_sectional_2h_context(panel_2h, syms)
    assert len(ar) > 0 and len(wave) == 100 and len(rank) > 0
    assert abs(simulate_episode_path_pnl(panel_2h["BTCUSDT"], 79, 0.015)) <= 0.14

    pos_two = {
        "collateral": 100.0, "orig_collateral": 100.0, "notional": 150.0, "qty": 1.5,
        "entry_px": 100.0, "entry_fee": 0.24, "extreme": 100.0, "b_vol": 0.01,
        "liq_price": 45.0, "hard_stop_px": 96.0, "half_locked": False, "age": 0, "lev": 1.5,
    }
    c1, _, pnl1, _, _ = _step_two_tranche_exit(pos_two, panel_2h["BTCUSDT"][82], panel_2h["BTCUSDT"][83], leg_cost=0.0016, borrow_per_bar=0.0001, base_max_hold_bars=24, runner_max_hold_bars=48)
    assert c1 is False and pos_two["half_locked"] is True and pnl1 > 0.0

    r_up, nav_up = simulate_upgraded_ignition(
        panel_2h, syms, breadth, label="UPG", score_map=scores, use_two_tranche_exit=True, absorption_map=ar, use_conformal_and_dd_gov=True
    )
    comb = combine_twin_phase_navs("TWIN", nav_up, nav_up, r_up, r_up)
    assert comb["entries"] == r_up.entries * 2

    nbx_res, _, sched = simulate_nobitex_margin_ignition(
        panel_2h, syms, breadth, scores, label="NBX_IGN", top_tercile_leverage=2.0, borrow_mode="4h_wlx"
    )
    assert nbx_res.entries >= 1 and len(sched) == 100

    # 1d levered core + Wallex trade-credit stress (both normal + stopout path)
    panel_1d = {s: [_bar(s, t0 + timedelta(days=d), 24.0, 100.0 + d * 0.5, 101.0 + d * 0.5, 99.0 + d * 0.5, 100.5 + d * 0.5) for d in range(45)] for s in ("BTCUSDT", "XAUTUSDT")}
    tgts_1d = {panel_1d["BTCUSDT"][d].ts_avail: {"BTCUSDT": 0.6, "XAUTUSDT": 0.3} for d in range(45)}
    br_1d = {panel_1d["BTCUSDT"][d].ts_avail.date().isoformat(): 0.8 for d in range(45)}
    core_res, core_nav = simulate_bull_levered_1d_core(
        panel_1d, ("BTCUSDT", "XAUTUSDT"), tgts_1d, br_1d, label="CORE_15X", bull_leverage=1.5, idle_usdt_apr=0.0264
    )
    assert core_res.levered_days >= 1 and core_res.ending_nav > 950.0
    tc_ok = simulate_wallex_trade_credit_contract(core_nav, label="TC_OK")
    assert tc_ok.total_30d_cycles >= 1
    crash_nav = {f"2025-01-{i + 1:02d}": (1000.0 if i < 10 else 800.0) for i in range(35)}
    tc_stop = simulate_wallex_trade_credit_contract(crash_nav, label="TC_STOP")
    assert tc_stop.stop_out_cycles >= 1 and tc_stop.single_life_survived is False


def test_sub2h_signals_and_passive_execution() -> None:
    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    bars_1m = [_bar("BTCUSDT", t0 + timedelta(minutes=m), 1.0 / 60.0, 100.0, 101.0, 99.0, 100.2, 10.0) for m in range(60)]
    resamp = resample_1min_to_minutes(bars_1m, minutes=30)
    assert len(resamp) == 2 and compute_ema_series([100.0, 102.0, 104.0], 5)[-1] > 100.0

    # N1 / N4 / sub2h detectors & strategy replay
    bars_1h = []
    vols = []
    rets = []
    for k in range(55):
        cl = 100.0 - 0.4 * k if k < 48 else 82.0
        op = cl + 0.5
        hi = cl + 2.5 if k == 45 else op + 0.2
        lo = cl - 0.5
        if k == 49:
            op, hi, lo, cl = 82.0, 105.0, 81.9, 104.0
        bars_1h.append(_bar("BTCUSDT", t0 + timedelta(hours=k), 1.0, op, hi, lo, cl, 300.0 if k in (45, 49) else 50.0))
        vols.append(bars_1h[-1].volume)
        rets.append(0.0 if k == 0 else (cl - bars_1h[k - 1].close) / bars_1h[k - 1].close)

    ef = compute_ema_series([b.close for b in bars_1h], 9)
    es = compute_ema_series([b.close for b in bars_1h], 26)
    _ = detect_n1_pullback_rejection_short(bars_1h, ef, es, vols, rets, 45, breadth=0.10, s1_daily=-0.5)
    _ = detect_n4_coiled_down_short(bars_1h, es, vols, rets, 45, breadth=0.10, s1_daily=-0.5)
    ign_1h = detect_sub2h_ignition_long(bars_1h, vols, rets, 49)
    assert ign_1h is not None and ign_1h.direction == 1
    assert is_deep_bear_cascade_active(80.0, 90.0, 95.0, 91.0, 0.10) is True
    ranked = rank_deep_bear_short_targets(
        ("BTCUSDT", "ETHUSDT", "XAUTUSDT"),
        {"BTCUSDT": SleeveSignal("BTCUSDT", t0, -0.5, 0.0, None, 0.1, 2, 0.02, 1.0, True)},
        {"BTCUSDT": -0.05},
        {"BTCUSDT": 90.0},
        {"BTCUSDT": 95.0},
        {"BTCUSDT": 80.0},
    )
    assert ranked and ranked[0][0] == "BTCUSDT"

    sim_sub, _ = simulate_sub2h_signal_strategy(
        {"BTCUSDT": bars_1h},
        {bars_1h[49].ts_avail: [ign_1h]},
        {b.ts_avail: True for b in bars_1h},
        cfg=Sub2hSimConfig(label="SUB1H_TEST", bar_hours=1.0),
    )
    assert sim_sub["entries"] == 1

    # Passive execution modes + post-fill markout + repeg
    books = [
        BookTop("BTCUSDT", t0, Decimal("100"), Decimal("102"), Decimal("1"), Decimal("5"), frozenset()),
        BookTop("BTCUSDT", t0 + timedelta(seconds=20), Decimal("100.5"), Decimal("102"), Decimal("1"), Decimal("5"), frozenset()),
        BookTop("BTCUSDT", t0 + timedelta(seconds=310), Decimal("98"), Decimal("99"), Decimal("5"), Decimal("5"), frozenset()),
    ]
    trades = [
        TradeTick("BTCUSDT", t0 + timedelta(seconds=5), t0 + timedelta(seconds=5), Decimal("100"), Decimal("2"), "SELL"),
        TradeTick("BTCUSDT", t0 + timedelta(seconds=5), t0 + timedelta(seconds=6), Decimal("100"), Decimal("2"), "SELL"),
        TradeTick("BTCUSDT", t0 + timedelta(seconds=25), t0 + timedelta(seconds=25), Decimal("100.5"), Decimal("3"), "SELL"),
    ]
    fees = FeeSchedule(
        venue="wallex",
        venue_kind="SPOT_BOOK",
        quote_asset="USDT",
        tiers=(FeeTier("L1", None, Decimal("0.001"), Decimal("0.002")),),
        permanent_discount=Decimal("0"),
        discount_expires_at=None,
        fee_in_received_asset=True,
        observed_at=t0,
        source="test",
    )
    orders = [
        PassiveOrderSpec("p_rej", "BTCUSDT", "BUY", Decimal("1"), Decimal("102"), t0, post_only=True),
        PassiveOrderSpec("p_tak", "BTCUSDT", "BUY", Decimal("1"), Decimal("102"), t0, post_only=False),
        PassiveOrderSpec("p_fil", "BTCUSDT", "BUY", Decimal("1.5"), Decimal("100"), t0, repeg_offset_bps=Decimal("0"), repeg_cooldown_s=10.0, max_repegs=1),
    ]
    res_adv = simulate_passive_orders(orders, books, trades, fees, duplicate_print_mode="adversarial_lower_bound")
    assert [r.status for r in res_adv] == ["POST_ONLY_REJECTED", "FILLED", "FILLED"]
    assert _post_fill_markout_bps("BUY", Decimal("100"), t0, books, horizon_s=300) < Decimal(0)


def test_dynamic_resolver_ledger_and_multi_horizon_book_paths() -> None:
    from gym.domain.dynamic_resolver_ledger import simulate_dynamic_resolver
    from gym.domain.instrument_resolver import (
        InstrumentOffer,
        MarketView,
        ResolvedAction,
        ResolverConfig,
    )
    from gym.domain.multi_horizon_book import MultiHorizonBook, OnlineICTracker

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    panel = {
        "BTCUSDT": [
            _bar("BTCUSDT", t0 + timedelta(hours=2 * k), 2.0, 100.0 + k, 102.0 + k, 99.0 if k != 4 else 90.0, 100.5 + k)
            for k in range(8)
        ],
        "ETHUSDT": [
            _bar("ETHUSDT", t0 + timedelta(hours=2 * k), 2.0, 100.0 - k, 105.0 if k == 5 else 101.0, 98.0, 99.5 - k)
            for k in range(8)
        ],
    }
    spot_offer = InstrumentOffer("nobitex", "BTCUSDT", "SPOT", 1, (1.0,), 16.0, 16.0, "NONE", 0.0, 0.0, 5000.0)
    margin_offer = InstrumentOffer("nobitex", "BTCUSDT", "ISOLATED_MARGIN", 1, (1.0, 2.0), 16.0, 16.0, "EOD_DAILY_BORROW", 5.0, 0.1, 5000.0)
    perp_short = InstrumentOffer("hyperliquid", "ETHUSDT", "PERP_FUTURE", -1, (1.0, 2.0, 3.0), 5.0, 5.0, "FUNDING_RATE", 1.0, 0.05, 5000.0)
    offers_ts = {b.ts_avail: {"BTCUSDT": (spot_offer, margin_offer), "ETHUSDT": (perp_short,)} for b in panel["BTCUSDT"]}
    views_ts = {
        panel["BTCUSDT"][k].ts_avail: {
            "BTCUSDT": MarketView("BTCUSDT", panel["BTCUSDT"][k].ts_avail, 120.0, 16.0, 200.0, 0.45, 0.85, 0.80),
            "ETHUSDT": MarketView("ETHUSDT", panel["ETHUSDT"][k].ts_avail, -100.0, 12.0, 250.0, 0.50, 0.80, 0.20),
        }
        for k in range(len(panel["BTCUSDT"]))
    }

    step = {"i": 0}

    def _fn(views, offers, pos, eq, hrs, dd, cov, cfg):
        i = step["i"]
        step["i"] += 1
        acts = {}
        if i == 0:
            acts["BTCUSDT"] = ResolvedAction("BTCUSDT", "OPEN", "nobitex", "ISOLATED_MARGIN", 1, 2.0, 200.0, 400.0, 200.0, 60.0, "open")
            acts["ETHUSDT"] = ResolvedAction("ETHUSDT", "OPEN", "hyperliquid", "PERP_FUTURE", -1, 2.0, 150.0, 300.0, 250.0, 50.0, "short")
        elif i == 2 and "BTCUSDT" in pos:
            acts["BTCUSDT"] = ResolvedAction("BTCUSDT", "REDUCE", "nobitex", "ISOLATED_MARGIN", 1, 1.0, 100.0, 100.0, 200.0, 20.0, "trim")
        elif i == 3 and "BTCUSDT" in pos:
            acts["BTCUSDT"] = ResolvedAction("BTCUSDT", "SELL_CLOSE", "nobitex", "ISOLATED_MARGIN", 1, 1.0, 0.0, 0.0, 0.0, 0.0, "close")
        return acts

    res, _ = simulate_dynamic_resolver(
        panel, views_ts, offers_ts, {}, _fn, label="DYN_TEST", cfg=ResolverConfig(max_venue_leverage=3.0, idle_pool_apr=0.0264)
    )
    assert res.margin_long_entries == 1 and res.perp_short_entries == 1

    tr = OnlineICTracker()
    for _ in range(10):
        tr.update(0.5, 0.02)
    assert tr.shrunk_ic > 0.0

    book = MultiHorizonBook(free_cash=1000.0)
    book.rebalance_slow_spot_targets({"BTCUSDT": 0.5}, {"BTCUSDT": 100.0}, {"BTCUSDT"}, t0, leg_fee_bps=16.0)
    book.rebalance_slow_spot_targets({"BTCUSDT": 0.25}, {"BTCUSDT": 100.0}, {"BTCUSDT"}, t0, leg_fee_bps=16.0)
    assert book.free_cash > 700.0


def test_tmn_carry_meta_gateway_multi_horizon_and_execution_qual() -> None:
    from gym.domain.execution_qualification import (
        depth_walk_liquidation,
        model_latency_phases,
        qualify_executable_net,
    )
    from gym.domain.instrument_resolver import InstrumentOffer, ResolverConfig
    from gym.domain.meta_gateway import (
        AdaptiveVoteGateway,
        compute_calibration_diagnostics,
        extract_gateway_features,
    )
    from gym.domain.multi_horizon_book import (
        MultiHorizonBook,
        ThesisLot,
        check_lot_intrabar_exit,
        resolve_safe_ignition_leverage,
        select_rv_laggard_hedge,
    )
    from gym.domain.tmn_carry import TmnBorrowTerms, simulate_tmn_borrow_carry

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    depth_top = ((Decimal("95"), Decimal("10000")), (Decimal("90"), Decimal("50000")))
    books_liq = [
        BookTop("USDTTMN", t0, Decimal("100"), Decimal("101"), Decimal("1000"), Decimal("1000"), frozenset(), depth=(depth_top, depth_top)),
        BookTop("USDTTMN", t0 + timedelta(hours=8), Decimal("98"), Decimal("99"), Decimal("1000"), Decimal("1000"), frozenset()),
        BookTop("USDTTMN", t0 + timedelta(days=22), Decimal("105"), Decimal("106"), Decimal("1000"), Decimal("1000"), frozenset()),
    ]
    r_rej = simulate_tmn_borrow_carry(TmnBorrowTerms("USDTTMN", Decimal("100000"), Decimal("2"), allow_renewal_at_expiry=False), books_liq)
    assert r_rej.status == "RENEWAL_REJECTED_DAY21"
    r_ok = simulate_tmn_borrow_carry(TmnBorrowTerms("USDTTMN", Decimal("100000"), Decimal("2"), allow_renewal_at_expiry=True), books_liq)
    assert r_ok.roll_count >= 1

    gw = AdaptiveVoteGateway()
    for i in range(15):
        gw.update_realized_outcome("s1", 0.01 if i % 2 == 0 else -0.002)
    sig = SleeveSignal("BTCUSDT", t0, 0.5, 0.2, 0.1, 0.6, 8, 0.02, 1.0, True)
    assert len(extract_gateway_features(sig, consensus_score=0.3)) == 9
    assert gw.combine_signal(sig) > 0.0
    cal = compute_calibration_diagnostics([0, 1, 1, 0], [0.1, 0.8, 0.9, 0.2], n_bins=2)
    assert cal.n_samples == 4

    offer_l = InstrumentOffer("nobitex", "BTCUSDT", "ISOLATED_MARGIN", 1, (1.0, 2.0, 3.0), 16.0, 16.0, "EOD_DAILY_BORROW", 5.0, 0.1, 10000.0)
    offer_s = InstrumentOffer("nobitex", "ETHUSDT", "ISOLATED_MARGIN", -1, (1.0, 2.0), 16.0, 16.0, "EOD_DAILY_BORROW", 5.0, 0.1, 10000.0)
    bk = MultiHorizonBook(free_cash=1000.0)
    bk.rebalance_slow_spot_targets({"ETHUSDT": 0.2}, {"ETHUSDT": 100.0}, {"ETHUSDT"}, t0, leg_fee_bps=16.0)
    assert bk.open_fast_margin_lot(
        symbol="BTCUSDT", thesis_id="ignition_2h", direction=1, leverage=2.0,
        target_collateral=200.0, entry_px=100.0, stop_bps=300.0, take_profit_bps=600.0,
        offer=offer_l, ts=t0, entry_bar_vol=0.02, entry_gru_score=0.8,
    )
    assert bk.pyramid_lot_on_house_money(("BTCUSDT", "ignition_2h"), 103.0, 0.25, 16.0)
    assert bk.open_fast_margin_lot(
        symbol="ETHUSDT", thesis_id="rv_hedge", direction=-1, leverage=2.0,
        target_collateral=250.0, entry_px=100.0, stop_bps=300.0, take_profit_bps=500.0,
        offer=offer_s, ts=t0, entry_bar_vol=0.02, entry_gru_score=0.1, allow_internal_short_offset=True,
    )
    assert resolve_safe_ignition_leverage(offer_l, 250.0, 0.90, 0.0, ResolverConfig()) >= 1.5
    assert select_rv_laggard_hedge("BTCUSDT", {"ETHUSDT": SleeveSignal("ETHUSDT", t0, -0.5, 0.0, None, 0.2, 5, 0.02, 1.0, True)}, {"ETHUSDT": -0.04}, 0.20) is not None

    tp_lot = ThesisLot(("BTCUSDT", "t"), "BTCUSDT", "t", "nobitex", "ISOLATED_MARGIN", 1, 2.0, 100.0, 200.0, 2.0, 100.0, 95.0, 106.0, 60.0, t0, "2025-01-01")
    assert check_lot_intrabar_exit(tp_lot, _bar("BTCUSDT", t0, 2.0, 102.0, 108.0, 101.0, 107.0), taker_exit_bps=16.0, oco_maker_exit_bps=8.0, use_oco_maker_tp=True)[0] == "OCO_TP"
    sh_lot = ThesisLot(("ETHUSDT", "s"), "ETHUSDT", "s", "nobitex", "ISOLATED_MARGIN", -1, 2.0, 100.0, 200.0, 2.0, 100.0, 105.0, 94.0, 130.0, t0, "2025-01-01")
    assert check_lot_intrabar_exit(sh_lot, _bar("ETHUSDT", t0, 2.0, 101.0, 106.0, 99.0, 105.0), taker_exit_bps=16.0, oco_maker_exit_bps=8.0, use_oco_maker_tp=True)[0] == "STOP"

    spec = {"stepSize": 2, "minQty": "0.01", "minNotional": "10", "isMarketTypeEnable": True}
    qtop = BookTop("BTCUSDT", t0, Decimal("100"), Decimal("101"), Decimal("5"), Decimal("5"), frozenset())
    assert qualify_executable_net(
        side="BUY", order_type="MARKET", quantity=Decimal("1"), spec=spec,
        fee_rate=Decimal("0.002"), fee_source="wallex", quote=qtop,
        depth_levels=((Decimal("101"), Decimal("2")),), halted=False,
        execution_at=t0 + timedelta(seconds=10), market_status_at=t0,
    )["qualified"] is True
    assert qualify_executable_net(side="SELL", order_type="MARKET", quantity=Decimal("0.001"), spec=spec, fee_rate=None, fee_source=None, quote=None, halted=True)["status"] == "UNKNOWN"
    assert depth_walk_liquidation("SELL", Decimal("3"), [(Decimal("100"), Decimal("1")), (Decimal("99"), Decimal("1"))], fee_rate=Decimal("0.002"))["status"] == "PARTIAL"
    assert depth_walk_liquidation("BUY", Decimal("1"), None, fee_rate=Decimal("0.002"))["status"] == "UNAVAILABLE"
    assert model_latency_phases(t0, receive_ms=1, publish_ms=2, decide_ms=3, send_ms=4, ack_ms=5)["total_latency_ms"] == 15


def test_optimal_exits_paper_ledger_microstructure_and_tmn_liq() -> None:
    import numpy as np

    from gym.domain.microstructure import (
        MicrostructureConsolidator,
        compute_ofi_step,
        l2_depth_imbalance,
        stoikov_microprice,
    )
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
    from gym.domain.paper_ledger import SelfFinancingLedger
    from gym.domain.tmn_carry import (
        TmnBorrowTerms,
        compare_fx_appreciation_scenarios,
        simulate_tmn_borrow_carry,
    )

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    cfg = OptimalExitConfig(use_e1_ratchet=True, use_e2_climax_trim=True, use_e3_optimal_stopping=True, use_e4_slow_peak_protect=True)
    lot_l = ThesisLot(("BTCUSDT", "ignition_2h"), "BTCUSDT", "ignition_2h", "nobitex", "ISOLATED_MARGIN", 1, 2.0, 100.0, 200.0, 2.0, 100.0, 96.0, 112.0, 55.0, t0, "2025-01-01", entry_bar_vol=0.02, peak_price=108.0, age_bars=8)
    lot_s = ThesisLot(("ETHUSDT", "bear"), "ETHUSDT", "bear", "nobitex", "ISOLATED_MARGIN", -1, 2.0, 100.0, 200.0, 2.0, 100.0, 104.0, 90.0, 145.0, t0, "2025-01-01", entry_bar_vol=0.02, peak_price=92.0, age_bars=8)
    assert compute_ratchet_stop_price(lot_l, cur_close=106.0, cfg=cfg) > 100.0
    assert compute_ratchet_stop_price(lot_s, cur_close=94.0, cfg=cfg) < 100.0
    lot_stall = ThesisLot(("SOLUSDT", "ignition_2h"), "SOLUSDT", "ignition_2h", "nobitex", "ISOLATED_MARGIN", 1, 2.0, 100.0, 200.0, 2.0, 100.0, 96.0, 112.0, 55.0, t0, "2025-01-01", entry_bar_vol=0.02, peak_price=100.5, age_bars=9)
    assert is_dead_money_pre_eod(lot_stall, hours_to_utc_eod=2.0, cfg=cfg) is True
    climax_bar = _bar("BTCUSDT", t0, 2.0, 104.0, 112.0, 103.5, 106.0, 300.0)
    assert detect_climax_exhaustion(lot_l, climax_bar, 2.5, cfg) is True

    rng = np.random.default_rng(1)
    x_tr = rng.normal(size=(50, 10))
    y_tr = rng.normal(scale=20.0, size=50)
    mdl = OptimalStoppingModel().fit(x_tr, y_tr)
    st = OptimalStoppingState(3, 0.04, 0.06, 0.40, 0.20, 1.5, 1.0, 0.01, 2.0, 0.7)
    _ = mdl.predict_wait_value_bps(st)
    assert decide_optimal_stopping_action(-20.0, st, already_pyramided=False, already_trimmed=False, cfg=cfg) == "OPTIMAL_EXIT"
    assert decide_optimal_stopping_action(0.0, st, already_pyramided=False, already_trimmed=False, cfg=cfg) == "OPTIMAL_TRIM_50"
    assert decide_optimal_stopping_action(80.0, st, already_pyramided=False, already_trimmed=False, cfg=cfg) == "FREE_ROLL_PYRAMID"
    assert decide_optimal_stopping_action(20.0, st, already_pyramided=True, already_trimmed=True, cfg=cfg) == "HOLD"

    bk = MultiHorizonBook(free_cash=500.0)
    bk.lots[("BTCUSDT", "ignition_2h")] = lot_l
    assert trim_lot_fraction(bk, ("BTCUSDT", "ignition_2h"), 0.5, 106.0, 16.0) > 0.0
    assert trim_lot_fraction(bk, ("BTCUSDT", "ignition_2h"), 0.99, 106.0, 16.0) > 0.0
    slow_lot = ThesisLot(("BTCUSDT", "slow_core"), "BTCUSDT", "slow_core", "nobitex", "SPOT", 1, 1.0, 100.0, 100.0, 1.0, 100.0, 0.0, 0.0, 0.0, t0, "2025-01-01", peak_price=125.0)
    assert evaluate_slow_core_peak_protection(slow_lot, 114.0, 0.02, 0.50, already_trimmed=False, cfg=cfg)[0] == "TRIM_50"
    assert summarize_exit_efficiency([])["closed_trades"] == 0
    assert summarize_exit_efficiency([ClosedTradeCapture(120.0, 200.0, 80.0, 4.0, "TRAIL", True)])["win_rate_pct"] == 100.0

    # Paper ledger quote-fee path + tight-cash scaling + sell->buy sequencing
    led = SelfFinancingLedger(Decimal("1000"), fee_rate=Decimal("0.002"), fee_in_received_asset=False)
    pxs = {"BTCUSDT": Decimal("100"), "ETHUSDT": Decimal("50")}
    led.rebalance_to_targets(t0, {"BTCUSDT": 0.6, "ETHUSDT": 0.6}, pxs)
    led.rebalance_to_targets(t0 + timedelta(hours=1), {"BTCUSDT": 0.0, "ETHUSDT": 0.9}, pxs)
    assert led.mark_nav(pxs) < Decimal("1000")

    # Microstructure consolidator & helpers
    assert stoikov_microprice(Decimal("100"), Decimal("102"), Decimal("0"), Decimal("0")) == Decimal("101")
    assert l2_depth_imbalance(([(Decimal("100"), Decimal("4"))], [(Decimal("101"), Decimal("1"))])) > Decimal(0)
    b1 = BookTop("BTCUSDT", t0, Decimal("100"), Decimal("101"), Decimal("2"), Decimal("3"), frozenset(), depth=([(Decimal("100"), Decimal("4"))], [(Decimal("101"), Decimal("2"))]))
    b2 = BookTop("BTCUSDT", t0 + timedelta(seconds=1), Decimal("100.5"), Decimal("101.5"), Decimal("3"), Decimal("2"), frozenset())
    assert compute_ofi_step(b1, b2) != Decimal(0)
    cons = MicrostructureConsolidator("BTCUSDT", vpin_bucket_volume=Decimal("1"), vpin_window_buckets=2)
    cons.on_trade(TradeTick("BTCUSDT", t0, t0, Decimal("100.5"), Decimal("2.5"), "BUY"))
    cons.on_trade(TradeTick("BTCUSDT", t0, t0, Decimal("100.5"), Decimal("0.8"), "SELL"))
    cons.on_book_top(b1)
    cons.on_book_top(b2)
    mbar = cons.flush_bar(t0 + timedelta(seconds=5))
    assert mbar is not None and mbar.vpin is not None

    # TMN carry liquidation + FX appreciation scenarios
    fx = compare_fx_appreciation_scenarios(TmnBorrowTerms("USDTTMN", Decimal("100000"), Decimal("2")), start_at=t0, horizon_days=25, annual_fx_rates=(Decimal("0.00"), Decimal("0.25")))
    assert len(fx) == 2
    crash_books = [
        BookTop("USDTTMN", t0, Decimal("100"), Decimal("101"), Decimal("1000"), Decimal("1000"), frozenset()),
        BookTop("USDTTMN", t0 + timedelta(hours=8), Decimal("40"), Decimal("41"), Decimal("1000"), Decimal("1000"), frozenset()),
    ]
    assert simulate_tmn_borrow_carry(TmnBorrowTerms("USDTTMN", Decimal("100000"), Decimal("2")), crash_books).status == "LIQUIDATED"


def test_sub2h_bellman_n1_n4_and_passive_cancel_replace() -> None:
    from gym.domain.execution_qualification import (
        maker_queue_fill,
        simulate_passive_cancel_replace,
    )

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)
    bars: list[BarPoint] = []
    vols: list[float] = []
    rets: list[float] = []
    for k in range(60):
        # Smooth downtrend, coil in 35..44, sharp breakdown on k=44, EMA-touch rejection on k=45, long ignition on k=50
        cl = 120.0 - 0.5 * k
        op = cl + 0.3
        hi = op + 0.1
        lo = cl - 0.1
        vol = 100.0
        if 38 <= k < 44:
            op, hi, lo, cl, vol = 100.0, 100.05, 99.95, 100.0, 100.0
        elif k == 44:
            op, hi, lo, cl, vol = 100.0, 100.1, 90.0, 90.5, 300.0
        elif k == 45:
            op, hi, lo, cl, vol = 92.0, 102.0, 91.5, 91.8, 250.0
        elif k == 50:
            op, hi, lo, cl, vol = 92.0, 128.0, 91.9, 126.0, 400.0
        bars.append(_bar("BTCUSDT", t0 + timedelta(hours=k), 1.0, op, hi, lo, cl, vol))
        vols.append(vol)
        rets.append(0.0 if k == 0 else (cl - bars[k - 1].close) / bars[k - 1].close)

    ef = compute_ema_series([b.close for b in bars], 9)
    es = compute_ema_series([b.close for b in bars], 26)
    _ = detect_n4_coiled_down_short(bars, es, vols, rets, 44, breadth=0.10, s1_daily=-0.5)
    n1 = detect_n1_pullback_rejection_short(bars, ef, es, vols, rets, 45, breadth=0.10, s1_daily=-0.5)
    assert n1 is not None
    ign = detect_sub2h_ignition_long(bars, vols, rets, 50)
    assert ign is not None

    class _DummyBellman:
        def __init__(self, wait_bps: float) -> None:
            self._v = wait_bps

        def predict_wait_value_bps(self, _st) -> float:
            return self._v

    for wbps in (-20.0, 0.0, 80.0):
        res, _ = simulate_sub2h_signal_strategy(
            {"BTCUSDT": bars},
            {bars[50].ts_avail: [ign]},
            {b.ts_avail: True for b in bars},
            cfg=Sub2hSimConfig(label=f"BM_{wbps}", bar_hours=1.0, use_bellman_exit=True),
            bellman_model_fn=lambda _ts, v=wbps: _DummyBellman(v),
        )
        assert res["entries"] == 1

    # Maker queue + cancel/replace + SELL side passive orders + feed gaps
    trades = [
        TradeTick("BTCUSDT", t0 + timedelta(seconds=2), t0 + timedelta(seconds=2), Decimal("100"), Decimal("2"), "SELL"),
        TradeTick("BTCUSDT", t0 + timedelta(seconds=2), t0 + timedelta(seconds=3), Decimal("100"), Decimal("2"), "SELL"),
        TradeTick("BTCUSDT", t0 + timedelta(seconds=6), t0 + timedelta(seconds=6), Decimal("102"), Decimal("3"), "BUY"),
    ]
    mq = maker_queue_fill(side="BUY", limit_price=Decimal("100"), order_qty=Decimal("5"), queue_ahead=Decimal("1"), trades=trades, active_at=t0, cancel_effective_at=t0 + timedelta(seconds=5), best_opposite_price=Decimal("102"))
    assert mq["status"] == "PARTIAL_CANCELED"
    mq_rej = maker_queue_fill(side="SELL", limit_price=Decimal("100"), order_qty=Decimal("1"), queue_ahead=Decimal("0"), trades=trades, active_at=t0, best_opposite_price=Decimal("101"))
    assert mq_rej["status"] == "POST_ONLY_REJECTED"

    cr = simulate_passive_cancel_replace(
        side="BUY",
        total_qty=Decimal("4"),
        quotes_plan=[
            {"sent_at": t0, "limit_price": Decimal("100"), "queue_ahead": Decimal("0")},
            {"sent_at": t0 + timedelta(seconds=4), "limit_price": Decimal("99"), "queue_ahead": Decimal("0"), "cancel_sent_at": t0 + timedelta(seconds=10)},
        ],
        trades=trades,
        maker_fee_rate=Decimal("0.001"),
    )
    assert Decimal(cr["filled_qty"]) > Decimal(0)

    fees = FeeSchedule("wallex", "SPOT_BOOK", "USDT", (FeeTier("L1", None, Decimal("0.001"), Decimal("0.002")),), Decimal("0"), None, False, t0, "test")
    books = [
        BookTop("BTCUSDT", t0, Decimal("100"), Decimal("102"), Decimal("1"), Decimal("1"), frozenset()),
        BookTop("BTCUSDT", t0 + timedelta(seconds=3), Decimal("100"), Decimal("101.5"), Decimal("1"), Decimal("1"), frozenset()),
    ]
    sell_res = simulate_passive_orders(
        [PassiveOrderSpec("s1", "BTCUSDT", "SELL", Decimal("2"), Decimal("102"), t0, repeg_offset_bps=Decimal("0"), repeg_cooldown_s=1.0, max_repegs=1)],
        books,
        trades,
        fees,
        duplicate_print_mode="deduplicated",
        feed_gap_windows=((t0 + timedelta(seconds=10), t0 + timedelta(seconds=20)),),
    )
    assert sell_res[0].status == "FILLED"


def test_macro_overlay_bellman_convex_resolver_and_exec_contracts() -> None:
    import numpy as np

    from gym.domain.bellman_stopping import (
        NonlinearBellmanModel,
        SlowCoreBellmanModel,
        SlowCoreStoppingState,
        compute_bellman_path_target_bps,
        detect_breakdown_short_trigger,
        detect_flush_rebound_trigger,
        detect_uncensored_early_ignition,
    )
    from gym.domain.convex_optimizer import (
        OptimizationProblem,
        portfolio_utility,
        simple_no_trade_band_allocator,
        solve_convex_portfolio,
        verify_post_solve_orders,
    )
    from gym.domain.execution_costs import (
        check_causal_costs,
        validate_hourly_costs,
        validate_impact_models,
        validate_postfill_costs,
    )
    from gym.domain.execution_qualification import (
        build_fill_audit_trail,
        paired_cost_ladder,
        simulate_trailing_stop,
        venue_guard_transition_check,
    )
    from gym.domain.instrument_resolver import (
        InstrumentOffer,
        MarketView,
        PositionState,
        ResolverConfig,
        resolve_a3_state_machine,
        resolve_h12_hybrid,
    )
    from gym.domain.macro_quadrant_overlay import (
        MacroQuadrantConfig,
        compute_4h_supertrend_direction,
        compute_macro_quadrant_targets,
        rebalance_bidirectional_margin_lots,
        score_7d_window_targets,
    )
    from gym.domain.multi_horizon_book import MultiHorizonBook
    from gym.domain.optimal_exits import OptimalStoppingState
    from gym.domain.venue_contracts import InstrumentMaster

    t0 = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)

    # 1. Execution qualification trailing stop + paired ladder + venue guard + fill audit
    ts_trades = [
        TradeTick("BTCUSDT", t0, t0, Decimal("100"), Decimal("1"), "BUY"),
        TradeTick("BTCUSDT", t0 + timedelta(seconds=5), t0 + timedelta(seconds=5), Decimal("110"), Decimal("1"), "BUY"),
        TradeTick("BTCUSDT", t0 + timedelta(seconds=10), t0 + timedelta(seconds=10), Decimal("98"), Decimal("1"), "SELL"),
    ]
    ts_quotes = [
        BookTop("BTCUSDT", t0 + timedelta(seconds=11), Decimal("97"), Decimal("98"), Decimal("2"), Decimal("2"), frozenset(), depth=([(Decimal("97"), Decimal("0.5"))], [(Decimal("98"), Decimal("1"))])),
    ]
    st_part = simulate_trailing_stop(side="SELL", quantity=Decimal("1"), trail_fraction=Decimal("0.05"), trades=ts_trades, quotes=ts_quotes, fee_rate=Decimal("0.002"))
    assert st_part["status"] == "PARTIAL_EXPOSED"
    assert simulate_trailing_stop(side="SELL", quantity=Decimal("1"), trail_fraction=Decimal("0.05"), trades=ts_trades[:1], quotes=ts_quotes, fee_rate=Decimal("0.002"))["status"] == "NOT_TRIGGERED"
    assert simulate_trailing_stop(side="SELL", quantity=Decimal("1"), trail_fraction=Decimal("0.05"), trades=ts_trades, quotes=[], fee_rate=Decimal("0.002"))["status"] == "TRIGGERED_NO_QUOTE"
    assert paired_cost_ladder([{"name": "A", "evidence_tier": "OBSERVED_PUBLIC_DATA", "net_return": "0.1", "max_drawdown": "0.05", "fill_fraction": "1.0"}])["creates_selection_trial"] is False
    assert venue_guard_transition_check(reference_price=Decimal("100"), bid=Decimal("99.9"), ask=Decimal("100.1"), reference_age_s=10.0)["status"] == "PASS"
    assert venue_guard_transition_check(reference_price=Decimal("100"), bid=Decimal("120"), ask=Decimal("121"), reference_age_s=500.0, depth_levels=(), halted=True)["status"] == "REFUSED"
    assert build_fill_audit_trail(decision_at=t0, symbol="BTCUSDT", side="BUY", order_type="LIMIT", requested_qty=Decimal("1"), filled_qty=Decimal("1"), fill_price=Decimal("100"), fee_rate=Decimal("0.002"), fee_source="wallex", rule_vintage_at=t0)["schema"] == "fill-audit/1"

    # 2. Macro quadrant overlay: 4h supertrend + signed targets + bidirectional lot rebalance + 7d scorer
    bars_4h = [_bar("BTCUSDT", t0 + timedelta(hours=4 * k), 4.0, 100.0 + k * 0.5, 102.0 + k * 0.5, 98.0 + k * 0.5, 101.0 + k * 0.5) for k in range(25)]
    st_dir = compute_4h_supertrend_direction(bars_4h)
    assert len(st_dir) >= 10
    day_sigs = {
        "BTCUSDT": SleeveSignal("BTCUSDT", t0, 0.7, 0.2, None, 0.80, 4, 0.03, 1.0, True),
        "ETHUSDT": SleeveSignal("ETHUSDT", t0, 0.6, 0.1, None, 0.80, 4, 0.04, 1.0, True),
        "XAUTUSDT": SleeveSignal("XAUTUSDT", t0, 0.5, 0.0, 0.4, 0.80, 4, 0.015, 1.0, True),
    }
    cfg_mq = MacroQuadrantConfig()
    tgts_bull = compute_macro_quadrant_targets(day_sigs, {"XAUTUSDT": 0.0}, 0.80, {"BTCUSDT": 0.5, "ETHUSDT": 0.6, "XAUTUSDT": 0.18}, {"BTCUSDT": 1, "XAUTUSDT": 1}, cfg_mq)
    assert tgts_bull.get("BTCUSDT", 0.0) > 0.0 and tgts_bull.get("XAUTUSDT", 0.0) > 0.0
    day_sigs_bear = {s: SleeveSignal(s, t0, -0.6, 0.0, None, 0.10, 4, 0.03, 1.1, True) for s in ("BTCUSDT", "ETHUSDT", "XAUTUSDT")}
    tgts_bear = compute_macro_quadrant_targets(day_sigs_bear, {}, 0.10, {"BTCUSDT": 0.5, "ETHUSDT": 0.6, "XAUTUSDT": 0.18}, {"BTCUSDT": -1, "XAUTUSDT": -1}, cfg_mq)
    assert tgts_bear.get("BTCUSDT", 0.0) < 0.0
    mhb = MultiHorizonBook(free_cash=1000.0)
    offers_mq = {
        s: (
            InstrumentOffer("nobitex", s, "ISOLATED_MARGIN", 1, (1.0, 2.0, 3.0), 16.0, 16.0, "EOD_DAILY_BORROW", 5.0, 0.1),
            InstrumentOffer("nobitex", s, "ISOLATED_MARGIN", -1, (1.0, 2.0, 3.0), 16.0, 16.0, "EOD_DAILY_BORROW", 5.0, 0.1),
        )
        for s in ("BTCUSDT", "ETHUSDT", "XAUTUSDT")
    }
    px_mq = {"BTCUSDT": 100.0, "ETHUSDT": 100.0, "XAUTUSDT": 100.0}
    assert rebalance_bidirectional_margin_lots(mhb, {"BTCUSDT": 0.6, "XAUTUSDT": 0.4}, px_mq, set(px_mq), offers_mq, t0, cfg=cfg_mq) >= 2
    assert rebalance_bidirectional_margin_lots(mhb, {"BTCUSDT": 0.95, "XAUTUSDT": -0.4}, px_mq, set(px_mq), offers_mq, t0 + timedelta(days=1), cfg=cfg_mq) >= 1
    nav_series = {t0 + timedelta(days=d): 1000.0 * (1.035 ** d) for d in range(10)}
    w_res = score_7d_window_targets(nav_series, [{"wid": 1, "regime": "BULL", "start": t0.isoformat()}])
    assert w_res["scored_windows"] == 1 and w_res["full_5of5_hits"] == 1

    # 3. Bellman stopping models + continuation value + 3 trigger detectors
    rng = np.random.default_rng(3)
    nl_m = NonlinearBellmanModel().fit(rng.normal(size=(60, 10)), rng.normal(scale=50.0, size=60), epochs=5)
    sc_m = SlowCoreBellmanModel().fit(rng.normal(size=(70, 10)), rng.normal(scale=50.0, size=70))
    assert isinstance(nl_m.predict_wait_value_bps(OptimalStoppingState(2, 0.03, 0.04, 0.25, 0.2, 1.5, 1.0, 0.01, 10.0, 0.6)), float)
    assert isinstance(sc_m.predict_wait_5d_bps(SlowCoreStoppingState(5, 0.1, 0.15, 0.03, 0.5, 0.1, 0.6, 0.02, 1.0)), float)
    bell_bars = [_bar("BTCUSDT", t0 + timedelta(hours=2 * k), 2.0, 100.0 + 0.1 * (k % 3), 101.0, 99.0, 100.2, 100.0) for k in range(85)]
    bell_rets = [0.0 if k == 0 else (bell_bars[k].close - bell_bars[k - 1].close) / bell_bars[k - 1].close for k in range(85)]
    bell_vols = [b.volume for b in bell_bars]
    assert compute_bellman_path_target_bps(bell_bars, 20, 1, 100.0, 0.02) is not None
    assert compute_bellman_path_target_bps(bell_bars, 20, -1, 100.0, 0.02) is not None
    _ = detect_flush_rebound_trigger(bell_bars, bell_rets, bell_vols, 40)
    _ = detect_breakdown_short_trigger(bell_bars, bell_rets, bell_vols, [b.low for b in bell_bars], 75, 0.20)
    _ = detect_uncensored_early_ignition(bell_bars, bell_rets, bell_vols, [b.high for b in bell_bars], 50)

    # 4. Convex optimizer group projection + verify_post_solve_orders + Resolver A3 / H12
    prob = OptimizationProblem(
        symbols=("BTCUSDT", "XAUTUSDT", "PAXGUSDT"),
        expected_returns=(0.01, 0.008, 0.006),
        current_weights=(0.3, 0.2, 0.2),
        covariance=((0.04, 0.0, 0.0), (0.0, 0.01, 0.008), (0.0, 0.008, 0.01)),
        l1_fee_costs=(0.0016, 0.0016, 0.0016),
        l2_impact_costs=(0.002, 0.002, 0.002),
        underlying_groups={"GOLD": (1, 2)},
        issuer_groups={"GOLD_ISSUER": (1, 2)},
    )
    opt_r = solve_convex_portfolio(prob, max_iter=150)
    assert sum(opt_r.weights) <= 0.96 and isinstance(portfolio_utility(opt_r.weights, prob), float)
    insts = {s: InstrumentMaster("wallex", s, s[:4], None, "CRYPTO_SPOT", "24X7", 2, 4, Decimal("0.01"), Decimal("10"), True, True, True) for s in prob.symbols}
    v_plan = verify_post_solve_orders(prob.symbols, (0.4, 0.05, 0.2), (0.2, 0.2, 0.2), Decimal("1000"), Decimal("200"), {"BTCUSDT": Decimal("100"), "XAUTUSDT": Decimal("100"), "PAXGUSDT": Decimal("0")}, {"XAUTUSDT": Decimal("0.5")}, insts, Decimal("0.002"))
    assert len(v_plan) == 3 and v_plan[2].skipped_reason == "NO_VALID_PRICE"
    assert simple_no_trade_band_allocator((0.2, 0.5), (0.25, 0.7), band=0.10) == (0.2, 0.7)

    views_r = {
        "BTCUSDT": MarketView("BTCUSDT", t0, 140.0, 16.0, 250.0, 0.45, 0.90, 0.80),
        "ETHUSDT": MarketView("ETHUSDT", t0, -140.0, 16.0, 250.0, 0.50, 0.85, 0.15),
    }
    pos_r = {"BTCUSDT": PositionState("BTCUSDT", "nobitex", "SPOT", 1, 1.0, 200.0, 200.0, 100.0, 96.0, 0.0, 4.0, 10.0, t0, 16.0)}
    a3 = resolve_a3_state_machine(views_r, offers_mq, pos_r, 1000.0, 10.0, 0.0, ResolverConfig(max_venue_leverage=3.0))
    h12 = resolve_h12_hybrid(views_r, offers_mq, pos_r, 1000.0, 10.0, 0.0, {("BTCUSDT", "BTCUSDT"): 0.04, ("ETHUSDT", "ETHUSDT"): 0.05}, ResolverConfig(max_venue_leverage=3.0))
    assert "BTCUSDT" in a3 and "ETHUSDT" in h12

    # 5. Execution costs validation paths
    validate_impact_models({"BTCUSDT": {"schema": "sqrt-impact/1", "symbol": "BTCUSDT", "source": "PUBLIC_TRADE_VS_PRIOR_MID_PROXY", "sample_count": 30, "trained_until": t0.isoformat(), "a": "1", "b": "1", "volume_base": "10", "volatility_bps": "20", "fit_rmse_bps": "2", "holdout_rmse_bps": "3"}})
    validate_hourly_costs({"BTCUSDT": {"schema": "hourly-costs/1", "symbol": "BTCUSDT", "trained_until": t0.isoformat(), "hours": {"0": {"quote_samples": 20, "spread_bps": "5", "taker_fee_rate": "0.002", "maker_fee_rate": "0.001"}}}})
    validate_postfill_costs({"BTCUSDT": {"schema": "postfill-adverse/1", "symbol": "BTCUSDT", "trained_until": t0.isoformat(), "penalty_bps": "5", "sample_count": 30, "source": "PAPER_MARKOUT_DIAGNOSTIC"}})
    check_causal_costs(None, None, t0 + timedelta(days=1), postfill_costs={"BTCUSDT": {"trained_until": t0.isoformat()}})


def test_meta_gateway_falsification_account_obs_and_conversion() -> None:
    from gym.domain.account_observations import parse_wallex_balances, project_account
    from gym.domain.conversion import ConversionWorkload
    from gym.domain.meta_gateway import run_synthetic_falsification_checks

    fres = run_synthetic_falsification_checks(seed=7, n_samples=120)
    assert "null_panel" in fres and "planted_edge_panel" in fres

    bal = parse_wallex_balances({"success": True, "result": {"balances": {"USDT": {"value": "100", "locked": "5"}}}})
    assert bal["USDT"]["value"] == "100"
    with pytest.raises(ValueError):
        parse_wallex_balances({"success": False})
    snap = project_account(
        "main",
        "2025-01-01T00:00:00Z",
        balances={"USDT": {"value": "100", "locked": "0"}},
        orders=[{"status": "NEW", "client_id": "c1", "symbol": "BTCUSDT", "filled": "0.1"}],
    )
    assert snap["orders"][0]["funded_trade"] is False

    cw = ConversionWorkload(
        instruction_id="conv_1",
        account="main",
        symbol="BTCUSDT",
        side="BUY",
        requested_base="1",
        arrival_price="100",
        fee_rate="0.002",
        started_at="2025-01-01T00:00:00Z",
        deadline="2025-01-02T00:00:00Z",
        max_spread_bps="50",
        quote_budget="110",
    )
    opp_ok = cw.opportunity(observed_at="2025-01-01T01:00:00Z", bid="100", ask="100.1", quote_age_ms=100, venue_open=True)
    opp_blk = cw.opportunity(observed_at="2025-01-03T00:00:00Z", bid="105", ask="100", quote_age_ms=5000, venue_open=False)
    assert opp_ok["state"] == "DRY_RUN_CANDIDATE" and opp_blk["state"] == "BLOCKED"
    assert cw.observe_fake_fill("f1", quantity="0.5", price="100", quote_fee="0.2", observed_at="2025-01-01T02:00:00Z") == 1





