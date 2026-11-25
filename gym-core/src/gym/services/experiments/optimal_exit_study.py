"""Head-to-head strictly causal evaluation of Optimal Position-Closing Mechanisms (E1-E4).

Benchmarks each exit upgrade individually and combined on top of our standing record champion
WINNERS_ONLY_F1_F2CLOCK_F4_5X (Sharpe 0.952, +38.50%, 0 liqs) and frozen V2_CHAMPION (Sharpe 0.849),
measuring both portfolio metrics AND per-trade MFE Capture Ratio, giveback bps, and pre-EOD exits.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

import numpy as np

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
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
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from ...domain.venue_leverage_models import simulate_nobitex_margin_ignition
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


def _daily_atr_pct_map(panel_1d: dict[str, list[BarPoint]], window: int = 14) -> dict[str, dict[datetime, float]]:
    out: dict[str, dict[datetime, float]] = {}
    for sym, bars in panel_1d.items():
        m: dict[datetime, float] = {}
        trs: list[float] = []
        for i in range(1, len(bars)):
            pc = bars[i - 1].close
            if pc <= 0:
                continue
            tr = max(bars[i].high - bars[i].low, abs(bars[i].high - pc), abs(bars[i].low - pc)) / pc
            trs.append(tr)
            if len(trs) >= window:
                m[bars[i].ts_avail] = sum(trs[-window:]) / window
        out[sym] = m
    return out


def _extract_optimal_stopping_dataset(
    panel_2h: dict[str, list[BarPoint]],
    gru_scores: dict[tuple[datetime, str], float],
) -> tuple[list[datetime], np.ndarray, np.ndarray]:
    """Build strictly causal 10-feature optimal-stopping training dataset (E[Wait vs ExitNow] in bps)."""
    btc_bars = panel_2h.get("BTCUSDT", [])
    btc_ret = {
        btc_bars[i].ts_avail: (btc_bars[i].close - btc_bars[i - 1].close) / btc_bars[i - 1].close
        for i in range(1, len(btc_bars))
        if btc_bars[i - 1].close > 0
    }
    dts: list[datetime] = []
    xs: list[list[float]] = []
    ys: list[float] = []

    for sym, bars in panel_2h.items():
        if sym not in IGNITION_18_CRYPTO or len(bars) < 65:
            continue
        rets = [0.0] + [
            (bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0
            for i in range(1, len(bars))
        ]
        vols = [b.volume for b in bars]
        for i in range(40, len(bars) - 18):
            g_sc = gru_scores.get((bars[i].ts_avail, sym))
            if g_sc is None or g_sc <= 0.001:
                continue
            entry_px = bars[i + 1].open
            if entry_px <= 0:
                continue
            pr = rets[i - 36 : i]
            b_vol = max(0.005, math.sqrt(sum((r - sum(pr) / 36.0) ** 2 for r in pr) / 35.0))
            mv = max(1e-9, median(vols[i - 36 : i]))
            peak = entry_px
            for k in range(1, 11):
                idx = i + k
                if idx + 5 >= len(bars):
                    break
                cur = bars[idx]
                peak = max(peak, cur.close)
                upnl = (cur.close - entry_px) / entry_px
                mfe = max(0.0, (peak - entry_px) / entry_px)
                gb_ratio = (mfe - upnl) / max(mfe, 1e-4) if mfe > 1e-4 else 0.0
                span = max(cur.high - cur.low, 1e-9)
                wick = max(0.0, cur.high - cur.close) / span
                hrs_eod = 24.0 - (cur.ts_avail.hour + cur.ts_avail.minute / 60.0)
                st = OptimalStoppingState(
                    age_bars=k, unrealized_ret=upnl, peak_mfe=mfe, giveback_ratio=gb_ratio,
                    upper_wick_ratio=wick, volume_ratio=cur.volume / mv,
                    bar_ret_z=rets[idx] / b_vol, rel_btc_ret=rets[idx] - btc_ret.get(cur.ts_avail, 0.0),
                    hours_to_utc_eod=hrs_eod, entry_gru_score=g_sc,
                )
                # Optimal-stopping Bellman target: realistic path return over next 4 bars (8h) minus carry & adverse penalty
                now_px = bars[idx + 1].open
                if now_px <= 0:
                    continue
                stop_px = peak * (1.0 - 2.0 * b_vol)
                fut_exit_px = bars[idx + 4].open
                for f_step in range(idx + 1, idx + 4):
                    if bars[f_step].low <= stop_px:
                        fut_exit_px = min(bars[f_step].open, stop_px)
                        break
                wait_bps = ((fut_exit_px - now_px) / now_px) * 10_000.0
                dts.append(cur.ts_avail)
                xs.append(st.to_vector())
                ys.append(max(-800.0, min(800.0, wait_bps)))

    if not xs:
        return [], np.zeros((0, 10)), np.zeros((0,))
    return dts, np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)


def _train_walkforward_stopping_models(
    dts: list[datetime],
    x_mat: np.ndarray,
    y_vec: np.ndarray,
) -> list[tuple[datetime, datetime, OptimalStoppingModel]]:
    folds = [
        (datetime(2024, 9, 1, tzinfo=UTC), datetime(2025, 4, 1, tzinfo=UTC)),
        (datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 11, 24, tzinfo=UTC)),
        (datetime(2025, 11, 24, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    ]
    purge = timedelta(hours=48)
    out = []
    for s, e in folds:
        tr = [k for k, dt in enumerate(dts) if dt < s - purge]
        m = OptimalStoppingModel(l2_alpha=40.0)
        if len(tr) >= 50:
            m.fit(x_mat[tr], y_vec[tr])
        out.append((s, e, m))
    return out


def _get_stopping_model(
    ts: datetime,
    models: list[tuple[datetime, datetime, OptimalStoppingModel]],
) -> OptimalStoppingModel | None:
    for s, e, m in models:
        if s <= ts < e:
            return m
    return None


def _record_closed_trade(
    trades_log: list[ClosedTradeCapture],
    lot,
    exit_px: float,
    ts: datetime,
    reason: str,
) -> None:
    if lot.entry_price <= 0:
        return
    real_bps = lot.direction * ((exit_px / lot.entry_price) - 1.0) * 10_000.0
    if lot.direction > 0:
        mfe_bps = max(0.0, ((lot.peak_price / lot.entry_price) - 1.0) * 10_000.0)
    else:
        mfe_bps = max(0.0, ((lot.entry_price - lot.peak_price) / lot.entry_price) * 10_000.0)
    held_h = max(2.0, (ts - lot.entry_ts).total_seconds() / 3600.0)
    closed_pre_eod = lot.entry_ts.date() == ts.date()
    trades_log.append(
        ClosedTradeCapture(
            realized_ret_bps=real_bps,
            peak_mfe_bps=mfe_bps,
            giveback_bps=max(0.0, mfe_bps - real_bps),
            held_hours=held_h,
            exit_reason=reason,
            closed_before_eod_borrow=closed_pre_eod,
        )
    )


def _manage_fast_optimal_exits(
    book: MultiHorizonBook,
    by_avail: dict[str, dict[datetime, BarPoint]],
    exec_px: dict[str, float],
    tradable: set[str],
    ts: datetime,
    bret_map: dict[str, dict[datetime, float]],
    vrat_map: dict[str, dict[datetime, float]],
    stop_model: OptimalStoppingModel | None,
    trimmed_lots: set[tuple[str, str]],
    trades_log: list[ClosedTradeCapture],
    cfg: OptimalExitConfig,
) -> None:
    """Apply E1 (Chandelier Ratchet + Pre-EOD Dead-Money), E2 (Climax Maker Trim), and E3 (Optimal Stopping)."""
    btc_r = bret_map.get("BTCUSDT", {}).get(ts, 0.0)
    taker_bps = tehran_execution_cost_bps(ts.hour)
    hours_to_eod = 24.0 - (ts.hour + ts.minute / 60.0)

    for key in list(book.lots):
        lot = book.lots[key]
        if lot.thesis_id != "ignition_2h":
            continue
        lot.age_bars += 1
        bar = by_avail.get(lot.symbol, {}).get(ts)
        if bar is not None:
            evt, px, fee_bps = check_lot_intrabar_exit(
                lot, bar, taker_exit_bps=taker_bps, oco_maker_exit_bps=cfg.maker_trim_fee_bps,
                use_oco_maker_tp=False,
            )
            if evt == "LIQ":
                _record_closed_trade(trades_log, lot, px, ts, "LIQ")
                book.liquidations += 1
                del book.lots[key]
                trimmed_lots.discard(key)
                continue
            if evt == "STOP":
                _record_closed_trade(trades_log, lot, px, ts, "RATCHET_STOP" if cfg.use_e1_ratchet else "HARD_STOP")
                book.close_lot(key, px, fee_bps)
                book.stop_outs += 1
                trimmed_lots.discard(key)
                continue
            lot.peak_price = max(lot.peak_price, bar.close)

        if lot.symbol not in tradable or lot.symbol not in exec_px or bar is None:
            continue
        px_now = exec_px[lot.symbol]

        # E1: Update nonlinear Chandelier Ratchet stop & check dead-money pre-EOD exit
        if cfg.use_e1_ratchet:
            lot.stop_price = compute_ratchet_stop_price(lot, cur_close=bar.close, cfg=cfg)
            if is_dead_money_pre_eod(lot, hours_to_utc_eod=hours_to_eod, cfg=cfg):
                _record_closed_trade(trades_log, lot, px_now, ts, "DEAD_MONEY_PRE_EOD")
                book.close_lot(key, px_now, taker_bps)
                trimmed_lots.discard(key)
                continue

        # Standard close trail or timeout (runners with E1 or pyramid get up to 24 bars = 48h!)
        trail_mult = 2.6 if not cfg.use_e1_ratchet else 2.2
        trail_hit = bar.close < lot.peak_price * (1.0 - trail_mult * lot.entry_bar_vol)
        max_bars = 24 if (lot.pyramided or key in trimmed_lots) else (16 if cfg.use_e1_ratchet else 12)
        if lot.age_bars >= max_bars or trail_hit:
            _record_closed_trade(trades_log, lot, px_now, ts, "TRAIL" if trail_hit else "TIMEOUT")
            book.close_lot(key, px_now, taker_bps)
            trimmed_lots.discard(key)
            continue

        # E2: Parabolic Climax / Upper-Wick Exhaustion -> 50% passive maker scale-out into strength!
        vol_r = vrat_map.get(lot.symbol, {}).get(ts, 1.0)
        if cfg.use_e2_climax_trim and key not in trimmed_lots and detect_climax_exhaustion(lot, bar, vol_r, cfg):
            trim_lot_fraction(book, key, 0.50, px_now, cfg.maker_trim_fee_bps)
            trimmed_lots.add(key)
            book.oco_profit_exits += 1
            # Tighten stop on remaining 50% runner to lock gain
            lot.stop_price = max(lot.stop_price, bar.low, lot.entry_price * 1.005)
            continue

        # E3: Optimal-Stopping Bellman E[Hold] vs Exit Now
        if cfg.use_e3_optimal_stopping and stop_model is not None:
            upnl = (bar.close - lot.entry_price) / max(lot.entry_price, 1e-9)
            mfe = max(0.0, (lot.peak_price - lot.entry_price) / max(lot.entry_price, 1e-9))
            gb_ratio = (mfe - upnl) / max(mfe, 1e-4) if mfe > 1e-4 else 0.0
            span = max(bar.high - bar.low, 1e-9)
            wick = max(0.0, bar.high - bar.close) / span
            st = OptimalStoppingState(
                age_bars=lot.age_bars, unrealized_ret=upnl, peak_mfe=mfe, giveback_ratio=gb_ratio,
                upper_wick_ratio=wick, volume_ratio=vol_r,
                bar_ret_z=bret_map.get(lot.symbol, {}).get(ts, 0.0) / max(lot.entry_bar_vol, 1e-4),
                rel_btc_ret=bret_map.get(lot.symbol, {}).get(ts, 0.0) - btc_r,
                hours_to_utc_eod=hours_to_eod, entry_gru_score=lot.entry_gru_score,
            )
            pred_wait = stop_model.predict_wait_value_bps(st)
            act = decide_optimal_stopping_action(
                pred_wait, st, already_pyramided=lot.pyramided,
                already_trimmed=(key in trimmed_lots), cfg=cfg,
            )
            if act == "OPTIMAL_EXIT":
                _record_closed_trade(trades_log, lot, px_now, ts, "OPTIMAL_ML_EXIT")
                book.close_lot(key, px_now, taker_bps)
                book.early_ml_exits += 1
                trimmed_lots.discard(key)
            elif act == "OPTIMAL_TRIM_50":
                trim_lot_fraction(book, key, 0.50, px_now, cfg.maker_trim_fee_bps)
                trimmed_lots.add(key)
                book.oco_profit_exits += 1
                lot.stop_price = max(lot.stop_price, lot.entry_price * 1.004)
            elif act == "FREE_ROLL_PYRAMID":
                book.pyramid_lot_on_house_money(key, px_now, add_fraction=0.45, entry_fee_bps=taker_bps)


def _apply_slow_peak_protection(
    book: MultiHorizonBook,
    exec_px: dict[str, float],
    tradable: set[str],
    atr_1d_pct: dict[str, dict[datetime, float]],
    cur_sig_ts: datetime | None,
    breadth_now: float,
    trimmed_lots: set[tuple[str, str]],
    exit_cfg: OptimalExitConfig,
) -> int:
    """Apply E4 active peak-protection trims across open 1d slow Spot lots."""
    if not exit_cfg.use_e4_slow_peak_protect:
        return 0
    trims = 0
    for key in list(book.lots):
        lot = book.lots[key]
        if lot.thesis_id != "slow_core" or lot.symbol not in tradable or lot.symbol not in exec_px:
            continue
        px = exec_px[lot.symbol]
        lot.peak_price = max(lot.peak_price, px)
        atr_p = atr_1d_pct.get(lot.symbol, {}).get(cur_sig_ts, 0.04) if cur_sig_ts else 0.04
        act_s, frac = evaluate_slow_core_peak_protection(
            lot, px, atr_p, breadth_now, already_trimmed=(key in trimmed_lots), cfg=exit_cfg,
        )
        if act_s == "TRIM_50" and frac > 0:
            trim_lot_fraction(book, key, frac, px, exit_cfg.maker_trim_fee_bps)
            trimmed_lots.add(key)
            trims += 1
    return trims


def _open_fast_exit_study_entries(
    book: MultiHorizonBook,
    ts: datetime,
    equity: float,
    dd_pct: float,
    exec_px: dict[str, float],
    tradable: set[str],
    gru_scores: dict[tuple[datetime, str], float],
    recent_gru: list[float],
    bvol_map: dict[str, dict[datetime, float]],
    offers_by_sym: dict,
    r_cfg: ResolverConfig,
) -> None:
    """Identical fast 2h GRU-Ignition entry rule shared across all exit arms (isolates exit alpha)."""
    active_ign = sum(1 for k in book.lots if k[1] == "ignition_2h")
    if active_ign >= 3 or book.free_cash < 40.0:
        return
    for sym in IGNITION_18_CRYPTO:
        if active_ign >= 3 or sym not in tradable or (sym, "ignition_2h") in book.lots:
            continue
        g_sc = gru_scores.get((ts, sym))
        if g_sc is None:
            continue
        rank = (
            sum(1 for x in recent_gru if x <= g_sc) / len(recent_gru)
            if len(recent_gru) >= 25
            else 0.55
        )
        recent_gru.append(g_sc)
        if len(recent_gru) > 120:
            del recent_gru[:-120]
        if g_sc <= 0.002 or rank < 0.45:
            continue
        b_vol = bvol_map.get(sym, {}).get(ts, 0.02)
        stop_bps = max(180.0, min(650.0, 2.5 * b_vol * 10_000.0))
        nbx_long = [o for o in offers_by_sym[sym] if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == 1]
        offer = nbx_long[0] if nbx_long else offers_by_sym[sym][0]
        lev = resolve_safe_ignition_leverage(offer, stop_bps, rank, dd_pct, r_cfg)
        stop_frac = max(0.015, (stop_bps + 35.0) / 10_000.0)
        tgt_col = min(0.16 * equity, (0.014 * equity / stop_frac) / lev, max(0.0, book.free_cash - 10.0))
        if book.open_fast_margin_lot(
            symbol=sym, thesis_id="ignition_2h", direction=1, leverage=lev,
            target_collateral=tgt_col, entry_px=exec_px[sym], stop_bps=stop_bps,
            take_profit_bps=0.0, offer=offer, ts=ts, entry_bar_vol=b_vol, entry_gru_score=g_sc,
        ):
            active_ign += 1


def _simulate_exit_phase(
    panel_2h: dict[str, list[BarPoint]],
    sigs_13: dict,
    accel_13: dict,
    sigs_metals: dict,
    cov_h_by_ts: dict,
    atr_1d_pct: dict[str, dict[datetime, float]],
    daily_breadth: dict[str, float],
    gru_scores: dict[tuple[datetime, str], float],
    stop_models: list[tuple[datetime, datetime, OptimalStoppingModel]],
    bar_stats: tuple,
    exit_cfg: OptimalExitConfig,
) -> tuple[dict, dict[str, float]]:
    """Run one phase (0h or 1h) with identical entries (F1+F2 Tehran Clock) and pluggable exit engine."""
    bvol_map, _, vrat_map, bret_map = bar_stats
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    all_ts = sorted({t for s in IGNITION_18_CRYPTO for t in by_avail[s]})

    offers_by_sym = {s: build_local_venue_offers(s, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in ADAPTIVE_UNIVERSE}
    r_cfg = ResolverConfig(max_venue_leverage=5.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR)

    book = MultiHorizonBook(free_cash=1000.0)
    pending_slow_targets: dict[str, float] | None = None
    last_px: dict[str, float] = {}
    recent_gru: list[float] = []
    trimmed_lots: set[tuple[str, str]] = set()
    trades_log: list[ClosedTradeCapture] = []
    slow_peak_trims = 0
    peak_nav = 1000.0
    nav_by_date: dict[str, float] = {}

    sig_dates = sorted(sigs_13)
    sig_ptr = 0
    last_sig_applied: datetime | None = None

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, 2.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR, eod_borrow_bps=5.0)
        exec_px: dict[str, float] = {}
        tradable: set[str] = set()
        for sym in ADAPTIVE_UNIVERSE:
            nxt, cur = by_start[sym].get(ts), by_avail[sym].get(ts)
            if nxt is not None and nxt.open > 0:
                exec_px[sym] = nxt.open
                last_px[sym] = nxt.open
                if cur is not None and cur.entry_eligible:
                    tradable.add(sym)
            elif cur is not None and cur.close > 0:
                exec_px[sym] = cur.close
                last_px[sym] = cur.close
            elif sym in last_px:
                exec_px[sym] = last_px[sym]

        _manage_fast_optimal_exits(
            book, by_avail, exec_px, tradable, ts, bret_map, vrat_map,
            _get_stopping_model(ts, stop_models), trimmed_lots, trades_log, exit_cfg,
        )

        while sig_ptr + 1 < len(sig_dates) and sig_dates[sig_ptr + 1] <= ts:
            sig_ptr += 1
        cur_sig_ts = sig_dates[sig_ptr] if (sig_dates and sig_dates[sig_ptr] <= ts) else None
        slow_peak_trims += _apply_slow_peak_protection(
            book, exec_px, tradable, atr_1d_pct, cur_sig_ts,
            daily_breadth.get(ts.date().isoformat(), 0.5), trimmed_lots, exit_cfg,
        )

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
            slow_fee = tehran_execution_cost_bps(10, use_passive_maker=True)
            pending_slow_targets = _solve_slow_targets_for_day(
                active_slow, sigs_13[cur_sig_ts], accel_13.get(cur_sig_ts, {}), cur_slow_w, cov_h,
                sigs_metals.get(cur_sig_ts, {}), exec_px, 0.08, slow_fee,
            )

        if pending_slow_targets is not None and ts.hour >= 10:
            slow_exec_fee = tehran_execution_cost_bps(ts.hour, use_passive_maker=True)
            for s in list(pending_slow_targets):
                if pending_slow_targets[s] < 0.01:
                    trimmed_lots.discard((s, "slow_core"))
            book.rebalance_slow_spot_targets(pending_slow_targets, exec_px, tradable, ts, leg_fee_bps=slow_exec_fee)
            pending_slow_targets = None

        _open_fast_exit_study_entries(
            book, ts, equity, dd_pct, exec_px, tradable, gru_scores, recent_gru, bvol_map, offers_by_sym, r_cfg,
        )
        nav_by_date[ts.date().isoformat()] = book.mark_equity(exec_px)

    eff = summarize_exit_efficiency(trades_log)
    return {
        "fees": round(book.total_fees, 2),
        "borrow": round(book.total_borrow, 2),
        "pool_yield": round(book.total_pool_yield, 2),
        "liqs": book.liquidations,
        "climax_or_opt_trims": book.oco_profit_exits,
        "early_ml_exits": book.early_ml_exits,
        "pyramids": book.pyramids,
        "slow_peak_trims": slow_peak_trims,
        "max_lev": round(book.max_leverage_used, 2),
        "exit_efficiency": eff,
    }, nav_by_date


def run_optimal_exit_study(
    db_path: Path,
    *,
    report_md: Path | None = None,
    report_json: Path | None = None,
) -> dict:
    """Run controlled head-to-head optimal-closing ablation study (E0 baseline vs E1..E4 & combinations)."""
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

    d0, s0, x0, yb0, yp0 = _extract_11feat_coiled_spring_dataset(p2_0, IGNITION_18_CRYPTO, daily_breadth)
    d1, s1, x1, yb1, yp1 = _extract_11feat_coiled_spring_dataset(p2_1, IGNITION_18_CRYPTO, daily_breadth)
    sc11_0, _, _ = _walkforward_gru_scores(d0, s0, x0, yp0, yb0, task="regression")
    sc11_1, _, _ = _walkforward_gru_scores(d1, s1, x1, yp1, yb1, task="regression")

    st_d0, st_x0, st_y0 = _extract_optimal_stopping_dataset(p2_0, sc11_0)
    st_d1, st_x1, st_y1 = _extract_optimal_stopping_dataset(p2_1, sc11_1)
    stop_0 = _train_walkforward_stopping_models(st_d0, st_x0, st_y0)
    stop_1 = _train_walkforward_stopping_models(st_d1, st_x1, st_y1)
    stats_0 = _compute_2h_bar_stats(p2_0)
    stats_1 = _compute_2h_bar_stats(p2_1)

    # Benchmark V2_CHAMPION
    _, _, sch0 = simulate_nobitex_margin_ignition(
        p2_0, IGNITION_18_CRYPTO, daily_breadth, sc11_0,
        label="V2_IGN_0H", offset_hours=0, score_is_return=True, base_prob=0.46,
        top_tercile_leverage=1.5, leg_cost=0.0016, borrow_mode="eod_utc", borrow_rate=0.0005,
    )
    _, _, sch1 = simulate_nobitex_margin_ignition(
        p2_1, IGNITION_18_CRYPTO, daily_breadth, sc11_1,
        label="V2_IGN_1H", offset_hours=1, score_is_return=True, base_prob=0.46,
        top_tercile_leverage=1.5, leg_cost=0.0016, borrow_mode="eod_utc", borrow_rate=0.0005,
    )
    v2_run = _run_v2_joint_shared_ledger(
        panel_1h, ADAPTIVE_UNIVERSE, sigs_13, accel_13, sigs_metals, cov_h_by_ts,
        _merge_twin_schedules(sch0, sch1), slow_budget=0.60, ign_budget=0.40,
        fee_rate=Decimal("0.0016"), use_metals_reserve=True,
    )
    v2_nav = v2_run["nav_by_date"]
    v2_rets = _daily_returns_map(v2_nav)
    stress_iso = STRESS_REPLAY_START.date().isoformat()

    configs: tuple[tuple[str, OptimalExitConfig], ...] = (
        ("E0_BASELINE_STATIC_EXIT", OptimalExitConfig()),
        ("E1_MFE_RATCHET_PRE_EOD", OptimalExitConfig(use_e1_ratchet=True)),
        ("E2_CLIMAX_MAKER_TRIM", OptimalExitConfig(use_e2_climax_trim=True)),
        ("E3_OPTIMAL_STOPPING_ML", OptimalExitConfig(use_e3_optimal_stopping=True)),
        ("E4_SLOW_CORE_PEAK_PROTECT", OptimalExitConfig(use_e4_slow_peak_protect=True)),
        ("E1_E2_RATCHET_PLUS_CLIMAX", OptimalExitConfig(use_e1_ratchet=True, use_e2_climax_trim=True)),
        ("E1_E2_E3_FAST_OPTIMAL_STACK", OptimalExitConfig(use_e1_ratchet=True, use_e2_climax_trim=True, use_e3_optimal_stopping=True)),
        ("E1_TO_E4_FULL_OPTIMAL_CLOSER", OptimalExitConfig(use_e1_ratchet=True, use_e2_climax_trim=True, use_e3_optimal_stopping=True, use_e4_slow_peak_protect=True)),
    )

    arm_rows: list[dict] = []
    e0_rets: dict[str, float] = {}
    for label, ecfg in configs:
        m0, n0 = _simulate_exit_phase(p2_0, sigs_13, accel_13, sigs_metals, cov_h_by_ts, atr_1d_pct, daily_breadth, sc11_0, stop_0, stats_0, ecfg)
        m1, n1 = _simulate_exit_phase(p2_1, sigs_13, accel_13, sigs_metals, cov_h_by_ts, atr_1d_pct, daily_breadth, sc11_1, stop_1, stats_1, ecfg)
        shared = sorted(set(n0) & set(n1))
        tn = {d: 0.5 * (n0[d] + n1[d]) for d in shared}
        fm = _portfolio_metrics(tn)
        sm = _portfolio_metrics({d: v for d, v in tn.items() if d >= stress_iso})
        s0_m = _portfolio_metrics(n0)
        s1_m = _portfolio_metrics(n1)
        tn_rets = _daily_returns_map(tn)
        if label == "E0_BASELINE_STATIC_EXIT":
            e0_rets = tn_rets
        up_v2 = paired_baseline_uplift(tn_rets, v2_rets, simulations=499, seed=42)
        ci_v2 = up_v2.get("ci_95") or (0.0, 0.0)
        up_e0 = paired_baseline_uplift(tn_rets, e0_rets, simulations=499, seed=42) if e0_rets else {"mean_uplift": 0.0, "ci_95": (0.0, 0.0)}
        ef0, ef1 = m0["exit_efficiency"], m1["exit_efficiency"]
        arm_rows.append({
            "label": label,
            "days": len(tn),
            "ending_nav": fm["ending_nav"],
            "ret_pct": fm["ret_pct"],
            "stress_ret_pct": sm["ret_pct"],
            "ann_sharpe": fm["ann_sharpe"],
            "max_dd_pct": fm["max_dd_pct"],
            "sharpe_0h": s0_m["ann_sharpe"],
            "sharpe_1h": s1_m["ann_sharpe"],
            "liquidations_sum": m0["liqs"] + m1["liqs"],
            "fees_usdt_avg": round(0.5 * (m0["fees"] + m1["fees"]), 2),
            "borrow_usdt_avg": round(0.5 * (m0["borrow"] + m1["borrow"]), 2),
            "pool_yield_usdt_avg": round(0.5 * (m0["pool_yield"] + m1["pool_yield"]), 2),
            "mfe_capture_ratio": round(0.5 * (ef0["mfe_capture_ratio"] + ef1["mfe_capture_ratio"]), 3),
            "avg_realized_bps": round(0.5 * (ef0["avg_realized_bps"] + ef1["avg_realized_bps"]), 1),
            "avg_giveback_bps": round(0.5 * (ef0["avg_giveback_bps"] + ef1["avg_giveback_bps"]), 1),
            "win_rate_pct": round(0.5 * (ef0["win_rate_pct"] + ef1["win_rate_pct"]), 1),
            "profit_factor": round(0.5 * (ef0["profit_factor"] + ef1["profit_factor"]), 3),
            "pre_eod_zero_borrow_pct": round(0.5 * (ef0["pre_eod_zero_borrow_pct"] + ef1["pre_eod_zero_borrow_pct"]), 1),
            "avg_hold_hours": round(0.5 * (ef0["avg_hold_hours"] + ef1["avg_hold_hours"]), 1),
            "climax_trims_avg": round(0.5 * (m0["climax_or_opt_trims"] + m1["climax_or_opt_trims"]), 1),
            "ml_exits_avg": round(0.5 * (m0["early_ml_exits"] + m1["early_ml_exits"]), 1),
            "pyramids_avg": round(0.5 * (m0["pyramids"] + m1["pyramids"]), 1),
            "slow_peak_trims_avg": round(0.5 * (m0["slow_peak_trims"] + m1["slow_peak_trims"]), 1),
            "vs_e0_bps": round(float(up_e0.get("mean_uplift", 0.0)) * 10_000.0, 2),
            "vs_v2_bps": round(float(up_v2.get("mean_uplift", 0.0)) * 10_000.0, 2),
            "vs_v2_ci": [round(ci_v2[0] * 10_000.0, 2), round(ci_v2[1] * 10_000.0, 2)],
        })

    best_arm = max(arm_rows, key=lambda r: (r["liquidations_sum"] == 0, r["ann_sharpe"]))
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "stopping_training_rows": {"phase_0h": len(st_d0), "phase_1h": len(st_d1)},
        "v2_reference": {
            "label": "V2_CHAMPION_60_40_NBX16_REF",
            "full": _portfolio_metrics(v2_nav),
            "stress": _portfolio_metrics({k: v for k, v in v2_nav.items() if k >= stress_iso}),
        },
        "arms": arm_rows,
        "best_arm": best_arm,
    }
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if report_md is not None:
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text(_render_optimal_exit_md(payload), encoding="utf-8")
    return payload


def _render_optimal_exit_md(p: dict) -> str:
    v2 = p["v2_reference"]
    best = p["best_arm"]
    lines = [
        "# Optimal Position-Closing & Exit-Timing Study (`E1`–`E4`)",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`PAPER_ONLY`)",
        f"- **Frozen v2 Reference:** NAV `${v2['full']['ending_nav']:.2f}` (`{v2['full']['ret_pct']:+.2f}%`), Bear `{v2['stress']['ret_pct']:+.2f}%`, Sharpe `{v2['full']['ann_sharpe']:.3f}`, MaxDD `{v2['full']['max_dd_pct']:.2f}%`",
        f"- **Best Closing Engine:** `{best['label']}` — NAV `${best['ending_nav']:.2f}` (`{best['ret_pct']:+.2f}%`), Bear `{best['stress_ret_pct']:+.2f}%`, Sharpe `{best['ann_sharpe']:.3f}` (`0h={best['sharpe_0h']:.3f}`/`1h={best['sharpe_1h']:.3f}`), MaxDD `{best['max_dd_pct']:.2f}%`, MFE Capture `{best['mfe_capture_ratio']:.3f}`, Profit Factor `{best['profit_factor']:.3f}`, Liqs `{best['liquidations_sum']}`",
        "",
        "## Controlled Head-to-Head Exit Comparison (Identical Entries, Different Closing Engines)",
        "",
        "| Closing Arm | Ending NAV | Full Ret | Bear Stress | Sharpe (`0h`/`1h`) | MaxDD | Liqs | MFE Capture | Giveback (bps) | Win% / PF | Pre-EOD 0% Brw | vs E0 / vs v2 (bps/d) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for r in p["arms"]:
        lines.append(
            f"| `{r['label']}` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` "
            f"| `{r['ann_sharpe']:.3f}` (`{r['sharpe_0h']:.3f}`/`{r['sharpe_1h']:.3f}`) | `{r['max_dd_pct']:.2f}%` "
            f"| `{r['liquidations_sum']}` | `{r['mfe_capture_ratio']:.3f}` | `{r['avg_giveback_bps']:.1f}` "
            f"| `{r['win_rate_pct']:.1f}%` / `{r['profit_factor']:.2f}` | `{r['pre_eod_zero_borrow_pct']:.1f}%` "
            f"| `{r['vs_e0_bps']:+.2f}` / `{r['vs_v2_bps']:+.2f}` |"
        )
    lines.append("")
    return "\n".join(lines)
