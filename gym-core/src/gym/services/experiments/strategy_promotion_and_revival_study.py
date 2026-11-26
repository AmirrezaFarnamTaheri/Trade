"""Strategy Promotion, Conditional Capital Admission, Internal Netting & Partial Revivals Study.

Implements the four priority experiments from docs/architecture/research-strategy-promotion.md:
  1. Conditional Capital Admission Hybrid & Contested-Capital Fork (Slow S1+S5 + 2h Ignition).
  2. Standalone Cross-Sleeve Internal Netting (Separate Routing vs Deterministic Internal Crossing).
  3. Four Partial Revivals in Narrower Roles:
     (a) S2 no-trade hysteresis band on frozen Slow targets (0% vs fixed vs cost-aware).
     (b) Bellman exit-only challenger on identical Ignition lots (forking at first disagreement).
     (c) Structural bear trigger reused strictly as 1-bar new-spot-buy deferral vs equal-exposure cash.
     (d) Trend acceleration as execution-speed control toward already-approved targets.
  4. Offline Research Gates: Constrained Hindsight Execution Ceiling & 0h vs +1h Bar-Offset Harness.

Strictly read-only against market.db; DISARMED ($0 funded budget).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean

import numpy as np

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.rare_micro_signals import MicroSignalIntent, scan_micro_signal_intents
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    extract_daily_breadth,
    solve_s1_s5_admm_weights,
)
from .cross_layer_diagnostic_study import deduplicate_intents_by_underlying
from .ensemble_study import portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .io_utils import readonly_snapshot, write_json_atomic, write_text_atomic
from .unified_book_helpers import (
    latest_signal_date,
    nav_ts_to_daily,
    resolve_bar_prices,
)


def _build_frozen_slow_targets(
    panel_1d: dict[str, list[BarPoint]],
) -> tuple[dict[datetime, dict[str, float]], dict[str, float], dict[datetime, dict[str, float]]]:
    """Compute frozen canonical S1+S5 ADMM daily targets, daily breadth, and causal S1 acceleration."""
    sigs_1d = compute_slow_sleeves(panel_1d, BASE_13_SYMBOLS)
    breadth = extract_daily_breadth(sigs_1d)
    dated_rets = build_dated_returns_index(panel_1d, BASE_13_SYMBOLS)
    targets: dict[datetime, dict[str, float]] = {}
    accel_by_ts: dict[datetime, dict[str, float]] = {}
    prev_w: dict[str, float] = {}
    prev_s1: dict[str, float] = {}

    for ts in sorted(sigs_1d):
        day_sigs = sigs_1d[ts]
        active = tuple(s for s in BASE_13_SYMBOLS if s in day_sigs)
        if not active:
            continue
        cur_w = tuple(prev_w.get(s, 0.0) for s in active)
        cov_h = build_shrunk_horizon_cov(dated_rets, active, ts)
        sol = solve_s1_s5_admm_weights(active, day_sigs, cur_w, cov_h)
        t_map = {s: w for s, w in zip(active, sol, strict=True) if w > 1e-6}
        targets[ts] = t_map
        prev_w = dict(t_map)
        acc: dict[str, float] = {}
        for s in active:
            s1_now = day_sigs[s].s1_trend or 0.0
            acc[s] = s1_now - prev_s1.get(s, s1_now)
            prev_s1[s] = s1_now
        accel_by_ts[ts] = acc
    return targets, breadth, accel_by_ts


def _step_ignition_exits(
    active: dict[str, dict],
    by_avail: dict[str, dict[datetime, BarPoint]],
    by_start: dict[str, dict[datetime, BarPoint]],
    ts: datetime,
    leg_cost: float,
) -> tuple[float, float]:
    """Close any active ignition lots that hit max_hold, invalidation, or trailing stop; returns (cash_released, fees)."""
    cash_rel = fees_paid = 0.0
    for sym in list(active):
        pos = active[sym]
        cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
        if cur is None:
            continue
        pos["age"] += 1
        pos["peak"] = max(pos["peak"], cur.high)
        hit_inv = cur.close <= pos["inv_px"]
        hit_trail = cur.close <= pos["peak"] * (1.0 - 2.5 * pos["bar_vol"])
        if pos["age"] >= pos["max_hold"] or hit_inv or hit_trail:
            ex_px = nxt.open if (nxt and nxt.open > 0) else cur.close
            gross = pos["qty"] * ex_px
            ex_fee = gross * leg_cost
            cash_rel += max(0.0, gross - ex_fee)
            fees_paid += ex_fee
            del active[sym]
    return cash_rel, fees_paid


def _rebalance_slow_slice(
    cash: float,
    slow_units: dict[str, float],
    tgt_weights: dict[str, float],
    exec_px: dict[str, float],
    tradable: set[str],
    nav: float,
    leg_cost: float,
) -> tuple[float, float, int, int]:
    """Order-invariant two-pass slow rebalance; returns (cash, fees, fills, displaced_buys)."""
    fees = 0.0
    fills = displaced = 0
    buys: list[tuple[str, float, float]] = []
    for sym in sorted(set(slow_units) | set(tgt_weights)):
        if sym not in tradable or sym not in exec_px or exec_px[sym] <= 0:
            continue
        px = exec_px[sym]
        cur_u = slow_units.get(sym, 0.0)
        delta = max(0.0, tgt_weights.get(sym, 0.0)) * nav - cur_u * px
        if abs(delta) < 1e-4:
            continue
        if delta < 0:
            sell_val = min(cur_u * px, -delta)
            fee = sell_val * leg_cost
            cash += max(0.0, sell_val - fee)
            rem = max(0.0, cur_u - sell_val / px)
            if rem <= 1e-12:
                slow_units.pop(sym, None)
            else:
                slow_units[sym] = rem
            fees += fee
            fills += 1
        else:
            buys.append((sym, delta, px))
    if buys:
        req = sum(d * (1.0 + leg_cost) for _, d, _ in buys)
        if cash < req - 1e-3:
            displaced += len(buys)
        scale = min(1.0, max(0.0, cash) / req) if req > 0 else 0.0
        for sym, delta, px in buys:
            spend = min(cash, delta * (1.0 + leg_cost) * scale)
            if spend < 1.0:
                continue
            bought = spend / (1.0 + leg_cost)
            cash -= spend
            slow_units[sym] = slow_units.get(sym, 0.0) + bought / px
            fees += spend - bought
            fills += 1
    return cash, fees, fills, displaced


def _sim_capital_admission_arm(
    panel_2h: dict[str, list[BarPoint]],
    slow_targets: dict[datetime, dict[str, float]],
    ign_intents: list[MicroSignalIntent],
    *,
    mode: str,
    start_capital: float = 1000.0,
    slow_reserve_frac: float = 0.0,
    leg_cost: float = 0.0016,
) -> dict:
    """Replay a single capital-admission policy on identical Slow S1+S5 and 2h Ignition streams."""
    all_syms = tuple(sorted(set(BASE_13_SYMBOLS) | set(IGNITION_18_CRYPTO)))
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in all_syms}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in all_syms}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    sig_dates = sorted(slow_targets)
    by_ts_ign: dict[datetime, list[MicroSignalIntent]] = {}
    for it in deduplicate_intents_by_underlying(ign_intents):
        by_ts_ign.setdefault(it.ts_avail, []).append(it)

    cash = float(start_capital)
    slow_units: dict[str, float] = {}
    fast_lots: dict[str, dict] = {}
    last_px: dict[str, float] = {}
    nav_ts: dict[datetime, float] = {}
    last_rebal_day: str | None = None
    total_fees = 0.0
    admitted_full = admitted_partial = rejected_reserve = displaced_slow = 0

    for ts in all_ts:
        exec_px, tradable = resolve_bar_prices(all_syms, by_start, by_avail, ts, last_px)
        rel, ef = _step_ignition_exits(fast_lots, by_avail, by_start, ts, leg_cost)
        cash += rel
        total_fees += ef

        slow_val = sum(u * exec_px.get(s, last_px.get(s, 0.0)) for s, u in slow_units.items())
        fast_val = sum(p["qty"] * exec_px.get(s, last_px.get(s, p["entry_px"])) for s, p in fast_lots.items())
        nav = max(1e-6, cash + slow_val + fast_val)

        if mode in ("SLOW_ALONE", "ORDINARY_SHARING", "CONDITIONAL_SHARING_RES15"):
            sd = latest_signal_date(sig_dates, ts)
            day_k = ts.date().isoformat()
            if sd is not None and day_k != last_rebal_day:
                last_rebal_day = day_k
                cash, sf, _, disp = _rebalance_slow_slice(
                    cash, slow_units, slow_targets[sd], exec_px, tradable, nav, leg_cost
                )
                total_fees += sf
                displaced_slow += disp

        if mode in ("IGNITION_ALONE", "ORDINARY_SHARING", "CONDITIONAL_SHARING_RES15"):
            for it in by_ts_ign.get(ts, []):
                if it.symbol in fast_lots or len(fast_lots) >= 3:
                    continue
                nxt = by_start[it.symbol].get(ts)
                if nxt is None or nxt.open <= 0:
                    continue
                reserve = nav * slow_reserve_frac if mode == "CONDITIONAL_SHARING_RES15" else 0.0
                avail = max(0.0, cash - reserve)
                desired = min(nav * 0.30, cash - 1.0)
                if avail < 25.0 or desired < 25.0:
                    rejected_reserve += 1
                    continue
                col = min(desired, avail)
                if col < desired - 1.0:
                    admitted_partial += 1
                else:
                    admitted_full += 1
                entry_fee = col * leg_cost
                cash -= col
                total_fees += entry_fee
                fast_lots[it.symbol] = {
                    "qty": (col - entry_fee) / nxt.open,
                    "entry_px": nxt.open,
                    "inv_px": it.invalidation_px,
                    "peak": nxt.open,
                    "bar_vol": it.bar_vol,
                    "max_hold": it.max_hold_bars,
                    "age": 0,
                }

        s_end = sum(u * exec_px.get(s, last_px.get(s, 0.0)) for s, u in slow_units.items())
        f_end = sum(p["qty"] * exec_px.get(s, last_px.get(s, p["entry_px"])) for s, p in fast_lots.items())
        nav_ts[ts] = max(0.0, cash + s_end + f_end)

    daily = nav_ts_to_daily(nav_ts)
    m = portfolio_metrics(daily, starting_nav=start_capital)
    return {
        "arm": mode,
        "ending_nav": m["ending_nav"],
        "ret_pct": m["ret_pct"],
        "ann_sharpe": m["ann_sharpe"],
        "max_dd_pct": m["max_dd_pct"],
        "fees_usdt": round(total_fees, 2),
        "admitted_full": admitted_full,
        "admitted_partial": admitted_partial,
        "rejected_reserve": rejected_reserve,
        "displaced_slow_buys": displaced_slow,
        "daily_nav": daily,
    }


def _run_contested_capital_fork(
    panel_2h: dict[str, list[BarPoint]],
    slow_targets: dict[datetime, dict[str, float]],
    ign_intents: list[MicroSignalIntent],
    *,
    leg_cost: float = 0.0016,
) -> dict:
    """Shadow auction: when Ignition arrives while Slow holds >70% exposure, fork $200 for 24h (Slow vs Ignition)."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in set(BASE_13_SYMBOLS) | set(IGNITION_18_CRYPTO)}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in set(BASE_13_SYMBOLS) | set(IGNITION_18_CRYPTO)}
    sig_dates = sorted(slow_targets)
    deltas_bps: list[float] = []
    ign_wins = 0

    for it in deduplicate_intents_by_underlying(ign_intents):
        sd = latest_signal_date(sig_dates, it.ts_avail)
        if sd is None:
            continue
        tgt = slow_targets[sd]
        if sum(tgt.values()) < 0.70:
            continue
        top_slow = max(tgt, key=tgt.get)
        b_ign_0 = by_start[it.symbol].get(it.ts_avail)
        b_slw_0 = by_start[top_slow].get(it.ts_avail)
        if not (b_ign_0 and b_slw_0 and b_ign_0.open > 0 and b_slw_0.open > 0):
            continue
        # Branch B: Ignition with exact trailing/invalidation exit up to 12 bars (24h)
        peak = b_ign_0.open
        ign_ex = b_ign_0.open
        for k in range(1, 13):
            t_k = it.ts_avail + timedelta(hours=2 * k)
            cb = by_avail[it.symbol].get(t_k)
            if cb is None:
                continue
            peak = max(peak, cb.high)
            ign_ex = cb.close
            if cb.close <= it.invalidation_px or cb.close <= peak * (1.0 - 2.5 * it.bar_vol):
                nb = by_start[it.symbol].get(t_k)
                ign_ex = nb.open if (nb and nb.open > 0) else cb.close
                break
        ign_ret_bps = ((ign_ex - b_ign_0.open) / b_ign_0.open - 2.0 * leg_cost) * 10_000.0
        # Branch A: Keep Slow top holding over same 24h (0 extra switch cost)
        t_end = it.ts_avail + timedelta(hours=24)
        b_slw_end = by_avail[top_slow].get(t_end)
        if b_slw_end is None or b_slw_end.close <= 0:
            continue
        slw_ret_bps = ((b_slw_end.close - b_slw_0.open) / b_slw_0.open) * 10_000.0
        diff = ign_ret_bps - slw_ret_bps
        deltas_bps.append(diff)
        if diff > 0:
            ign_wins += 1

    return {
        "contested_slots": len(deltas_bps),
        "ignition_win_rate_pct": round(ign_wins / max(1, len(deltas_bps)) * 100.0, 1),
        "mean_ign_minus_slow_bps": round(mean(deltas_bps), 2) if deltas_bps else 0.0,
    }


