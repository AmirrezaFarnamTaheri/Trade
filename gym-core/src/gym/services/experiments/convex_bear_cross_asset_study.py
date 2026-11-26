"""Comprehensive Diverse Short Discovery (+3%/1d, +5%/3d, +15%/7d) & Unified E3_V2 Absorption Study.

Part 1: Benchmarks 10 diverse standalone short mechanisms across 1,085d (2024-2026) OOS + 1d/3d/7d Northstar:
        Convex Tiered Majors, Anti-Squeeze Tier-2 Alts, Cross-Asset Gold (XAUT), CTA Volatility Targeting,
        Kaufman ER Trend-Persistence, 4h Fast Squeeze Guard, and Maker vs Taker execution.
Part 2: Absorbs validated zero-liquidation winners (CTA Vol-Targeted M4+XAUT, Kaufman ER Daily, and Full
        Vol+ER+4h Synthesis) directly inside the unified MultiHorizonBook twin-phase (0h+1h) ledger alongside
        E3_V2_NONLINEAR_BELLMAN, verified with exact conservation, year-by-year stability, and 95% bootstrap CIs.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.bear_majors_sleeve import (
    BEAR_MAJORS_4,
    BEAR_MAJORS_4_PLUS_GOLD,
    BearMajorsConfig,
    CtaBearVolConfig,
    compute_calm_bear_majors_targets,
    compute_cta_vol_targeted_bear_targets,
    compute_daily_vol_and_kaufman_er,
    rebalance_slow_short_lots,
)
from ...domain.bellman_stopping import NonlinearBellmanModel
from ...domain.core_signal_geometry import DEFENSIVE_METALS_CAPS
from ...domain.higher_order_and_sparse import compute_second_order_trend_map
from ...domain.in_position_and_execution import tehran_execution_cost_bps
from ...domain.instrument_resolver import ResolverConfig, build_local_venue_offers
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.multi_horizon_book import MultiHorizonBook, check_lot_intrabar_exit
from ...domain.optimal_exits import (
    ClosedTradeCapture,
    OptimalExitConfig,
    summarize_exit_efficiency,
)
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.sub_2h_signals import compute_ema_series
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from ...domain.venue_leverage_models import simulate_nobitex_margin_ignition
from .admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    extract_daily_breadth,
)
from .bellman_resurrection_study import (
    _step_bellman_fast_lots,
    _train_wf_nonlinear_bellman,
)
from .champion_v2_verification import _merge_twin_schedules, _run_v2_joint_shared_ledger
from .ensemble_study import STRESS_REPLAY_START, _daily_returns_map, _portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .ignition_upgrade_ablation_study import (
    _extract_11feat_coiled_spring_dataset,
    _walkforward_gru_scores,
)
from .multi_horizon_adaptive_study import (
    ADAPTIVE_UNIVERSE,
    NOBITEX_IDLE_USDT_APR,
    _compute_2h_bar_stats,
    _solve_slow_targets_for_day,
)
from .optimal_exit_study import (
    _extract_optimal_stopping_dataset,
    _open_fast_exit_study_entries,
)
from .unified_book_helpers import (
    latest_signal_date,
    nav_ts_to_daily,
    resolve_bar_prices,
    window_return_pct,
    year_returns_pct,
)

NORTHSTAR_TARGETS = {"1d": 3.0, "3d": 5.0, "7d": 15.0}


def _build_4h_squeeze_map(bars_4h: list[BarPoint], jump_thr: float) -> tuple[list[datetime], dict[datetime, bool]]:
    cs = [b.close for b in bars_4h]
    e12 = compute_ema_series(cs, 12)
    out: dict[datetime, bool] = {}
    for i, b in enumerate(bars_4h):
        r4 = (cs[i] / cs[i - 1] - 1.0) if i > 0 and cs[i - 1] > 0 else 0.0
        out[b.ts_avail] = (b.close > e12[i] * 1.006) or (r4 > jump_thr)
    return sorted(out), out


def _is_4h_squeezing(ts: datetime, ts_list: list[datetime], sq_map: dict[datetime, bool]) -> bool:
    dt = latest_signal_date(ts_list, ts)
    return sq_map[dt] if dt is not None else False


def _check_short_stops(book: MultiHorizonBook, by_avail: dict[str, dict[datetime, BarPoint]], ts: datetime, fee_bps: float) -> None:
    for key in list(book.lots):
        if key[1] != "slow_bear_short":
            continue
        lot = book.lots[key]
        bar = by_avail.get(lot.symbol, {}).get(ts)
        if bar is None:
            continue
        evt, px, fbps = check_lot_intrabar_exit(lot, bar, taker_exit_bps=fee_bps, oco_maker_exit_bps=4.5, use_oco_maker_tp=False)
        if evt == "LIQ":
            book.liquidations += 1
            del book.lots[key]
        elif evt == "STOP":
            book.close_lot(key, px, fbps)
            book.stop_outs += 1


def _simulate_standalone_cta_bear(
    panel_2h: dict[str, list[BarPoint]],
    sigs_u: dict,
    accel_u: dict,
    daily_breadth: dict[str, float],
    ann_vol: dict[str, dict[datetime, float]],
    kaufman_er: dict[str, dict[datetime, float]],
    btc_sq: tuple[list[datetime], dict[datetime, bool]],
    xaut_sq: tuple[list[datetime], dict[datetime, bool]],
    cfg: CtaBearVolConfig,
) -> dict:
    """Run one standalone CTA Cross-Asset Bear Short sleeve inside MultiHorizonBook over 1,085d."""
    syms = tuple(dict.fromkeys(cfg.crypto_symbols + ((cfg.gold_symbol,) if cfg.gold_symbol else ())))
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in syms}
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in syms}
    all_ts = sorted({t for s in syms for t in by_avail[s] if t >= datetime(2024, 1, 1, tzinfo=UTC)})
    offers = {s: build_local_venue_offers(s, nobitex_leg_bps=cfg.leg_fee_bps, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in syms}
    book = MultiHorizonBook(free_cash=1000.0)
    last_px: dict[str, float] = {}
    nav_ts: dict[datetime, float] = {}
    sig_dates, sig_ptr = sorted(sigs_u), 0
    last_sig_applied: datetime | None = None
    pending: dict[str, float] | None = None
    fills = 0

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, 2.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR, eod_borrow_bps=5.0)
        exec_px, tradable = resolve_bar_prices(syms, by_start, by_avail, ts, last_px)
        _check_short_stops(book, by_avail, ts, cfg.leg_fee_bps)
        while sig_ptr + 1 < len(sig_dates) and sig_dates[sig_ptr + 1] <= ts:
            sig_ptr += 1
        cur_sig = sig_dates[sig_ptr] if (sig_dates and sig_dates[sig_ptr] <= ts) else None
        if cur_sig is None:
            nav_ts[ts] = book.mark_equity(exec_px)
            continue

        b_sq = _is_4h_squeezing(ts, *btc_sq) if cfg.use_4h_squeeze_guard else False
        x_sq = _is_4h_squeezing(ts, *xaut_sq) if cfg.use_4h_squeeze_guard else False
        vol_now = {s: ann_vol.get(s, {}).get(cur_sig, 0.50) for s in syms}
        er_now = {s: kaufman_er.get(s, {}).get(cur_sig, 0.25) for s in syms}
        br = daily_breadth.get(cur_sig.date().isoformat(), 0.5)

        if cfg.use_4h_squeeze_guard:
            if b_sq or x_sq or ts.hour in (10, 11):
                if cur_sig != last_sig_applied or b_sq or x_sq:
                    if ts.hour in (10, 11):
                        last_sig_applied = cur_sig
                    tgts = compute_cta_vol_targeted_bear_targets(
                        sigs_u[cur_sig], accel_u.get(cur_sig, {}), br, vol_now, er_now, cfg,
                        btc_4h_squeezing=b_sq, gold_4h_squeezing=x_sq,
                    )
                    fills += rebalance_slow_short_lots(book, tgts, exec_px, tradable, offers, ts, cfg=cfg)
        else:
            if cur_sig != last_sig_applied:
                last_sig_applied = cur_sig
                pending = compute_cta_vol_targeted_bear_targets(
                    sigs_u[cur_sig], accel_u.get(cur_sig, {}), br, vol_now, er_now, cfg,
                )
            if pending is not None and ts.hour >= 10:
                fills += rebalance_slow_short_lots(book, pending, exec_px, tradable, offers, ts, cfg=cfg)
                pending = None

        nav_ts[ts] = book.mark_equity(exec_px)

    daily = nav_ts_to_daily(nav_ts)
    fm = _portfolio_metrics(daily)
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    sm = _portfolio_metrics({k: v for k, v in daily.items() if k >= stress_iso})
    r24, r72, r7d = window_return_pct(nav_ts, 24.0), window_return_pct(nav_ts, 72.0), window_return_pct(nav_ts, 168.0)
    return {
        "label": cfg.label,
        "ret_24h_pct": r24,
        "ret_72h_pct": r72,
        "ret_7d_pct": r7d,
        "hit_3_5_15": (r24 >= 3.0 and r72 >= 5.0 and r7d >= 15.0),
        "ending_nav": fm["ending_nav"],
        "full_ret_pct": fm["ret_pct"],
        "stress_ret_pct": sm["ret_pct"],
        "ann_sharpe": fm["ann_sharpe"],
        "max_dd_pct": fm["max_dd_pct"],
        "liqs": book.liquidations,
        "stops": book.stop_outs,
        "fills": fills,
        "fees_usdt": round(book.total_fees, 2),
        "borrow_usdt": round(book.total_borrow, 2),
        "pool_yield_usdt": round(book.total_pool_yield, 2),
        "year_rets": year_returns_pct(daily),
    }


def _simulate_unified_e3v2_phase(
    panel_2h: dict[str, list[BarPoint]],
    sigs_13: dict,
    accel_13: dict,
    sigs_metals: dict,
    sigs_u: dict,
    accel_u: dict,
    cov_h_by_ts: dict,
    daily_breadth: dict[str, float],
    ann_vol: dict[str, dict[datetime, float]],
    kaufman_er: dict[str, dict[datetime, float]],
    btc_sq: tuple[list[datetime], dict[datetime, bool]],
    xaut_sq: tuple[list[datetime], dict[datetime, bool]],
    gru_scores: dict[tuple[datetime, str], float],
    nl_models: list[tuple[datetime, datetime, NonlinearBellmanModel]],
    bar_stats: tuple,
    bear_cfg: BearMajorsConfig | CtaBearVolConfig | None,
) -> tuple[dict, dict[datetime, float]]:
    """True single-ledger MultiHorizonBook combining E3_V2_NONLINEAR_BELLMAN + CTA Cross-Asset Bear Short."""
    bvol_map, _, vrat_map, bret_map = bar_stats
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    all_ts = sorted({t for s in IGNITION_18_CRYPTO for t in by_avail[s]})
    short_fee = bear_cfg.leg_fee_bps if bear_cfg is not None else 16.0
    offers_by_sym = {s: build_local_venue_offers(s, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in ADAPTIVE_UNIVERSE}
    short_offers = {s: build_local_venue_offers(s, nobitex_leg_bps=short_fee, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in ADAPTIVE_UNIVERSE}
    r_cfg = ResolverConfig(max_venue_leverage=5.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR)
    exit_cfg = OptimalExitConfig(use_e3_optimal_stopping=True)

    book = MultiHorizonBook(free_cash=1000.0)
    pending_slow: dict[str, float] | None = None
    pending_bear: dict[str, float] | None = None
    last_px: dict[str, float] = {}
    recent_gru: list[float] = []
    trimmed_lots: set[tuple[str, str]] = set()
    trades_log: list[ClosedTradeCapture] = []
    peak_nav, bear_fills = 1000.0, 0
    nav_ts: dict[datetime, float] = {}
    sig_dates, sig_ptr = sorted(sigs_13), 0
    last_sig_applied: datetime | None = None

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, 2.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR, eod_borrow_bps=5.0)
        exec_px, tradable = resolve_bar_prices(ADAPTIVE_UNIVERSE, by_start, by_avail, ts, last_px)
        saved_shorts = {k: book.lots.pop(k) for k in list(book.lots) if k[1] == "slow_bear_short"}
        _step_bellman_fast_lots(
            book, by_avail, exec_px, tradable, ts, bret_map, vrat_map,
            nl_models, None, trimmed_lots, trades_log, exit_cfg, pyramid_frac=0.45,
        )
        book.lots.update(saved_shorts)
        _check_short_stops(book, by_avail, ts, short_fee)

        while sig_ptr + 1 < len(sig_dates) and sig_dates[sig_ptr + 1] <= ts:
            sig_ptr += 1
        cur_sig = sig_dates[sig_ptr] if (sig_dates and sig_dates[sig_ptr] <= ts) else None

        equity = book.mark_equity(exec_px)
        peak_nav = max(peak_nav, equity)
        dd_pct = ((peak_nav - equity) / peak_nav * 100.0) if peak_nav > 0 else 0.0
        if equity < 20.0:
            nav_ts[ts] = equity
            continue

        if cur_sig is not None and cur_sig != last_sig_applied and cur_sig in cov_h_by_ts:
            last_sig_applied = cur_sig
            active_slow, cov_h = cov_h_by_ts[cur_sig]
            cur_slow_w = tuple(
                (book.lots[(s, "slow_core")].qty * exec_px.get(s, 0.0) / equity) if (s, "slow_core") in book.lots else 0.0
                for s in active_slow
            )
            pending_slow = _solve_slow_targets_for_day(
                active_slow, sigs_13[cur_sig], accel_13.get(cur_sig, {}), cur_slow_w, cov_h,
                sigs_metals.get(cur_sig, {}), exec_px, 0.08, tehran_execution_cost_bps(10, use_passive_maker=True),
            )
            if bear_cfg is not None:
                pending_bear = _compute_bear_targets(bear_cfg, cur_sig, sigs_u, accel_u, daily_breadth, ann_vol, kaufman_er, False, False)

        if pending_slow is not None and ts.hour >= 10:
            if bear_cfg is not None and pending_bear is not None and not pending_bear:
                bear_fills += rebalance_slow_short_lots(book, {}, exec_px, tradable, short_offers, ts, cfg=bear_cfg)
                pending_bear = None
            book.rebalance_slow_spot_targets(
                pending_slow, exec_px, tradable, ts, leg_fee_bps=tehran_execution_cost_bps(ts.hour, use_passive_maker=True),
            )
            pending_slow = None
            if bear_cfg is not None and pending_bear is not None:
                bear_fills += rebalance_slow_short_lots(book, pending_bear, exec_px, tradable, short_offers, ts, cfg=bear_cfg)
                pending_bear = None

        # Optional 4h intraday fast squeeze guard on active slow_bear_short lots
        if isinstance(bear_cfg, CtaBearVolConfig) and bear_cfg.use_4h_squeeze_guard and cur_sig is not None:
            b_sq, x_sq = _is_4h_squeezing(ts, *btc_sq), _is_4h_squeezing(ts, *xaut_sq)
            if (b_sq or x_sq) and any(k[1] == "slow_bear_short" for k in book.lots):
                sq_tgts = _compute_bear_targets(bear_cfg, cur_sig, sigs_u, accel_u, daily_breadth, ann_vol, kaufman_er, b_sq, x_sq)
                bear_fills += rebalance_slow_short_lots(book, sq_tgts, exec_px, tradable, short_offers, ts, cfg=bear_cfg)

        _open_fast_exit_study_entries(
            book, ts, equity, dd_pct, exec_px, tradable, gru_scores, recent_gru, bvol_map, offers_by_sym, r_cfg,
        )
        nav_ts[ts] = book.mark_equity(exec_px)

    return {
        "fees": round(book.total_fees, 2),
        "borrow": round(book.total_borrow, 2),
        "pool_yield": round(book.total_pool_yield, 2),
        "liqs": book.liquidations,
        "stops": book.stop_outs,
        "bear_fills": bear_fills,
        "eff": summarize_exit_efficiency(trades_log),
    }, nav_ts


def _compute_bear_targets(
    bear_cfg: BearMajorsConfig | CtaBearVolConfig,
    cur_sig: datetime,
    sigs_u: dict,
    accel_u: dict,
    daily_breadth: dict[str, float],
    ann_vol: dict[str, dict[datetime, float]],
    kaufman_er: dict[str, dict[datetime, float]],
    b_sq: bool,
    x_sq: bool,
) -> dict[str, float]:
    br = daily_breadth.get(cur_sig.date().isoformat(), 0.5)
    ds, ac = sigs_u.get(cur_sig, {}), accel_u.get(cur_sig, {})
    if isinstance(bear_cfg, BearMajorsConfig):
        return compute_calm_bear_majors_targets(ds, ac, br, bear_cfg)
    syms = bear_cfg.crypto_symbols + ((bear_cfg.gold_symbol,) if bear_cfg.gold_symbol else ())
    v_now = {s: ann_vol.get(s, {}).get(cur_sig, 0.50) for s in syms}
    er_now = {s: kaufman_er.get(s, {}).get(cur_sig, 0.25) for s in syms}
    return compute_cta_vol_targeted_bear_targets(
        ds, ac, br, v_now, er_now, bear_cfg, btc_4h_squeezing=b_sq, gold_4h_squeezing=x_sq,
    )


def run_convex_bear_cross_asset_study(
    db_path: Path,
    *,
    report_md: Path | None = None,
    report_json: Path | None = None,
) -> dict:
    """Execute full +3%/5%/15% Diverse Short Discovery + Unified E3_V2 MultiHorizonBook Absorption Study."""
    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in ADAPTIVE_UNIVERSE}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in ADAPTIVE_UNIVERSE}
    finally:
        con.close()

    panel_13 = {s: panel_1d[s] for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    accel_13 = compute_second_order_trend_map(sigs_13, BASE_13_SYMBOLS)
    metal_syms = tuple(DEFENSIVE_METALS_CAPS)
    sigs_metals = compute_slow_sleeves({s: panel_1d[s] for s in metal_syms}, metal_syms)
    sigs_u = compute_slow_sleeves({s: panel_1d[s] for s in BEAR_MAJORS_4_PLUS_GOLD}, BEAR_MAJORS_4_PLUS_GOLD)
    accel_u = compute_second_order_trend_map(sigs_u, BEAR_MAJORS_4_PLUS_GOLD)
    daily_breadth = extract_daily_breadth(sigs_13)
    ann_vol, kaufman_er = compute_daily_vol_and_kaufman_er(panel_1d, BEAR_MAJORS_4_PLUS_GOLD)

    dated_13 = build_dated_returns_index(panel_13, BASE_13_SYMBOLS)
    cov_h_by_ts = {}
    for t_day in sorted(sigs_13):
        if t_day < datetime(2024, 1, 1, tzinfo=UTC):
            continue
        act_s = tuple(s for s in BASE_13_SYMBOLS if s in sigs_13[t_day])
        if len(act_s) >= 2:
            cov_h_by_ts[t_day] = (act_s, build_shrunk_horizon_cov(dated_13, act_s, t_day))

    p2_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in ADAPTIVE_UNIVERSE if panel_1h[s]}
    p2_1 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=1) for s in ADAPTIVE_UNIVERSE if panel_1h[s]}
    btc_sq = _build_4h_squeeze_map(resample_hourly_to_bucket(panel_1h["BTCUSDT"], 4, offset_hours=0), 0.028)
    xaut_sq = _build_4h_squeeze_map(resample_hourly_to_bucket(panel_1h["XAUTUSDT"], 4, offset_hours=0), 0.015)

    # Part 1: Standalone CTA / Kaufman / 4h-Guard / Gold Cross-Asset Benchmarks (all L=0 design!)
    standalone_cfgs = [
        CtaBearVolConfig("CTA_VOLTGT65_M4_XAUT_TAKER", target_ann_vol=0.65, max_crypto_gross=2.20, max_gold_gross=1.00),
        CtaBearVolConfig("CTA_VOLTGT80_M4_XAUT_TAKER", target_ann_vol=0.80, max_crypto_gross=2.40, max_gold_gross=1.10),
        CtaBearVolConfig("CTA_VOLTGT80_M4_XAUT_MAKER", target_ann_vol=0.80, max_crypto_gross=2.40, max_gold_gross=1.10, leg_fee_bps=8.5),
        CtaBearVolConfig("CTA_VOLTGT80_KAUFMAN_DAILY_TAKER", target_ann_vol=0.80, max_crypto_gross=2.40, max_gold_gross=1.10, use_kaufman_er=True),
        CtaBearVolConfig("CTA_VOLTGT80_KAUFMAN_DAILY_MAKER", target_ann_vol=0.80, max_crypto_gross=2.40, max_gold_gross=1.10, use_kaufman_er=True, leg_fee_bps=8.5),
        CtaBearVolConfig("SYNTHESIS_VOL_ER_4H_BR35_TAKER", breadth_max=0.35, target_ann_vol=0.78, max_crypto_gross=2.35, max_gold_gross=1.10, use_kaufman_er=True, use_4h_squeeze_guard=True, rebal_band=0.12),
        CtaBearVolConfig("SYNTHESIS_VOL_ER_4H_BR35_MAKER", breadth_max=0.35, target_ann_vol=0.78, max_crypto_gross=2.35, max_gold_gross=1.10, use_kaufman_er=True, use_4h_squeeze_guard=True, rebal_band=0.12, leg_fee_bps=8.5),
    ]
    standalone_rows = [
        _simulate_standalone_cta_bear(p2_0, sigs_u, accel_u, daily_breadth, ann_vol, kaufman_er, btc_sq, xaut_sq, c)
        for c in standalone_cfgs
    ]

    # Part 2: Unified Single-Ledger Twin-Phase Absorption into E3_V2_NONLINEAR_BELLMAN
    stats_0, stats_1 = _compute_2h_bar_stats(p2_0), _compute_2h_bar_stats(p2_1)
    d0, s0, x0, yb0, yp0 = _extract_11feat_coiled_spring_dataset(p2_0, IGNITION_18_CRYPTO, daily_breadth)
    d1, s1, x1, yb1, yp1 = _extract_11feat_coiled_spring_dataset(p2_1, IGNITION_18_CRYPTO, daily_breadth)
    sc11_0, _, _ = _walkforward_gru_scores(d0, s0, x0, yp0, yb0, task="regression")
    sc11_1, _, _ = _walkforward_gru_scores(d1, s1, x1, yp1, yb1, task="regression")
    st_d0, st_x0, st_y0 = _extract_optimal_stopping_dataset(p2_0, sc11_0)
    st_d1, st_x1, st_y1 = _extract_optimal_stopping_dataset(p2_1, sc11_1)
    nl_0, nl_1 = _train_wf_nonlinear_bellman(st_d0, st_x0, st_y0), _train_wf_nonlinear_bellman(st_d1, st_x1, st_y1)

    _, _, sch0 = simulate_nobitex_margin_ignition(p2_0, IGNITION_18_CRYPTO, daily_breadth, sc11_0, label="V2_0", offset_hours=0, score_is_return=True, base_prob=0.46, top_tercile_leverage=1.5, leg_cost=0.0016, borrow_mode="eod_utc", borrow_rate=0.0005)
    _, _, sch1 = simulate_nobitex_margin_ignition(p2_1, IGNITION_18_CRYPTO, daily_breadth, sc11_1, label="V2_1", offset_hours=1, score_is_return=True, base_prob=0.46, top_tercile_leverage=1.5, leg_cost=0.0016, borrow_mode="eod_utc", borrow_rate=0.0005)
    v2_run = _run_v2_joint_shared_ledger(panel_1h, ADAPTIVE_UNIVERSE, sigs_13, accel_13, sigs_metals, cov_h_by_ts, _merge_twin_schedules(sch0, sch1), slow_budget=0.60, ign_budget=0.40, fee_rate=Decimal("0.0016"), use_metals_reserve=True)
    v2_rets = _daily_returns_map(v2_run["nav_by_date"])

    unified_specs: list[tuple[str, BearMajorsConfig | CtaBearVolConfig | None]] = [
        ("MAIN_E3_V2_STANDALONE", None),
        ("E3_V2_PLUS_BEAR50_PREV_CHAMP", BearMajorsConfig("B50", BEAR_MAJORS_4, breadth_max=0.30, gross_short_budget=0.50)),
        ("E3_V2_PLUS_CTA_VOLTGT65_M4_XAUT", CtaBearVolConfig("U_V65", target_ann_vol=0.65, max_crypto_gross=2.20, max_gold_gross=1.00)),
        ("E3_V2_PLUS_CTA_VOLTGT80_M4_XAUT", CtaBearVolConfig("U_V80", target_ann_vol=0.80, max_crypto_gross=2.40, max_gold_gross=1.10)),
        ("E3_V2_PLUS_CTA_VOLTGT80_KAUFMAN", CtaBearVolConfig("U_V80K", target_ann_vol=0.80, max_crypto_gross=2.40, max_gold_gross=1.10, use_kaufman_er=True)),
        ("E3_V2_PLUS_CTA_VOLTGT80_KAUFMAN_MK", CtaBearVolConfig("U_V80KM", target_ann_vol=0.80, max_crypto_gross=2.40, max_gold_gross=1.10, use_kaufman_er=True, leg_fee_bps=8.5)),
        ("E3_V2_PLUS_SYNTHESIS_VOL_ER_4H_TK", CtaBearVolConfig("U_SYN_TK", breadth_max=0.35, target_ann_vol=0.78, max_crypto_gross=2.35, max_gold_gross=1.10, use_kaufman_er=True, use_4h_squeeze_guard=True, rebal_band=0.12)),
        ("E3_V2_PLUS_SYNTHESIS_VOL_ER_4H_MK", CtaBearVolConfig("U_SYN_MK", breadth_max=0.35, target_ann_vol=0.78, max_crypto_gross=2.35, max_gold_gross=1.10, use_kaufman_er=True, use_4h_squeeze_guard=True, rebal_band=0.12, leg_fee_bps=8.5)),
    ]

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    unified_rows: list[dict] = []
    e3_rets: dict[str, float] = {}
    for lbl, bcfg in unified_specs:
        m0, nt0 = _simulate_unified_e3v2_phase(p2_0, sigs_13, accel_13, sigs_metals, sigs_u, accel_u, cov_h_by_ts, daily_breadth, ann_vol, kaufman_er, btc_sq, xaut_sq, sc11_0, nl_0, stats_0, bcfg)
        m1, nt1 = _simulate_unified_e3v2_phase(p2_1, sigs_13, accel_13, sigs_metals, sigs_u, accel_u, cov_h_by_ts, daily_breadth, ann_vol, kaufman_er, btc_sq, xaut_sq, sc11_1, nl_1, stats_1, bcfg)
        d0_m, d1_m = nav_ts_to_daily(nt0), nav_ts_to_daily(nt1)
        shared_d = sorted(set(d0_m) & set(d1_m))
        twin_d = {d: 0.5 * (d0_m[d] + d1_m[d]) for d in shared_d}
        r24 = round(0.5 * (window_return_pct(nt0, 24.0) + window_return_pct(nt1, 24.0)), 2)
        r72 = round(0.5 * (window_return_pct(nt0, 72.0) + window_return_pct(nt1, 72.0)), 2)
        r7d = round(0.5 * (window_return_pct(nt0, 168.0) + window_return_pct(nt1, 168.0)), 2)
        twin_rets = _daily_returns_map(twin_d)
        if lbl == "MAIN_E3_V2_STANDALONE":
            e3_rets = twin_rets
        up_e3 = paired_baseline_uplift(twin_rets, e3_rets, simulations=499, seed=42)
        up_v2 = paired_baseline_uplift(twin_rets, v2_rets, simulations=499, seed=42)
        ci_e3 = up_e3.get("ci_95") or (0.0, 0.0)
        fm = _portfolio_metrics(twin_d)
        sm = _portfolio_metrics({k: v for k, v in twin_d.items() if k >= stress_iso})
        unified_rows.append({
            "label": lbl,
            "ret_24h_pct": r24,
            "ret_72h_pct": r72,
            "ret_7d_pct": r7d,
            "hit_3_5_15": (r24 >= 3.0 and r72 >= 5.0 and r7d >= 15.0),
            "ending_nav": fm["ending_nav"],
            "full_ret_pct": fm["ret_pct"],
            "stress_ret_pct": sm["ret_pct"],
            "ann_sharpe": fm["ann_sharpe"],
            "max_dd_pct": fm["max_dd_pct"],
            "liqs": m0["liqs"] + m1["liqs"],
            "stops": round(0.5 * (m0["stops"] + m1["stops"]), 1),
            "bear_fills": round(0.5 * (m0["bear_fills"] + m1["bear_fills"]), 1),
            "fees_usdt": round(0.5 * (m0["fees"] + m1["fees"]), 2),
            "borrow_usdt": round(0.5 * (m0["borrow"] + m1["borrow"]), 2),
            "pool_yield_usdt": round(0.5 * (m0["pool_yield"] + m1["pool_yield"]), 2),
            "year_rets": year_returns_pct(twin_d),
            "vs_e3v2_bps": round(float(up_e3.get("mean_uplift", 0.0)) * 10_000.0, 2),
            "vs_e3v2_ci95_bps": [round(float(ci_e3[0]) * 10_000.0, 2), round(float(ci_e3[1]) * 10_000.0, 2)],
            "vs_v2_bps": round(float(up_v2.get("mean_uplift", 0.0)) * 10_000.0, 2),
        })

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "northstar_targets_pct": NORTHSTAR_TARGETS,
        "standalone_cta_bear_benchmarks": standalone_rows,
        "unified_main_engine_absorption": unified_rows,
        "best_sharpe_unified_arm": max(unified_rows, key=lambda r: (r["liqs"] == 0, r["ann_sharpe"])),
        "best_northstar_hit_unified_arm": max(
            [r for r in unified_rows if r["hit_3_5_15"] and r["liqs"] == 0] or unified_rows,
            key=lambda r: r["ann_sharpe"],
        ),
    }
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if report_md is not None:
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text(_render_md(payload), encoding="utf-8")
    return payload


def _render_md(p: dict) -> str:
    b_sr = p["best_sharpe_unified_arm"]
    b_ns = p["best_northstar_hit_unified_arm"]
    lines = [
        "# Convex Cross-Asset Bear Short (`+3% / 1d`, `+5% / 3d`, `+15% / 7d`) & Unified `E3_V2` Absorption Study",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`PAPER_ONLY`)",
        f"- **Best Sharpe Unified Main Engine:** `{b_sr['label']}` — Ending `${b_sr['ending_nav']:.2f}` (`{b_sr['full_ret_pct']:+.2f}%`), Bear `{b_sr['stress_ret_pct']:+.2f}%`, Sharpe `{b_sr['ann_sharpe']:.3f}`, MaxDD `{b_sr['max_dd_pct']:.2f}%`, Liqs `{b_sr['liqs']}`, 1d/3d/7d = `{b_sr['ret_24h_pct']:+.2f}%` / `{b_sr['ret_72h_pct']:+.2f}%` / `{b_sr['ret_7d_pct']:+.2f}%`",
        f"- **Best `3%/5%/15%` Northstar-Hitting Unified Main Engine:** `{b_ns['label']}` — Ending `${b_ns['ending_nav']:.2f}` (`{b_ns['full_ret_pct']:+.2f}%`), Bear `{b_ns['stress_ret_pct']:+.2f}%`, Sharpe `{b_ns['ann_sharpe']:.3f}`, MaxDD `{b_ns['max_dd_pct']:.2f}%`, Liqs `{b_ns['liqs']}`, 1d/3d/7d = `{b_ns['ret_24h_pct']:+.2f}%` / `{b_ns['ret_72h_pct']:+.2f}%` / `{b_ns['ret_7d_pct']:+.2f}%`",
        "",
        "## Part 1 — Standalone Zero-Liquidation Cross-Asset Bear Sleeves (`MultiHorizonBook`, `1,085d` `2024–2026` OOS)",
        "",
        "| Arm | 1d (`>=3%`) | 3d (`>=5%`) | 7d (`>=15%`) | NS | Ending NAV | Full Ret | Bear Stress | Ann. Sharpe | MaxDD | Liqs | Fills | Fees / Borrow / Yield | 2024 / 2025 / 2026 |",
        "| --- | ---: | ---: | ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for r in p["standalone_cta_bear_benchmarks"]:
        yr = r["year_rets"]
        lines.append(
            f"| `{r['label']}` | `{r['ret_24h_pct']:+.2f}%` | `{r['ret_72h_pct']:+.2f}%` | `{r['ret_7d_pct']:+.2f}%` "
            f"| `{'HIT' if r['hit_3_5_15'] else '—'}` | `${r['ending_nav']:.2f}` | `{r['full_ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` "
            f"| `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['liqs']}` | `{r['fills']}` "
            f"| `${r['fees_usdt']:.1f}` / `${r['borrow_usdt']:.1f}` / `+${r['pool_yield_usdt']:.1f}` "
            f"| `{yr.get('2024', 0):+.1f}%` / `{yr.get('2025', 0):+.1f}%` / `{yr.get('2026', 0):+.1f}%` |"
        )
    lines += [
        "",
        "## Part 2 — True Single-Ledger (`MultiHorizonBook`, Twin-Phase `0h+1h`) Absorption Into `E3_V2_NONLINEAR_BELLMAN`",
        "",
        "| Main Engine Variant | 1d (`>=3%`) | 3d (`>=5%`) | 7d (`>=15%`) | NS | Ending NAV | Full Ret | Bear Stress | Ann. Sharpe | MaxDD | Liqs | vs E3v2 (`95% CI` bps/d) | 2024 / 2025 / 2026 |",
        "| --- | ---: | ---: | ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for r in p["unified_main_engine_absorption"]:
        yr, ci = r["year_rets"], r["vs_e3v2_ci95_bps"]
        lines.append(
            f"| `{r['label']}` | `{r['ret_24h_pct']:+.2f}%` | `{r['ret_72h_pct']:+.2f}%` | `{r['ret_7d_pct']:+.2f}%` "
            f"| `{'HIT' if r['hit_3_5_15'] else '—'}` | `${r['ending_nav']:.2f}` | `{r['full_ret_pct']:+.2f}%` "
            f"| `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['liqs']}` "
            f"| `{r['vs_e3v2_bps']:+.2f}` (`[{ci[0]:+.2f}, {ci[1]:+.2f}]`) "
            f"| `{yr.get('2024', 0):+.1f}%` / `{yr.get('2025', 0):+.1f}%` / `{yr.get('2026', 0):+.1f}%` |"
        )
    lines.append("")
    return "\n".join(lines)
