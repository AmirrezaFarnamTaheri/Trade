"""Pure domain simulator for rare 2h downward short-ignition and short-duration levered long-ignition.

Models exact Wallex credit-ratio margin economics:
- Borrow/extend fee: 0.015% per 4h (0.0075% per 2h bar) on full shorted notional (SHORT) or (L-1)*collateral (LONG).
- Exact intra-bar liquidation checks: bar.high >= liq_price (SHORT), bar.low <= liq_price (LONG when L > 1).
- Strict next-bar open entry/exit with live all-in spread + fee per leg (zero lookahead).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median

from .timeframe_panel import BarPoint


@dataclass(frozen=True)
class LeveredIgnitionResult:
    label: str
    side: str
    leverage: float
    markets: int
    offset_hours: int
    cost_bps: float
    days: int
    ending_nav: float
    ret_pct: float
    stress_ret_pct: float
    ann_sharpe: float
    max_dd_pct: float
    entries: int
    win_rate_pct: float
    liquidations: int
    avg_hold_hours: float
    total_borrow_usdt: float
    total_fees_usdt: float


def _breakdown_or_breakout_z(
    bar: BarPoint,
    bar_ret: float,
    prior_highs: list[float],
    prior_lows: list[float],
    prior_rets: list[float],
    prior_vols: list[float],
    *,
    side: str,
    breakout_bars: int,
    vol_lookback: int,
    z_threshold: float,
    vol_mult: float,
) -> tuple[float, float] | None:
    if len(prior_highs) < breakout_bars or len(prior_rets) < vol_lookback or len(prior_vols) < vol_lookback:
        return None
    mean_r = sum(prior_rets) / len(prior_rets)
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in prior_rets) / max(1, len(prior_rets) - 1))
    med_v = median(prior_vols)
    if med_v <= 0 or bar.volume < vol_mult * med_v:
        return None
    z = (bar_ret - mean_r) / max(std_r, 1e-4)
    if side == "LONG" and z >= z_threshold and bar.close > max(prior_highs):
        return z, max(std_r, 0.005)
    if side == "SHORT" and z <= -z_threshold and bar.close < min(prior_lows):
        return -z, max(std_r, 0.005)
    return None


def _check_margin_exit(
    pos: dict,
    cur: BarPoint | None,
    nxt: BarPoint | None,
    *,
    side: str,
    leverage: float,
    max_hold_bars: int,
    trail_stop_mult: float,
    hard_stop_pct: float,
    leg_cost: float,
    borrow_per_bar: float,
) -> tuple[bool, bool, float, float, float]:
    """Advance one bar on an open position. Returns (closed, liquidated, realized_pnl, borrow_paid, fee_paid)."""
    pos["age"] += 1
    borrowed_notional = pos["notional"] if side == "SHORT" else pos["collateral"] * max(0.0, leverage - 1.0)
    borrow_paid = borrowed_notional * borrow_per_bar

    if cur is not None and cur.close > 0:
        if side == "SHORT" and cur.high >= pos["liq_price"]:
            return True, True, -pos["collateral"], borrow_paid, 0.0
        if side == "LONG" and leverage > 1.0 and cur.low <= pos["liq_price"]:
            return True, True, -pos["collateral"], borrow_paid, 0.0

        if side == "LONG":
            pos["extreme"] = max(pos["extreme"], cur.close)
            hit_trail = cur.close < pos["extreme"] * (1.0 - trail_stop_mult * pos["b_vol"])
            hit_hard = cur.close < pos["entry_px"] * (1.0 - hard_stop_pct)
        else:
            pos["extreme"] = min(pos["extreme"], cur.close)
            hit_trail = cur.close > pos["extreme"] * (1.0 + trail_stop_mult * pos["b_vol"])
            hit_hard = cur.close > pos["entry_px"] * (1.0 + hard_stop_pct)

        if pos["age"] >= max_hold_bars or hit_trail or hit_hard:
            raw_exit = nxt.open if (nxt is not None and nxt.open > 0) else cur.close
            fee_paid = pos["qty"] * raw_exit * leg_cost
            if side == "LONG":
                pnl = pos["qty"] * (raw_exit - pos["entry_px"]) - fee_paid
            else:
                pnl = pos["qty"] * (pos["entry_px"] - raw_exit) - fee_paid
            return True, False, max(-pos["collateral"], pnl), borrow_paid, fee_paid
    elif pos["age"] >= max_hold_bars:
        return True, False, 0.0, borrow_paid, 0.0

    return False, False, 0.0, borrow_paid, 0.0


def _summarize_levered_nav(
    label: str,
    side: str,
    leverage: float,
    markets: int,
    offset_hours: int,
    leg_cost: float,
    nav_by_date: dict[str, float],
    stress_iso: str,
    entries: int,
    wins: int,
    closed: int,
    liquidations: int,
    hold_hours_sum: float,
    total_borrow: float,
    total_fees: float,
) -> LeveredIgnitionResult:
    dates = sorted(nav_by_date)
    if len(dates) < 5:
        return LeveredIgnitionResult(label, side, leverage, markets, offset_hours, round(leg_cost * 10000, 1), len(dates), 1000.0, 0.0, 0.0, 0.0, 0.0, entries, 0.0, liquidations, 0.0, round(total_borrow, 2), round(total_fees, 2))
    navs = [nav_by_date[d] for d in dates]
    rets = [(navs[i] / navs[i - 1] - 1.0) for i in range(1, len(navs)) if navs[i - 1] > 0]
    mean_r = sum(rets) / max(1, len(rets))
    var_r = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
    sr = (mean_r / math.sqrt(var_r)) * math.sqrt(365.0) if var_r > 1e-14 else 0.0
    peak, max_dd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)

    st_dates = [d for d in dates if d >= stress_iso]
    st_ret = ((nav_by_date[st_dates[-1]] / nav_by_date[st_dates[0]] - 1.0) * 100.0) if len(st_dates) >= 2 and nav_by_date[st_dates[0]] > 0 else 0.0
    return LeveredIgnitionResult(
        label=label,
        side=side,
        leverage=leverage,
        markets=markets,
        offset_hours=offset_hours,
        cost_bps=round(leg_cost * 10000.0, 1),
        days=len(dates),
        ending_nav=round(navs[-1], 2),
        ret_pct=round((navs[-1] / navs[0] - 1.0) * 100.0, 2),
        stress_ret_pct=round(st_ret, 2),
        ann_sharpe=round(sr, 3),
        max_dd_pct=round(max_dd * 100.0, 2),
        entries=entries,
        win_rate_pct=round((wins / closed * 100.0) if closed else 0.0, 1),
        liquidations=liquidations,
        avg_hold_hours=round((hold_hours_sum / closed) if closed else 0.0, 1),
        total_borrow_usdt=round(total_borrow, 2),
        total_fees_usdt=round(total_fees, 2),
    )


def simulate_levered_ignition(
    panel_tf: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth_by_date: dict[str, float],
    *,
    label: str,
    side: str,
    leverage: float = 1.0,
    bucket_hours: int = 2,
    offset_hours: int = 0,
    leg_cost: float = 0.0016,            # live half-spread + fee per leg (16 bps Nobitex / 25 bps Wallex)
    borrow_per_4h: float = 0.00015,      # exact Wallex 0.015% / 4h (32.85%/yr)
    liq_margin_ratio: float = 0.15,
    z_threshold: float = 3.0,
    vol_mult: float = 2.5,
    breakout_hours: int = 144,
    hold_hours: int = 48,
    trail_stop_mult: float = 2.5,
    hard_stop_pct: float = 0.04,
    breadth_gate: float = 0.45,          # LONG requires >= breadth_gate; SHORT requires <= breadth_gate
    max_slots: int = 3,
    slot_collateral_frac: float = 0.30,
    stress_iso: str = "2025-11-24",
) -> tuple[LeveredIgnitionResult, dict[str, float]]:
    """Simulate rare 2h LONG/SHORT ignition with exact Wallex 4h borrow fees and intra-bar liquidations."""
    if side not in ("LONG", "SHORT"):
        raise ValueError("side must be 'LONG' or 'SHORT'")
    if leverage < 1.0 or leverage > 3.0:
        raise ValueError("leverage must be in [1.0, 3.0]")

    breakout_bars = max(12, breakout_hours // bucket_hours)
    max_hold_bars = max(4, hold_hours // bucket_hours)
    vol_lookback = max(24, 72 // bucket_hours)
    borrow_per_bar = borrow_per_4h * (bucket_hours / 4.0)

    by_avail = {s: {b.ts_avail: b for b in panel_tf.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_tf.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    vol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    high_hist: dict[str, list[float]] = {s: [] for s in symbols}
    low_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}

    equity = 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    entries, wins, closed, liquidations = 0, 0, 0, 0
    hold_hours_sum, total_borrow, total_fees = 0.0, 0.0, 0.0

    for ts in all_ts:
        candidates: list[tuple[float, str, float]] = []
        for sym in symbols:
            cur = by_avail[sym].get(ts)
            nxt = by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            bar_ret = ((cur.close - prev_close[sym]) / prev_close[sym]) if (sym in prev_close and prev_close[sym] > 0) else 0.0
            can_trade = cur.entry_eligible and nxt is not None and nxt.open > 0
            if can_trade and sym not in active:
                hit = _breakdown_or_breakout_z(
                    cur,
                    bar_ret,
                    high_hist[sym][-breakout_bars:],
                    low_hist[sym][-breakout_bars:],
                    ret_hist[sym][-vol_lookback:],
                    vol_hist[sym][-vol_lookback:],
                    side=side,
                    breakout_bars=breakout_bars,
                    vol_lookback=vol_lookback,
                    z_threshold=z_threshold,
                    vol_mult=vol_mult,
                )
                if hit is not None:
                    candidates.append((hit[0], sym, hit[1]))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append(bar_ret)
            prev_close[sym] = cur.close
            vol_hist[sym].append(cur.volume)
            high_hist[sym].append(cur.high)
            low_hist[sym].append(cur.low)

        # Advance open positions (exact borrow, bar-high/low liquidation, trailing/hard/time stops)
        for sym in list(active):
            pos = active[sym]
            is_closed, is_liq, pnl, brw, fee = _check_margin_exit(
                pos,
                by_avail[sym].get(ts),
                by_start[sym].get(ts),
                side=side,
                leverage=leverage,
                max_hold_bars=max_hold_bars,
                trail_stop_mult=trail_stop_mult,
                hard_stop_pct=hard_stop_pct,
                leg_cost=leg_cost,
                borrow_per_bar=borrow_per_bar,
            )
            equity -= brw
            total_borrow += brw
            total_fees += fee
            if is_closed:
                equity = max(0.0, equity + pnl)
                closed += 1
                hold_hours_sum += pos["age"] * bucket_hours
                if is_liq:
                    liquidations += 1
                elif pnl - pos["entry_fee"] > 0:
                    wins += 1
                del active[sym]

        # Open new rare ignition positions strictly when macro breadth regime matches side
        day_br = daily_breadth_by_date.get(ts.date().isoformat())
        regime_ok = (
            day_br is not None
            and ((side == "LONG" and day_br >= breadth_gate) or (side == "SHORT" and day_br <= breadth_gate))
        )
        if equity > 100.0 and regime_ok and candidates and len(active) < max_slots:
            candidates.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in candidates:
                if len(active) >= max_slots:
                    break
                nxt = by_start[sym].get(ts)
                if nxt is None or nxt.open <= 0:
                    continue
                used_col = sum(p["collateral"] for p in active.values())
                free_col = max(0.0, equity - used_col)
                col = min(equity * slot_collateral_frac, free_col)
                if col < 25.0:
                    continue
                notional = col * leverage
                entry_fee = notional * leg_cost
                equity = max(0.0, equity - entry_fee)
                total_fees += entry_fee
                liq_move = (1.0 - liq_margin_ratio) / leverage
                liq_px = nxt.open * (1.0 + liq_move) if side == "SHORT" else nxt.open * max(0.0, 1.0 - liq_move)
                active[sym] = {
                    "collateral": col,
                    "notional": notional,
                    "qty": notional / nxt.open,
                    "entry_px": nxt.open,
                    "entry_fee": entry_fee,
                    "extreme": nxt.open,
                    "b_vol": b_vol,
                    "liq_price": liq_px,
                    "age": 0,
                }
                entries += 1

        # Mark-to-market equity
        unreal = 0.0
        for sym, pos in active.items():
            cur = by_avail[sym].get(ts)
            if cur is not None and cur.close > 0:
                raw_u = pos["qty"] * (cur.close - pos["entry_px"]) if side == "LONG" else pos["qty"] * (pos["entry_px"] - cur.close)
                unreal += max(-pos["collateral"], raw_u)
        nav_by_date[ts.date().isoformat()] = max(0.0, equity + unreal)

    res = _summarize_levered_nav(
        label,
        side,
        leverage,
        len(symbols),
        offset_hours,
        leg_cost,
        nav_by_date,
        stress_iso,
        entries,
        wins,
        closed,
        liquidations,
        hold_hours_sum,
        total_borrow,
        total_fees,
    )
    return res, nav_by_date