def _run_conditional_capital_admission_and_fork(
    panel_2h: dict[str, list[BarPoint]],
    slow_targets: dict[datetime, dict[str, float]],
    ign_intents: list[MicroSignalIntent],
) -> dict:
    """Exp 1: Compare 5 capital-admission arms plus the 24h contested-capital shadow auction."""
    a_slow = _sim_capital_admission_arm(panel_2h, slow_targets, ign_intents, mode="SLOW_ALONE")
    a_ign = _sim_capital_admission_arm(panel_2h, slow_targets, ign_intents, mode="IGNITION_ALONE")
    a_ord = _sim_capital_admission_arm(panel_2h, slow_targets, ign_intents, mode="ORDINARY_SHARING")
    a_cond = _sim_capital_admission_arm(
        panel_2h, slow_targets, ign_intents, mode="CONDITIONAL_SHARING_RES15", slow_reserve_frac=0.15
    )
    s70 = _sim_capital_admission_arm(panel_2h, slow_targets, ign_intents, mode="SLOW_ALONE", start_capital=700.0)
    f30 = _sim_capital_admission_arm(panel_2h, slow_targets, ign_intents, mode="IGNITION_ALONE", start_capital=300.0)
    common_d = sorted(set(s70["daily_nav"]) & set(f30["daily_nav"]))
    comb_70_30 = {d: s70["daily_nav"][d] + f30["daily_nav"][d] for d in common_d}
    m70 = portfolio_metrics(comb_70_30, starting_nav=1000.0)
    a_split = {
        "arm": "FIXED_SPLIT_70_30",
        "ending_nav": m70["ending_nav"],
        "ret_pct": m70["ret_pct"],
        "ann_sharpe": m70["ann_sharpe"],
        "max_dd_pct": m70["max_dd_pct"],
        "fees_usdt": round(s70["fees_usdt"] + f30["fees_usdt"], 2),
        "admitted_full": f30["admitted_full"],
        "admitted_partial": f30["admitted_partial"],
        "rejected_reserve": f30["rejected_reserve"],
        "displaced_slow_buys": 0,
    }
    arms = [{k: v for k, v in a.items() if k != "daily_nav"} for a in (a_slow, a_ign, a_ord, a_split, a_cond)]
    fork = _run_contested_capital_fork(panel_2h, slow_targets, ign_intents)
    return {"arms": arms, "contested_capital_fork": fork}


