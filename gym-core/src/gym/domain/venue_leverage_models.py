"""Pure domain models for Nobitex pay-as-you-go margin vs. Wallex fixed trade-credit economics.

All simulations are strictly causal (decision at bar close t, fill at next bar open t+1,
intra-bar high/low liquidation checks, zero lookahead) and pure (zero filesystem/DB IO).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .ignition_upgrades import _select_lev_and_col
from .short_and_levered_ignition import (
    LeveredIgnitionResult,
    _breakdown_or_breakout_z,
    _summarize_levered_nav,
)
from .timeframe_panel import BarPoint

# Verified live via GET https://apiv2.nobitex.ir/margin/markets/list (2026-11-25):
# All 13 BASE_13 symbols (incl. XAUTUSDT) and all 18 IGNITION_18 symbols (incl. FILUSDT)
# have buyEnabled=True, sellEnabled=True, maxLeverage=5, positionFeeRate=0.0005 (0.05%/day).
NOBITEX_MARGIN_ELIGIBLE_USDT: frozenset[str] = frozenset({
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "TRXUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "AAVEUSDT",
    "XAUTUSDT",
    "AVAXUSDT",
    "NEARUSDT",
    "UNIUSDT",
    "ATOMUSDT",
    "DOTUSDT",
    "FILUSDT",
    "XLMUSDT",
})


@dataclass(frozen=True)
class BullLeveredCoreResult:
    label: str
    bull_leverage: float
    leg_cost_bps: float
    borrow_apr_pct: float
    idle_pool_apr_pct: float
    days: int
    levered_days: int
    ending_nav: float
    ret_pct: float
    cagr_pct: float
    stress_ret_pct: float
    ann_sharpe: float
    max_dd_pct: float
    liquidations: int
    total_borrow_usdt: float
    total_pool_yield_usdt: float
    total_fees_usdt: float


@dataclass(frozen=True)
class WallexCreditStressResult:
    label: str
    unit_collateral_usdt: float
    unit_credit_usdt: float
    leverage_multiple: float
    fixed_fee_per_30d_usdt: float
    stop_out_subacct_dd_pct: float
    total_days: int
    total_30d_cycles: int
    profitable_cycles: int
    cash_bleed_cycles: int
    stop_out_cycles: int
    single_life_survived: bool
    first_stop_out_date: str | None
    single_life_ending_equity_usdt: float
    single_life_return_pct: float
    unlevered_ending_equity_usdt: float
    unlevered_return_pct: float
    total_fixed_interest_paid_usdt: float
    mean_cycle_equity_roi_pct: float
    median_cycle_equity_roi_pct: float
    worst_cycle_equity_roi_pct: float
    best_cycle_equity_roi_pct: float


def nobitex_long_liquidation_price(entry_px: float, leverage: float) -> float:
    """Conservative isolated LONG liquidation price matching Nobitex marginRatio=1.1 floor."""
    if leverage <= 1.0 or entry_px <= 0.0:
        return 0.0
    # Nobitex isolated liquidation at marginRatio = totalAsset / liability = 1.1:
    # (L * P / P0) / (L - 1) <= 1.1  =>  P <= P0 * 1.1 * (L - 1) / L
    # Also enforce conservative Wallex-style 85% equity wipeout guard if tighter.
    nbx_ratio = 1.1 * (leverage - 1.0) / leverage
    wlx_ratio = max(0.0, 1.0 - (0.85 / leverage))
    return entry_px * max(nbx_ratio, wlx_ratio)


def _nav_stats(nav_by_date: dict[str, float], stress_iso: str) -> tuple[float, float, float, float, float, float]:
    dates = sorted(nav_by_date)
    if len(dates) < 2:
        return 1000.0, 0.0, 0.0, 0.0, 0.0, 0.0
    navs = [nav_by_date[d] for d in dates]
    start_nav, end_nav = navs[0], navs[-1]
    ret_pct = ((end_nav / start_nav) - 1.0) * 100.0 if start_nav > 0 else 0.0
    years = max(len(dates) / 365.0, 1e-6)
    cagr_pct = (((end_nav / start_nav) ** (1.0 / years)) - 1.0) * 100.0 if (start_nav > 0 and end_nav > 0) else -100.0
    rets = [(navs[i] / navs[i - 1] - 1.0) for i in range(1, len(navs)) if navs[i - 1] > 0]
    mean_r = sum(rets) / max(1, len(rets))
    var_r = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
    sharpe = (mean_r / math.sqrt(var_r)) * math.sqrt(365.0) if var_r > 1e-14 else 0.0
    peak, max_dd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    st_dates = [d for d in dates if d >= stress_iso]
    st_ret = (
        ((nav_by_date[st_dates[-1]] / nav_by_date[st_dates[0]] - 1.0) * 100.0)
        if len(st_dates) >= 2 and nav_by_date[st_dates[0]] > 0
        else 0.0
    )
    return end_nav, ret_pct, cagr_pct, st_ret, sharpe, max_dd * 100.0


def simulate_bull_levered_1d_core(
    panel_1d: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    base_targets_by_ts: dict[datetime, dict[str, float]],
    daily_breadth: dict[str, float],
    *,
    label: str,
    bull_leverage: float = 1.0,
    bull_breadth_threshold: float = 0.55,
    leg_cost: float = 0.0016,
    borrow_per_day: float = 0.0005,
    idle_usdt_apr: float = 0.0,
    margin_eligible: frozenset[str] = NOBITEX_MARGIN_ELIGIBLE_USDT,
    stress_iso: str = "2025-11-24",
) -> tuple[BullLeveredCoreResult, dict[str, float]]:
    """Strictly causal self-financing 1d core simulator with selective bull-regime margin leverage.

    Decisions at bar close ts execute at next bar open (t+1). Borrow accrues strictly on
    borrowed notional max(0, gross_invested - equity). Idle cash earns optional pool APR.
    """
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in symbols}
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in symbols}
    eval_ts = sorted(base_targets_by_ts)

    equity = 1000.0
    qty_held: dict[str, float] = {s: 0.0 for s in symbols}
    cash = 1000.0  # negative cash == borrowed USDT liability
    last_px: dict[str, float] = {}
    nav_by_date: dict[str, float] = {}

    total_fees, total_borrow, total_pool_yield = 0.0, 0.0, 0.0
    levered_days, liquidations = 0, 0
    daily_pool_rate = idle_usdt_apr / 365.0

    for ts in eval_ts:
        exec_px: dict[str, float] = {}
        tradable: set[str] = set()
        for sym in symbols:
            nxt, cur = by_start[sym].get(ts), by_avail[sym].get(ts)
            if nxt is not None and nxt.open > 0:
                exec_px[sym] = nxt.open
                last_px[sym] = nxt.open
                if nxt.entry_eligible and cur is not None and cur.entry_eligible:
                    tradable.add(sym)
            elif cur is not None and cur.close > 0:
                exec_px[sym] = cur.close
                last_px[sym] = cur.close
            elif sym in last_px:
                exec_px[sym] = last_px[sym]

        # Check intra-day low liquidation on existing borrowed portfolio before rebalance
        if cash < -1e-6:
            borrowed = -cash
            low_val = 0.0
            for sym, q in qty_held.items():
                if q <= 0:
                    continue
                cur = by_avail[sym].get(ts)
                px_low = cur.low if (cur is not None and cur.low > 0) else exec_px.get(sym, 0.0)
                low_val += q * px_low
            if borrowed > 0 and (low_val / borrowed) <= 1.1:
                liquidations += 1
                equity = max(0.0, low_val - borrowed)
                cash = equity
                qty_held = {s: 0.0 for s in symbols}

        # Accrue 1 day of borrow cost on negative cash OR idle liquidity-pool yield on free cash
        if cash < -1e-6:
            brw = (-cash) * borrow_per_day
            cash -= brw
            total_borrow += brw
            levered_days += 1
        elif cash > 1e-6 and daily_pool_rate > 0.0:
            yld = cash * daily_pool_rate
            cash += yld
            total_pool_yield += yld

        gross_val = sum(qty_held[s] * exec_px.get(s, 0.0) for s in symbols)
        equity = max(0.0, cash + gross_val)
        if equity < 10.0:
            nav_by_date[ts.date().isoformat()] = equity
            continue

        day_br = daily_breadth.get(ts.date().isoformat(), 0.0)
        eff_lev = bull_leverage if (bull_leverage > 1.0 and day_br >= bull_breadth_threshold) else 1.0
        raw_t = base_targets_by_ts[ts]
        scaled_t: dict[str, float] = {}
        for sym in symbols:
            w = raw_t.get(sym, 0.0)
            mult = eff_lev if (sym in margin_eligible) else 1.0
            scaled_t[sym] = w * mult
        max_gross = 0.95 * eff_lev
        tot_w = sum(scaled_t.values())
        if tot_w > max_gross and tot_w > 0:
            sc = max_gross / tot_w
            scaled_t = {s: w * sc for s, w in scaled_t.items()}

        # Rebalance tradable symbols at next bar open with exact leg cost
        for sym in symbols:
            if sym not in tradable or sym not in exec_px or exec_px[sym] <= 0:
                continue
            px = exec_px[sym]
            cur_val = qty_held[sym] * px
            tgt_val = scaled_t.get(sym, 0.0) * equity
            delta_val = tgt_val - cur_val
            if abs(delta_val) < 1e-4:
                continue
            fee = abs(delta_val) * leg_cost
            qty_held[sym] = max(0.0, qty_held[sym] + delta_val / px)
            cash -= delta_val + fee
            total_fees += fee

        mark_nav = max(0.0, cash + sum(qty_held[s] * exec_px.get(s, 0.0) for s in symbols))
        nav_by_date[ts.date().isoformat()] = mark_nav

    end_nav, ret_p, cagr_p, st_p, sr, mdd = _nav_stats(nav_by_date, stress_iso)
    return (
        BullLeveredCoreResult(
            label=label,
            bull_leverage=bull_leverage,
            leg_cost_bps=round(leg_cost * 10000.0, 1),
            borrow_apr_pct=round(borrow_per_day * 365.0 * 100.0, 2),
            idle_pool_apr_pct=round(idle_usdt_apr * 100.0, 2),
            days=len(nav_by_date),
            levered_days=levered_days,
            ending_nav=round(end_nav, 2),
            ret_pct=round(ret_p, 2),
            cagr_pct=round(cagr_p, 2),
            stress_ret_pct=round(st_p, 2),
            ann_sharpe=round(sr, 3),
            max_dd_pct=round(mdd, 2),
            liquidations=liquidations,
            total_borrow_usdt=round(total_borrow, 2),
            total_pool_yield_usdt=round(total_pool_yield, 2),
            total_fees_usdt=round(total_fees, 2),
        ),
        nav_by_date,
    )


def _step_venue_margin_2h_exit(
    pos: dict,
    cur: BarPoint | None,
    nxt: BarPoint | None,
    *,
    cur_ts: datetime,
    prev_ts: datetime | None,
    leg_cost: float,
    borrow_mode: str,
    borrow_rate: float,
    max_hold_bars: int = 24,
    trail_stop_mult: float = 2.5,
    hard_stop_pct: float = 0.04,
) -> tuple[bool, bool, float, float, float]:
    """Advance one 2h bar on a levered LONG ignition position under exact Nobitex EOD or Wallex 4h borrow."""
    pos["age"] += 1
    borrowed_notional = pos["collateral"] * max(0.0, pos["lev"] - 1.0)
    if borrowed_notional <= 0.0:
        borrow_paid = 0.0
    elif borrow_mode == "eod_utc":
        # Nobitex bills daily extension fee at end-of-day UTC; intraday closed same UTC day pays $0
        crossed_day = prev_ts is not None and cur_ts.date() > prev_ts.date()
        borrow_paid = borrowed_notional * borrow_rate if crossed_day else 0.0
    else:
        # Wallex 0.015% per 4h -> 0.0075% per 2h bar
        borrow_paid = borrowed_notional * borrow_rate

    if cur is not None and cur.close > 0:
        if pos["lev"] > 1.0 and cur.low <= pos["liq_price"]:
            return True, True, -pos["collateral"], borrow_paid, 0.0
        pos["extreme"] = max(pos["extreme"], cur.close)
        hit_trail = cur.close < pos["extreme"] * (1.0 - trail_stop_mult * pos["b_vol"])
        hit_hard = cur.close < pos["entry_px"] * (1.0 - hard_stop_pct)
        if pos["age"] >= max_hold_bars or hit_trail or hit_hard:
            raw_exit = nxt.open if (nxt is not None and nxt.open > 0) else cur.close
            fee_paid = pos["qty"] * raw_exit * leg_cost
            pnl = pos["qty"] * (raw_exit - pos["entry_px"]) - fee_paid
            return True, False, max(-pos["collateral"], pnl), borrow_paid, fee_paid
    elif pos["age"] >= max_hold_bars:
        return True, False, 0.0, borrow_paid, 0.0

    return False, False, 0.0, borrow_paid, 0.0


def simulate_nobitex_margin_ignition(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth: dict[str, float],
    score_map: dict[tuple[datetime, str], float] | None,
    *,
    label: str,
    offset_hours: int = 0,
    score_is_return: bool = False,
    base_prob: float = 0.46,
    top_tercile_leverage: float = 1.5,
    leg_cost: float = 0.0016,
    borrow_mode: str = "eod_utc",
    borrow_rate: float = 0.0005,
    dd_throttle_pct: float = 0.05,
    margin_eligible: frozenset[str] = NOBITEX_MARGIN_ELIGIBLE_USDT,
    stress_iso: str = "2025-11-24",
) -> tuple[LeveredIgnitionResult, dict[str, float], dict[datetime, dict[str, float]]]:
    """Strictly causal 2h GRU-Ignition simulator with configurable top-tercile leverage & exact venue borrow."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_h: dict[str, list[float]] = {s: [] for s in symbols}
    vol_h: dict[str, list[float]] = {s: [] for s in symbols}
    high_h: dict[str, list[float]] = {s: [] for s in symbols}
    low_h: dict[str, list[float]] = {s: [] for s in symbols}
    prev_c: dict[str, float] = {}
    recent_sc: list[float] = []

    equity, peak_eq = 1000.0, 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    schedule: dict[datetime, dict[str, float]] = {}
    entries, wins, closed, liqs = 0, 0, 0, 0
    hold_h, total_borrow, total_fees = 0.0, 0.0, 0.0
    prev_ts: datetime | None = None

    for ts in all_ts:
        cands = []
        for sym in symbols:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_c[sym]) / prev_c[sym]) if (sym in prev_c and prev_c[sym] > 0) else 0.0
            if cur.entry_eligible and nxt and nxt.entry_eligible and nxt.open > 0 and sym not in active:
                hit = _breakdown_or_breakout_z(
                    cur, r, high_h[sym][-72:], low_h[sym][-72:], ret_h[sym][-36:], vol_h[sym][-36:],
                    side="LONG", breakout_bars=72, vol_lookback=36, z_threshold=3.0, vol_mult=2.5,
                )
                if hit is not None:
                    cands.append((hit[0], sym, hit[1]))
            if sym in prev_c and prev_c[sym] > 0:
                ret_h[sym].append(r)
            prev_c[sym] = cur.close
            vol_h[sym].append(cur.volume)
            high_h[sym].append(cur.high)
            low_h[sym].append(cur.low)

        for sym in list(active):
            pos = active[sym]
            is_c, is_l, pnl, brw, fee = _step_venue_margin_2h_exit(
                pos, by_avail[sym].get(ts), by_start[sym].get(ts),
                cur_ts=ts, prev_ts=prev_ts, leg_cost=leg_cost,
                borrow_mode=borrow_mode, borrow_rate=borrow_rate,
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
                elif pnl - pos["entry_fee"] > 0:
                    wins += 1
                del active[sym]

        mark_u = sum(
            max(-p["collateral"], p["qty"] * (by_avail[s][ts].close - p["entry_px"]))
            for s, p in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        mark_eq = max(0.0, equity + mark_u)
        peak_eq = max(peak_eq, mark_eq)
        in_dd = peak_eq > 0 and ((peak_eq - mark_eq) / peak_eq >= dd_throttle_pct)

        if equity > 100.0 and daily_breadth.get(ts.date().isoformat(), 0.0) >= 0.45 and cands and len(active) < 3:
            cands.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in cands:
                sc = score_map.get((ts, sym)) if score_map is not None else None
                if sc is not None:
                    recent_sc.append(sc)
                if len(active) >= 3:
                    break
                nxt = by_start[sym].get(ts)
                if not nxt or nxt.open <= 0:
                    continue
                base_lev, col_f = _select_lev_and_col(
                    sc, score_is_return=score_is_return, base_prob=base_prob,
                    use_conformal=True, recent_scores=recent_sc, in_dd_throttle=in_dd,
                )
                lev = top_tercile_leverage if (base_lev > 1.0 and sym in margin_eligible) else 1.0
                free_c = max(0.0, equity - sum(p["collateral"] for p in active.values()))
                col = min(equity * col_f, free_c)
                if col < 25.0:
                    continue
                notional = col * lev
                ef = notional * leg_cost
                equity = max(0.0, equity - ef)
                total_fees += ef
                active[sym] = {
                    "collateral": col, "notional": notional, "qty": notional / nxt.open,
                    "entry_px": nxt.open, "entry_fee": ef, "extreme": nxt.open,
                    "b_vol": b_vol, "liq_price": nobitex_long_liquidation_price(nxt.open, lev),
                    "age": 0, "lev": lev, "slot_w": col_f * lev,
                }
                entries += 1

        unreal = sum(
            max(-p["collateral"], p["qty"] * (by_avail[s][ts].close - p["entry_px"]))
            for s, p in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        nav_by_date[ts.date().isoformat()] = max(0.0, equity + unreal)
        schedule[ts] = {s: p["slot_w"] for s, p in active.items()}
        prev_ts = ts

    res = _summarize_levered_nav(
        label, "LONG_IGNITION", top_tercile_leverage, len(symbols), offset_hours, leg_cost,
        nav_by_date, stress_iso, entries, wins, closed, liqs, hold_h, total_borrow, total_fees,
    )
    return res, nav_by_date, schedule


def simulate_wallex_trade_credit_contract(
    strategy_nav_by_date: dict[str, float],
    *,
    label: str,
    unit_collateral_usdt: float = 200.0,
    unit_credit_usdt: float = 1000.0,
    fixed_fee_rate_30d: float = 0.015,
    stop_out_subacct_dd: float = 0.13,
    cycle_days: int = 30,
) -> WallexCreditStressResult:
    """Simulate Wallex's exact 5x Fixed Trade-Credit contract (200 collateral + 1,000 credit = 1,200 sub-acct).

    Rules from Wallex webpage:
    - Sub-account starts each 30d cycle with (equity + credit), e.g. $200 + $1,000 = $1,200.
    - Fixed repayment = credit * (1 + 0.015) = $1,015 at day 30 regardless of cash utilization.
    - Sub-account forced stop-out if sub-account value drops >= 13% from cycle start ($1,200 -> <= $1,044),
      leaving residual = max(0, sub_acct_at_stopout - credit * 1.015 - 0.0025 * sub_acct_at_stopout).
    - Tracks BOTH strict single-life compounded survival (no top-ups) and independent 30-day cycle distribution.
    """
    dates = sorted(strategy_nav_by_date)
    if len(dates) < cycle_days + 1:
        return WallexCreditStressResult(
            label, unit_collateral_usdt, unit_credit_usdt, unit_credit_usdt / unit_collateral_usdt,
            round(unit_credit_usdt * fixed_fee_rate_30d, 2), round(stop_out_subacct_dd * 100.0, 1),
            len(dates), 0, 0, 0, 0, True, None, unit_collateral_usdt, 0.0, unit_collateral_usdt, 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0,
        )

    navs = [strategy_nav_by_date[d] for d in dates]
    lev_mult = unit_credit_usdt / unit_collateral_usdt
    unlev_end = unit_collateral_usdt * (navs[-1] / navs[0])

    # 1. Independent non-overlapping 30-day cycles (measures true cash-bleed & stop-out frequency)
    cycle_rois: list[float] = []
    profitable_c, bleed_c, stop_c = 0, 0, 0
    for start_i in range(0, len(dates) - cycle_days, cycle_days):
        end_i = start_i + cycle_days
        base_nav = navs[start_i]
        sub_start = unit_collateral_usdt + unit_credit_usdt
        repay = unit_credit_usdt * (1.0 + fixed_fee_rate_30d)
        hit_stop = False
        sub_end = sub_start
        for k in range(start_i + 1, end_i + 1):
            sub_k = sub_start * (navs[k] / base_nav)
            if (sub_k / sub_start - 1.0) <= -stop_out_subacct_dd:
                hit_stop = True
                sub_end = sub_k
                break
            sub_end = sub_k
        if hit_stop:
            stop_c += 1
            eq_end = max(0.0, sub_end - repay - 0.0025 * sub_end)
        else:
            eq_end = max(0.0, sub_end - repay)
        roi = (eq_end / unit_collateral_usdt - 1.0) * 100.0
        cycle_rois.append(roi)
        if roi > 0.0:
            profitable_c += 1
        elif not hit_stop:
            bleed_c += 1

    # 2. Strict single-life compounded trajectory (start with $200, roll at 5x credit each 30d, NO top-ups)
    sl_equity = unit_collateral_usdt
    sl_survived = True
    first_stop_date: str | None = None
    total_interest = 0.0
    for start_i in range(0, len(dates) - cycle_days, cycle_days):
        if sl_equity < 20.0:
            sl_survived = False
            break
        end_i = start_i + cycle_days
        base_nav = navs[start_i]
        credit = sl_equity * lev_mult
        sub_start = sl_equity + credit
        fee_due = credit * fixed_fee_rate_30d
        repay = credit + fee_due
        total_interest += fee_due
        hit_stop = False
        sub_end = sub_start
        for k in range(start_i + 1, end_i + 1):
            sub_k = sub_start * (navs[k] / base_nav)
            if (sub_k / sub_start - 1.0) <= -stop_out_subacct_dd:
                hit_stop = True
                sub_end = sub_k
                if first_stop_date is None:
                    first_stop_date = dates[k]
                break
            sub_end = sub_k
        if hit_stop:
            sl_equity = max(0.0, sub_end - repay - 0.0025 * sub_end)
            sl_survived = False
            break
        sl_equity = max(0.0, sub_end - repay)

    sorted_rois = sorted(cycle_rois)
    med_roi = sorted_rois[len(sorted_rois) // 2] if sorted_rois else 0.0
    mean_roi = sum(cycle_rois) / len(cycle_rois) if cycle_rois else 0.0

    return WallexCreditStressResult(
        label=label,
        unit_collateral_usdt=unit_collateral_usdt,
        unit_credit_usdt=unit_credit_usdt,
        leverage_multiple=lev_mult,
        fixed_fee_per_30d_usdt=round(unit_credit_usdt * fixed_fee_rate_30d, 2),
        stop_out_subacct_dd_pct=round(stop_out_subacct_dd * 100.0, 1),
        total_days=len(dates),
        total_30d_cycles=len(cycle_rois),
        profitable_cycles=profitable_c,
        cash_bleed_cycles=bleed_c,
        stop_out_cycles=stop_c,
        single_life_survived=sl_survived,
        first_stop_out_date=first_stop_date,
        single_life_ending_equity_usdt=round(sl_equity, 2),
        single_life_return_pct=round((sl_equity / unit_collateral_usdt - 1.0) * 100.0, 2),
        unlevered_ending_equity_usdt=round(unlev_end, 2),
        unlevered_return_pct=round((unlev_end / unit_collateral_usdt - 1.0) * 100.0, 2),
        total_fixed_interest_paid_usdt=round(total_interest, 2),
        mean_cycle_equity_roi_pct=round(mean_roi, 2),
        median_cycle_equity_roi_pct=round(med_roi, 2),
        worst_cycle_equity_roi_pct=round(min(cycle_rois), 2) if cycle_rois else 0.0,
        best_cycle_equity_roi_pct=round(max(cycle_rois), 2) if cycle_rois else 0.0,
    )
