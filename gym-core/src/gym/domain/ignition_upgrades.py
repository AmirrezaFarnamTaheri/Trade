"""Pure domain upgrades for 2h Ignition & GRU-Ignition (Track II):
- #2 Amended: 50/50 phase-averaged 0h + 1h twin book
- #3 Amended: Vol-normalized two-tranche exit (50% profit-lock + breakeven stop + unlocked 96h runner)
- #10: Eigenvalue Absorption-Ratio single-factor slot throttle
- #12: Online conformal quantile rank calibration + equity-curve drawdown leverage governor
"""
from __future__ import annotations

import math
from dataclasses import asdict
from datetime import datetime
from statistics import median

import numpy as np

from .short_and_levered_ignition import (
    LeveredIgnitionResult,
    _breakdown_or_breakout_z,
    _check_margin_exit,
    _summarize_levered_nav,
)
from .timeframe_panel import BarPoint


def compute_absorption_ratio_map(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    *,
    window: int = 36,
) -> dict[datetime, float]:
    """Compute strictly causal 1st-eigenvalue absorption ratio AR_t = lambda_1(R) / N over trailing 36 2h bars."""
    by_avail = {s: {b.ts_avail: b.close for b in panel_2h.get(s, []) if b.close > 0} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_c: dict[str, float] = {}
    ar_map: dict[datetime, float] = {}

    for ts in all_ts:
        for sym in symbols:
            c = by_avail[sym].get(ts)
            if c is not None:
                if sym in prev_c and prev_c[sym] > 0:
                    ret_hist[sym].append((c - prev_c[sym]) / prev_c[sym])
                prev_c[sym] = c
        rows = [ret_hist[s][-window:] for s in symbols if len(ret_hist[s]) >= window]
        if len(rows) < 4:
            continue
        mat = np.asarray(rows, dtype=np.float64)
        stds = np.std(mat, axis=1)
        valid = stds > 1e-8
        if int(np.sum(valid)) < 4:
            continue
        z = (mat[valid] - np.mean(mat[valid], axis=1, keepdims=True)) / stds[valid][:, None]
        corr = (z @ z.T) / float(window)
        lam_max = float(np.linalg.eigvalsh(corr)[-1])
        ar_map[ts] = max(0.0, min(1.0, lam_max / float(corr.shape[0])))
    return ar_map


def _slot_limit_from_ar(ar_val: float | None, base_max_slots: int) -> int:
    if ar_val is None:
        return base_max_slots
    if ar_val > 0.72:
        return 1
    if ar_val > 0.55:
        return min(2, base_max_slots)
    return base_max_slots


def _step_two_tranche_exit(
    pos: dict,
    cur: BarPoint | None,
    nxt: BarPoint | None,
    *,
    leg_cost: float,
    borrow_per_bar: float,
    base_max_hold_bars: int,
    runner_max_hold_bars: int,
) -> tuple[bool, bool, float, float, float]:
    """Advance one 2h bar with vol-normalized 50% partial profit-lock + breakeven stop + unlocked runner."""
    pos["age"] += 1
    borrowed_notional = pos["collateral"] * max(0.0, pos["lev"] - 1.0)
    borrow_paid = borrowed_notional * borrow_per_bar

    if cur is None or cur.close <= 0:
        if pos["age"] >= base_max_hold_bars:
            return True, False, 0.0, borrow_paid, 0.0
        return False, False, 0.0, borrow_paid, 0.0

    if pos["lev"] > 1.0 and cur.low <= pos["liq_price"]:
        return True, True, -pos["collateral"], borrow_paid, 0.0

    pos["extreme"] = max(pos["extreme"], cur.close)
    raw_px = nxt.open if (nxt is not None and nxt.open > 0) else cur.close

    # Step 1: Take 50% partial profit once gain clears +2.0 * entry_bar_vol; move remaining stop to breakeven
    partial_pnl = 0.0
    partial_fee = 0.0
    if not pos["half_locked"] and cur.close >= pos["entry_px"] * (1.0 + 2.0 * pos["b_vol"]):
        half_qty = 0.5 * pos["qty"]
        partial_fee = half_qty * raw_px * leg_cost
        partial_pnl = half_qty * (raw_px - pos["entry_px"]) - partial_fee
        pos["qty"] -= half_qty
        pos["collateral"] *= 0.5
        pos["notional"] *= 0.5
        pos["half_locked"] = True
        pos["hard_stop_px"] = pos["entry_px"]

    trail_mult = 3.0 if pos["half_locked"] else 2.5
    max_hold = runner_max_hold_bars if (pos["half_locked"] and pos["lev"] > 1.0) else base_max_hold_bars
    hit_trail = cur.close < pos["extreme"] * (1.0 - trail_mult * pos["b_vol"])
    hit_hard = cur.close < pos["hard_stop_px"]

    if pos["age"] >= max_hold or hit_trail or hit_hard:
        exit_fee = pos["qty"] * raw_px * leg_cost
        rem_pnl = pos["qty"] * (raw_px - pos["entry_px"]) - exit_fee
        total_pnl = max(-pos["orig_collateral"], partial_pnl + rem_pnl)
        return True, False, total_pnl, borrow_paid, partial_fee + exit_fee

    return False, False, partial_pnl, borrow_paid, partial_fee


def _select_lev_and_col(
    score: float | None,
    *,
    score_is_return: bool,
    base_prob: float,
    use_conformal: bool,
    recent_scores: list[float],
    in_dd_throttle: bool,
) -> tuple[float, float]:
    """Map GRU score -> (leverage, collateral_frac) with optional conformal quantile gate & DD leverage governor."""
    if score is None:
        return 1.0, 0.30
    if use_conformal and len(recent_scores) >= 30:
        s_sorted = sorted(recent_scores[-100:])
        q67 = s_sorted[int(0.67 * (len(s_sorted) - 1))]
        q33 = s_sorted[int(0.33 * (len(s_sorted) - 1))]
        min_pos = 0.002 if score_is_return else 0.50
        if score >= max(q67, min_pos):
            lev, col_f = 1.5, 0.30
        elif score >= q33:
            lev, col_f = 1.0, 0.30
        else:
            lev, col_f = 1.0, 0.15
    elif score_is_return:
        if score >= 0.008:
            lev, col_f = 1.5, 0.30
        elif score >= 0.0:
            lev, col_f = 1.0, 0.30
        else:
            lev, col_f = 1.0, 0.15
    else:
        if score >= base_prob + 0.05:
            lev, col_f = 1.5, 0.30
        elif score >= base_prob - 0.05:
            lev, col_f = 1.0, 0.30
        else:
            lev, col_f = 1.0, 0.15

    if in_dd_throttle and lev > 1.0:
        lev = 1.0
    return lev, col_f


def simulate_upgraded_ignition(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth: dict[str, float],
    *,
    label: str,
    offset_hours: int = 0,
    leg_cost: float = 0.0016,
    score_map: dict[tuple[datetime, str], float] | None = None,
    score_is_return: bool = False,
    base_prob: float = 0.46,
    use_two_tranche_exit: bool = False,
    absorption_map: dict[datetime, float] | None = None,
    use_conformal_and_dd_gov: bool = False,
    dd_throttle_pct: float = 0.05,
    max_slots: int = 3,
    stress_iso: str = "2025-11-24",
) -> tuple[LeveredIgnitionResult, dict[str, float]]:
    """Strictly causal 2h ignition simulator with clean toggles for Track II ablations (#3, #4, #10, #12)."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    vol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    high_hist: dict[str, list[float]] = {s: [] for s in symbols}
    low_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}
    recent_scores: list[float] = []

    equity, peak_eq = 1000.0, 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    entries, wins, closed, liqs = 0, 0, 0, 0
    hold_h, total_borrow, total_fees = 0.0, 0.0, 0.0
    borrow_bar = 0.00015 * 0.5

    for ts in all_ts:
        cands = []
        for sym in symbols:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_close[sym]) / prev_close[sym]) if (sym in prev_close and prev_close[sym] > 0) else 0.0
            if cur.entry_eligible and nxt and nxt.entry_eligible and nxt.open > 0 and sym not in active:
                hit = _breakdown_or_breakout_z(
                    cur, r, high_hist[sym][-72:], low_hist[sym][-72:], ret_hist[sym][-36:], vol_hist[sym][-36:],
                    side="LONG", breakout_bars=72, vol_lookback=36, z_threshold=3.0, vol_mult=2.5,
                )
                if hit is not None:
                    cands.append((hit[0], sym, hit[1]))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append(r)
            prev_close[sym] = cur.close
            vol_hist[sym].append(cur.volume)
            high_hist[sym].append(cur.high)
            low_hist[sym].append(cur.low)

        for sym in list(active):
            pos = active[sym]
            if use_two_tranche_exit:
                is_c, is_l, pnl, brw, fee = _step_two_tranche_exit(
                    pos, by_avail[sym].get(ts), by_start[sym].get(ts),
                    leg_cost=leg_cost, borrow_per_bar=borrow_bar,
                    base_max_hold_bars=24, runner_max_hold_bars=48,
                )
            else:
                is_c, is_l, pnl, brw, fee = _check_margin_exit(
                    pos, by_avail[sym].get(ts), by_start[sym].get(ts),
                    side="LONG", leverage=pos["lev"], max_hold_bars=24, trail_stop_mult=2.5,
                    hard_stop_pct=0.04, leg_cost=leg_cost, borrow_per_bar=borrow_bar,
                )
            equity -= brw
            total_borrow += brw
            total_fees += fee
            if is_c:
                equity = max(0.0, equity + pnl)
                closed += 1
                hold_h += pos["age"] * 2.0
                if is_l:
                    liqs += 1
                elif pnl + pos.get("realized_partial", 0.0) - pos["entry_fee"] > 0:
                    wins += 1
                del active[sym]
            elif pnl != 0.0:
                equity = max(0.0, equity + pnl)
                pos["realized_partial"] = pos.get("realized_partial", 0.0) + pnl

        mark_unreal = sum(
            max(-pos["collateral"], pos["qty"] * (by_avail[s][ts].close - pos["entry_px"]))
            for s, pos in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        mark_eq = max(0.0, equity + mark_unreal)
        peak_eq = max(peak_eq, mark_eq)
        in_dd = use_conformal_and_dd_gov and peak_eq > 0 and ((peak_eq - mark_eq) / peak_eq >= dd_throttle_pct)
        slot_cap = _slot_limit_from_ar(absorption_map.get(ts), max_slots) if absorption_map is not None else max_slots

        day_br = daily_breadth.get(ts.date().isoformat(), 0.0)
        if equity > 100.0 and day_br >= 0.45 and cands and len(active) < slot_cap:
            cands.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in cands:
                sc = score_map.get((ts, sym)) if score_map is not None else None
                if sc is not None:
                    recent_scores.append(sc)
                if len(active) >= slot_cap:
                    break
                nxt = by_start[sym].get(ts)
                if not nxt or nxt.open <= 0:
                    continue
                lev, col_f = _select_lev_and_col(
                    sc, score_is_return=score_is_return, base_prob=base_prob,
                    use_conformal=use_conformal_and_dd_gov, recent_scores=recent_scores,
                    in_dd_throttle=in_dd,
                )
                free_col = max(0.0, equity - sum(p["collateral"] for p in active.values()))
                col = min(equity * col_f, free_col)
                if col < 25.0:
                    continue
                notional = col * lev
                ef = notional * leg_cost
                equity = max(0.0, equity - ef)
                total_fees += ef
                liq_px = nxt.open * max(0.0, 1.0 - (0.85 / lev)) if lev > 1.0 else 0.0
                active[sym] = {
                    "collateral": col, "orig_collateral": col, "notional": notional,
                    "qty": notional / nxt.open, "entry_px": nxt.open, "entry_fee": ef,
                    "extreme": nxt.open, "b_vol": b_vol, "liq_price": liq_px,
                    "hard_stop_px": nxt.open * 0.96, "half_locked": False,
                    "age": 0, "lev": lev,
                }
                entries += 1

        final_unreal = sum(
            max(-pos["collateral"], pos["qty"] * (by_avail[s][ts].close - pos["entry_px"]))
            for s, pos in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        nav_by_date[ts.date().isoformat()] = max(0.0, equity + final_unreal)

    res = _summarize_levered_nav(
        label, "LONG", 1.25 if score_map else 1.0, len(symbols), offset_hours, leg_cost,
        nav_by_date, stress_iso, entries, wins, closed, liqs, hold_h, total_borrow, total_fees,
    )
    return res, nav_by_date


def combine_twin_phase_navs(
    label: str,
    nav_0h: dict[str, float],
    nav_1h: dict[str, float],
    res_0h: LeveredIgnitionResult,
    res_1h: LeveredIgnitionResult,
    *,
    stress_iso: str = "2025-11-24",
) -> dict:
    """Combine 50% 0h-phase + 50% +1h-phase twin sub-books into exact clock-invariant NAV metrics."""
    dates = sorted(set(nav_0h) & set(nav_1h))
    comb = {d: 0.5 * nav_0h[d] + 0.5 * nav_1h[d] for d in dates}
    summary = _summarize_levered_nav(
        label, "LONG_TWIN", res_0h.leverage, res_0h.markets, 0, res_0h.cost_bps / 10000.0,
        comb, stress_iso, res_0h.entries + res_1h.entries,
        int(round(0.5 * (res_0h.win_rate_pct + res_1h.win_rate_pct))), 100,
        res_0h.liquidations + res_1h.liquidations,
        0.5 * (res_0h.avg_hold_hours + res_1h.avg_hold_hours) * 100.0,
        0.5 * (res_0h.total_borrow_usdt + res_1h.total_borrow_usdt),
        0.5 * (res_0h.total_fees_usdt + res_1h.total_fees_usdt),
    )
    return {**asdict(summary), "nav_by_date": comb}


def simulate_episode_path_pnl(
    bars: list[BarPoint],
    entry_idx: int,
    b_vol: float,
    *,
    leg_cost: float = 0.0016,
    max_hold_bars: int = 24,
) -> float:
    """Compute exact path-dependent net return of a 1x trade starting at bars[entry_idx + 1].open."""
    if entry_idx + 2 >= len(bars):
        return 0.0
    entry_px = bars[entry_idx + 1].open
    if entry_px <= 0:
        return 0.0
    pos = {
        "collateral": 1.0, "notional": 1.0, "qty": 1.0 / entry_px,
        "entry_px": entry_px, "entry_fee": leg_cost, "extreme": entry_px,
        "b_vol": max(b_vol, 0.005), "liq_price": 0.0, "age": 0,
    }
    for k in range(entry_idx + 1, min(len(bars) - 1, entry_idx + 1 + max_hold_bars)):
        is_c, _, pnl, _, _ = _check_margin_exit(
            pos, bars[k], bars[k + 1], side="LONG", leverage=1.0,
            max_hold_bars=max_hold_bars, trail_stop_mult=2.5,
            hard_stop_pct=0.04, leg_cost=leg_cost, borrow_per_bar=0.0,
        )
        if is_c:
            return float(max(-0.06, min(0.14, pnl - leg_cost)))
    last_px = bars[min(len(bars) - 1, entry_idx + max_hold_bars)].close
    raw = (last_px - entry_px) / entry_px - 2.0 * leg_cost
    return float(max(-0.06, min(0.14, raw)))


def compute_cross_sectional_2h_context(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
) -> tuple[dict[datetime, float], dict[tuple[datetime, str], float]]:
    """Compute strictly causal cross-sectional ignition wave fraction and 72h strength rank per (ts, sym)."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    ret_h: dict[str, list[float]] = {s: [] for s in symbols}
    vol_h: dict[str, list[float]] = {s: [] for s in symbols}
    cls_h: dict[str, list[float]] = {s: [] for s in symbols}
    prev_c: dict[str, float] = {}

    wave_by_ts: dict[datetime, float] = {}
    rank_by_ts_sym: dict[tuple[datetime, str], float] = {}

    for ts in all_ts:
        active_n, wave_n = 0, 0
        r72_list: list[tuple[float, str]] = []
        for sym in symbols:
            cur = by_avail[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_c[sym]) / prev_c[sym]) if (sym in prev_c and prev_c[sym] > 0) else 0.0
            if len(ret_h[sym]) >= 36 and len(vol_h[sym]) >= 36:
                active_n += 1
                pr = ret_h[sym][-36:]
                mr = sum(pr) / 36.0
                sr = math.sqrt(sum((x - mr) ** 2 for x in pr) / 35.0)
                mv = median(vol_h[sym][-36:])
                if sr > 1e-4 and mv > 0 and (r - mr) / sr >= 1.5 and cur.volume >= 1.5 * mv:
                    wave_n += 1
            if len(cls_h[sym]) >= 36 and cls_h[sym][-36] > 0:
                r72_list.append(((cur.close - cls_h[sym][-36]) / cls_h[sym][-36], sym))
            if sym in prev_c and prev_c[sym] > 0:
                ret_h[sym].append(r)
            prev_c[sym] = cur.close
            vol_h[sym].append(cur.volume)
            cls_h[sym].append(cur.close)

        wave_by_ts[ts] = (wave_n / active_n) if active_n > 0 else 0.0
        if len(r72_list) >= 2:
            r72_list.sort(key=lambda x: (x[0], x[1]))
            denom = float(len(r72_list) - 1)
            for idx, (_, sym) in enumerate(r72_list):
                rank_by_ts_sym[(ts, sym)] = idx / denom
    return wave_by_ts, rank_by_ts_sym