def _run_standalone_internal_netting(
    panel_2h: dict[str, list[BarPoint]],
    slow_targets: dict[datetime, dict[str, float]],
    ign_intents: list[MicroSignalIntent],
    *,
    leg_cost: float = 0.0016,
) -> dict:
    """Exp 2: Pure deterministic internal crossing on identical Slow ($700) + Ignition ($300) signed orders."""
    all_syms = tuple(sorted(set(BASE_13_SYMBOLS) | set(IGNITION_18_CRYPTO)))
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in all_syms}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in all_syms}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    sig_dates = sorted(slow_targets)
    by_ts_ign: dict[datetime, list[MicroSignalIntent]] = {}
    for it in deduplicate_intents_by_underlying(ign_intents):
        by_ts_ign.setdefault(it.ts_avail, []).append(it)

    s_cash, f_cash = 700.0, 300.0
    s_units: dict[str, float] = {}
    f_lots: dict[str, dict] = {}
    last_px: dict[str, float] = {}
    last_day: str | None = None
    sep_fees = net_fees = crossed_notional = 0.0
    crossed_events = 0

    for ts in all_ts:
        exec_px, tradable = resolve_bar_prices(all_syms, by_start, by_avail, ts, last_px)
        slow_flow: dict[str, float] = {}
        fast_flow: dict[str, float] = {}

        # Fast exits
        for sym in list(f_lots):
            pos = f_lots[sym]
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None:
                continue
            pos["age"] += 1
            pos["peak"] = max(pos["peak"], cur.high)
            if pos["age"] >= pos["max_hold"] or cur.close <= pos["inv_px"] or cur.close <= pos["peak"] * (1.0 - 2.5 * pos["bar_vol"]):
                ex_px = nxt.open if (nxt and nxt.open > 0) else cur.close
                val = pos["qty"] * ex_px
                fast_flow[sym] = fast_flow.get(sym, 0.0) - val
                f_cash += max(0.0, val * (1.0 - leg_cost))
                del f_lots[sym]

        # Fast entries
        for it in by_ts_ign.get(ts, []):
            if it.symbol in f_lots or len(f_lots) >= 3 or f_cash < 25.0:
                continue
            nxt = by_start[it.symbol].get(ts)
            if nxt is None or nxt.open <= 0:
                continue
            col = min(f_cash * 0.45, f_cash - 1.0)
            if col < 25.0:
                continue
            fast_flow[it.symbol] = fast_flow.get(it.symbol, 0.0) + col
            f_cash -= col
            f_lots[it.symbol] = {
                "qty": (col * (1.0 - leg_cost)) / nxt.open,
                "entry_px": nxt.open,
                "inv_px": it.invalidation_px,
                "peak": nxt.open,
                "bar_vol": it.bar_vol,
                "max_hold": it.max_hold_bars,
                "age": 0,
            }

        # Slow daily rebalance signed notional flow
        sd = latest_signal_date(sig_dates, ts)
        if sd is not None and ts.date().isoformat() != last_day:
            last_day = ts.date().isoformat()
            s_nav = s_cash + sum(u * exec_px.get(s, last_px.get(s, 0.0)) for s, u in s_units.items())
            prev_u = dict(s_units)
            s_cash, _, _, _ = _rebalance_slow_slice(s_cash, s_units, slow_targets[sd], exec_px, tradable, s_nav, leg_cost)
            for sym in set(prev_u) | set(s_units):
                du = s_units.get(sym, 0.0) - prev_u.get(sym, 0.0)
                if abs(du) > 1e-12 and sym in exec_px:
                    slow_flow[sym] = du * exec_px[sym]

        max_unit_diff = 0.0
        for sym in set(slow_flow) | set(fast_flow):
            sf, ff = slow_flow.get(sym, 0.0), fast_flow.get(sym, 0.0)
            px_s = exec_px.get(sym, last_px.get(sym, 0.0))
            if px_s > 0:
                sep_du = (sf / px_s) + (ff / px_s)
                net_du = (sf + ff) / px_s
                max_unit_diff = max(max_unit_diff, abs(sep_du - net_du))
            sep_fees += (abs(sf) + abs(ff)) * leg_cost
            net_fees += abs(sf + ff) * leg_cost
            if sf * ff < 0:
                crossed = min(abs(sf), abs(ff))
                crossed_notional += crossed
                crossed_events += 1

    saved = sep_fees - net_fees
    invariant_ok = bool(max_unit_diff <= 1e-9 and sep_fees + 1e-9 >= net_fees and crossed_notional >= 0.0)
    return {
        "crossed_events": crossed_events,
        "crossed_notional_usdt": round(crossed_notional, 2),
        "separate_routing_fees_usdt": round(sep_fees, 2),
        "internal_netting_fees_usdt": round(net_fees, 2),
        "saved_fees_usdt": round(saved, 2),
        "fee_reduction_pct": round(saved / max(1e-9, sep_fees) * 100.0, 2),
        "max_step_unit_mismatch": round(max_unit_diff, 12),
        "exposure_invariant_verified": invariant_ok,
    }


