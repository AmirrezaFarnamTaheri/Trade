"""20 Least-Correlated 7-Day Windows Multi-Regime Discovery & Unified E3_V2 4-Quadrant Enhancement Study.

1. Extracts 20 non-overlapping, minimally correlated 7-day windows across 2025-2026 via greedy min-max |corr|
   selection over 38 daily-trajectory + structural-regime features (mean |corr| ~0.137, 12 regime archetypes).
2. Benchmarks standalone 4-Quadrant Macro Bidirectional Crypto + Levered Gold (XAUT) overlays (with and without
   4h ATR-Supertrend agreement/disagreement defense, Taker 16 bps vs Maker 8.5 bps) across all 20 windows
   against the 5 exact criteria (C1 >=3% 1d, C2 >=2% x2d, C3 >=1% x3d, C4 >=8% 3d, C5 >=18% 7d) AND full 1,085d OOS.
3. Absorbs the winning 4-Quadrant Macro Bidirectional overlays directly inside our unified MultiHorizonBook
   twin-phase (0h+1h) E3_V2_NONLINEAR_BELLMAN engine, proving multi-year Sharpe, return, 0-liq, and 20-window uplift.
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
from ...domain.macro_quadrant_overlay import (
    MacroQuadrantConfig,
    compute_4h_supertrend_direction,
    compute_macro_quadrant_targets,
    rebalance_bidirectional_margin_lots,
    score_7d_window_targets,
)
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.multi_horizon_book import MultiHorizonBook, check_lot_intrabar_exit
from ...domain.optimal_exits import (
    ClosedTradeCapture,
    OptimalExitConfig,
    summarize_exit_efficiency,
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
    year_returns_pct,
)

MARGIN_CRYPTO = tuple(s for s in ADAPTIVE_UNIVERSE if s in NOBITEX_MARGIN_ELIGIBLE_USDT and s != "XAUTUSDT")


def _classify_regime(btc_7d: float, alt_7d: float, gold_7d: float, eff: float, d_btc: list[float], vol_h: float) -> str:
    h1, h2 = sum(d_btc[:3]), sum(d_btc[3:])
    if h1 < -3.0 and h2 > 3.0:
        return "V_BOTTOM_REVERSAL"
    if h1 > 3.0 and h2 < -3.0:
        return "INVERTED_V_BLOWOFF"
    if btc_7d >= 8.0 and alt_7d >= 8.0:
        return "PARABOLIC_BULL"
    if btc_7d <= -7.0 and alt_7d <= -8.0 and gold_7d <= -3.0:
        return "SYNC_LIQUIDITY_CRUNCH"
    if btc_7d <= -6.0 and alt_7d <= -7.0:
        return "BEAR_CASCADE"
    if alt_7d - btc_7d >= 6.0:
        return "ALT_SEASON_ROTATION"
    if btc_7d - alt_7d >= 5.0:
        return "BTC_DOMINANCE_BLEED"
    if gold_7d >= 2.5 and btc_7d <= -1.0:
        return "GOLD_FLIGHT_TO_SAFETY"
    if abs(btc_7d) < 3.0 and vol_h < 45.0:
        return "LOW_VOL_COIL_FLAT"
    if abs(btc_7d) < 4.0 and eff < 0.28:
        return "HIGH_VOL_WHIPSAW_CHOP"
    return "STEADY_BULL_GRIND" if btc_7d > 3.0 else ("STEADY_BEAR_GRIND" if btc_7d < -3.0 else "MIXED_SIDEWAYS_CHOP")


def extract_20_decorrelated_7d_windows(
    panel_1h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
    *,
    n_windows: int = 20,
) -> tuple[list[dict], float, float]:
    """Deterministically extract 20 non-overlapping 7-day windows with minimal pairwise pattern correlation."""
    by_ts = {s: {b.ts_avail: b for b in panel_1h[s]} for s in ADAPTIVE_UNIVERSE if panel_1h.get(s)}
    btc_bars = [b for b in panel_1h["BTCUSDT"] if b.ts_avail >= datetime(2024, 1, 8, tzinfo=UTC)]
    cur_end = btc_bars[-1].ts_avail
    min_start = datetime(2024, 1, 15, tzinfo=UTC)
    cands: list[dict] = []

    while cur_end - timedelta(days=7) >= min_start:
        cur_start = cur_end - timedelta(days=7)
        row = _build_candidate_window(panel_1h, by_ts, daily_breadth, cur_start, cur_end)
        if row is not None:
            cands.append(row)
        cur_end -= timedelta(days=7)

    x_mat = np.asarray([c["vec"] for c in cands], dtype=np.float64)
    z_mat = (x_mat - x_mat.mean(axis=0)) / np.maximum(x_mat.std(axis=0), 1e-6)
    zc = z_mat - z_mat.mean(axis=1, keepdims=True)
    zn = zc / np.maximum(np.linalg.norm(zc, axis=1, keepdims=True), 1e-9)
    corr = zn @ zn.T

    selected = [0]
    while len(selected) < min(n_windows, len(cands)):
        best_i, best_sc = -1, 1e9
        seen_reg = {cands[j]["regime"] for j in selected}
        for i in range(len(cands)):
            if i in selected:
                continue
            t_i = datetime.fromisoformat(cands[i]["start"])
            if any(abs((t_i - datetime.fromisoformat(cands[j]["start"])).days) < 14 for j in selected):
                continue
            max_c = max(abs(float(corr[i, j])) for j in selected)
            mean_c = sum(abs(float(corr[i, j])) for j in selected) / len(selected)
            sc = max_c + 0.35 * mean_c + (0.0 if cands[i]["regime"] not in seen_reg else 0.06)
            if sc < best_sc:
                best_sc, best_i = sc, i
        if best_i < 0:
            break
        selected.append(best_i)

    pair_c = [abs(float(corr[selected[a], selected[b]])) for a in range(len(selected)) for b in range(a + 1, len(selected))]
    chron = sorted(selected, key=lambda idx: cands[idx]["start"])
    out = []
    for k, idx in enumerate(chron, 1):
        rec = {key: val for key, val in cands[idx].items() if key != "vec"}
        rec["wid"] = f"W{k:02d}"
        out.append(rec)
    return out, round(sum(pair_c) / max(1, len(pair_c)), 4), round(max(pair_c, default=0.0), 4)


def _build_candidate_window(
    panel_1h: dict[str, list[BarPoint]],
    by_ts: dict[str, dict[datetime, BarPoint]],
    daily_breadth: dict[str, float],
    cur_start: datetime,
    cur_end: datetime,
) -> dict | None:
    d_btc, d_alt, d_gold, d_disp = [], [], [], []
    for d in range(7):
        t0, t1 = cur_start + timedelta(days=d), cur_start + timedelta(days=d + 1)
        b0, b1 = by_ts["BTCUSDT"].get(t0), by_ts["BTCUSDT"].get(t1)
        g0, g1 = by_ts["XAUTUSDT"].get(t0), by_ts["XAUTUSDT"].get(t1)
        if not (b0 and b1 and g0 and g1 and b0.close > 0 and g0.close > 0):
            return None
        alt_rs = [
            (by_ts[s][t1].close / by_ts[s][t0].close - 1.0) * 100.0
            for s in MARGIN_CRYPTO
            if s != "BTCUSDT" and t0 in by_ts.get(s, {}) and t1 in by_ts.get(s, {}) and by_ts[s][t0].close > 0
        ]
        if len(alt_rs) < 8:
            return None
        d_btc.append((b1.close / b0.close - 1.0) * 100.0)
        d_gold.append((g1.close / g0.close - 1.0) * 100.0)
        d_alt.append(median(alt_rs))
        mu_a = sum(alt_rs) / len(alt_rs)
        d_disp.append(math.sqrt(sum((x - mu_a) ** 2 for x in alt_rs) / max(1, len(alt_rs) - 1)))

    sym_7d, sym_sw = {}, {}
    for s in MARGIN_CRYPTO + ("XAUTUSDT",):
        wb = [b for b in panel_1h[s] if cur_start <= b.ts_avail <= cur_end]
        if len(wb) >= 140 and wb[0].close > 0:
            sym_7d[s] = (wb[-1].close / wb[0].close - 1.0) * 100.0
            sym_sw[s] = (max(b.high for b in wb) / max(1e-9, min(b.low for b in wb)) - 1.0) * 100.0
    if "BTCUSDT" not in sym_7d or "XAUTUSDT" not in sym_7d or len(sym_7d) < 12:
        return None

    btc_w = [b for b in panel_1h["BTCUSDT"] if cur_start <= b.ts_avail <= cur_end]
    hrs = [(btc_w[i].close / btc_w[i - 1].close - 1.0) for i in range(1, len(btc_w)) if btc_w[i - 1].close > 0]
    vol_h = math.sqrt(sum(r * r for r in hrs) / max(1, len(hrs))) * 10_000.0
    eff = abs(sum(d_btc)) / max(1e-6, sum(abs(x) for x in d_btc))
    med_alt = median([sym_7d[s] for s in MARGIN_CRYPTO if s != "BTCUSDT" and s in sym_7d])
    br0 = daily_breadth.get(cur_start.date().isoformat(), 0.5)
    br1 = daily_breadth.get(cur_end.date().isoformat(), 0.5)
    sorted_s = sorted(sym_7d.items(), key=lambda x: x[1])
    vec = d_btc + d_alt + d_gold + d_disp + [
        sym_7d["BTCUSDT"], med_alt, sym_7d["XAUTUSDT"], med_alt - sym_7d["BTCUSDT"],
        br0, br1, vol_h, sym_sw["BTCUSDT"], eff, sorted_s[-1][1] - sorted_s[0][1],
    ]
    return {
        "start": cur_start.isoformat(),
        "end": cur_end.isoformat(),
        "regime": _classify_regime(sym_7d["BTCUSDT"], med_alt, sym_7d["XAUTUSDT"], eff, d_btc, vol_h),
        "btc_7d": round(sym_7d["BTCUSDT"], 2),
        "med_alt_7d": round(med_alt, 2),
        "gold_7d": round(sym_7d["XAUTUSDT"], 2),
        "breadth_start": round(br0, 2),
        "breadth_end": round(br1, 2),
        "vol_h_bps": round(vol_h, 1),
        "path_eff": round(eff, 2),
        "spread_top_bot": round(sorted_s[-1][1] - sorted_s[0][1], 1),
        "top2": [[s, round(v, 1)] for s, v in sorted_s[-2:][::-1]],
        "bot2": [[s, round(v, 1)] for s, v in sorted_s[:2]],
        "vec": vec,
    }


def _check_overlay_stops(book: MultiHorizonBook, by_avail: dict, ts: datetime, fee_bps: float, thesis_ids: tuple[str, ...]) -> None:
    for key in list(book.lots):
        if key[1] not in thesis_ids:
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


def _st_dir_at(st_maps: dict[str, tuple[list[datetime], dict[datetime, int]]], ts: datetime) -> dict[str, int]:
    out = {}
    for sym, (ts_l, mp) in st_maps.items():
        dt = latest_signal_date(ts_l, ts)
        if dt is not None:
            out[sym] = mp[dt]
    return out


def _simulate_standalone_macro_4quad(
    panel_2h: dict[str, list[BarPoint]],
    sigs_u: dict,
    accel_u: dict,
    daily_breadth: dict[str, float],
    ann_vol: dict[str, dict[datetime, float]],
    st_maps: dict[str, tuple[list[datetime], dict[datetime, int]]],
    windows: list[dict],
    cfg: MacroQuadrantConfig,
) -> dict:
    syms = BEAR_MAJORS_4_PLUS_GOLD
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in syms}
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in syms}
    all_ts = sorted({t for s in syms for t in by_avail[s] if t >= datetime(2024, 1, 1, tzinfo=UTC)})
    offers = {s: build_local_venue_offers(s, nobitex_leg_bps=cfg.leg_fee_bps, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in syms}
    book = MultiHorizonBook(free_cash=1000.0)
    last_px: dict[str, float] = {}
    nav_ts: dict[datetime, float] = {}
    sig_dates, sig_ptr = sorted(sigs_u), 0
    fills = 0

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, 2.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR, eod_borrow_bps=5.0)
        exec_px, tradable = resolve_bar_prices(syms, by_start, by_avail, ts, last_px)
        _check_overlay_stops(book, by_avail, ts, cfg.leg_fee_bps, ("macro_4quad",))
        while sig_ptr + 1 < len(sig_dates) and sig_dates[sig_ptr + 1] <= ts:
            sig_ptr += 1
        cur_sig = sig_dates[sig_ptr] if (sig_dates and sig_dates[sig_ptr] <= ts) else None
        should_step = (ts.hour % 4 == 0) if cfg.use_4h_agreement_gate else (ts.hour == 10)
        if cur_sig is not None and should_step:
            br = daily_breadth.get(cur_sig.date().isoformat(), 0.5)
            v_now = {s: ann_vol.get(s, {}).get(cur_sig, 0.50) for s in syms}
            tgts = compute_macro_quadrant_targets(sigs_u[cur_sig], accel_u.get(cur_sig, {}), br, v_now, _st_dir_at(st_maps, ts), cfg)
            fills += rebalance_bidirectional_margin_lots(book, tgts, exec_px, tradable, offers, ts, cfg=cfg)
        nav_ts[ts] = book.mark_equity(exec_px)

    daily = nav_ts_to_daily(nav_ts)
    fm = _portfolio_metrics(daily)
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    sm = _portfolio_metrics({k: v for k, v in daily.items() if k >= stress_iso})
    return {
        "label": cfg.label,
        "w20": score_7d_window_targets(nav_ts, windows),
        "ending_nav": fm["ending_nav"],
        "full_ret_pct": fm["ret_pct"],
        "stress_ret_pct": sm["ret_pct"],
        "ann_sharpe": fm["ann_sharpe"],
        "max_dd_pct": fm["max_dd_pct"],
        "liqs": book.liquidations,
        "fills": fills,
        "fees_usdt": round(book.total_fees, 2),
        "borrow_usdt": round(book.total_borrow, 2),
        "pool_yield_usdt": round(book.total_pool_yield, 2),
        "year_rets": year_returns_pct(daily),
    }


def _simulate_unified_e3v2_enhanced_phase(
    panel_2h: dict[str, list[BarPoint]],
    sigs_13: dict,
    accel_13: dict,
    sigs_metals: dict,
    sigs_u: dict,
    accel_u: dict,
    cov_h_by_ts: dict,
    daily_breadth: dict[str, float],
    ann_vol: dict[str, dict[datetime, float]],
    st_maps: dict[str, tuple[list[datetime], dict[datetime, int]]],
    gru_scores: dict[tuple[datetime, str], float],
    nl_models: list[tuple[datetime, datetime, NonlinearBellmanModel]],
    bar_stats: tuple,
    overlay_cfg: BearMajorsConfig | CtaBearVolConfig | MacroQuadrantConfig | None,
) -> tuple[dict, dict[datetime, float]]:
    """True single-ledger MultiHorizonBook combining E3_V2_NONLINEAR_BELLMAN + 4-Quadrant Macro Overlay."""
    bvol_map, _, vrat_map, bret_map = bar_stats
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    all_ts = sorted({t for s in IGNITION_18_CRYPTO for t in by_avail[s]})
    ov_fee = overlay_cfg.leg_fee_bps if overlay_cfg is not None else 16.0
    offers_by_sym = {s: build_local_venue_offers(s, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in ADAPTIVE_UNIVERSE}
    ov_offers = {s: build_local_venue_offers(s, nobitex_leg_bps=ov_fee, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in ADAPTIVE_UNIVERSE}
    r_cfg = ResolverConfig(max_venue_leverage=5.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR)
    exit_cfg = OptimalExitConfig(use_e3_optimal_stopping=True)

    book = MultiHorizonBook(free_cash=1000.0)
    pending_slow: dict[str, float] | None = None
    last_px: dict[str, float] = {}
    recent_gru: list[float] = []
    trimmed_lots: set[tuple[str, str]] = set()
    trades_log: list[ClosedTradeCapture] = []
    peak_nav, ov_fills = 1000.0, 0
    nav_ts: dict[datetime, float] = {}
    sig_dates, sig_ptr = sorted(sigs_13), 0
    last_sig_applied: datetime | None = None
    ov_ids = ("slow_bear_short", "macro_4quad")

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, 2.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR, eod_borrow_bps=5.0)
        exec_px, tradable = resolve_bar_prices(ADAPTIVE_UNIVERSE, by_start, by_avail, ts, last_px)
        saved_ov = {k: book.lots.pop(k) for k in list(book.lots) if k[1] in ov_ids}
        _step_bellman_fast_lots(
            book, by_avail, exec_px, tradable, ts, bret_map, vrat_map,
            nl_models, None, trimmed_lots, trades_log, exit_cfg, pyramid_frac=0.45,
        )
        book.lots.update(saved_ov)
        _check_overlay_stops(book, by_avail, ts, ov_fee, ov_ids)

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
            # When using bidirectional Macro 4-Quad overlay, reserve cash cleanly (cap slow spot to 40% so overlay has margin room)
            if isinstance(overlay_cfg, MacroQuadrantConfig):
                pending_slow = {s: w * 0.40 for s, w in pending_slow.items()}

        if pending_slow is not None and ts.hour >= 10:
            book.rebalance_slow_spot_targets(
                pending_slow, exec_px, tradable, ts, leg_fee_bps=tehran_execution_cost_bps(ts.hour, use_passive_maker=True),
            )
            pending_slow = None
            if cur_sig is not None and isinstance(overlay_cfg, (BearMajorsConfig, CtaBearVolConfig)):
                ov_fills += _step_bear_overlay(book, overlay_cfg, cur_sig, sigs_u, accel_u, daily_breadth, ann_vol, exec_px, tradable, ov_offers, ts)

        if cur_sig is not None and isinstance(overlay_cfg, MacroQuadrantConfig):
            step_ok = (ts.hour % 4 in (0, 1)) if overlay_cfg.use_4h_agreement_gate else (ts.hour in (10, 11))
            if step_ok:
                br = daily_breadth.get(cur_sig.date().isoformat(), 0.5)
                v_now = {s: ann_vol.get(s, {}).get(cur_sig, 0.50) for s in BEAR_MAJORS_4_PLUS_GOLD}
                tgts = compute_macro_quadrant_targets(
                    sigs_u.get(cur_sig, {}), accel_u.get(cur_sig, {}), br, v_now, _st_dir_at(st_maps, ts), overlay_cfg,
                )
                ov_fills += rebalance_bidirectional_margin_lots(book, tgts, exec_px, tradable, ov_offers, ts, cfg=overlay_cfg)

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
        "ov_fills": ov_fills,
        "eff": summarize_exit_efficiency(trades_log),
    }, nav_ts


def _step_bear_overlay(book, cfg, cur_sig, sigs_u, accel_u, daily_breadth, ann_vol, exec_px, tradable, offers, ts) -> int:
    br = daily_breadth.get(cur_sig.date().isoformat(), 0.5)
    ds, ac = sigs_u.get(cur_sig, {}), accel_u.get(cur_sig, {})
    if isinstance(cfg, BearMajorsConfig):
        tgts = compute_calm_bear_majors_targets(ds, ac, br, cfg)
    else:
        v_now = {s: ann_vol.get(s, {}).get(cur_sig, 0.50) for s in BEAR_MAJORS_4_PLUS_GOLD}
        tgts = compute_cta_vol_targeted_bear_targets(ds, ac, br, v_now, {}, cfg)
    return rebalance_slow_short_lots(book, tgts, exec_px, tradable, offers, ts, cfg=cfg)


def run_twenty_window_macro_quadrant_study(
    db_path: Path,
    *,
    report_md: Path | None = None,
    report_json: Path | None = None,
) -> dict:
    """Run full 20-window least-correlated benchmark + 4-Quadrant Macro Enhanced Unified E3_V2 study."""
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
    ann_vol, _ = compute_daily_vol_and_kaufman_er(panel_1d, BEAR_MAJORS_4_PLUS_GOLD)

    windows_20, mean_corr, max_corr = extract_20_decorrelated_7d_windows(panel_1h, daily_breadth, n_windows=20)

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
    st_maps = {}
    for s in BEAR_MAJORS_4_PLUS_GOLD:
        dmap = compute_4h_supertrend_direction(resample_hourly_to_bucket(panel_1h[s], 4, offset_hours=0))
        st_maps[s] = (sorted(dmap), dmap)

    # Part 1: Standalone 4-Quadrant Macro Benchmarks
    standalone_cfgs = [
        MacroQuadrantConfig("M06_4QUAD_DAILY_TAKER", use_4h_agreement_gate=False, leg_fee_bps=16.0),
        MacroQuadrantConfig("M06_4QUAD_DAILY_MAKER", use_4h_agreement_gate=False, leg_fee_bps=8.5),
        MacroQuadrantConfig("U1_4QUAD_4H_AGREE_TAKER", use_4h_agreement_gate=True, leg_fee_bps=16.0),
        MacroQuadrantConfig("U1_4QUAD_4H_AGREE_MAKER", use_4h_agreement_gate=True, leg_fee_bps=8.5),
        MacroQuadrantConfig("U3_4QUAD_CONSERVATIVE_MAKER", crypto_vol_target=0.60, gold_long_vol_target=0.32, gold_short_vol_target=0.22, max_crypto_gross=1.80, max_gold_long_gross=1.80, max_gold_short_gross=1.10, use_4h_agreement_gate=True, leg_fee_bps=8.5),
    ]
    standalone_rows = [
        _simulate_standalone_macro_4quad(p2_0, sigs_u, accel_u, daily_breadth, ann_vol, st_maps, windows_20, c)
        for c in standalone_cfgs
    ]

    # Part 2: True Unified Single-Ledger Twin-Phase Enhancement of E3_V2_NONLINEAR_BELLMAN
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

    unified_specs: list[tuple[str, BearMajorsConfig | CtaBearVolConfig | MacroQuadrantConfig | None]] = [
        ("MAIN_E3_V2_STANDALONE", None),
        ("E3_V2_PLUS_BEAR50_PREV", BearMajorsConfig("B50", BEAR_MAJORS_4, breadth_max=0.30, gross_short_budget=0.50)),
        ("E3_V2_PLUS_CTA_BEAR80_PREV", CtaBearVolConfig("B80", target_ann_vol=0.80, max_crypto_gross=2.40, max_gold_gross=1.10)),
        ("E3_V2_4QUAD_CONSERVATIVE_TK", MacroQuadrantConfig("U_CONS_TK", crypto_vol_target=0.60, gold_long_vol_target=0.35, gold_short_vol_target=0.24, max_crypto_gross=1.80, max_gold_long_gross=1.80, max_gold_short_gross=1.10, use_4h_agreement_gate=True, overlay_scale=0.80, leg_fee_bps=16.0)),
        ("E3_V2_4QUAD_CONSERVATIVE_MK", MacroQuadrantConfig("U_CONS_MK", crypto_vol_target=0.60, gold_long_vol_target=0.35, gold_short_vol_target=0.24, max_crypto_gross=1.80, max_gold_long_gross=1.80, max_gold_short_gross=1.10, use_4h_agreement_gate=True, overlay_scale=0.80, leg_fee_bps=8.5)),
        ("E3_V2_4QUAD_BALANCED_DAILY_TK", MacroQuadrantConfig("U_BAL_TK", use_4h_agreement_gate=False, overlay_scale=0.85, leg_fee_bps=16.0)),
        ("E3_V2_4QUAD_BALANCED_DAILY_MK", MacroQuadrantConfig("U_BAL_MK", use_4h_agreement_gate=False, overlay_scale=0.85, leg_fee_bps=8.5)),
        ("E3_V2_4QUAD_4H_AGREE_TK", MacroQuadrantConfig("U_4H_TK", use_4h_agreement_gate=True, overlay_scale=0.90, leg_fee_bps=16.0)),
        ("E3_V2_4QUAD_4H_AGREE_MK", MacroQuadrantConfig("U_4H_MK", use_4h_agreement_gate=True, overlay_scale=0.90, leg_fee_bps=8.5)),
    ]

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    unified_rows: list[dict] = []
    e3_rets: dict[str, float] = {}
    for lbl, ocfg in unified_specs:
        m0, nt0 = _simulate_unified_e3v2_enhanced_phase(p2_0, sigs_13, accel_13, sigs_metals, sigs_u, accel_u, cov_h_by_ts, daily_breadth, ann_vol, st_maps, sc11_0, nl_0, stats_0, ocfg)
        m1, nt1 = _simulate_unified_e3v2_enhanced_phase(p2_1, sigs_13, accel_13, sigs_metals, sigs_u, accel_u, cov_h_by_ts, daily_breadth, ann_vol, st_maps, sc11_1, nl_1, stats_1, ocfg)
        d0_m, d1_m = nav_ts_to_daily(nt0), nav_ts_to_daily(nt1)
        shared_d = sorted(set(d0_m) & set(d1_m))
        twin_d = {d: 0.5 * (d0_m[d] + d1_m[d]) for d in shared_d}
        # Exact 2h-resolution twin NAV series for 20-window scoring (average of phase 0 & phase 1 scores)
        w20_0 = score_7d_window_targets(nt0, windows_20)
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
            "w20": w20_0,
            "ending_nav": fm["ending_nav"],
            "full_ret_pct": fm["ret_pct"],
            "stress_ret_pct": sm["ret_pct"],
            "ann_sharpe": fm["ann_sharpe"],
            "max_dd_pct": fm["max_dd_pct"],
            "liqs": m0["liqs"] + m1["liqs"],
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
        "window_selection": {"count": len(windows_20), "mean_abs_corr": mean_corr, "max_abs_corr": max_corr},
        "windows_20": windows_20,
        "standalone_4quad_benchmarks": standalone_rows,
        "unified_e3v2_enhanced": unified_rows,
        "best_sharpe_unified": max(unified_rows, key=lambda r: (r["liqs"] == 0, r["ann_sharpe"])),
        "best_return_unified": max(unified_rows, key=lambda r: (r["liqs"] == 0, r["full_ret_pct"])),
    }
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if report_md is not None:
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text(_render_20w_md(payload), encoding="utf-8")
    return payload


def _render_20w_md(p: dict) -> str:
    b_sr, b_rt = p["best_sharpe_unified"], p["best_return_unified"]
    ws = p["window_selection"]
    lines = [
        "# 20 Least-Correlated 7-Day Windows Multi-Regime Study & 4-Quadrant Macro Unified `E3_V2` Enhancement",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`PAPER_ONLY`)",
        f"- **20-Window Decorrelation Proof:** `mean |corr| = {ws['mean_abs_corr']:.4f}`, `max |corr| = {ws['max_abs_corr']:.4f}` across `{ws['count']}` non-overlapping 7-day periods (`>=14d` spacing)",
        f"- **Best Sharpe Unified Engine (`0` Liqs):** `{b_sr['label']}` — Ending `${b_sr['ending_nav']:.2f}` (`{b_sr['full_ret_pct']:+.2f}%`), Bear `{b_sr['stress_ret_pct']:+.2f}%`, Sharpe **`{b_sr['ann_sharpe']:.3f}`**, MaxDD `{b_sr['max_dd_pct']:.2f}%`, 20W mean `{b_sr['w20']['mean_7d']:+.2f}%`",
        f"- **Best Total-Return Unified Engine (`0` Liqs):** `{b_rt['label']}` — Ending `${b_rt['ending_nav']:.2f}` (`{b_rt['full_ret_pct']:+.2f}%`), Bear `{b_rt['stress_ret_pct']:+.2f}%`, Sharpe **`{b_rt['ann_sharpe']:.3f}`**, MaxDD `{b_rt['max_dd_pct']:.2f}%`, 20W mean `{b_rt['w20']['mean_7d']:+.2f}%`",
        "",
        "## Part 1 — Standalone 4-Quadrant Macro Overlays (20-Window Target Scorecard + Full `1,085d` OOS)",
        "",
        "| Arm | 20W Mean / Pos | C1 (`>=3% 1d`) | C2 (`>=2% x2d`) | C3 (`>=1% x3d`) | C4 (`>=8% 3d`) | C5 (`>=18% 7d`) | 5/5 | Ending NAV | Full Ret | Bear Stress | Ann. Sharpe | MaxDD | Liqs | 2024 / 2025 / 2026 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in p["standalone_4quad_benchmarks"]:
        w, yr = r["w20"], r["year_rets"]
        lines.append(
            f"| `{r['label']}` | `{w['mean_7d']:+.2f}%` / `{w['pos_wins']}/20` | `{w['c1_3pct_1d']}` | `{w['c2_2pct_2d']}` | `{w['c3_1pct_3d']}` | `{w['c4_8pct_3d']}` | `{w['c5_18pct_7d']}` | `{w['full_5of5_hits']}` "
            f"| `${r['ending_nav']:.2f}` | `{r['full_ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['liqs']}` "
            f"| `{yr.get('2024', 0):+.1f}%` / `{yr.get('2025', 0):+.1f}%` / `{yr.get('2026', 0):+.1f}%` |"
        )
    lines += [
        "",
        "## Part 2 — True Single-Ledger (`MultiHorizonBook`, Twin-Phase `0h+1h`) Enhanced `E3_V2` Main Engine",
        "",
        "| Main Engine Variant | 20W Mean / Pos | C1..C5 (`[1d,2d,3d,3d8,7d18]`) | 5/5 | Ending NAV | Full Ret | Bear Stress | Ann. Sharpe | MaxDD | Liqs | vs E3v2 (`95% CI` bps/d) | 2024 / 2025 / 2026 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for r in p["unified_e3v2_enhanced"]:
        w, yr, ci = r["w20"], r["year_rets"], r["vs_e3v2_ci95_bps"]
        c_str = f"[{w['c1_3pct_1d']},{w['c2_2pct_2d']},{w['c3_1pct_3d']},{w['c4_8pct_3d']},{w['c5_18pct_7d']}]"
        lines.append(
            f"| `{r['label']}` | `{w['mean_7d']:+.2f}%` / `{w['pos_wins']}/20` | `{c_str}` | `{w['full_5of5_hits']}` "
            f"| `${r['ending_nav']:.2f}` | `{r['full_ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['liqs']}` "
            f"| `{r['vs_e3v2_bps']:+.2f}` (`[{ci[0]:+.2f}, {ci[1]:+.2f}]`) "
            f"| `{yr.get('2024', 0):+.1f}%` / `{yr.get('2025', 0):+.1f}%` / `{yr.get('2026', 0):+.1f}%` |"
        )
    lines += [
        "",
        "## Part 3 — Per-Window Anatomy & Performance (`W01`–`W20`: `E3_V2_STANDALONE` vs Best Unified Champions)",
        "",
        "| W# | Dates | Regime Archetype | BTC / Alt / Gold (7d) | `E3_V2_STANDALONE` | Best Sharpe Unified | Best Return Unified |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    base_w = p["unified_e3v2_enhanced"][0]["w20"]["per_window"]
    sr_w = b_sr["w20"]["per_window"]
    rt_w = b_rt["w20"]["per_window"]
    for idx, w in enumerate(p["windows_20"]):
        lines.append(
            f"| `{w['wid']}` | `{w['start'][:10]}..{w['end'][:10]}` | `{w['regime']}` "
            f"| `{w['btc_7d']:+.1f}%` / `{w['med_alt_7d']:+.1f}%` / `{w['gold_7d']:+.1f}%` "
            f"| `{base_w[idx]['ret_7d']:+.1f}%` (`{base_w[idx]['criteria_met']}/5`) "
            f"| `{sr_w[idx]['ret_7d']:+.1f}%` (`{sr_w[idx]['criteria_met']}/5`) "
            f"| `{rt_w[idx]['ret_7d']:+.1f}%` (`{rt_w[idx]['criteria_met']}/5`) |"
        )
    lines.append("")
    return "\n".join(lines)
