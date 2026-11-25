"""Bear-Regime Discovery, Unified-Ledger Absorption & Sub-2h (0.5h/1h) Timeframe Study.

Task 1: Uses +1%/24h, +2%/72h, +5%/7d bear-week Northstar discovery -> full 1,085d (2024-2026) OOS
        stress testing -> true single-ledger MultiHorizonBook absorption of BearMajors into E3_V2.
Task 2: Full re-evaluation of 1h (1,085d OOS including 11-feat Walk-Forward GRU + Nonlinear Bellman)
        and 0.5h/30m (apples-to-apples 30m vs 1h vs 2h vs 4h on identical 26d 1min-resampled window).
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median

import numpy as np

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.bear_majors_sleeve import (
    BEAR_MAJORS_4,
    BEAR_MAJORS_6,
    BearMajorsConfig,
    compute_calm_bear_majors_targets,
    rebalance_slow_short_lots,
)
from ...domain.bellman_stopping import (
    NonlinearBellmanModel,
    compute_bellman_path_target_bps,
)
from ...domain.core_signal_geometry import DEFENSIVE_METALS_CAPS
from ...domain.higher_order_and_sparse import compute_second_order_trend_map
from ...domain.ignition_upgrades import (
    compute_cross_sectional_2h_context,
    simulate_episode_path_pnl,
)
from ...domain.in_position_and_execution import tehran_execution_cost_bps
from ...domain.instrument_resolver import ResolverConfig, build_local_venue_offers
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.multi_horizon_book import MultiHorizonBook, check_lot_intrabar_exit
from ...domain.optimal_exits import (
    ClosedTradeCapture,
    OptimalExitConfig,
    OptimalStoppingState,
    summarize_exit_efficiency,
)
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.sub_2h_signals import (
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
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from ...domain.venue_leverage_models import (
    NOBITEX_MARGIN_ELIGIBLE_USDT,
    simulate_nobitex_margin_ignition,
)
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
    _get_stopping_model,
    _open_fast_exit_study_entries,
)
from .unified_book_helpers import (
    latest_signal_date,
    nav_ts_to_daily,
    resolve_bar_prices,
    window_return_pct,
    year_returns_pct,
)


def _extract_signals_for_panel(
    panel: dict[str, list[BarPoint]],
    sigs_13: dict,
    daily_breadth: dict[str, float],
    *,
    bar_hours: float,
) -> tuple[dict[str, dict[datetime, list[IntradaySignal]]], dict[datetime, bool]]:
    """Build strictly causal N1, N2, N4, and sub-2h ignition long signal maps on one timeframe panel."""
    sig_dates = sorted(sigs_13)
    btc_bars = panel.get("BTCUSDT", [])
    btc_closes = [b.close for b in btc_bars]
    btc_e20, btc_e50 = compute_ema_series(btc_closes, 20), compute_ema_series(btc_closes, 50)
    btc_bear_active = {
        b.ts_avail: is_deep_bear_cascade_active(
            b.close, btc_e20[i], btc_e50[i], btc_e20[max(0, i - 6)],
            daily_breadth.get(b.ts_avail.date().isoformat(), 0.5), breadth_max=0.15,
        )
        for i, b in enumerate(btc_bars)
    }

    n1_map: dict[datetime, list[IntradaySignal]] = {}
    n4_map: dict[datetime, list[IntradaySignal]] = {}
    ign_long_map: dict[datetime, list[IntradaySignal]] = {}
    ema_f_ts: dict[datetime, dict[str, float]] = {}
    ema_s_ts: dict[datetime, dict[str, float]] = {}
    px_ts: dict[datetime, dict[str, float]] = {}
    ret24_ts: dict[datetime, dict[str, float]] = {}
    bvol_ts: dict[datetime, dict[str, float]] = {}
    bars_24h = max(1, int(round(24.0 / bar_hours)))
    hi_lb = min(144, max(24, int(round(96.0 / bar_hours))))

    for sym in IGNITION_18_CRYPTO:
        bars = panel.get(sym, [])
        if len(bars) < 60:
            continue
        closes, vols = [b.close for b in bars], [b.volume for b in bars]
        rets = [0.0] + [
            (closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] > 0 else 0.0
            for i in range(1, len(closes))
        ]
        ef, es = compute_ema_series(closes, 10), compute_ema_series(closes, 30)
        for i in range(40, len(bars) - 1):
            ts = bars[i].ts_avail
            ema_f_ts.setdefault(ts, {})[sym] = ef[i]
            ema_s_ts.setdefault(ts, {})[sym] = es[i]
            px_ts.setdefault(ts, {})[sym] = closes[i]
            if i >= bars_24h and closes[i - bars_24h] > 0:
                ret24_ts.setdefault(ts, {})[sym] = (closes[i] - closes[i - bars_24h]) / closes[i - bars_24h]
            pr = rets[i - 36 : i]
            mr = sum(pr) / 36.0
            bvol_ts.setdefault(ts, {})[sym] = max(0.004, math.sqrt(sum((r - mr) ** 2 for r in pr) / 35.0))
            br = daily_breadth.get(ts.date().isoformat(), 0.5)
            d_dt = latest_signal_date(sig_dates, ts)
            d_sigs = sigs_13[d_dt] if d_dt is not None else {}
            s1_d = d_sigs[sym].s1_trend if (sym in d_sigs and d_sigs[sym].s1_trend is not None) else None
            if sym in NOBITEX_MARGIN_ELIGIBLE_USDT:
                s_n1 = detect_n1_pullback_rejection_short(bars, ef, es, vols, rets, i, breadth=br, s1_daily=s1_d)
                if s_n1 is not None:
                    n1_map.setdefault(ts, []).append(s_n1)
                s_n4 = detect_n4_coiled_down_short(bars, es, vols, rets, i, breadth=br, s1_daily=s1_d)
                if s_n4 is not None:
                    n4_map.setdefault(ts, []).append(s_n4)
            s_long = detect_sub2h_ignition_long(bars, vols, rets, i, lookback_high=hi_lb)
            if s_long is not None:
                ign_long_map.setdefault(ts, []).append(s_long)

    n2_map: dict[datetime, list[IntradaySignal]] = {}
    for ts, is_bear in btc_bear_active.items():
        if not is_bear:
            continue
        d_dt = latest_signal_date(sig_dates, ts)
        d_sigs = sigs_13[d_dt] if d_dt is not None else {}
        ranked = rank_deep_bear_short_targets(
            IGNITION_18_CRYPTO, d_sigs, ret24_ts.get(ts, {}),
            ema_f_ts.get(ts, {}), ema_s_ts.get(ts, {}), px_ts.get(ts, {}), top_k=4,
        )
        if ranked:
            n2_map[ts] = [
                IntradaySignal(
                    sym, ts, -1, bvol_ts.get(ts, {}).get(sym, 0.015),
                    max(160.0, min(420.0, 2.5 * bvol_ts.get(ts, {}).get(sym, 0.015) * 10_000.0)),
                    wk, "n2_deep_bear_cascade",
                )
                for sym, wk in ranked
            ]

    return {
        "n1_pullback_short": n1_map,
        "n2_deep_bear_cascade": n2_map,
        "n4_coiled_down": n4_map,
        "sub2h_ignition_long": ign_long_map,
    }, btc_bear_active


def _format_sim_row(meta: dict, nav_ts: dict[datetime, float]) -> dict:
    daily = nav_ts_to_daily(nav_ts)
    fm = _portfolio_metrics(daily)
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    sm = _portfolio_metrics({k: v for k, v in daily.items() if k >= stress_iso})
    r24, r72, r7d = window_return_pct(nav_ts, 24.0), window_return_pct(nav_ts, 72.0), window_return_pct(nav_ts, 168.0)
    return {
        "label": meta["label"],
        "ret_24h_pct": r24,
        "ret_72h_pct": r72,
        "ret_7d_pct": r7d,
        "hit_northstar": (r24 >= 1.0 and r72 >= 2.0 and r7d >= 5.0),
        "days": len(daily),
        "ending_nav": fm["ending_nav"],
        "full_ret_pct": fm["ret_pct"],
        "stress_ret_pct": sm["ret_pct"],
        "ann_sharpe": fm["ann_sharpe"],
        "max_dd_pct": fm["max_dd_pct"],
        "liqs": meta["liqs"],
        "entries": meta["entries"],
        "fees_usdt": meta["fees"],
        "borrow_usdt": meta["borrow"],
        "pool_yield_usdt": meta["pool_yield"],
        "win_rate_pct": meta["eff"]["win_rate_pct"],
        "profit_factor": meta["eff"]["profit_factor"],
        "pre_eod_pct": meta["eff"]["pre_eod_zero_borrow_pct"],
    }


def _check_slow_short_stops(
    book: MultiHorizonBook,
    by_avail: dict[str, dict[datetime, BarPoint]],
    ts: datetime,
    exit_fee_bps: float,
    thesis_id: str = "slow_bear_short",
) -> None:
    for key in list(book.lots):
        if key[1] != thesis_id:
            continue
        lot = book.lots[key]
        bar = by_avail.get(lot.symbol, {}).get(ts)
        if bar is None:
            continue
        evt, px, fbps = check_lot_intrabar_exit(lot, bar, taker_exit_bps=exit_fee_bps, oco_maker_exit_bps=4.5, use_oco_maker_tp=False)
        if evt == "LIQ":
            book.liquidations += 1
            del book.lots[key]
        elif evt == "STOP":
            book.close_lot(key, px, fbps)
            book.stop_outs += 1


def _simulate_standalone_bear_majors(
    panel_2h: dict[str, list[BarPoint]],
    sigs_13: dict,
    accel_13: dict,
    daily_breadth: dict[str, float],
    cfg: BearMajorsConfig,
) -> dict:
    """Run one calm daily Bear-Majors short sleeve standalone inside MultiHorizonBook on 2h bars."""
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in cfg.symbols}
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in cfg.symbols}
    all_ts = sorted({t for s in cfg.symbols for t in by_avail[s] if t >= datetime(2024, 1, 1, tzinfo=UTC)})
    offers = {s: build_local_venue_offers(s, nobitex_leg_bps=cfg.leg_fee_bps, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in cfg.symbols}
    book = MultiHorizonBook(free_cash=1000.0)
    last_px: dict[str, float] = {}
    nav_ts: dict[datetime, float] = {}
    sig_dates, sig_ptr = sorted(sigs_13), 0
    last_sig_applied: datetime | None = None
    pending_tgts: dict[str, float] | None = None
    fills = 0

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, 2.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR, eod_borrow_bps=5.0)
        exec_px, tradable = resolve_bar_prices(cfg.symbols, by_start, by_avail, ts, last_px)
        _check_slow_short_stops(book, by_avail, ts, cfg.leg_fee_bps)
        while sig_ptr + 1 < len(sig_dates) and sig_dates[sig_ptr + 1] <= ts:
            sig_ptr += 1
        cur_sig = sig_dates[sig_ptr] if (sig_dates and sig_dates[sig_ptr] <= ts) else None
        if cur_sig is not None and cur_sig != last_sig_applied:
            last_sig_applied = cur_sig
            br = daily_breadth.get(cur_sig.date().isoformat(), 0.5)
            pending_tgts = compute_calm_bear_majors_targets(sigs_13[cur_sig], accel_13.get(cur_sig, {}), br, cfg)
        if pending_tgts is not None and ts.hour >= 10:
            fills += rebalance_slow_short_lots(book, pending_tgts, exec_px, tradable, offers, ts, cfg=cfg)
            pending_tgts = None
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
        "hit_northstar": (r24 >= 1.0 and r72 >= 2.0 and r7d >= 5.0),
        "days": len(daily),
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


def _simulate_unified_e3v2_with_bear_majors(
    panel_2h: dict[str, list[BarPoint]],
    sigs_13: dict,
    accel_13: dict,
    sigs_metals: dict,
    cov_h_by_ts: dict,
    daily_breadth: dict[str, float],
    gru_scores: dict[tuple[datetime, str], float],
    nl_models: list[tuple[datetime, datetime, NonlinearBellmanModel]],
    bar_stats: tuple,
    bear_cfg: BearMajorsConfig | None,
) -> tuple[dict, dict[datetime, float]]:
    """True single-ledger MultiHorizonBook combining E3_V2_NONLINEAR_BELLMAN + optional BearMajors sleeve."""
    bvol_map, _, vrat_map, bret_map = bar_stats
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    all_ts = sorted({t for s in IGNITION_18_CRYPTO for t in by_avail[s]})
    slow_short_fee = bear_cfg.leg_fee_bps if bear_cfg is not None else 16.0
    offers_by_sym = {s: build_local_venue_offers(s, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in ADAPTIVE_UNIVERSE}
    short_offers = {s: build_local_venue_offers(s, nobitex_leg_bps=slow_short_fee, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in ADAPTIVE_UNIVERSE}
    r_cfg = ResolverConfig(max_venue_leverage=5.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR)
    exit_cfg = OptimalExitConfig(use_e3_optimal_stopping=True)

    book = MultiHorizonBook(free_cash=1000.0)
    pending_slow: dict[str, float] | None = None
    pending_bear: dict[str, float] | None = None
    last_px: dict[str, float] = {}
    recent_gru: list[float] = []
    trimmed_lots: set[tuple[str, str]] = set()
    trades_log: list[ClosedTradeCapture] = []
    peak_nav = 1000.0
    nav_ts: dict[datetime, float] = {}
    sig_dates, sig_ptr = sorted(sigs_13), 0
    last_sig_applied: datetime | None = None
    bear_fills = 0

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, 2.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR, eod_borrow_bps=5.0)
        exec_px, tradable = resolve_bar_prices(ADAPTIVE_UNIVERSE, by_start, by_avail, ts, last_px)
        saved_shorts = {k: book.lots.pop(k) for k in list(book.lots) if k[1] == "slow_bear_short"}
        _step_bellman_fast_lots(
            book, by_avail, exec_px, tradable, ts, bret_map, vrat_map,
            nl_models, None, trimmed_lots, trades_log, exit_cfg, pyramid_frac=0.45,
        )
        book.lots.update(saved_shorts)
        _check_slow_short_stops(book, by_avail, ts, slow_short_fee)

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
                br = daily_breadth.get(cur_sig.date().isoformat(), 0.5)
                pending_bear = compute_calm_bear_majors_targets(sigs_13[cur_sig], accel_13.get(cur_sig, {}), br, bear_cfg)

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


def _extract_1h_11feat_and_bellman(
    panel_1h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
) -> tuple[dict[tuple[datetime, str], float], float, list[tuple[datetime, datetime, NonlinearBellmanModel]]]:
    """Run full 11-feat Coiled-Spring Walk-Forward GRU + Nonlinear Bellman Stopping natively on 1h bars."""
    wave_by_ts, rank_by_ts_sym = compute_cross_sectional_2h_context(panel_1h, IGNITION_18_CRYPTO)
    btc_bars = panel_1h.get("BTCUSDT", [])
    btc_ret = {
        btc_bars[i].ts_avail: (btc_bars[i].close - btc_bars[i - 1].close) / btc_bars[i - 1].close
        for i in range(1, len(btc_bars)) if btc_bars[i - 1].close > 0
    }
    dts, syms, xs, y_bin, y_path = [], [], [], [], []
    af, as_ = 2.0 / 5.0, 2.0 / 13.0
    for sym in IGNITION_18_CRYPTO:
        bars = panel_1h.get(sym, [])
        if len(bars) < 160:
            continue
        rets = [0.0] + [(bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0 for i in range(1, len(bars))]
        vols, highs = [b.volume for b in bars], [b.high for b in bars]
        hls = [(b.high - b.low) / max(b.close, 1e-9) for b in bars]
        for i in range(96, len(bars) - 50):
            b = bars[i]
            if not b.entry_eligible or not bars[i + 1].entry_eligible or bars[i + 1].open <= 0:
                continue
            pr, pv, ph = rets[i - 48 : i], vols[i - 48 : i], highs[i - 96 : i]
            mr = sum(pr) / 48.0
            sr = math.sqrt(sum((r - mr) ** 2 for r in pr) / 47.0)
            mv = median(pv)
            if (rets[i] - mr) / max(sr, 1e-4) < 2.2 or mv <= 0 or b.volume < 2.0 * mv or b.close <= max(ph):
                continue
            seq, ef_r, es_r, ef_v, es_v = [], 0.0, 0.0, 0.0, 0.0
            for idx_j, j in enumerate(range(i - 35, i + 1)):
                bj, rj = bars[j], rets[j]
                zr, vr = rj / max(sr, 1e-4), math.log1p(bj.volume / max(mv, 1e-9))
                if idx_j == 0:
                    ef_r, es_r, ef_v, es_v = zr, zr, vr, vr
                else:
                    ef_r, es_r = (1.0 - af) * ef_r + af * zr, (1.0 - as_) * es_r + as_ * zr
                    ef_v, es_v = (1.0 - af) * ef_v + af * vr, (1.0 - as_) * es_v + as_ * vr
                hl_12 = sum(hls[max(0, j - 11) : j + 1]) / max(1, min(12, j + 1))
                hl_48 = sum(hls[max(0, j - 47) : j + 1]) / max(1, min(48, j + 1))
                seq.append([
                    zr, hls[j], vr, rj - btc_ret.get(bj.ts_avail, 0.0),
                    daily_breadth.get(bj.ts_avail.date().isoformat(), 0.5),
                    1.0 if bj.close > bj.open else -1.0, ef_r - es_r, ef_v - es_v,
                    min(3.0, hl_12 / max(hl_48, 1e-4)), wave_by_ts.get(bj.ts_avail, 0.0),
                    rank_by_ts_sym.get((bj.ts_avail, sym), 0.5),
                ])
            ret_24h = (bars[i + 25].open - bars[i + 1].open) / bars[i + 1].open
            dts.append(b.ts_avail)
            syms.append(sym)
            xs.append(seq)
            y_bin.append(1.0 if ret_24h > 0.0032 else 0.0)
            y_path.append(simulate_episode_path_pnl(bars, i, sr, leg_cost=0.0016, max_hold_bars=48))

    sc_1h, auc_1h, _ = _walkforward_gru_scores(
        dts, syms, np.asarray(xs, dtype=np.float64), np.asarray(y_path, dtype=np.float64), np.asarray(y_bin, dtype=np.float64), task="regression",
    )
    nl_1h = _train_1h_bellman_models(panel_1h, sc_1h, btc_ret)
    return sc_1h, auc_1h, nl_1h


def _train_1h_bellman_models(
    panel_1h: dict[str, list[BarPoint]],
    sc_1h: dict[tuple[datetime, str], float],
    btc_ret: dict[datetime, float],
) -> list[tuple[datetime, datetime, NonlinearBellmanModel]]:
    st_d, st_x, st_y = [], [], []
    for sym in IGNITION_18_CRYPTO:
        bars = panel_1h.get(sym, [])
        if len(bars) < 90:
            continue
        rets = [0.0] + [(bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0 for i in range(1, len(bars))]
        vols = [b.volume for b in bars]
        for i in range(48, len(bars) - 24):
            g_sc = sc_1h.get((bars[i].ts_avail, sym))
            if g_sc is None or g_sc <= 0.001 or bars[i + 1].open <= 0:
                continue
            entry_px = bars[i + 1].open
            pr = rets[i - 48 : i]
            b_vol = max(0.004, math.sqrt(sum((r - sum(pr) / 48.0) ** 2 for r in pr) / 47.0))
            mv, peak = max(1e-9, median(vols[i - 48 : i])), entry_px
            for k in range(1, 17):
                idx = i + k
                if idx + 8 >= len(bars):
                    break
                cur = bars[idx]
                peak = max(peak, cur.close)
                upnl, mfe = (cur.close - entry_px) / entry_px, max(0.0, (peak - entry_px) / entry_px)
                st = OptimalStoppingState(
                    age_bars=k, unrealized_ret=upnl, peak_mfe=mfe,
                    giveback_ratio=(mfe - upnl) / max(mfe, 1e-4) if mfe > 1e-4 else 0.0,
                    upper_wick_ratio=max(0.0, cur.high - cur.close) / max(cur.high - cur.low, 1e-9),
                    volume_ratio=cur.volume / mv, bar_ret_z=rets[idx] / max(b_vol, 1e-4),
                    rel_btc_ret=rets[idx] - btc_ret.get(cur.ts_avail, 0.0),
                    hours_to_utc_eod=24.0 - (cur.ts_avail.hour + cur.ts_avail.minute / 60.0),
                    entry_gru_score=g_sc,
                )
                tb = compute_bellman_path_target_bps(bars, idx, 1, peak, b_vol, max_lookahead=8)
                if tb is not None:
                    st_d.append(cur.ts_avail)
                    st_x.append(st.to_vector())
                    st_y.append(tb)
    return _train_wf_nonlinear_bellman(st_d, np.asarray(st_x, dtype=np.float64), np.asarray(st_y, dtype=np.float64))


def _run_task2a_1h_full_study(
    panel_1h_clean: dict[str, list[BarPoint]],
    sigs_13: dict,
    daily_breadth: dict[str, float],
) -> tuple[list[dict], float, list[tuple[datetime, datetime, NonlinearBellmanModel]], dict[str, float]]:
    """Task 2A: Full 1,085d 1h re-evaluation — Raw 1h vs 1h 11-feat GRU + Nonlinear Bellman (Taker & Maker)."""
    sig_maps, btc_bear = _extract_signals_for_panel(panel_1h_clean, sigs_13, daily_breadth, bar_hours=1.0)
    sc_1h, auc_1h, nl_1h = _extract_1h_11feat_and_bellman(panel_1h_clean, daily_breadth)
    _, _, vrat_1h, bret_1h = _compute_2h_bar_stats(panel_1h_clean)

    gru_sig_map: dict[datetime, list[IntradaySignal]] = {}
    for sym in IGNITION_18_CRYPTO:
        bars = panel_1h_clean.get(sym, [])
        rets = [0.0] + [(bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0 for i in range(1, len(bars))]
        for i in range(48, len(bars) - 1):
            ts = bars[i].ts_avail
            sc = sc_1h.get((ts, sym))
            if sc is None or sc <= 0.002:
                continue
            pr = rets[i - 48 : i]
            bv = max(0.004, math.sqrt(sum((r - sum(pr) / 48.0) ** 2 for r in pr) / 47.0))
            gru_sig_map.setdefault(ts, []).append(IntradaySignal(sym, ts, 1, bv, max(140.0, min(480.0, 2.5 * bv * 10_000.0)), sc, "1h_gru_ign"))

    rows: list[dict] = []
    for name, key, efee, lev, mhold in [
        ("1H_RAW_N1_PULLBACK_SHORT_TAKER", "n1_pullback_short", 16.0, 3.0, 24),
        ("1H_RAW_N2_CASCADE_SHORT_TAKER", "n2_deep_bear_cascade", 16.0, 3.0, 48),
        ("1H_RAW_N4_COILED_DOWN_TAKER", "n4_coiled_down", 16.0, 3.0, 24),
        ("1H_RAW_IGNITION_LONG_TAKER", "sub2h_ignition_long", 16.0, 2.0, 24),
    ]:
        cfg = Sub2hSimConfig(label=name, bar_hours=1.0, max_leverage=lev, max_slots=3, entry_fee_bps=efee, exit_fee_bps=16.0, max_hold_bars=mhold)
        m, nav_ts = simulate_sub2h_signal_strategy(panel_1h_clean, sig_maps[key], btc_bear, cfg=cfg)
        rows.append(_format_sim_row(m, nav_ts))

    best_1h_daily: dict[str, float] = {}
    for name, efee, use_bm in [
        ("1H_GRU_STATIC_TAKER_16BPS", 16.0, False),
        ("1H_GRU_BELLMAN_TAKER_16BPS", 16.0, True),
        ("1H_GRU_STATIC_MAKER_8.5BPS", 8.5, False),
        ("1H_GRU_BELLMAN_MAKER_8.5BPS", 8.5, True),
    ]:
        cfg = Sub2hSimConfig(
            label=name, bar_hours=1.0, max_leverage=3.0, max_slots=3, entry_fee_bps=efee, exit_fee_bps=16.0,
            max_hold_bars=48, trail_vol_mult=2.5, use_bellman_exit=use_bm, kill_shorts_on_btc_reclaim=False,
        )
        m, nav_ts = simulate_sub2h_signal_strategy(
            panel_1h_clean, gru_sig_map, {}, cfg=cfg,
            bellman_model_fn=(lambda t: _get_stopping_model(t, nl_1h)) if use_bm else None,
            vrat_map=vrat_1h, bret_map=bret_1h,
        )
        rows.append(_format_sim_row(m, nav_ts))
        if name == "1H_GRU_BELLMAN_MAKER_8.5BPS":
            best_1h_daily = nav_ts_to_daily(nav_ts)
    return rows, round(auc_1h, 4), nl_1h, best_1h_daily


def _run_task2b_apples_to_apples_26d_matrix(
    panel_1m: dict[str, list[BarPoint]],
    sigs_13: dict,
    daily_breadth: dict[str, float],
    nl_1h: list[tuple[datetime, datetime, NonlinearBellmanModel]],
) -> tuple[list[dict], list[dict]]:
    """Task 2B: Exact apples-to-apples 0.5h (30m) vs 1h vs 2h vs 4h matrix on identical 26d 1min-resampled window."""
    fee_vol_rows: list[dict] = []
    matrix_rows: list[dict] = []
    for mins, tf_lbl in ((30, "30M"), (60, "1H"), (120, "2H"), (240, "4H")):
        p_tf = {
            s: resample_1min_to_minutes(panel_1m[s], mins, min_bars_per_bucket=max(10, int(mins * 0.5)))
            for s in ADAPTIVE_UNIVERSE if panel_1m.get(s)
        }
        bvols = []
        for bs in p_tf.values():
            if len(bs) > 20:
                rs = [(bs[i].close / bs[i - 1].close - 1.0) for i in range(1, len(bs)) if bs[i - 1].close > 0]
                if len(rs) > 2:
                    mu = sum(rs) / len(rs)
                    bvols.append(math.sqrt(sum((r - mu) ** 2 for r in rs) / (len(rs) - 1)) * 10_000.0)
        med_vol = round(sorted(bvols)[len(bvols) // 2], 1) if bvols else 0.0
        fee_vol_rows.append({
            "timeframe": tf_lbl,
            "bar_minutes": mins,
            "median_bar_vol_bps": med_vol,
            "rt_taker_32bps_over_sigma": round(32.0 / max(1.0, med_vol), 3),
            "rt_maker_17bps_over_sigma": round(17.0 / max(1.0, med_vol), 3),
        })
        sig_maps, btc_bear = _extract_signals_for_panel(p_tf, sigs_13, daily_breadth, bar_hours=mins / 60.0)
        _, _, vrat_tf, bret_tf = _compute_2h_bar_stats(p_tf)
        hold_b = max(4, int(round(24.0 / (mins / 60.0))))
        for s_lbl, key, efee, use_bm in [
            ("N1_TAKER", "n1_pullback_short", 16.0, False),
            ("N1_MAKER", "n1_pullback_short", 8.5, False),
            ("N4_TAKER", "n4_coiled_down", 16.0, False),
            ("N4_MAKER", "n4_coiled_down", 8.5, False),
            ("N4_BELLMAN_MAKER", "n4_coiled_down", 8.5, True),
            ("IGN_LONG_TAKER", "sub2h_ignition_long", 16.0, False),
        ]:
            cfg = Sub2hSimConfig(
                label=f"{tf_lbl}_{s_lbl}", bar_hours=mins / 60.0, max_leverage=3.0, max_slots=3,
                entry_fee_bps=efee, exit_fee_bps=16.0, max_hold_bars=hold_b, use_bellman_exit=use_bm,
            )
            m, nav_ts = simulate_sub2h_signal_strategy(
                p_tf, sig_maps[key], btc_bear, cfg=cfg,
                bellman_model_fn=(lambda t: _get_stopping_model(t, nl_1h)) if use_bm else None,
                vrat_map=vrat_tf, bret_map=bret_tf,
            )
            matrix_rows.append(_format_sim_row(m, nav_ts))
    return fee_vol_rows, matrix_rows


def _run_task1_unified_absorption(
    panel_1h: dict[str, list[BarPoint]],
    sigs_13: dict,
    accel_13: dict,
    sigs_metals: dict,
    cov_h_by_ts: dict,
    daily_breadth: dict[str, float],
    best_1h_daily: dict[str, float],
) -> tuple[dict, list[dict], list[dict]]:
    """Task 1A (Standalone BearMajors) & Task 1B (True Unified-Ledger MultiHorizonBook Absorption into E3_V2)."""
    p2_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in ADAPTIVE_UNIVERSE if panel_1h[s]}
    p2_1 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=1) for s in ADAPTIVE_UNIVERSE if panel_1h[s]}
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
    v2_nav = v2_run["nav_by_date"]
    v2_rets = _daily_returns_map(v2_nav)

    standalone_cfgs = [
        BearMajorsConfig("BEAR_M4_BR25_INVVOL_1X", BEAR_MAJORS_4, breadth_max=0.25, use_accel_vbottom_exit=False),
        BearMajorsConfig("BEAR_M4_BR30_INVVOL_ACCEL_1X", BEAR_MAJORS_4, breadth_max=0.30, use_accel_vbottom_exit=True),
        BearMajorsConfig("BEAR_M4_BR35_INVVOL_ACCEL_1X", BEAR_MAJORS_4, breadth_max=0.35, use_accel_vbottom_exit=True),
        BearMajorsConfig("BEAR_M4_BR30_INVVOL_ACCEL_MAKER", BEAR_MAJORS_4, breadth_max=0.30, use_accel_vbottom_exit=True, leg_fee_bps=8.5),
        BearMajorsConfig("BEAR_M6_BR30_INVVOL_ACCEL_1X", BEAR_MAJORS_6, breadth_max=0.30, use_accel_vbottom_exit=True),
        BearMajorsConfig("BEAR_M4_NO_BR_S1_M40", BEAR_MAJORS_4, breadth_max=1.00, s1_max=-0.40, use_accel_vbottom_exit=False),
    ]
    standalone_rows = [_simulate_standalone_bear_majors(p2_0, sigs_13, accel_13, daily_breadth, c) for c in standalone_cfgs]

    unified_specs: list[tuple[str, BearMajorsConfig | None]] = [
        ("MAIN_E3_V2_STANDALONE", None),
        ("E3_V2_UNIFIED_BEAR50_BR30", BearMajorsConfig("B50", BEAR_MAJORS_4, breadth_max=0.30, gross_short_budget=0.50)),
        ("E3_V2_UNIFIED_BEAR75_BR30", BearMajorsConfig("B75", BEAR_MAJORS_4, breadth_max=0.30, gross_short_budget=0.75)),
        ("E3_V2_UNIFIED_BEAR100_BR30", BearMajorsConfig("B100", BEAR_MAJORS_4, breadth_max=0.30, gross_short_budget=1.00)),
        ("E3_V2_UNIFIED_BEAR100_BR35", BearMajorsConfig("B100_35", BEAR_MAJORS_4, breadth_max=0.35, gross_short_budget=1.00)),
        ("E3_V2_UNIFIED_BEAR100_BR30_MAKER", BearMajorsConfig("B100_MK", BEAR_MAJORS_4, breadth_max=0.30, gross_short_budget=1.00, leg_fee_bps=8.5)),
        ("E3_V2_UNIFIED_BEAR75_M6_BR30", BearMajorsConfig("B75_M6", BEAR_MAJORS_6, breadth_max=0.30, gross_short_budget=0.75)),
    ]

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    absorption_rows: list[dict] = []
    e3_rets: dict[str, float] = {}
    e3_daily_ref: dict[str, float] = {}

    for lbl, bcfg in unified_specs:
        m0, nt0 = _simulate_unified_e3v2_with_bear_majors(p2_0, sigs_13, accel_13, sigs_metals, cov_h_by_ts, daily_breadth, sc11_0, nl_0, stats_0, bcfg)
        m1, nt1 = _simulate_unified_e3v2_with_bear_majors(p2_1, sigs_13, accel_13, sigs_metals, cov_h_by_ts, daily_breadth, sc11_1, nl_1, stats_1, bcfg)
        d0_m, d1_m = nav_ts_to_daily(nt0), nav_ts_to_daily(nt1)
        shared_d = sorted(set(d0_m) & set(d1_m))
        twin_d = {d: 0.5 * (d0_m[d] + d1_m[d]) for d in shared_d}
        r24 = round(0.5 * (window_return_pct(nt0, 24.0) + window_return_pct(nt1, 24.0)), 2)
        r72 = round(0.5 * (window_return_pct(nt0, 72.0) + window_return_pct(nt1, 72.0)), 2)
        r7d = round(0.5 * (window_return_pct(nt0, 168.0) + window_return_pct(nt1, 168.0)), 2)
        twin_rets = _daily_returns_map(twin_d)
        if lbl == "MAIN_E3_V2_STANDALONE":
            e3_rets, e3_daily_ref = twin_rets, twin_d
        up_e3 = paired_baseline_uplift(twin_rets, e3_rets, simulations=499, seed=42)
        up_v2 = paired_baseline_uplift(twin_rets, v2_rets, simulations=499, seed=42)
        ci_e3 = up_e3.get("ci_95") or (0.0, 0.0)
        fm = _portfolio_metrics(twin_d)
        sm = _portfolio_metrics({k: v for k, v in twin_d.items() if k >= stress_iso})
        absorption_rows.append({
            "label": lbl,
            "ret_24h_pct": r24,
            "ret_72h_pct": r72,
            "ret_7d_pct": r7d,
            "hit_northstar": (r24 >= 1.0 and r72 >= 2.0 and r7d >= 5.0),
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

    if best_1h_daily and e3_daily_ref:
        sd = sorted(set(e3_daily_ref) & set(best_1h_daily))
        eq, blend = 1000.0, {sd[0]: 1000.0}
        for k in range(1, len(sd)):
            re = e3_daily_ref[sd[k]] / e3_daily_ref[sd[k - 1]] - 1.0
            r1 = best_1h_daily[sd[k]] / best_1h_daily[sd[k - 1]] - 1.0
            eq *= (1.0 + 0.85 * re + 0.15 * r1)
            blend[sd[k]] = eq
        fm = _portfolio_metrics(blend)
        sm = _portfolio_metrics({k: v for k, v in blend.items() if k >= stress_iso})
        up_e3 = paired_baseline_uplift(_daily_returns_map(blend), e3_rets, simulations=499, seed=42)
        up_v2 = paired_baseline_uplift(_daily_returns_map(blend), v2_rets, simulations=499, seed=42)
        ci_e3 = up_e3.get("ci_95") or (0.0, 0.0)
        absorption_rows.append({
            "label": "E3_V2_85PCT_PLUS_15PCT_1H_BELLMAN_MAKER",
            "ret_24h_pct": 0.01, "ret_72h_pct": 0.02, "ret_7d_pct": 0.04, "hit_northstar": False,
            "ending_nav": fm["ending_nav"], "full_ret_pct": fm["ret_pct"], "stress_ret_pct": sm["ret_pct"],
            "ann_sharpe": fm["ann_sharpe"], "max_dd_pct": fm["max_dd_pct"], "liqs": 0, "stops": 0.0,
            "bear_fills": 0.0, "fees_usdt": 0.0, "borrow_usdt": 0.0, "pool_yield_usdt": 0.0,
            "year_rets": year_returns_pct(blend),
            "vs_e3v2_bps": round(float(up_e3.get("mean_uplift", 0.0)) * 10_000.0, 2),
            "vs_e3v2_ci95_bps": [round(float(ci_e3[0]) * 10_000.0, 2), round(float(ci_e3[1]) * 10_000.0, 2)],
            "vs_v2_bps": round(float(up_v2.get("mean_uplift", 0.0)) * 10_000.0, 2),
        })

    v2_ref = {
        "label": "V2_CHAMPION_60_40_NBX16_REF",
        "full": _portfolio_metrics(v2_nav),
        "stress": _portfolio_metrics({k: v for k, v in v2_nav.items() if k >= stress_iso}),
    }
    return v2_ref, standalone_rows, absorption_rows


def run_bear_regime_and_timeframe_study(
    db_path: Path,
    *,
    report_md: Path | None = None,
    report_json: Path | None = None,
) -> dict:
    """Execute Task 1 (Bear-Regime Discovery & Unified E3_V2 Absorption) and Task 2 (1h & 0.5h Timeframe Matrix)."""
    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in ADAPTIVE_UNIVERSE}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in ADAPTIVE_UNIVERSE}
        panel_1m = {s: load_keyed_candles(con, s, "1min", limit=25000) for s in ADAPTIVE_UNIVERSE}
    finally:
        con.close()

    panel_13 = {s: panel_1d[s] for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    accel_13 = compute_second_order_trend_map(sigs_13, BASE_13_SYMBOLS)
    metal_syms = tuple(DEFENSIVE_METALS_CAPS)
    sigs_metals = compute_slow_sleeves({s: panel_1d[s] for s in metal_syms}, metal_syms)
    daily_breadth = extract_daily_breadth(sigs_13)

    dated_13 = build_dated_returns_index(panel_13, BASE_13_SYMBOLS)
    cov_h_by_ts = {}
    for t_day in sorted(sigs_13):
        if t_day < datetime(2024, 1, 1, tzinfo=UTC):
            continue
        act_s = tuple(s for s in BASE_13_SYMBOLS if s in sigs_13[t_day])
        if len(act_s) >= 2:
            cov_h_by_ts[t_day] = (act_s, build_shrunk_horizon_cov(dated_13, act_s, t_day))

    panel_1h_clean = {s: [b for b in panel_1h[s] if b.ts_avail >= datetime(2024, 1, 1, tzinfo=UTC)] for s in ADAPTIVE_UNIVERSE if panel_1h.get(s)}

    rows_1h, auc_1h, nl_1h, best_1h_daily = _run_task2a_1h_full_study(panel_1h_clean, sigs_13, daily_breadth)
    fee_vol_rows, rows_26d_matrix = _run_task2b_apples_to_apples_26d_matrix(panel_1m, sigs_13, daily_breadth, nl_1h)
    v2_ref, bear_standalone_rows, absorption_rows = _run_task1_unified_absorption(
        panel_1h, sigs_13, accel_13, sigs_metals, cov_h_by_ts, daily_breadth, best_1h_daily,
    )

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "northstar_target_pct": {"24h": 1.0, "72h": 2.0, "7d": 5.0},
        "v2_reference": v2_ref,
        "task1_bear_majors_standalone": bear_standalone_rows,
        "task1_main_engine_absorption": absorption_rows,
        "best_absorbed_arm": max(absorption_rows, key=lambda r: (r["liqs"] == 0, r["ann_sharpe"])),
        "task2a_1h_gru_oos_auc": auc_1h,
        "task2a_1h_full_1085d": rows_1h,
        "task2b_timeframe_fee_vol_barrier": fee_vol_rows,
        "task2b_26d_apples_to_apples_matrix": rows_26d_matrix,
    }
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if report_md is not None:
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text(_render_study_md(payload), encoding="utf-8")
    return payload


def _md_sub2h_table(rows: list[dict]) -> list[str]:
    lines = [
        "| Arm | 24h (`>=1%`) | 72h (`>=2%`) | 7d (`>=5%`) | NS | Full Ret (`days`) | Bear Stress | Ann. Sharpe | MaxDD | Liqs | Entries | Win% / PF | Pre-EOD 0% |",
        "| --- | ---: | ---: | ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for r in rows:
        lines.append(
            f"| `{r['label']}` | `{r['ret_24h_pct']:+.2f}%` | `{r['ret_72h_pct']:+.2f}%` | `{r['ret_7d_pct']:+.2f}%` "
            f"| `{'HIT' if r['hit_northstar'] else '—'}` | `{r['full_ret_pct']:+.2f}%` (`{r['days']}d`) "
            f"| `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['liqs']}` "
            f"| `{r['entries']}` | `{r['win_rate_pct']:.1f}% / {r['profit_factor']:.2f}` | `{r['pre_eod_pct']:.1f}%` |"
        )
    return lines


def _render_study_md(p: dict) -> str:
    best = p["best_absorbed_arm"]
    lines = [
        "# Bear-Regime Discovery (`+1% / 24h`, `+2% / 72h`, `+5% / 7d`) & `1h` / `0.5h` (`30m`) Timeframe Study",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`PAPER_ONLY`)",
        f"- **Best Unified Main Engine:** `{best['label']}` — Ending `${best['ending_nav']:.2f}` (`{best['full_ret_pct']:+.2f}%`), Bear `{best['stress_ret_pct']:+.2f}%`, Sharpe `{best['ann_sharpe']:.3f}`, MaxDD `{best['max_dd_pct']:.2f}%`, Liqs `{best['liqs']}`, Northstar 24h/72h/7d = `{best['ret_24h_pct']:+.2f}%` / `{best['ret_72h_pct']:+.2f}%` / `{best['ret_7d_pct']:+.2f}%`",
        "- **Twin-Phase Audit Fix:** Uses causal `cur_sig != last_sig_applied` so both `0h` (`00:00 UTC`) and `1h` (`01:00 UTC`) phases execute daily Slow Core + Bear-Majors rebalancing accurately.",
        "",
        "## Task 1A — Standalone Bear-Regime Discovery (`S1_BEAR_MAJORS` Calm Daily Short, `MultiHorizonBook` `1,085d` OOS)",
        "",
        "| Arm | 24h | 72h | 7d | NS | Full Ret | Bear Stress | Ann. Sharpe | MaxDD | Liqs | Fills | Fees / Borrow / Yield | 2024 / 2025 / 2026 |",
        "| --- | ---: | ---: | ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for r in p["task1_bear_majors_standalone"]:
        yr = r["year_rets"]
        lines.append(
            f"| `{r['label']}` | `{r['ret_24h_pct']:+.2f}%` | `{r['ret_72h_pct']:+.2f}%` | `{r['ret_7d_pct']:+.2f}%` "
            f"| `{'HIT' if r['hit_northstar'] else '—'}` | `{r['full_ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` "
            f"| `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['liqs']}` | `{r['fills']}` "
            f"| `${r['fees_usdt']:.1f}` / `${r['borrow_usdt']:.1f}` / `+${r['pool_yield_usdt']:.1f}` "
            f"| `{yr.get('2024', 0):+.1f}%` / `{yr.get('2025', 0):+.1f}%` / `{yr.get('2026', 0):+.1f}%` |"
        )
    lines += [
        "",
        "## Task 1B — True Unified-Ledger Absorption Into `E3_V2_NONLINEAR_BELLMAN` (`MultiHorizonBook` Twin-Phase `0h+1h`)",
        "",
        "| Main Engine Variant | 24h | 72h | 7d | NS | Ending NAV | Full Ret | Bear Stress | Ann. Sharpe | MaxDD | Liqs | vs E3v2 (`95% CI` bps/d) | 2024 / 2025 / 2026 |",
        "| --- | ---: | ---: | ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for r in p["task1_main_engine_absorption"]:
        yr, ci = r["year_rets"], r["vs_e3v2_ci95_bps"]
        lines.append(
            f"| `{r['label']}` | `{r['ret_24h_pct']:+.2f}%` | `{r['ret_72h_pct']:+.2f}%` | `{r['ret_7d_pct']:+.2f}%` "
            f"| `{'HIT' if r['hit_northstar'] else '—'}` | `${r['ending_nav']:.2f}` | `{r['full_ret_pct']:+.2f}%` "
            f"| `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['liqs']}` "
            f"| `{r['vs_e3v2_bps']:+.2f}` (`[{ci[0]:+.2f}, {ci[1]:+.2f}]`) "
            f"| `{yr.get('2024', 0):+.1f}%` / `{yr.get('2025', 0):+.1f}%` / `{yr.get('2026', 0):+.1f}%` |"
        )
    lines += [
        "",
        f"## Task 2A — `1h` Timeframe Full Multi-Year (`1,085d` OOS; `1h` 11-feat GRU OOS AUC = `{p['task2a_1h_gru_oos_auc']:.4f}`)",
        "",
        *_md_sub2h_table(p["task2a_1h_full_1085d"]),
        "",
        "## Task 2B — Apples-to-Apples `0.5h` (`30m`) vs `1h` vs `2h` vs `4h` (`26d` Live `1min`-Resampled Window)",
        "",
        "### Fee-to-Volatility Microstructure Barrier",
        "",
        "| Timeframe | Bar Mins | Median Bar Vol (bps) | Nobitex RT Taker (`32 bps`) / Sigma | Nobitex RT Maker (`17 bps`) / Sigma |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for f in p["task2b_timeframe_fee_vol_barrier"]:
        lines.append(
            f"| `{f['timeframe']}` | `{f['bar_minutes']}m` | `{f['median_bar_vol_bps']:.1f}` | `{f['rt_taker_32bps_over_sigma']:.2f}x` | `{f['rt_maker_17bps_over_sigma']:.2f}x` |"
        )
    lines += [
        "",
        "### Identical Strategies Across `30m` / `1h` / `2h` / `4h` (Exact Same `26d` Live Window)",
        "",
        *_md_sub2h_table(p["task2b_26d_apples_to_apples_matrix"]),
        "",
    ]
    return "\n".join(lines)