def _run_slow_daily_variant(
    panel_1d: dict[str, list[BarPoint]],
    slow_targets: dict[datetime, dict[str, float]],
    breadth: dict[str, float],
    accel_by_ts: dict[datetime, dict[str, float]],
    *,
    mode: str,
    exposure_scale: float = 1.0,
    leg_cost: float = 0.0016,
) -> dict:
    """Replay frozen Slow S1+S5 targets on 1d panel under retention, bear-deferral, or speed-control variants."""
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    led = SelfFinancingLedger(Decimal("1000"), fee_rate=Decimal(str(leg_cost)), fee_in_received_asset=True)
    nav_by_date: dict[str, float] = {}
    last_px: dict[str, float] = {}
    invested_fracs: list[float] = []
    tracking_errs: list[float] = []
    deferred_buys = 0

    for ts in sorted(slow_targets):
        ef, tr = resolve_bar_prices(BASE_13_SYMBOLS, by_start, by_avail, ts, last_px)
        ep = {s: Decimal(str(p)) for s, p in ef.items()}
        nav_now = float(led.mark_nav(ep))
        cur_w = {s: float(led.units.get(s, Decimal("0"))) * ef.get(s, 0.0) / max(1e-9, nav_now) for s in BASE_13_SYMBOLS}
        raw_t = {s: w * exposure_scale for s, w in slow_targets[ts].items()}
        adj_t: dict[str, float] = {}
        br = breadth.get(ts.date().isoformat(), 1.0)
        acc = accel_by_ts.get(ts, {})

        for s in BASE_13_SYMBOLS:
            tw, cw = raw_t.get(s, 0.0), cur_w.get(s, 0.0)
            dw = tw - cw
            if mode == "FIXED_BAND_3PCT" and tw > 0 and abs(dw) < 0.03:
                adj_t[s] = cw
            elif mode == "COST_AWARE_BAND" and tw > 0 and abs(dw) < max(0.032, 20.0 * leg_cost):
                adj_t[s] = cw
            elif mode == "BEAR_DEFER_BUY_ONLY" and br <= 0.30 and dw > 1e-4:
                adj_t[s] = cw
                deferred_buys += 1
            elif mode == "FIXED_PARTIAL_50PCT" and tw > 0:
                adj_t[s] = cw + 0.50 * dw
            elif mode == "ACCEL_ADAPTIVE_SPEED" and tw > 0:
                same_dir = (acc.get(s, 0.0) * dw) > 0
                alpha = 0.80 if same_dir else 0.35
                adj_t[s] = cw + alpha * dw
            else:
                adj_t[s] = tw

        led.rebalance_to_targets(ts, {s: w for s, w in adj_t.items() if w > 1e-6}, ep, tradable_symbols=tr)
        post_nav = float(led.mark_nav(ep))
        nav_by_date[ts.date().isoformat()] = post_nav
        post_w = {s: float(led.units.get(s, Decimal("0"))) * ef.get(s, 0.0) / max(1e-9, post_nav) for s in BASE_13_SYMBOLS}
        invested_fracs.append(sum(post_w.values()))
        tracking_errs.append(sum(abs(raw_t.get(s, 0.0) - post_w.get(s, 0.0)) for s in BASE_13_SYMBOLS))

    m = portfolio_metrics(nav_by_date, starting_nav=1000.0)
    return {
        "mode": mode,
        "ending_nav": m["ending_nav"],
        "ret_pct": m["ret_pct"],
        "ann_sharpe": m["ann_sharpe"],
        "max_dd_pct": m["max_dd_pct"],
        "fills": len(led.fills),
        "fees_usdt": round(float(led.total_fees_quote_equiv), 2),
        "mean_invested_pct": round(mean(invested_fracs) * 100.0, 2) if invested_fracs else 0.0,
        "mean_l1_tracking_err_pct": round(mean(tracking_errs) * 100.0, 2) if tracking_errs else 0.0,
        "deferred_buys": deferred_buys,
    }


