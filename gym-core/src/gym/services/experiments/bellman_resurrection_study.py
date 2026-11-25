"""Bellman Optimal-Stopping V2 (Nonlinear + 1d Slow Core) & Defeated-Strategy Resurrection Study.

Part 1: Upgrades E3_V1 (Sharpe 1.067) with Nonlinear Interaction+MLP Bellman Stopping (E3_V2) and
        dedicated 1d Slow-Core Bellman Stopping (E3_SLOW_1D).
Part 2: Tests whether dedicated purged walk-forward Bellman Optimal-Stopping resurrects 3 previously
        defeated entry strategies (2h Flush Rebound, 2h Breakdown Short on Nobitex EOD Margin, and
        Uncensored z>=1.5 Early Ignition) vs. identical entries under static exits.
Part 3: Integrates any genuinely resurrected sleeve (OOS Sharpe > 0.30 & positive net return) into
        the unified Multi-Horizon Lot Book head-to-head against V2_CHAMPION and E3_V1.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

import numpy as np

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.bellman_stopping import (
    NonlinearBellmanModel,
    SlowCoreBellmanModel,
    SlowCoreStoppingState,
    compute_bellman_path_target_bps,
    detect_breakdown_short_trigger,
    detect_flush_rebound_trigger,
    detect_uncensored_early_ignition,
)
from ...domain.core_signal_geometry import DEFENSIVE_METALS_CAPS
from ...domain.higher_order_and_sparse import compute_second_order_trend_map
from ...domain.in_position_and_execution import tehran_execution_cost_bps
from ...domain.instrument_resolver import ResolverConfig, build_local_venue_offers
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.multi_horizon_book import (
    MultiHorizonBook,
    check_lot_intrabar_exit,
    resolve_safe_ignition_leverage,
)
from ...domain.optimal_exits import (
    ClosedTradeCapture,
    OptimalExitConfig,
    OptimalStoppingState,
    decide_optimal_stopping_action,
    summarize_exit_efficiency,
    trim_lot_fraction,
)
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
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
    _daily_atr_pct_map,
    _extract_optimal_stopping_dataset,
    _get_stopping_model,
    _open_fast_exit_study_entries,
    _record_closed_trade,
    _simulate_exit_phase,
    _train_walkforward_stopping_models,
)
from .unified_book_helpers import WALKFORWARD_FOLDS as FOLDS
from .unified_book_helpers import resolve_bar_prices


def _train_wf_nonlinear_bellman(
    dts: list[datetime],
    x10: np.ndarray,
    y_bps: np.ndarray,
) -> list[tuple[datetime, datetime, NonlinearBellmanModel]]:
    purge = timedelta(hours=48)
    out = []
    for s, e in FOLDS:
        tr = [k for k, dt in enumerate(dts) if dt < s - purge]
        m = NonlinearBellmanModel(l2_ridge=45.0, hidden_dim=12)
        if len(tr) >= 60:
            m.fit(x10[tr], y_bps[tr])
        out.append((s, e, m))
    return out


def _extract_resurrection_triggers_and_bellman_data(
    panel_2h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
    family: str,
) -> tuple[
    dict[tuple[datetime, str], tuple[int, float, float]],
    list[datetime],
    np.ndarray,
    np.ndarray,
]:
    """Extract strictly causal entry triggers + Bellman optimal-stopping rows for a defeated entry family."""
    btc_bars = panel_2h.get("BTCUSDT", [])
    btc_ret = {
        btc_bars[i].ts_avail: (btc_bars[i].close - btc_bars[i - 1].close) / btc_bars[i - 1].close
        for i in range(1, len(btc_bars))
        if btc_bars[i - 1].close > 0
    }
    direction = -1 if family == "breakdown_short" else 1
    triggers: dict[tuple[datetime, str], tuple[int, float, float]] = {}
    dts: list[datetime] = []
    xs: list[list[float]] = []
    ys: list[float] = []

    for sym in IGNITION_18_CRYPTO:
        if direction < 0 and sym not in NOBITEX_MARGIN_ELIGIBLE_USDT:
            continue
        bars = panel_2h.get(sym, [])
        if len(bars) < 90:
            continue
        rets = [0.0] + [
            (bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0
            for i in range(1, len(bars))
        ]
        vols = [b.volume for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]

        for i in range(72, len(bars) - 18):
            br = daily_breadth.get(bars[i].ts_avail.date().isoformat(), 0.5)
            if family == "flush_rebound":
                ok, b_vol, score = detect_flush_rebound_trigger(bars, rets, vols, i)
            elif family == "breakdown_short":
                ok, b_vol, score = detect_breakdown_short_trigger(bars, rets, vols, lows, i, br)
            else:
                ok, b_vol, score = detect_uncensored_early_ignition(bars, rets, vols, highs, i)
            if not ok:
                continue
            triggers[(bars[i].ts_avail, sym)] = (direction, b_vol, score)
            entry_px = bars[i + 1].open
            mv = max(1e-9, median(vols[i - 36 : i]))
            peak = entry_px
            for k in range(1, 9):
                idx = i + k
                if idx + 7 >= len(bars):
                    break
                cur = bars[idx]
                peak = max(peak, cur.close) if direction > 0 else min(peak, cur.close)
                upnl = direction * (cur.close - entry_px) / entry_px
                mfe = max(0.0, direction * (peak - entry_px) / entry_px)
                gb_r = (mfe - upnl) / max(mfe, 1e-4) if mfe > 1e-4 else 0.0
                span = max(cur.high - cur.low, 1e-9)
                wick = (max(0.0, cur.high - cur.close) if direction > 0 else max(0.0, cur.close - cur.low)) / span
                hrs_eod = 24.0 - (cur.ts_avail.hour + cur.ts_avail.minute / 60.0)
                st = OptimalStoppingState(
                    age_bars=k, unrealized_ret=upnl, peak_mfe=mfe, giveback_ratio=gb_r,
                    upper_wick_ratio=wick, volume_ratio=cur.volume / mv,
                    bar_ret_z=direction * rets[idx] / max(b_vol, 1e-4),
                    rel_btc_ret=direction * (rets[idx] - btc_ret.get(cur.ts_avail, 0.0)),
                    hours_to_utc_eod=hrs_eod, entry_gru_score=score,
                )
                target_bps = compute_bellman_path_target_bps(bars, idx, direction, peak, b_vol, max_lookahead=6)
                if target_bps is not None:
                    dts.append(cur.ts_avail)
                    xs.append(st.to_vector())
                    ys.append(target_bps)

    if not xs:
        return triggers, [], np.zeros((0, 10)), np.zeros((0,))
    return triggers, dts, np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)


def _step_bellman_fast_lots(
    book: MultiHorizonBook,
    by_avail: dict[str, dict[datetime, BarPoint]],
    exec_px: dict[str, float],
    tradable: set[str],
    ts: datetime,
    bret_map: dict[str, dict[datetime, float]],
    vrat_map: dict[str, dict[datetime, float]],
    primary_models: list[tuple[datetime, datetime, NonlinearBellmanModel]] | None,
    extra_models: list[tuple[datetime, datetime, NonlinearBellmanModel]] | None,
    trimmed_lots: set[tuple[str, str]],
    trades_log: list[ClosedTradeCapture],
    exit_cfg: OptimalExitConfig,
    *,
    pyramid_frac: float = 0.45,
) -> None:
    """Shared fast-lot exit & Bellman optimal-stopping manager for standalone & unified books."""
    taker_bps = tehran_execution_cost_bps(ts.hour)
    hrs_eod = 24.0 - (ts.hour + ts.minute / 60.0)
    btc_r = bret_map.get("BTCUSDT", {}).get(ts, 0.0)
    for key in list(book.lots):
        lot = book.lots[key]
        if lot.thesis_id == "slow_core":
            continue
        lot.age_bars += 1
        bar = by_avail[lot.symbol].get(ts)
        if bar is not None:
            evt, px, fbps = check_lot_intrabar_exit(lot, bar, taker_exit_bps=taker_bps, oco_maker_exit_bps=4.5, use_oco_maker_tp=False)
            if evt == "LIQ":
                _record_closed_trade(trades_log, lot, px, ts, "LIQ")
                book.liquidations += 1
                del book.lots[key]
                trimmed_lots.discard(key)
                continue
            if evt == "STOP":
                _record_closed_trade(trades_log, lot, px, ts, "STOP")
                book.close_lot(key, px, fbps)
                book.stop_outs += 1
                trimmed_lots.discard(key)
                continue
            lot.peak_price = max(lot.peak_price, bar.close) if lot.direction > 0 else min(lot.peak_price, bar.close)
        if lot.symbol not in tradable or lot.symbol not in exec_px or bar is None:
            continue
        px_now = exec_px[lot.symbol]
        trail_m = 2.6 if lot.direction > 0 else 2.4
        trail_hit = (
            bar.close < lot.peak_price * (1.0 - trail_m * lot.entry_bar_vol)
            if lot.direction > 0
            else bar.close > lot.peak_price * (1.0 + trail_m * lot.entry_bar_vol)
        )
        max_b = 24 if (lot.pyramided or key in trimmed_lots) else 12
        if lot.age_bars >= max_b or trail_hit:
            _record_closed_trade(trades_log, lot, px_now, ts, "TRAIL" if trail_hit else "TIMEOUT")
            book.close_lot(key, px_now, taker_bps)
            trimmed_lots.discard(key)
            continue
        models = extra_models if (lot.thesis_id == "resurrect" and extra_models is not None) else primary_models
        bm = _get_stopping_model(ts, models) if models is not None else None
        if bm is None:
            continue
        upnl = lot.direction * (bar.close - lot.entry_price) / max(lot.entry_price, 1e-9)
        mfe = max(0.0, lot.direction * (lot.peak_price - lot.entry_price) / max(lot.entry_price, 1e-9))
        gb_r = (mfe - upnl) / max(mfe, 1e-4) if mfe > 1e-4 else 0.0
        span = max(bar.high - bar.low, 1e-9)
        wick = (max(0.0, bar.high - bar.close) if lot.direction > 0 else max(0.0, bar.close - bar.low)) / span
        st = OptimalStoppingState(
            age_bars=lot.age_bars, unrealized_ret=upnl, peak_mfe=mfe, giveback_ratio=gb_r,
            upper_wick_ratio=wick, volume_ratio=vrat_map.get(lot.symbol, {}).get(ts, 1.0),
            bar_ret_z=lot.direction * bret_map.get(lot.symbol, {}).get(ts, 0.0) / max(lot.entry_bar_vol, 1e-4),
            rel_btc_ret=lot.direction * (bret_map.get(lot.symbol, {}).get(ts, 0.0) - btc_r),
            hours_to_utc_eod=hrs_eod, entry_gru_score=lot.entry_gru_score,
        )
        act = decide_optimal_stopping_action(
            bm.predict_wait_value_bps(st), st, already_pyramided=lot.pyramided,
            already_trimmed=(key in trimmed_lots), cfg=exit_cfg,
        )
        if act == "OPTIMAL_EXIT":
            _record_closed_trade(trades_log, lot, px_now, ts, "BELLMAN_V2_EXIT")
            book.close_lot(key, px_now, taker_bps)
            book.early_ml_exits += 1
            trimmed_lots.discard(key)
        elif act == "OPTIMAL_TRIM_50":
            trim_lot_fraction(book, key, 0.50, px_now, 4.5)
            trimmed_lots.add(key)
            book.oco_profit_exits += 1
            lot.stop_price = max(lot.stop_price, lot.entry_price * 1.004) if lot.direction > 0 else min(lot.stop_price, lot.entry_price * 0.996)
        elif act == "FREE_ROLL_PYRAMID":
            book.pyramid_lot_on_house_money(key, px_now, add_fraction=pyramid_frac, entry_fee_bps=taker_bps)


def _simulate_standalone_family(
    panel_2h: dict[str, list[BarPoint]],
    triggers: dict[tuple[datetime, str], tuple[int, float, float]],
    bellman_models: list[tuple[datetime, datetime, NonlinearBellmanModel]],
    bar_stats: tuple,
    *,
    use_bellman_exit: bool,
    direction: int,
    leverage: float = 1.5,
) -> tuple[dict, dict[str, float]]:
    """Run one defeated entry family standalone: static exit vs. purged walk-forward Bellman optimal closing."""
    _, _, vrat_map, bret_map = bar_stats
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    all_ts = sorted({t for s in IGNITION_18_CRYPTO for t in by_avail[s] if t >= datetime(2024, 9, 1, tzinfo=UTC)})
    offers_by_sym = {s: build_local_venue_offers(s, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in IGNITION_18_CRYPTO}

    book = MultiHorizonBook(free_cash=1000.0)
    trimmed: set[tuple[str, str]] = set()
    trades_log: list[ClosedTradeCapture] = []
    last_px: dict[str, float] = {}
    nav_by_date: dict[str, float] = {}
    exit_cfg = OptimalExitConfig(use_e3_optimal_stopping=True, wait_exit_threshold_bps=-4.0, wait_trim_threshold_bps=6.0)

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, 2.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR, eod_borrow_bps=5.0)
        exec_px, tradable = resolve_bar_prices(IGNITION_18_CRYPTO, by_start, by_avail, ts, last_px)

        _step_bellman_fast_lots(
            book, by_avail, exec_px, tradable, ts, bret_map, vrat_map,
            bellman_models if use_bellman_exit else None, None, trimmed, trades_log, exit_cfg, pyramid_frac=0.40,
        )

        equity = book.mark_equity(exec_px)
        if len(book.lots) < 3 and book.free_cash >= 40.0 and equity >= 50.0:
            for sym in IGNITION_18_CRYPTO:
                if len(book.lots) >= 3 or sym not in tradable or (sym, "resurrect") in book.lots:
                    continue
                trig = triggers.get((ts, sym))
                if trig is None:
                    continue
                tdir, b_vol, tscore = trig
                stop_bps = max(180.0, min(550.0, 2.3 * b_vol * 10_000.0))
                matched = [o for o in offers_by_sym[sym] if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == tdir]
                if not matched:
                    continue
                book.open_fast_margin_lot(
                    symbol=sym, thesis_id="resurrect", direction=tdir, leverage=leverage,
                    target_collateral=min(0.22 * equity, max(0.0, book.free_cash - 10.0)),
                    entry_px=exec_px[sym], stop_bps=stop_bps, take_profit_bps=0.0,
                    offer=matched[0], ts=ts, entry_bar_vol=b_vol, entry_gru_score=tscore,
                    allow_internal_short_offset=False,
                )
        nav_by_date[ts.date().isoformat()] = book.mark_equity(exec_px)

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    fm = _portfolio_metrics(nav_by_date)
    sm = _portfolio_metrics({k: v for k, v in nav_by_date.items() if k >= stress_iso})
    eff = summarize_exit_efficiency(trades_log)
    return {
        "ending_nav": fm["ending_nav"],
        "ret_pct": fm["ret_pct"],
        "stress_ret_pct": sm["ret_pct"],
        "ann_sharpe": fm["ann_sharpe"],
        "max_dd_pct": fm["max_dd_pct"],
        "liqs": book.liquidations,
        "borrow": round(book.total_borrow, 2),
        "pool_yield": round(book.total_pool_yield, 2),
        "fees": round(book.total_fees, 2),
        "bellman_exits": book.early_ml_exits,
        "pyramids": book.pyramids,
        "eff": eff,
    }, nav_by_date


def _train_slow_core_bellman_models(
    panel_1d: dict[str, list[BarPoint]],
    sigs_13: dict,
    accel_13: dict,
    atr_1d_pct: dict[str, dict[datetime, float]],
    daily_breadth: dict[str, float],
) -> list[tuple[datetime, datetime, SlowCoreBellmanModel]]:
    """Train strictly causal purged walk-forward Bellman 5d continuation model for 1d Slow Spot Core."""
    dts: list[datetime] = []
    xs: list[list[float]] = []
    ys: list[float] = []
    for sym in BASE_13_SYMBOLS:
        bars = panel_1d.get(sym, [])
        if len(bars) < 150:
            continue
        in_pos = False
        entry_px, peak_px, days_h = 0.0, 0.0, 0
        for i in range(130, len(bars) - 7):
            ts = bars[i].ts_avail
            sig = sigs_13.get(ts, {}).get(sym)
            if sig is None or sig.s1_trend is None:
                continue
            if not in_pos and sig.s1_trend > 0.15:
                in_pos, entry_px, peak_px, days_h = True, bars[i + 1].open, bars[i + 1].open, 1
                continue
            if in_pos:
                if sig.s1_trend <= 0.0 or entry_px <= 0:
                    in_pos = False
                    continue
                days_h += 1
                c = bars[i].close
                peak_px = max(peak_px, c)
                atr = max(0.015, atr_1d_pct.get(sym, {}).get(ts, 0.04))
                pc = bars[i - 1].close if bars[i - 1].close > 0 else c
                st = SlowCoreStoppingState(
                    days_held=days_h,
                    unrealized_ret=(c - entry_px) / entry_px,
                    peak_mfe=max(0.0, (peak_px - entry_px) / entry_px),
                    drawdown_from_peak=max(0.0, (peak_px - c) / max(peak_px, 1e-9)),
                    s1_trend=sig.s1_trend,
                    s1_accel=accel_13.get(ts, {}).get(sym, 0.0),
                    crypto_breadth=daily_breadth.get(ts.date().isoformat(), 0.5),
                    daily_atr_pct=atr,
                    bar_ret_vs_atr=((c - pc) / pc) / atr,
                )
                o_now, o_fut = bars[i + 1].open, bars[i + 6].open
                if o_now > 0 and o_fut > 0:
                    dts.append(ts)
                    xs.append(st.to_vector())
                    ys.append(max(-1500.0, min(1500.0, (o_fut - o_now) / o_now * 10_000.0)))

    if not xs:
        return []
    xm, ym = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
    purge = timedelta(days=6)
    out = []
    for s, e in FOLDS:
        tr = [k for k, dt in enumerate(dts) if dt < s - purge]
        m = SlowCoreBellmanModel(l2_alpha=60.0)
        if len(tr) >= 80:
            m.fit(xm[tr], ym[tr])
        out.append((s, e, m))
    return out


def _apply_slow_bellman_veto(
    book: MultiHorizonBook,
    pending_slow_targets: dict[str, float],
    ts: datetime,
    cur_sig_ts: datetime,
    day_sigs: dict,
    day_acc: dict,
    exec_px: dict[str, float],
    atr_1d_pct: dict[str, dict[datetime, float]],
    bret_map: dict[str, dict[datetime, float]],
    breadth: float,
    slow_model: SlowCoreBellmanModel | None,
) -> int:
    if slow_model is None:
        return 0
    exits = 0
    for s in list(pending_slow_targets):
        lot = book.lots.get((s, "slow_core"))
        sig = day_sigs.get(s)
        if lot is None or sig is None or sig.s1_trend is None or s not in exec_px:
            continue
        px = exec_px[s]
        lot.peak_price = max(lot.peak_price, px)
        atr = max(0.015, atr_1d_pct.get(s, {}).get(cur_sig_ts, 0.04))
        sst = SlowCoreStoppingState(
            days_held=max(1, int((ts - lot.entry_ts).total_seconds() // 86400)),
            unrealized_ret=(px - lot.entry_price) / max(lot.entry_price, 1e-9),
            peak_mfe=max(0.0, (lot.peak_price - lot.entry_price) / max(lot.entry_price, 1e-9)),
            drawdown_from_peak=max(0.0, (lot.peak_price - px) / max(lot.peak_price, 1e-9)),
            s1_trend=sig.s1_trend, s1_accel=day_acc.get(s, 0.0), crypto_breadth=breadth,
            daily_atr_pct=atr, bar_ret_vs_atr=bret_map.get(s, {}).get(ts, 0.0) / atr,
        )
        if slow_model.predict_wait_5d_bps(sst) < -45.0:
            pending_slow_targets[s] = 0.0
            exits += 1
    return exits


def _open_resurrected_entries(
    book: MultiHorizonBook,
    ts: datetime,
    equity: float,
    dd_pct: float,
    exec_px: dict[str, float],
    tradable: set[str],
    extra_triggers: dict[tuple[datetime, str], tuple[int, float, float]] | None,
    offers_by_sym: dict,
    r_cfg: ResolverConfig,
) -> int:
    if extra_triggers is None or book.free_cash < 40.0:
        return 0
    act_ex = sum(1 for k in book.lots if k[1] == "resurrect")
    opened = 0
    for sym in IGNITION_18_CRYPTO:
        if act_ex >= 2 or sym not in tradable or (sym, "resurrect") in book.lots or (sym, "ignition_2h") in book.lots:
            continue
        trig = extra_triggers.get((ts, sym))
        if trig is None:
            continue
        tdir, b_vol, tscore = trig
        stop_bps = max(180.0, min(550.0, 2.3 * b_vol * 10_000.0))
        matched = [o for o in offers_by_sym[sym] if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == tdir]
        if not matched:
            continue
        lev = resolve_safe_ignition_leverage(matched[0], stop_bps, 0.70, dd_pct, r_cfg)
        stop_frac = max(0.015, (stop_bps + 35.0) / 10_000.0)
        tgt_col = min(0.10 * equity, (0.010 * equity / stop_frac) / lev, max(0.0, book.free_cash - 10.0))
        if book.open_fast_margin_lot(
            symbol=sym, thesis_id="resurrect", direction=tdir, leverage=lev,
            target_collateral=tgt_col, entry_px=exec_px[sym], stop_bps=stop_bps,
            take_profit_bps=0.0, offer=matched[0], ts=ts, entry_bar_vol=b_vol, entry_gru_score=tscore,
            allow_internal_short_offset=True,
        ):
            act_ex += 1
            opened += 1
    return opened


def _simulate_upgraded_bellman_phase(
    panel_2h: dict[str, list[BarPoint]],
    sigs_13: dict,
    accel_13: dict,
    sigs_metals: dict,
    cov_h_by_ts: dict,
    atr_1d_pct: dict[str, dict[datetime, float]],
    daily_breadth: dict[str, float],
    gru_scores: dict[tuple[datetime, str], float],
    nl_models: list[tuple[datetime, datetime, NonlinearBellmanModel]],
    slow_models: list[tuple[datetime, datetime, SlowCoreBellmanModel]],
    bar_stats: tuple,
    *,
    use_slow_bellman: bool = False,
    extra_triggers: dict[tuple[datetime, str], tuple[int, float, float]] | None = None,
    extra_models: list[tuple[datetime, datetime, NonlinearBellmanModel]] | None = None,
) -> tuple[dict, dict[str, float]]:
    """Run E3_V2 Nonlinear Bellman Stopping + optional 1d Slow Bellman + optional resurrected sleeve."""
    bvol_map, _, vrat_map, bret_map = bar_stats
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    all_ts = sorted({t for s in IGNITION_18_CRYPTO for t in by_avail[s]})
    offers_by_sym = {s: build_local_venue_offers(s, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in ADAPTIVE_UNIVERSE}
    r_cfg = ResolverConfig(max_venue_leverage=5.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR)
    exit_cfg = OptimalExitConfig(use_e3_optimal_stopping=True)

    book = MultiHorizonBook(free_cash=1000.0)
    pending_slow_targets: dict[str, float] | None = None
    last_px: dict[str, float] = {}
    recent_gru: list[float] = []
    trimmed_lots: set[tuple[str, str]] = set()
    trades_log: list[ClosedTradeCapture] = []
    slow_bellman_exits, extra_entries = 0, 0
    peak_nav = 1000.0
    nav_by_date: dict[str, float] = {}
    sig_dates, sig_ptr = sorted(sigs_13), 0
    last_sig_applied: datetime | None = None

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, 2.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR, eod_borrow_bps=5.0)
        exec_px, tradable = resolve_bar_prices(ADAPTIVE_UNIVERSE, by_start, by_avail, ts, last_px)

        _step_bellman_fast_lots(
            book, by_avail, exec_px, tradable, ts, bret_map, vrat_map,
            nl_models, extra_models, trimmed_lots, trades_log, exit_cfg, pyramid_frac=0.45,
        )

        while sig_ptr + 1 < len(sig_dates) and sig_dates[sig_ptr + 1] <= ts:
            sig_ptr += 1
        cur_sig_ts = sig_dates[sig_ptr] if (sig_dates and sig_dates[sig_ptr] <= ts) else None

        equity = book.mark_equity(exec_px)
        peak_nav = max(peak_nav, equity)
        dd_pct = ((peak_nav - equity) / peak_nav * 100.0) if peak_nav > 0 else 0.0
        if equity < 20.0:
            nav_by_date[ts.date().isoformat()] = equity
            continue

        if cur_sig_ts is not None and cur_sig_ts != last_sig_applied and cur_sig_ts in cov_h_by_ts:
            last_sig_applied = cur_sig_ts
            active_slow, cov_h = cov_h_by_ts[cur_sig_ts]
            cur_slow_w = tuple(
                (book.lots[(s, "slow_core")].qty * exec_px.get(s, 0.0) / equity) if (s, "slow_core") in book.lots else 0.0
                for s in active_slow
            )
            pending_slow_targets = _solve_slow_targets_for_day(
                active_slow, sigs_13[cur_sig_ts], accel_13.get(cur_sig_ts, {}), cur_slow_w, cov_h,
                sigs_metals.get(cur_sig_ts, {}), exec_px, 0.08, tehran_execution_cost_bps(10, use_passive_maker=True),
            )
            if use_slow_bellman:
                slow_bellman_exits += _apply_slow_bellman_veto(
                    book, pending_slow_targets, ts, cur_sig_ts, sigs_13[cur_sig_ts], accel_13.get(cur_sig_ts, {}),
                    exec_px, atr_1d_pct, bret_map, daily_breadth.get(ts.date().isoformat(), 0.5),
                    _get_stopping_model(ts, slow_models),
                )

        if pending_slow_targets is not None and ts.hour >= 10:
            book.rebalance_slow_spot_targets(
                pending_slow_targets, exec_px, tradable, ts, leg_fee_bps=tehran_execution_cost_bps(ts.hour, use_passive_maker=True),
            )
            pending_slow_targets = None

        _open_fast_exit_study_entries(
            book, ts, equity, dd_pct, exec_px, tradable, gru_scores, recent_gru, bvol_map, offers_by_sym, r_cfg,
        )
        extra_entries += _open_resurrected_entries(book, ts, equity, dd_pct, exec_px, tradable, extra_triggers, offers_by_sym, r_cfg)
        nav_by_date[ts.date().isoformat()] = book.mark_equity(exec_px)

    return {
        "fees": round(book.total_fees, 2),
        "borrow": round(book.total_borrow, 2),
        "pool_yield": round(book.total_pool_yield, 2),
        "liqs": book.liquidations,
        "ml_exits": book.early_ml_exits,
        "pyramids": book.pyramids,
        "slow_bellman_exits": slow_bellman_exits,
        "internal_shorts": book.internal_short_offsets,
        "extra_entries": extra_entries,
        "eff": summarize_exit_efficiency(trades_log),
    }, nav_by_date


def _summarize_twin_run(label: str, m0: dict, n0: dict[str, float], m1: dict, n1: dict[str, float], v2_rets: dict[str, float], e3_rets: dict[str, float]) -> dict:
    shared = sorted(set(n0) & set(n1))
    tn = {d: 0.5 * (n0[d] + n1[d]) for d in shared}
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    fm = _portfolio_metrics(tn)
    sm = _portfolio_metrics({d: v for d, v in tn.items() if d >= stress_iso})
    tn_rets = _daily_returns_map(tn)
    up_v2 = paired_baseline_uplift(tn_rets, v2_rets, simulations=499, seed=42)
    up_e3 = paired_baseline_uplift(tn_rets, e3_rets, simulations=499, seed=42)
    ci_v2 = up_v2.get("ci_95") or (0.0, 0.0)
    return {
        "label": label,
        "days": len(tn),
        "ending_nav": fm["ending_nav"],
        "ret_pct": fm["ret_pct"],
        "stress_ret_pct": sm["ret_pct"],
        "ann_sharpe": fm["ann_sharpe"],
        "max_dd_pct": fm["max_dd_pct"],
        "sharpe_0h": _portfolio_metrics(n0)["ann_sharpe"],
        "sharpe_1h": _portfolio_metrics(n1)["ann_sharpe"],
        "liquidations_sum": m0["liqs"] + m1["liqs"],
        "fees_usdt_avg": round(0.5 * (m0["fees"] + m1["fees"]), 2),
        "borrow_usdt_avg": round(0.5 * (m0["borrow"] + m1["borrow"]), 2),
        "pool_yield_usdt_avg": round(0.5 * (m0["pool_yield"] + m1["pool_yield"]), 2),
        "ml_exits_avg": round(0.5 * (m0.get("ml_exits", m0.get("early_ml_exits", 0)) + m1.get("ml_exits", m1.get("early_ml_exits", 0))), 1),
        "pyramids_avg": round(0.5 * (m0["pyramids"] + m1["pyramids"]), 1),
        "slow_bellman_exits_avg": round(0.5 * (m0.get("slow_bellman_exits", 0) + m1.get("slow_bellman_exits", 0)), 1),
        "extra_entries_avg": round(0.5 * (m0.get("extra_entries", 0) + m1.get("extra_entries", 0)), 1),
        "vs_e3v1_bps": round(float(up_e3.get("mean_uplift", 0.0)) * 10_000.0, 2),
        "vs_v2_bps": round(float(up_v2.get("mean_uplift", 0.0)) * 10_000.0, 2),
        "vs_v2_ci": [round(ci_v2[0] * 10_000.0, 2), round(ci_v2[1] * 10_000.0, 2)],
    }


def run_bellman_resurrection_study(
    db_path: Path,
    *,
    report_md: Path | None = None,
    report_json: Path | None = None,
) -> dict:
    """Execute Part 1 (E3-v2 Nonlinear + 1d Slow Bellman), Part 2 (3 Resurrections), and Part 3 (Portfolio)."""
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
    daily_breadth = extract_daily_breadth(sigs_13)
    atr_1d_pct = _daily_atr_pct_map(panel_1d)

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
    stats_0 = _compute_2h_bar_stats(p2_0)
    stats_1 = _compute_2h_bar_stats(p2_1)

    d0, s0, x0, yb0, yp0 = _extract_11feat_coiled_spring_dataset(p2_0, IGNITION_18_CRYPTO, daily_breadth)
    d1, s1, x1, yb1, yp1 = _extract_11feat_coiled_spring_dataset(p2_1, IGNITION_18_CRYPTO, daily_breadth)
    sc11_0, _, _ = _walkforward_gru_scores(d0, s0, x0, yp0, yb0, task="regression")
    sc11_1, _, _ = _walkforward_gru_scores(d1, s1, x1, yp1, yb1, task="regression")

    # V2 benchmark
    _, _, sch0 = simulate_nobitex_margin_ignition(p2_0, IGNITION_18_CRYPTO, daily_breadth, sc11_0, label="V2_0", offset_hours=0, score_is_return=True, base_prob=0.46, top_tercile_leverage=1.5, leg_cost=0.0016, borrow_mode="eod_utc", borrow_rate=0.0005)
    _, _, sch1 = simulate_nobitex_margin_ignition(p2_1, IGNITION_18_CRYPTO, daily_breadth, sc11_1, label="V2_1", offset_hours=1, score_is_return=True, base_prob=0.46, top_tercile_leverage=1.5, leg_cost=0.0016, borrow_mode="eod_utc", borrow_rate=0.0005)
    v2_run = _run_v2_joint_shared_ledger(panel_1h, ADAPTIVE_UNIVERSE, sigs_13, accel_13, sigs_metals, cov_h_by_ts, _merge_twin_schedules(sch0, sch1), slow_budget=0.60, ign_budget=0.40, fee_rate=Decimal("0.0016"), use_metals_reserve=True)
    v2_nav = v2_run["nav_by_date"]
    v2_rets = _daily_returns_map(v2_nav)

    # E3_V1 linear Ridge benchmark
    st_d0, st_x0, st_y0 = _extract_optimal_stopping_dataset(p2_0, sc11_0)
    st_d1, st_x1, st_y1 = _extract_optimal_stopping_dataset(p2_1, sc11_1)
    lin_0 = _train_walkforward_stopping_models(st_d0, st_x0, st_y0)
    lin_1 = _train_walkforward_stopping_models(st_d1, st_x1, st_y1)
    e3_cfg = OptimalExitConfig(use_e3_optimal_stopping=True)
    e3_m0, e3_n0 = _simulate_exit_phase(p2_0, sigs_13, accel_13, sigs_metals, cov_h_by_ts, atr_1d_pct, daily_breadth, sc11_0, lin_0, stats_0, e3_cfg)
    e3_m1, e3_n1 = _simulate_exit_phase(p2_1, sigs_13, accel_13, sigs_metals, cov_h_by_ts, atr_1d_pct, daily_breadth, sc11_1, lin_1, stats_1, e3_cfg)
    e3_tn = {d: 0.5 * (e3_n0[d] + e3_n1[d]) for d in sorted(set(e3_n0) & set(e3_n1))}
    e3_rets = _daily_returns_map(e3_tn)

    # Part 1: Nonlinear Bellman Stopping V2 + 1d Slow Bellman
    nl_0 = _train_wf_nonlinear_bellman(st_d0, st_x0, st_y0)
    nl_1 = _train_wf_nonlinear_bellman(st_d1, st_x1, st_y1)
    slow_bm = _train_slow_core_bellman_models(panel_1d, sigs_13, accel_13, atr_1d_pct, daily_breadth)

    portfolio_arms: list[dict] = [_summarize_twin_run("E3_V1_RIDGE_REF", e3_m0, e3_n0, e3_m1, e3_n1, v2_rets, e3_rets)]
    for lbl, use_slow in (("E3_V2_NONLINEAR_BELLMAN", False), ("E3_V2_PLUS_SLOW_1D_BELLMAN", True)):
        m0, n0 = _simulate_upgraded_bellman_phase(p2_0, sigs_13, accel_13, sigs_metals, cov_h_by_ts, atr_1d_pct, daily_breadth, sc11_0, nl_0, slow_bm, stats_0, use_slow_bellman=use_slow)
        m1, n1 = _simulate_upgraded_bellman_phase(p2_1, sigs_13, accel_13, sigs_metals, cov_h_by_ts, atr_1d_pct, daily_breadth, sc11_1, nl_1, slow_bm, stats_1, use_slow_bellman=use_slow)
        portfolio_arms.append(_summarize_twin_run(lbl, m0, n0, m1, n1, v2_rets, e3_rets))

    # Part 2: Defeated Entry Families — Static Exit vs. Dedicated Bellman Optimal Closing
    resurrection_rows: list[dict] = []
    resurrected_assets: dict[str, tuple] = {}
    for fam, direction in (("flush_rebound", 1), ("breakdown_short", -1), ("early_ignition_z15", 1)):
        tr0, fd0, fx0, fy0 = _extract_resurrection_triggers_and_bellman_data(p2_0, daily_breadth, fam)
        tr1, fd1, fx1, fy1 = _extract_resurrection_triggers_and_bellman_data(p2_1, daily_breadth, fam)
        bm0 = _train_wf_nonlinear_bellman(fd0, fx0, fy0)
        bm1 = _train_wf_nonlinear_bellman(fd1, fx1, fy1)
        s0_st, sn0_st = _simulate_standalone_family(p2_0, tr0, bm0, stats_0, use_bellman_exit=False, direction=direction)
        s1_st, sn1_st = _simulate_standalone_family(p2_1, tr1, bm1, stats_1, use_bellman_exit=False, direction=direction)
        s0_bm, sn0_bm = _simulate_standalone_family(p2_0, tr0, bm0, stats_0, use_bellman_exit=True, direction=direction)
        s1_bm, sn1_bm = _simulate_standalone_family(p2_1, tr1, bm1, stats_1, use_bellman_exit=True, direction=direction)
        tn_st = {d: 0.5 * (sn0_st[d] + sn1_st[d]) for d in sorted(set(sn0_st) & set(sn1_st))}
        tn_bm = {d: 0.5 * (sn0_bm[d] + sn1_bm[d]) for d in sorted(set(sn0_bm) & set(sn1_bm))}
        fm_st, fm_bm = _portfolio_metrics(tn_st), _portfolio_metrics(tn_bm)
        stress_iso = STRESS_REPLAY_START.date().isoformat()
        sm_st = _portfolio_metrics({d: v for d, v in tn_st.items() if d >= stress_iso})
        sm_bm = _portfolio_metrics({d: v for d, v in tn_bm.items() if d >= stress_iso})
        resurrected = fm_bm["ann_sharpe"] > 0.25 and fm_bm["ret_pct"] > 5.0 and (s0_bm["liqs"] + s1_bm["liqs"]) == 0
        resurrection_rows.append({
            "family": fam,
            "static_exit": {
                "ending_nav": fm_st["ending_nav"], "ret_pct": fm_st["ret_pct"],
                "stress_ret_pct": sm_st["ret_pct"], "ann_sharpe": fm_st["ann_sharpe"],
                "max_dd_pct": fm_st["max_dd_pct"], "liqs": s0_st["liqs"] + s1_st["liqs"],
                "giveback_bps": round(0.5 * (s0_st["eff"]["avg_giveback_bps"] + s1_st["eff"]["avg_giveback_bps"]), 1),
            },
            "bellman_exit": {
                "ending_nav": fm_bm["ending_nav"], "ret_pct": fm_bm["ret_pct"],
                "stress_ret_pct": sm_bm["ret_pct"], "ann_sharpe": fm_bm["ann_sharpe"],
                "max_dd_pct": fm_bm["max_dd_pct"], "liqs": s0_bm["liqs"] + s1_bm["liqs"],
                "bellman_exits_avg": round(0.5 * (s0_bm["bellman_exits"] + s1_bm["bellman_exits"]), 1),
                "giveback_bps": round(0.5 * (s0_bm["eff"]["avg_giveback_bps"] + s1_bm["eff"]["avg_giveback_bps"]), 1),
                "pre_eod_pct": round(0.5 * (s0_bm["eff"]["pre_eod_zero_borrow_pct"] + s1_bm["eff"]["pre_eod_zero_borrow_pct"]), 1),
            },
            "sharpe_delta": round(fm_bm["ann_sharpe"] - fm_st["ann_sharpe"], 3),
            "ret_delta_pct": round(fm_bm["ret_pct"] - fm_st["ret_pct"], 2),
            "resurrected": resurrected,
        })
        resurrected_assets[fam] = (tr0, tr1, bm0, bm1, resurrected)

    # Part 3: Portfolio Integration of every candidate (always test each family integrated with E3_V2!)
    for fam, (tr0, tr1, bm0, bm1, is_res) in resurrected_assets.items():
        if not is_res and fam != "early_ignition_z15":
            # Still test breakdown_short if it produced positive bear stress!
            row = next(r for r in resurrection_rows if r["family"] == fam)
            if row["bellman_exit"]["stress_ret_pct"] <= 3.0:
                continue
        m0, n0 = _simulate_upgraded_bellman_phase(p2_0, sigs_13, accel_13, sigs_metals, cov_h_by_ts, atr_1d_pct, daily_breadth, sc11_0, nl_0, slow_bm, stats_0, use_slow_bellman=False, extra_triggers=tr0, extra_models=bm0)
        m1, n1 = _simulate_upgraded_bellman_phase(p2_1, sigs_13, accel_13, sigs_metals, cov_h_by_ts, atr_1d_pct, daily_breadth, sc11_1, nl_1, slow_bm, stats_1, use_slow_bellman=False, extra_triggers=tr1, extra_models=bm1)
        portfolio_arms.append(_summarize_twin_run(f"E3_V2_PLUS_{fam.upper()}", m0, n0, m1, n1, v2_rets, e3_rets))

    best_arm = max(portfolio_arms, key=lambda r: (r["liquidations_sum"] == 0, r["ann_sharpe"]))
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "v2_reference": {
            "label": "V2_CHAMPION_60_40_NBX16_REF",
            "full": _portfolio_metrics(v2_nav),
            "stress": _portfolio_metrics({k: v for k, v in v2_nav.items() if k >= stress_iso}),
        },
        "part1_and_3_portfolio_arms": portfolio_arms,
        "part2_resurrection_ablation": resurrection_rows,
        "best_arm": best_arm,
    }
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if report_md is not None:
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text(_render_resurrection_md(payload), encoding="utf-8")
    return payload


def _render_resurrection_md(p: dict) -> str:
    v2 = p["v2_reference"]
    best = p["best_arm"]
    lines = [
        "# Bellman Optimal-Stopping V2 & Defeated-Strategy Resurrection Study",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`PAPER_ONLY`)",
        f"- **Frozen v2 Reference:** NAV `${v2['full']['ending_nav']:.2f}` (`{v2['full']['ret_pct']:+.2f}%`), Bear `{v2['stress']['ret_pct']:+.2f}%`, Sharpe `{v2['full']['ann_sharpe']:.3f}`, MaxDD `{v2['full']['max_dd_pct']:.2f}%`",
        f"- **New Standing Best Arm:** `{best['label']}` — NAV `${best['ending_nav']:.2f}` (`{best['ret_pct']:+.2f}%`), Bear `{best['stress_ret_pct']:+.2f}%`, Sharpe `{best['ann_sharpe']:.3f}` (`0h={best['sharpe_0h']:.3f}`/`1h={best['sharpe_1h']:.3f}`), MaxDD `{best['max_dd_pct']:.2f}%`, Liqs `{best['liquidations_sum']}`",
        "",
        "## Part 1 & 3 — Bellman V2 Upgrades & Unified Portfolio Integration (`1,085d`, Twin `0h + 1h`)",
        "",
        "| Arm | Ending NAV | Full Ret | Bear Stress | Sharpe (`0h`/`1h`) | MaxDD | Liqs | Borrow / Pool ($) | ML-Exit / Pyr / SlowBM / Extra | vs E3v1 / vs v2 (bps/d) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for r in p["part1_and_3_portfolio_arms"]:
        bp = f"${r['borrow_usdt_avg']:.2f} / +${r['pool_yield_usdt_avg']:.2f}"
        ops = f"{r['ml_exits_avg']:.0f} / {r['pyramids_avg']:.0f} / {r['slow_bellman_exits_avg']:.0f} / {r['extra_entries_avg']:.0f}"
        lines.append(
            f"| `{r['label']}` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` "
            f"| `{r['ann_sharpe']:.3f}` (`{r['sharpe_0h']:.3f}`/`{r['sharpe_1h']:.3f}`) | `{r['max_dd_pct']:.2f}%` "
            f"| `{r['liquidations_sum']}` | `{bp}` | `{ops}` | `{r['vs_e3v1_bps']:+.2f}` / `{r['vs_v2_bps']:+.2f}` |"
        )
    lines += [
        "",
        "## Part 2 — Previously Defeated Entry Families: Static Exit vs. Bellman Optimal Closing (`2024-09..2026-11` OOS)",
        "",
        "| Defeated Family | Static Ret / Bear / Sharpe / DD | Bellman Ret / Bear / Sharpe / DD | Sharpe Delta | Giveback (Static → Bellman) | Pre-EOD 0% Brw | Resurrected? |",
        "| --- | --- | --- | ---: | --- | ---: | --- |",
    ]
    for r in p["part2_resurrection_ablation"]:
        st, bm = r["static_exit"], r["bellman_exit"]
        s_str = f"`{st['ret_pct']:+.1f}%` / `{st['stress_ret_pct']:+.1f}%` / `{st['ann_sharpe']:.3f}` / `{st['max_dd_pct']:.1f}%`"
        b_str = f"`{bm['ret_pct']:+.1f}%` / `{bm['stress_ret_pct']:+.1f}%` / `{bm['ann_sharpe']:.3f}` / `{bm['max_dd_pct']:.1f}%`"
        lines.append(
            f"| `{r['family']}` | {s_str} | {b_str} | `{r['sharpe_delta']:+.3f}` "
            f"| `{st['giveback_bps']:.0f} → {bm['giveback_bps']:.0f} bps` | `{bm['pre_eod_pct']:.1f}%` "
            f"| `{'YES' if r['resurrected'] else 'NO'}` |"
        )
    lines.append("")
    return "\n".join(lines)
