"""Higher-order momentum, tiered sparse universe ignition, walk-forward sleeve risk-parity, and structural bear breakdown shorts.

All computations are strictly causal (decision at bar close ts_avail, fill at next-bar open ts_start == ts_avail).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median

from .paper_ledger import SelfFinancingLedger
from .short_and_levered_ignition import (
    LeveredIgnitionResult,
    _check_margin_exit,
    _summarize_levered_nav,
)
from .strategy_sleeves import SleeveSignal
from .timeframe_panel import BarPoint


@dataclass(frozen=True)
class TieredIgnitionResult:
    base: LeveredIgnitionResult
    core_entries: int
    satellite_entries: int


def compute_second_order_trend_map(
    sigs_1d: dict[datetime, dict[str, SleeveSignal]],
    symbols: tuple[str, ...],
    *,
    fast_span: int = 5,
    slow_span: int = 20,
    scale: float = 0.25,
) -> dict[datetime, dict[str, float]]:
    """Compute strictly causal 2nd-order trend acceleration: clamp((EMA_fast(S1) - EMA_slow(S1)) / scale, -1, 1)."""
    a_fast = 2.0 / (fast_span + 1.0)
    a_slow = 2.0 / (slow_span + 1.0)
    ema_f: dict[str, float] = {}
    ema_s: dict[str, float] = {}
    out: dict[datetime, dict[str, float]] = {}

    for ts in sorted(sigs_1d):
        day_s = sigs_1d[ts]
        day_acc: dict[str, float] = {}
        for sym in symbols:
            sig = day_s.get(sym)
            if sig is None or sig.s1_trend is None:
                continue
            v = sig.s1_trend
            ema_f[sym] = v if sym not in ema_f else (1.0 - a_fast) * ema_f[sym] + a_fast * v
            ema_s[sym] = v if sym not in ema_s else (1.0 - a_slow) * ema_s[sym] + a_slow * v
            acc = max(-1.0, min(1.0, (ema_f[sym] - ema_s[sym]) / max(scale, 1e-6)))
            day_acc[sym] = acc
        out[ts] = day_acc
    return out


def _tiered_breakout_score(
    bar: BarPoint,
    bar_ret: float,
    prior_highs: list[float],
    prior_rets: list[float],
    prior_vols: list[float],
    prior_dvols: list[float],
    *,
    is_satellite: bool,
    breakout_bars: int,
    vol_lookback: int,
    core_z: float,
    core_vol: float,
    sat_z: float,
    sat_vol: float,
    sat_min_24h_dvol: float,
) -> tuple[float, float] | None:
    if len(prior_highs) < breakout_bars or len(prior_rets) < vol_lookback or len(prior_vols) < vol_lookback:
        return None
    if is_satellite and sum(prior_dvols[-12:]) < sat_min_24h_dvol:
        return None
    mean_r = sum(prior_rets) / len(prior_rets)
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in prior_rets) / max(1, len(prior_rets) - 1))
    med_v = median(prior_vols)
    z_req = sat_z if is_satellite else core_z
    v_req = sat_vol if is_satellite else core_vol
    if med_v <= 0 or bar.volume < v_req * med_v:
        return None
    z = (bar_ret - mean_r) / max(std_r, 1e-4)
    if z >= z_req and bar.close > max(prior_highs):
        # Penalize satellite ranking score slightly by hurdle gap so equal breakouts prefer liquid core
        rank_z = z - (sat_z - core_z) if is_satellite else z
        return rank_z, max(std_r, 0.005)
    return None


def simulate_tiered_sparse_ignition(
    panel_tf: dict[str, list[BarPoint]],
    core_symbols: tuple[str, ...],
    satellite_symbols: tuple[str, ...],
    daily_breadth_by_date: dict[str, float],
    *,
    label: str,
    bucket_hours: int = 2,
    offset_hours: int = 0,
    core_leg_cost: float = 0.0016,
    sat_extra_leg_cost: float = 0.0010,
    core_z: float = 3.0,
    core_vol: float = 2.5,
    sat_z: float = 3.6,
    sat_vol: float = 3.2,
    sat_min_24h_dvol: float = 15000.0,
    breakout_hours: int = 144,
    hold_hours: int = 48,
    trail_stop_mult: float = 2.5,
    hard_stop_pct: float = 0.04,
    breadth_gate: float = 0.45,
    max_slots: int = 3,
    slot_frac: float = 0.30,
    stress_iso: str = "2025-11-24",
) -> tuple[TieredIgnitionResult, dict[str, float], dict[datetime, dict[str, float]]]:
    """2h spot breakout ignition with tiered sparsity hurdle and explicit wider Tier-2 spread penalty."""
    symbols = tuple(dict.fromkeys(core_symbols + satellite_symbols))
    sat_set = set(satellite_symbols) - set(core_symbols)
    breakout_bars = max(12, breakout_hours // bucket_hours)
    max_hold_bars = max(4, hold_hours // bucket_hours)
    vol_lookback = max(24, 72 // bucket_hours)

    by_avail = {s: {b.ts_avail: b for b in panel_tf.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_tf.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    vol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    dvol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    high_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}

    equity = 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    targets_by_ts: dict[datetime, dict[str, float]] = {}
    entries, core_entries, sat_entries, wins, closed = 0, 0, 0, 0, 0
    hold_h, total_fees = 0.0, 0.0

    for ts in all_ts:
        cands: list[tuple[float, str, float]] = []
        for sym in symbols:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_close[sym]) / prev_close[sym]) if (sym in prev_close and prev_close[sym] > 0) else 0.0
            if cur.entry_eligible and nxt and nxt.open > 0 and sym not in active:
                hit = _tiered_breakout_score(
                    cur, r, high_hist[sym][-breakout_bars:], ret_hist[sym][-vol_lookback:],
                    vol_hist[sym][-vol_lookback:], dvol_hist[sym][-12:],
                    is_satellite=(sym in sat_set), breakout_bars=breakout_bars, vol_lookback=vol_lookback,
                    core_z=core_z, core_vol=core_vol, sat_z=sat_z, sat_vol=sat_vol,
                    sat_min_24h_dvol=sat_min_24h_dvol,
                )
                if hit is not None:
                    cands.append((hit[0], sym, hit[1]))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append(r)
            prev_close[sym] = cur.close
            vol_hist[sym].append(cur.volume)
            dvol_hist[sym].append(cur.volume * cur.close)
            high_hist[sym].append(cur.high)

        for sym in list(active):
            pos = active[sym]
            leg_c = core_leg_cost + (sat_extra_leg_cost if sym in sat_set else 0.0)
            is_c, _, pnl, _, fee = _check_margin_exit(
                pos, by_avail[sym].get(ts), by_start[sym].get(ts),
                side="LONG", leverage=1.0, max_hold_bars=max_hold_bars,
                trail_stop_mult=trail_stop_mult, hard_stop_pct=hard_stop_pct,
                leg_cost=leg_c, borrow_per_bar=0.0,
            )
            total_fees += fee
            if is_c:
                equity = max(0.0, equity + pnl)
                closed += 1
                hold_h += pos["age"] * bucket_hours
                if pnl - pos["entry_fee"] > 0:
                    wins += 1
                del active[sym]

        day_br = daily_breadth_by_date.get(ts.date().isoformat(), 0.0)
        if equity > 100.0 and day_br >= breadth_gate and cands and len(active) < max_slots:
            cands.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in cands:
                if len(active) >= max_slots:
                    break
                nxt = by_start[sym].get(ts)
                if nxt is None or nxt.open <= 0:
                    continue
                free_col = max(0.0, equity - sum(p["collateral"] for p in active.values()))
                col = min(equity * slot_frac, free_col)
                if col < 25.0:
                    continue
                leg_c = core_leg_cost + (sat_extra_leg_cost if sym in sat_set else 0.0)
                ef = col * leg_c
                equity = max(0.0, equity - ef)
                total_fees += ef
                active[sym] = {
                    "collateral": col, "notional": col, "qty": col / nxt.open,
                    "entry_px": nxt.open, "entry_fee": ef, "extreme": nxt.open,
                    "b_vol": b_vol, "liq_price": 0.0, "age": 0,
                }
                entries += 1
                if sym in sat_set:
                    sat_entries += 1
                else:
                    core_entries += 1

        targets_by_ts[ts] = {s: (slot_frac if s in active else 0.0) for s in symbols}
        unreal = sum(
            max(-pos["collateral"], pos["qty"] * (by_avail[s][ts].close - pos["entry_px"]))
            for s, pos in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        nav_by_date[ts.date().isoformat()] = max(0.0, equity + unreal)

    base = _summarize_levered_nav(
        label, "LONG", 1.0, len(symbols), offset_hours, core_leg_cost,
        nav_by_date, stress_iso, entries, wins, closed, 0, hold_h, 0.0, total_fees,
    )
    return TieredIgnitionResult(base=base, core_entries=core_entries, satellite_entries=sat_entries), nav_by_date, targets_by_ts


def compute_walkforward_sleeve_weights(
    slow_rets_by_date: dict[str, float],
    ign_rets_by_date: dict[str, float],
    *,
    mode: str = "WF_INV_VOL_RP",
    window: int = 60,
    min_slow: float = 0.25,
    max_slow: float = 0.85,
    default_slow: float = 0.70,
) -> dict[str, tuple[float, float]]:
    """Compute strictly causal (lagged 1-day) daily sleeve capital weights (w_slow, w_ign)."""
    dates = sorted(set(slow_rets_by_date) & set(ign_rets_by_date))
    out: dict[str, tuple[float, float]] = {}
    s_hist: list[float] = []
    i_hist: list[float] = []

    for d in dates:
        if len(s_hist) < 20:
            w_s = default_slow
        else:
            sw = s_hist[-window:]
            iw = i_hist[-window:]
            ms, mi = sum(sw) / len(sw), sum(iw) / len(iw)
            vs = sum((x - ms) ** 2 for x in sw) / max(1, len(sw) - 1)
            vi = sum((x - mi) ** 2 for x in iw) / max(1, len(iw) - 1)
            sig_s = math.sqrt(max(vs, 1e-8))
            sig_i = math.sqrt(max(vi, 1e-8))
            if mode == "WF_INV_VOL_RP":
                inv_s, inv_i = 1.0 / sig_s, 1.0 / sig_i
                w_s = inv_s / (inv_s + inv_i)
            else:
                # Shrunk 2x2 minimum-variance weights (50% shrinkage toward diagonal)
                cov_si = 0.5 * sum((x - ms) * (y - mi) for x, y in zip(sw, iw, strict=True)) / max(1, len(sw) - 1)
                denom = max(vs + vi - 2.0 * cov_si, 1e-8)
                w_s = (vi - cov_si) / denom
            w_s = max(min_slow, min(max_slow, w_s))
        out[d] = (w_s, 1.0 - w_s)
        # Append today's realized returns strictly AFTER setting today's weight (zero lookahead)
        s_hist.append(slow_rets_by_date[d])
        i_hist.append(ign_rets_by_date[d])
    return out


def run_dynamic_shared_ledger_blend(
    panel_1h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_targets_by_ts: dict[datetime, dict[str, float]],
    ignition_targets_by_ts: dict[datetime, dict[str, float]],
    sleeve_weights_by_date: dict[str, tuple[float, float]],
    *,
    default_weights: tuple[float, float] = (0.70, 0.30),
    fee_rate: Decimal = Decimal("0.0016"),
    max_asset_weight: float = 0.35,
    max_gross_weight: float = 0.95,
) -> dict:
    """Single shared SelfFinancingLedger with strictly causal time-varying sleeve weights."""
    by_avail = {s: {b.ts_avail: b for b in panel_1h.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_1h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    cur_slow: dict[str, float] = {s: 0.0 for s in symbols}
    prev_ign: dict[str, float] = {s: 0.0 for s in symbols}
    prev_day_w: tuple[float, float] = default_weights
    nav_by_date: dict[str, float] = {}
    used_slow_w: list[float] = []

    for ts in all_ts:
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        for sym in symbols:
            nxt, cur = by_start[sym].get(ts), by_avail[sym].get(ts)
            if nxt is not None and nxt.open > 0:
                exec_prices[sym] = Decimal(str(nxt.open))
                last_mark[sym] = exec_prices[sym]
                if cur is not None and cur.entry_eligible:
                    tradable.add(sym)
            elif cur is not None and cur.close > 0:
                exec_prices[sym] = Decimal(str(cur.close))
                last_mark[sym] = exec_prices[sym]
            elif sym in last_mark:
                exec_prices[sym] = last_mark[sym]

        day_iso = ts.date().isoformat()
        w_slow, w_ign = sleeve_weights_by_date.get(day_iso, default_weights)
        weight_shifted = abs(w_slow - prev_day_w[0]) >= 0.03
        slow_changed = ts in daily_targets_by_ts
        if slow_changed:
            cur_slow = daily_targets_by_ts[ts]
        ign_now = ignition_targets_by_ts.get(ts, prev_ign)
        ign_changed = any(abs(ign_now.get(s, 0.0) - prev_ign.get(s, 0.0)) > 1e-6 for s in symbols)
        prev_ign = ign_now

        if slow_changed or ign_changed or weight_shifted:
            prev_day_w = (w_slow, w_ign)
            raw = {
                s: min(max_asset_weight, w_slow * cur_slow.get(s, 0.0) + w_ign * ign_now.get(s, 0.0))
                for s in symbols
            }
            tot = sum(raw.values())
            if tot > max_gross_weight and tot > 0:
                sc = max_gross_weight / tot
                raw = {s: w * sc for s, w in raw.items()}
            ledger.rebalance_to_targets(ts, raw, exec_prices, tradable_symbols=tradable)

        nav_by_date[day_iso] = float(ledger.mark_nav(exec_prices))
        if slow_changed:
            used_slow_w.append(w_slow)

    return {
        "nav_by_date": nav_by_date,
        "fills": len(ledger.fills),
        "total_fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "turnover_multiple": round(float(ledger.cumulative_turnover_quote / ledger.starting_cash), 2),
        "avg_slow_weight": round(sum(used_slow_w) / max(1, len(used_slow_w)), 3),
    }


def _structural_breakdown_candidate(
    bar: BarPoint,
    bar_ret: float,
    prior_closes: list[float],
    prior_rets: list[float],
    prior_vols: list[float],
    btc_14d_ret: float,
    s1_val: float | None,
    *,
    floor_bars: int = 20,
    min_climax_z: float = -2.5,
    vol_mult: float = 1.15,
    rs_lag_threshold: float = -0.03,
) -> tuple[float, float] | None:
    """Identify structural bear-market support breakdowns on relative-strength laggards, excluding exhaustion climaxes."""
    if s1_val is None or s1_val > -0.35:
        return None
    if len(prior_closes) < floor_bars or len(prior_rets) < 20 or len(prior_vols) < 20:
        return None
    if bar.close >= min(prior_closes[-floor_bars:]):
        return None
    med_v = median(prior_vols[-20:])
    if med_v <= 0 or bar.volume < vol_mult * med_v:
        return None
    mean_r = sum(prior_rets[-20:]) / 20.0
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in prior_rets[-20:]) / 19.0)
    z = (bar_ret - mean_r) / max(std_r, 1e-4)
    # Exclude violent climax flushes (z < min_climax_z) that snap back violently
    if z < min_climax_z or z > -0.5:
        return None
    coin_14d = (bar.close - prior_closes[-14]) / max(prior_closes[-14], 1e-9)
    rs_diff = coin_14d - btc_14d_ret
    if rs_diff > rs_lag_threshold:
        return None
    score = (-s1_val) + (-rs_diff * 4.0)
    return score, max(std_r, 0.01)


def simulate_structural_breakdown_short(
    panel_1d: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    sigs_1d: dict[datetime, dict[str, SleeveSignal]],
    *,
    label: str,
    leg_cost: float = 0.0025,
    borrow_per_day: float = 0.0009,      # Wallex 0.015%/4h * 6 = 0.09%/day (32.85%/yr); 0.0 for perp counterfactual
    liq_margin_ratio: float = 0.15,
    max_breadth_gate: float = 0.25,
    max_hold_days: int = 10,
    trail_stop_mult: float = 2.5,
    hard_stop_pct: float = 0.06,
    max_slots: int = 3,
    slot_frac: float = 0.30,
    stress_iso: str = "2025-11-24",
) -> tuple[LeveredIgnitionResult, dict[str, float]]:
    """Multi-week 1d bear-momentum structural support breakdown short on relative-strength laggards."""
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    close_hist: dict[str, list[float]] = {s: [] for s in symbols}
    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    vol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}

    equity = 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    entries, wins, closed, liqs = 0, 0, 0, 0
    hold_h, total_borrow, total_fees = 0.0, 0.0, 0.0

    for ts in all_ts:
        btc_h = close_hist.get("BTCUSDT", [])
        btc_cur = by_avail.get("BTCUSDT", {}).get(ts)
        btc_14d = ((btc_cur.close - btc_h[-14]) / max(btc_h[-14], 1e-9)) if (btc_cur and len(btc_h) >= 14) else 0.0
        day_sigs = sigs_1d.get(ts, {})
        btc_sig = day_sigs.get("BTCUSDT")
        day_br = next((s.crypto_breadth for s in day_sigs.values() if s.crypto_breadth is not None), None)
        bear_ok = (
            day_br is not None
            and day_br <= max_breadth_gate
            and btc_sig is not None
            and (btc_sig.s1_trend or 0.0) <= -0.10
        )

        cands: list[tuple[float, str, float]] = []
        for sym in symbols:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_close[sym]) / prev_close[sym]) if (sym in prev_close and prev_close[sym] > 0) else 0.0
            if bear_ok and sym != "BTCUSDT" and cur.entry_eligible and nxt and nxt.open > 0 and sym not in active:
                s1_v = day_sigs[sym].s1_trend if sym in day_sigs else None
                hit = _structural_breakdown_candidate(
                    cur, r, close_hist[sym], ret_hist[sym], vol_hist[sym], btc_14d, s1_v,
                )
                if hit is not None:
                    cands.append((hit[0], sym, hit[1]))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append(r)
            prev_close[sym] = cur.close
            close_hist[sym].append(cur.close)
            vol_hist[sym].append(cur.volume)

        for sym in list(active):
            pos = active[sym]
            is_c, is_l, pnl, brw, fee = _check_margin_exit(
                pos, by_avail[sym].get(ts), by_start[sym].get(ts),
                side="SHORT", leverage=1.0, max_hold_bars=max_hold_days,
                trail_stop_mult=trail_stop_mult, hard_stop_pct=hard_stop_pct,
                leg_cost=leg_cost, borrow_per_bar=borrow_per_day,
            )
            equity -= brw
            total_borrow += brw
            total_fees += fee
            if is_c:
                equity = max(0.0, equity + pnl)
                closed += 1
                hold_h += pos["age"] * 24.0
                if is_l:
                    liqs += 1
                elif pnl - pos["entry_fee"] > 0:
                    wins += 1
                del active[sym]

        if equity > 100.0 and bear_ok and cands and len(active) < max_slots:
            cands.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in cands:
                if len(active) >= max_slots:
                    break
                nxt = by_start[sym].get(ts)
                if nxt is None or nxt.open <= 0:
                    continue
                free_col = max(0.0, equity - sum(p["collateral"] for p in active.values()))
                col = min(equity * slot_frac, free_col)
                if col < 25.0:
                    continue
                ef = col * leg_cost
                equity = max(0.0, equity - ef)
                total_fees += ef
                active[sym] = {
                    "collateral": col, "notional": col, "qty": col / nxt.open,
                    "entry_px": nxt.open, "entry_fee": ef, "extreme": nxt.open,
                    "b_vol": b_vol, "liq_price": nxt.open * (2.0 - liq_margin_ratio), "age": 0,
                }
                entries += 1

        unreal = sum(
            max(-pos["collateral"], pos["qty"] * (pos["entry_px"] - by_avail[s][ts].close))
            for s, pos in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        nav_by_date[ts.date().isoformat()] = max(0.0, equity + unreal)

    res = _summarize_levered_nav(
        label, "SHORT_STRUCTURAL", 1.0, len(symbols), 0, leg_cost,
        nav_by_date, stress_iso, entries, wins, closed, liqs, hold_h, total_borrow, total_fees,
    )
    return res, nav_by_date