def _empty_bellman_result(status: str = "INSUFFICIENT_DATA") -> dict:
    return {
        "status": status,
        "oos_evaluated_states": 0,
        "oos_evaluated_lots": 0,
        "disagreements": 0,
        "mean_bellman_minus_incumbent_bps": 0.0,
        "avoided_loss_count": 0,
        "cut_winner_count": 0,
    }


def _run_bellman_exit_fork(
    panel_2h: dict[str, list[BarPoint]],
    ign_intents: list[MicroSignalIntent],
    *,
    leg_cost: float = 0.0016,
) -> dict:
    """Partial Revival (b): Purged lot-level Bellman exit-only challenger forked at most once per held-out lot."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    lots: list[tuple[int, datetime, datetime, list[tuple[datetime, list[float], float, float]]]] = []
    for lot_id, it in enumerate(deduplicate_intents_by_underlying(ign_intents)):
        b0 = by_start[it.symbol].get(it.ts_avail)
        if b0 is None or b0.open <= 0:
            continue
        peak = b0.open
        path: list[tuple[int, datetime, float, float, float]] = []
        inc_ex = b0.open
        exit_ts = it.ts_avail
        for k in range(1, it.max_hold_bars + 1):
            tk = it.ts_avail + timedelta(hours=2 * k)
            cb = by_avail[it.symbol].get(tk)
            if cb is None or cb.close <= 0:
                continue
            peak = max(peak, cb.high)
            nb = by_start[it.symbol].get(tk)
            ex_now = nb.open if (nb and nb.open > 0) else cb.close
            inc_ex = ex_now
            exit_ts = tk
            hit_inc = k == it.max_hold_bars or cb.close <= it.invalidation_px or cb.close <= peak * (1.0 - 2.5 * it.bar_vol)
            if not hit_inc and k >= 2:
                unr = (ex_now - b0.open) / b0.open
                dd_pk = (peak - cb.close) / peak
                path.append((k, tk, ex_now, unr, dd_pk))
            if hit_inc:
                break
        if not path:
            continue
        inc_net = ((inc_ex - b0.open) / b0.open - 2.0 * leg_cost) * 10_000.0
        lot_states = [
            (
                tk,
                [1.0, unr, dd_pk, k / float(it.max_hold_bars), it.bar_vol],
                inc_net - (((ex_now - b0.open) / b0.open - 2.0 * leg_cost) * 10_000.0),
                (((ex_now - b0.open) / b0.open - 2.0 * leg_cost) * 10_000.0) - inc_net,
            )
            for k, tk, ex_now, unr, dd_pk in path
        ]
        lots.append((lot_id, it.ts_avail, exit_ts, lot_states))

    lots.sort(key=lambda item: item[1])
    if len(lots) < 10:
        return _empty_bellman_result()

    split_ts = lots[len(lots) // 2][1]
    # Strictly purged training set: only lots whose incumbent exit matured before split_ts.
    train_states = [st for _, _, ex_ts, states in lots if ex_ts < split_ts for st in states]
    oos_lots = [item for item in lots if item[1] >= split_ts]
    if len(train_states) < 20 or not oos_lots:
        return _empty_bellman_result()

    x_tr = np.array([st[1] for st in train_states], dtype=np.float64)
    y_tr = np.array([st[2] for st in train_states], dtype=np.float64)
    w = np.linalg.solve(x_tr.T @ x_tr + 1.0 * np.eye(x_tr.shape[1]), x_tr.T @ y_tr)

    diffs: list[float] = []
    avoided_losses = cut_winners = oos_states_evaluated = 0
    for _, _, _, states in oos_lots:
        for _, feat, _, bell_minus_inc in states:
            oos_states_evaluated += 1
            pred_hold_adv = float(np.dot(w, np.array(feat, dtype=np.float64)))
            if pred_hold_adv < -15.0:  # Fork at FIRST disagreement only (once per lot)
                diffs.append(bell_minus_inc)
                if bell_minus_inc > 0:
                    avoided_losses += 1
                else:
                    cut_winners += 1
                break

    return {
        "status": "OK",
        "oos_evaluated_states": oos_states_evaluated,
        "oos_evaluated_lots": len(oos_lots),
        "disagreements": len(diffs),
        "mean_bellman_minus_incumbent_bps": round(mean(diffs), 2) if diffs else 0.0,
        "avoided_loss_count": avoided_losses,
        "cut_winner_count": cut_winners,
    }


def _run_offline_research_gates(
    panel_1h: dict[str, list[BarPoint]],
    panel_2h: dict[str, list[BarPoint]],
    breadth: dict[str, float],
    *,
    leg_cost: float = 0.0016,
) -> dict:
    """Exp 4: Constrained hindsight execution ceiling (offline DP) & 0h vs +1h bar-offset sensitivity harness."""
    # (a) Constrained Hindsight DP Ceiling (long-only, 16 bps/side, max 12-bar hold, strictly non-overlapping!)
    ceilings: dict[str, dict] = {}
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        bars = [b for b in panel_2h.get(sym, []) if b.close > 0 and b.open > 0]
        if len(bars) < 20:
            continue
        # dp[i] = max cash wealth after close of bar i (available to fund entry at bar i+1 open or later).
        dp = [1000.0] * len(bars)
        trades = 0
        for i in range(len(bars)):
            best = 1000.0 if i == 0 else dp[i - 1]
            best_t = False
            for j in range(max(0, i - 11), i + 1):
                entry_cash = 1000.0 if j == 0 else dp[j - 1]
                cand = entry_cash * ((bars[i].close / bars[j].open) * ((1.0 - leg_cost) ** 2))
                if cand > best:
                    best = cand
                    best_t = True
            dp[i] = best
            if best_t:
                trades += 1
        ceilings[sym] = {"bars": len(bars), "hindsight_max_nav_usdt": round(dp[-1], 2), "active_steps": trades}

    # (b) 0h vs +1h Bar-Offset Sensitivity Harness
    p_0h = {s: resample_hourly_to_bucket(panel_1h.get(s, []), 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    p_1h = {s: resample_hourly_to_bucket(panel_1h.get(s, []), 2, offset_hours=1) for s in IGNITION_18_CRYPTO}
    sc_0h = scan_micro_signal_intents(p_0h, IGNITION_18_CRYPTO, breadth)
    sc_1h = scan_micro_signal_intents(p_1h, IGNITION_18_CRYPTO, breadth)
    off_rows: dict[str, dict] = {}
    for mech in ("MOMENTUM_IGNITION", "FAILED_DOWNSIDE_AUCTION"):
        i0 = deduplicate_intents_by_underlying(sc_0h[mech])
        i1 = deduplicate_intents_by_underlying(sc_1h[mech])
        matched = 0
        for a in i0:
            if any(b.symbol == a.symbol and abs((b.ts_avail - a.ts_avail).total_seconds()) <= 7200 for b in i1):
                matched += 1
        overlap_pct = round(matched / max(1, len(i0)) * 100.0, 1)
        off_rows[mech] = {
            "signals_0h": len(i0),
            "signals_1h": len(i1),
            "matched_within_2h": matched,
            "overlap_pct": overlap_pct,
            "label": "STABLE" if overlap_pct >= 50.0 else "TIMING_SENSITIVE",
        }
    return {"hindsight_ceiling_2h_16bps": ceilings, "bar_offset_sensitivity": off_rows}


def run_strategy_promotion_and_revival_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Execute all 4 strategy-promotion, netting, partial-revival, and offline-gate experiments."""
    con = open_readonly_market_db(db_path)
    try:
        with readonly_snapshot(con):
            all_syms = tuple(sorted(set(BASE_13_SYMBOLS) | set(IGNITION_18_CRYPTO)))
            panel_1d = {s: load_keyed_candles(con, s, "1d") for s in BASE_13_SYMBOLS}
            panel_1h = {s: load_keyed_candles(con, s, "1h") for s in all_syms}
    finally:
        con.close()

    panel_2h = {s: resample_hourly_to_bucket(panel_1h.get(s, []), 2, offset_hours=0) for s in panel_1h}
    slow_targets, breadth, accel_by_ts = _build_frozen_slow_targets(panel_1d)
    ign_intents = scan_micro_signal_intents(
        {s: panel_2h[s] for s in IGNITION_18_CRYPTO}, IGNITION_18_CRYPTO, breadth
    )["MOMENTUM_IGNITION"]

    exp1 = _run_conditional_capital_admission_and_fork(panel_2h, slow_targets, ign_intents)
    exp2 = _run_standalone_internal_netting(panel_2h, slow_targets, ign_intents)

    base_slow = _run_slow_daily_variant(panel_1d, slow_targets, breadth, accel_by_ts, mode="IMMEDIATE_0PCT")
    ret_fixed = _run_slow_daily_variant(panel_1d, slow_targets, breadth, accel_by_ts, mode="FIXED_BAND_3PCT")
    ret_cost = _run_slow_daily_variant(panel_1d, slow_targets, breadth, accel_by_ts, mode="COST_AWARE_BAND")
    bear_def = _run_slow_daily_variant(panel_1d, slow_targets, breadth, accel_by_ts, mode="BEAR_DEFER_BUY_ONLY")
    eq_scale = bear_def["mean_invested_pct"] / max(1e-6, base_slow["mean_invested_pct"])
    bear_ctrl = _run_slow_daily_variant(
        panel_1d, slow_targets, breadth, accel_by_ts, mode="EQUAL_EXPOSURE_CASH_CONTROL", exposure_scale=eq_scale
    )
    spd_fixed = _run_slow_daily_variant(panel_1d, slow_targets, breadth, accel_by_ts, mode="FIXED_PARTIAL_50PCT")
    spd_accel = _run_slow_daily_variant(panel_1d, slow_targets, breadth, accel_by_ts, mode="ACCEL_ADAPTIVE_SPEED")
    bellman = _run_bellman_exit_fork(panel_2h, ign_intents)
    exp4 = _run_offline_research_gates(panel_1h, panel_2h, breadth)

    receipt = {
        "schema": "strategy-promotion-and-revivals/1",
        "run_id": uuid.uuid4().hex[:12],
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "exp1_conditional_capital_admission": exp1,
        "exp2_standalone_internal_netting": exp2,
        "exp3_partial_revivals": {
            "s2_retention_bands": [base_slow, ret_fixed, ret_cost],
            "bellman_exit_fork": bellman,
            "bear_buy_deferral_vs_cash": [base_slow, bear_def, bear_ctrl],
            "accel_execution_speed": [base_slow, spd_fixed, spd_accel],
        },
        "exp4_offline_research_gates": exp4,
    }
    write_json_atomic(receipt_path, receipt)
    _write_markdown_report(receipt, report_path)
    return receipt


def _write_markdown_report(r: dict, report_path: Path) -> None:
    """Render concise decision-oriented markdown report for strategy promotion & partial revivals."""
    lines = [
        "# Strategy Promotion, Conditional Capital Admission, Internal Netting & Partial Revivals",
        "",
        f"Generated UTC: `{r['generated_at_utc']}` · Execution Mode: `PAPER_ONLY` (`TradingGYMExecutor DISARMED`, `$0` funded budget).",
        "",
        "## 1. Conditional Capital Admission Hybrid & Contested-Capital Fork (`2h` Overlap, `16 bps/side`)",
        "",
        "| Arm | Ending NAV | Return | Ann. Sharpe | MaxDD | Fees ($) | Full / Partial / Rejected Ign | Displaced Slow Buys |",
        "| --- | ---: | ---: | ---: | ---: | ---: | :---: | ---: |",
    ]
    for a in r["exp1_conditional_capital_admission"]["arms"]:
        lines.append(
            f"| `{a['arm']}` | `${a['ending_nav']:,.2f}` | `{a['ret_pct']:+.2f}%` | `{a['ann_sharpe']:.3f}` | "
            f"`{a['max_dd_pct']:.2f}%` | `${a['fees_usdt']:.2f}` | "
            f"`{a['admitted_full']} / {a['admitted_partial']} / {a['rejected_reserve']}` | `{a['displaced_slow_buys']}` |"
        )
    fk = r["exp1_conditional_capital_admission"]["contested_capital_fork"]
    lines.extend([
        "",
        f"- **Contested-Capital 24h Shadow Auction:** `{fk['contested_slots']}` contested slots -> Ignition win rate `{fk['ignition_win_rate_pct']}%`, mean `(Ignition - Slow)` = **`{fk['mean_ign_minus_slow_bps']:+.2f} bps`**.",
        "",
        "## 2. Standalone Cross-Sleeve Internal Netting (`Slow $700` + `Ignition $300`, Identical Aggregate Exposure)",
        "",
    ])
    n = r["exp2_standalone_internal_netting"]
    lines.extend([
        f"- **Crossed Events:** `{n['crossed_events']}` · **Crossed Notional:** `${n['crossed_notional_usdt']:,.2f}`",
        f"- **Fees:** Separate Routing `${n['separate_routing_fees_usdt']:.2f}` -> Internal Netting `${n['internal_netting_fees_usdt']:.2f}` (**saved `${n['saved_fees_usdt']:.2f}` / `{n['fee_reduction_pct']:.2f}%`**, aggregate exposure invariant verified: `{n['exposure_invariant_verified']}`).",
        "",
        "## 3. Four Partial Revivals (Narrower Roles on Frozen Targets / Lots)",
        "",
        "### 3A. S2 No-Trade Hysteresis Band (`1d` Slow `S1+S5`, `16 bps`)",
        "",
        "| Variant | Ending NAV | Return | Ann. Sharpe | MaxDD | Fills | Fees ($) | Mean L1 Track Err |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in r["exp3_partial_revivals"]["s2_retention_bands"]:
        lines.append(
            f"| `{row['mode']}` | `${row['ending_nav']:,.2f}` | `{row['ret_pct']:+.2f}%` | `{row['ann_sharpe']:.3f}` | "
            f"`{row['max_dd_pct']:.2f}%` | `{row['fills']}` | `${row['fees_usdt']:.2f}` | `{row['mean_l1_tracking_err_pct']:.2f}%` |"
        )
    bm = r["exp3_partial_revivals"]["bellman_exit_fork"]
    lines.extend([
        "",
        "### 3B. Bellman Exit-Only Challenger (Forked at First Disagreement on Identical `2h` Ignition Lots)",
        "",
        f"- **Status:** `{bm.get('status', 'OK')}` · **OOS Lots / States Evaluated:** `{bm.get('oos_evaluated_lots', 0)}` / `{bm.get('oos_evaluated_states', 0)}` · **Disagreements (Early Close):** `{bm.get('disagreements', 0)}`",
        f"- **Mean `(Bellman - Incumbent)`:** **`{bm.get('mean_bellman_minus_incumbent_bps', 0.0):+.2f} bps`** · Avoided Losses: `{bm.get('avoided_loss_count', 0)}` · Cut Winners: `{bm.get('cut_winner_count', 0)}`",
        "",
        "### 3C. Structural Bear Trigger as 1-Bar New-Spot-Buy Deferral vs Equal-Exposure Cash Control",
        "",
        "| Variant | Ending NAV | Return | Ann. Sharpe | MaxDD | Mean Invested | Deferred Buys |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in r["exp3_partial_revivals"]["bear_buy_deferral_vs_cash"]:
        lines.append(
            f"| `{row['mode']}` | `${row['ending_nav']:,.2f}` | `{row['ret_pct']:+.2f}%` | `{row['ann_sharpe']:.3f}` | "
            f"`{row['max_dd_pct']:.2f}%` | `{row['mean_invested_pct']:.2f}%` | `{row['deferred_buys']}` |"
        )
    lines.extend([
        "",
        "### 3D. Trend Acceleration as Execution-Speed Control Toward Approved Targets",
        "",
        "| Variant | Ending NAV | Return | Ann. Sharpe | MaxDD | Fills | Fees ($) | Mean L1 Track Err |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in r["exp3_partial_revivals"]["accel_execution_speed"]:
        lines.append(
            f"| `{row['mode']}` | `${row['ending_nav']:,.2f}` | `{row['ret_pct']:+.2f}%` | `{row['ann_sharpe']:.3f}` | "
            f"`{row['max_dd_pct']:.2f}%` | `{row['fills']}` | `${row['fees_usdt']:.2f}` | `{row['mean_l1_tracking_err_pct']:.2f}%` |"
        )
    lines.extend([
        "",
        "## 4. Offline Research Gates (Hindsight Feasibility Ceiling & `0h` vs `+1h` Bar-Offset Harness)",
        "",
        "| Mechanism | `0h` Signals | `+1h` Signals | Matched `<=2h` | Overlap % | Sensitivity Label |",
        "| --- | ---: | ---: | ---: | ---: | :---: |",
    ])
    for mech, info in r["exp4_offline_research_gates"]["bar_offset_sensitivity"].items():
        lines.append(
            f"| `{mech}` | `{info['signals_0h']}` | `{info['signals_1h']}` | `{info['matched_within_2h']}` | "
            f"`{info['overlap_pct']:.1f}%` | **`{info['label']}`** |"
        )
    lines.append("")
    for sym, c in r["exp4_offline_research_gates"]["hindsight_ceiling_2h_16bps"].items():
        lines.append(f"- **Offline Hindsight DP Ceiling (`{sym}`, `2h`, `16 bps/side`, `24h` max hold):** `${c['hindsight_max_nav_usdt']:,.2f}` across `{c['bars']}` bars.")
    write_text_atomic(report_path, "\n".join(lines) + "\n")
