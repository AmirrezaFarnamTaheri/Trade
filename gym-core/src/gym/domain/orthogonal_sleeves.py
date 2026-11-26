"""Orthogonal strategy sleeves: 2h capitulation-flush rebound, bear dead-cat short, and standalone macro commodities.

All signals are strictly causal (decision at bar close ts_avail, fill at next-bar open ts_start == ts_avail).
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
from .timeframe_panel import BarPoint
from .volatility_models import OhlcBar, yang_zhang_volatility

MACRO_COMMODITY_SYMBOLS = (
    "PAXGUSDT",
    "SLVONUSDT",
    "USOONUSDT",
    "COPXONUSDT",
    "UNGONUSDT",
)


@dataclass(frozen=True)
class MacroSleeveResult:
    label: str
    symbols: tuple[str, ...]
    days: int
    ending_nav: float
    ret_pct: float
    stress_ret_pct: float
    ann_sharpe: float
    max_dd_pct: float
    total_fees_usdt: float
    avg_gross_exposure_pct: float


def _flush_rebound_signal(
    bar: BarPoint,
    bar_ret: float,
    prior_lows: list[float],
    prior_rets: list[float],
    prior_vols: list[float],
    *,
    breakout_bars: int,
    vol_lookback: int,
    z_threshold: float,
    vol_mult: float,
) -> tuple[float, float] | None:
    """Detect extreme downward volume flush (mirror of failed SHORT_IGN18_2H) for spot rebound."""
    if len(prior_lows) < breakout_bars or len(prior_rets) < vol_lookback or len(prior_vols) < vol_lookback:
        return None
    mean_r = sum(prior_rets) / len(prior_rets)
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in prior_rets) / max(1, len(prior_rets) - 1))
    med_v = median(prior_vols)
    if med_v <= 0 or bar.volume < vol_mult * med_v:
        return None
    z = (bar_ret - mean_r) / max(std_r, 1e-4)
    if z <= -z_threshold and bar.close < min(prior_lows):
        return -z, max(std_r, 0.005)
    return None


def _dead_cat_exhaustion_signal(
    bar: BarPoint,
    bar_ret: float,
    prior_closes: list[float],
    prior_highs: list[float],
    prior_rets: list[float],
    prior_vols: list[float],
    *,
    trend_bars: int = 72,
    vol_lookback: int = 36,
    z_min: float = 1.2,
    z_max: float = 2.6,
    max_vol_mult: float = 0.90,
) -> tuple[float, float] | None:
    """Detect weak low-volume bear bounce below 72-bar SMA that fails to clear prior 36-bar high."""
    if len(prior_closes) < trend_bars or len(prior_rets) < vol_lookback or len(prior_vols) < vol_lookback:
        return None
    sma_trend = sum(prior_closes[-trend_bars:]) / trend_bars
    if bar.close >= sma_trend:
        return None
    if bar.close >= max(prior_highs[-vol_lookback:]):
        return None
    med_v = median(prior_vols[-vol_lookback:])
    if med_v <= 0 or bar.volume > max_vol_mult * med_v:
        return None
    mean_r = sum(prior_rets[-vol_lookback:]) / vol_lookback
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in prior_rets[-vol_lookback:]) / max(1, vol_lookback - 1))
    z = (bar_ret - mean_r) / max(std_r, 1e-4)
    if z_min <= z <= z_max:
        return z, max(std_r, 0.005)
    return None


def _open_rebound_slots(
    cands: list[tuple[float, str, float]],
    active: dict[str, dict],
    by_start: dict[str, dict[datetime, BarPoint]],
    ts: datetime,
    equity: float,
    *,
    max_slots: int,
    slot_frac: float,
    leg_cost: float,
) -> tuple[float, float, int]:
    """Open spot long rebound slots; returns (new_equity, fees_added, entries_added)."""
    fees_added, entries_added = 0.0, 0
    cands.sort(key=lambda x: (-x[0], x[1]))
    for _, sym, b_vol in cands:
        if len(active) >= max_slots:
            break
        nxt = by_start[sym].get(ts)
        if nxt is None or nxt.open <= 0:
            continue
        used_col = sum(p["collateral"] for p in active.values())
        col = min(equity * slot_frac, max(0.0, equity - used_col))
        if col < 25.0:
            continue
        ef = col * leg_cost
        equity = max(0.0, equity - ef)
        fees_added += ef
        active[sym] = {
            "collateral": col,
            "notional": col,
            "qty": col / nxt.open,
            "entry_px": nxt.open,
            "entry_fee": ef,
            "extreme": nxt.open,
            "b_vol": b_vol,
            "liq_price": 0.0,
            "age": 0,
        }
        entries_added += 1
    return equity, fees_added, entries_added


def simulate_capitulation_flush_rebound(
    panel_tf: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth_by_date: dict[str, float],
    *,
    label: str,
    bucket_hours: int = 2,
    offset_hours: int = 0,
    leg_cost: float = 0.0016,
    z_threshold: float = 3.0,
    vol_mult: float = 2.5,
    breakout_hours: int = 144,
    hold_hours: int = 24,
    trail_stop_mult: float = 2.5,
    hard_stop_pct: float = 0.05,
    max_breadth_gate: float = 1.0,
    max_slots: int = 3,
    slot_frac: float = 0.30,
    stress_iso: str = "2025-11-24",
) -> tuple[LeveredIgnitionResult, dict[str, float], dict[datetime, dict[str, float]]]:
    """Spot 1.0x LONG mean-reversion buying extreme 2h forced-liquidation flushes (zero lookahead)."""
    breakout_bars = max(12, breakout_hours // bucket_hours)
    max_hold_bars = max(4, hold_hours // bucket_hours)
    vol_lookback = max(24, 72 // bucket_hours)

    by_avail = {s: {b.ts_avail: b for b in panel_tf.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_tf.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    vol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    low_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}

    equity = 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    targets_by_ts: dict[datetime, dict[str, float]] = {}
    entries, wins, closed = 0, 0, 0
    hold_hours_sum, total_fees = 0.0, 0.0

    for ts in all_ts:
        cands: list[tuple[float, str, float]] = []
        for sym in symbols:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_close[sym]) / prev_close[sym]) if (sym in prev_close and prev_close[sym] > 0) else 0.0
            if cur.entry_eligible and nxt and nxt.open > 0 and sym not in active:
                hit = _flush_rebound_signal(
                    cur, r, low_hist[sym][-breakout_bars:], ret_hist[sym][-vol_lookback:], vol_hist[sym][-vol_lookback:],
                    breakout_bars=breakout_bars, vol_lookback=vol_lookback, z_threshold=z_threshold, vol_mult=vol_mult,
                )
                if hit is not None:
                    cands.append((hit[0], sym, hit[1]))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append(r)
            prev_close[sym] = cur.close
            vol_hist[sym].append(cur.volume)
            low_hist[sym].append(cur.low)

        for sym in list(active):
            pos = active[sym]
            is_c, _, pnl, _, fee = _check_margin_exit(
                pos, by_avail[sym].get(ts), by_start[sym].get(ts),
                side="LONG", leverage=1.0, max_hold_bars=max_hold_bars,
                trail_stop_mult=trail_stop_mult, hard_stop_pct=hard_stop_pct,
                leg_cost=leg_cost, borrow_per_bar=0.0,
            )
            total_fees += fee
            if is_c:
                equity = max(0.0, equity + pnl)
                closed += 1
                hold_hours_sum += pos["age"] * bucket_hours
                if pnl - pos["entry_fee"] > 0:
                    wins += 1
                del active[sym]

        day_br = daily_breadth_by_date.get(ts.date().isoformat(), 0.5)
        if equity > 100.0 and day_br <= max_breadth_gate and cands and len(active) < max_slots:
            equity, f_add, e_add = _open_rebound_slots(
                cands, active, by_start, ts, equity,
                max_slots=max_slots, slot_frac=slot_frac, leg_cost=leg_cost,
            )
            total_fees += f_add
            entries += e_add

        targets_by_ts[ts] = {s: (slot_frac if s in active else 0.0) for s in symbols}
        unreal = sum(
            max(-pos["collateral"], pos["qty"] * (by_avail[s][ts].close - pos["entry_px"]))
            for s, pos in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        nav_by_date[ts.date().isoformat()] = max(0.0, equity + unreal)

    res = _summarize_levered_nav(
        label, "LONG_REBOUND", 1.0, len(symbols), offset_hours, leg_cost,
        nav_by_date, stress_iso, entries, wins, closed, 0, hold_hours_sum, 0.0, total_fees,
    )
    return res, nav_by_date, targets_by_ts


def simulate_dead_cat_exhaustion_short(
    panel_tf: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth_by_date: dict[str, float],
    *,
    label: str,
    bucket_hours: int = 2,
    offset_hours: int = 0,
    leg_cost: float = 0.0016,
    borrow_per_4h: float = 0.00015,
    liq_margin_ratio: float = 0.15,
    max_breadth_gate: float = 0.35,
    hold_hours: int = 48,
    trail_stop_mult: float = 2.5,
    hard_stop_pct: float = 0.04,
    max_slots: int = 3,
    slot_frac: float = 0.30,
    stress_iso: str = "2025-11-24",
) -> tuple[LeveredIgnitionResult, dict[str, float]]:
    """Bear-market 1.0x SHORT fading weak low-volume bounces into downtrend resistance."""
    max_hold_bars = max(4, hold_hours // bucket_hours)
    borrow_per_bar = borrow_per_4h * (bucket_hours / 4.0)

    by_avail = {s: {b.ts_avail: b for b in panel_tf.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_tf.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    vol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    high_hist: dict[str, list[float]] = {s: [] for s in symbols}
    close_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}

    equity = 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    entries, wins, closed, liqs = 0, 0, 0, 0
    hold_hours_sum, total_borrow, total_fees = 0.0, 0.0, 0.0

    for ts in all_ts:
        cands: list[tuple[float, str, float]] = []
        for sym in symbols:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_close[sym]) / prev_close[sym]) if (sym in prev_close and prev_close[sym] > 0) else 0.0
            if cur.entry_eligible and nxt and nxt.open > 0 and sym not in active:
                hit = _dead_cat_exhaustion_signal(
                    cur, r, close_hist[sym], high_hist[sym], ret_hist[sym], vol_hist[sym],
                )
                if hit is not None:
                    cands.append((hit[0], sym, hit[1]))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append(r)
            prev_close[sym] = cur.close
            close_hist[sym].append(cur.close)
            vol_hist[sym].append(cur.volume)
            high_hist[sym].append(cur.high)

        for sym in list(active):
            pos = active[sym]
            is_c, is_l, pnl, brw, fee = _check_margin_exit(
                pos, by_avail[sym].get(ts), by_start[sym].get(ts),
                side="SHORT", leverage=1.0, max_hold_bars=max_hold_bars,
                trail_stop_mult=trail_stop_mult, hard_stop_pct=hard_stop_pct,
                leg_cost=leg_cost, borrow_per_bar=borrow_per_bar,
            )
            equity -= brw
            total_borrow += brw
            total_fees += fee
            if is_c:
                equity = max(0.0, equity + pnl)
                closed += 1
                hold_hours_sum += pos["age"] * bucket_hours
                if is_l:
                    liqs += 1
                elif pnl - pos["entry_fee"] > 0:
                    wins += 1
                del active[sym]

        day_br = daily_breadth_by_date.get(ts.date().isoformat())
        if equity > 100.0 and day_br is not None and day_br <= max_breadth_gate and cands and len(active) < max_slots:
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
        label, "SHORT_DEADCAT", 1.0, len(symbols), offset_hours, leg_cost,
        nav_by_date, stress_iso, entries, wins, closed, liqs, hold_hours_sum, total_borrow, total_fees,
    )
    return res, nav_by_date


def _summarize_macro_nav(
    label: str,
    symbols: tuple[str, ...],
    nav_by_date: dict[str, float],
    stress_iso: str,
    total_fees: float,
    gross_exposures: list[float],
) -> MacroSleeveResult:
    dates = sorted(nav_by_date)
    if len(dates) < 5:
        return MacroSleeveResult(label, symbols, len(dates), 1000.0, 0.0, 0.0, 0.0, 0.0, round(total_fees, 2), 0.0)
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
    avg_exp = (sum(gross_exposures) / len(gross_exposures) * 100.0) if gross_exposures else 0.0
    return MacroSleeveResult(
        label=label,
        symbols=symbols,
        days=len(dates),
        ending_nav=round(navs[-1], 2),
        ret_pct=round((navs[-1] / navs[0] - 1.0) * 100.0, 2),
        stress_ret_pct=round(st_ret, 2),
        ann_sharpe=round(sr, 3),
        max_dd_pct=round(max_dd * 100.0, 2),
        total_fees_usdt=round(total_fees, 2),
        avg_gross_exposure_pct=round(avg_exp, 1),
    )


def simulate_macro_risk_parity_sleeve(
    panel_1d: dict[str, list[BarPoint]],
    symbols: tuple[str, ...] = MACRO_COMMODITY_SYMBOLS,
    *,
    label: str = "MACRO_COMMODITIES_RP_TREND",
    fee_rate: Decimal = Decimal("0.0013"),
    warmup_bars: int = 64,
    max_weight: float = 0.45,
    max_gross: float = 0.95,
    rebalance_band: float = 0.04,
    stress_iso: str = "2025-11-24",
) -> tuple[MacroSleeveResult, dict[str, float], dict[datetime, dict[str, float]]]:
    """Standalone long-only inverse-vol EWMAC trend sleeve for non-crypto metals/commodities."""
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ohlc_hist: dict[str, list[OhlcBar]] = {s: [] for s in symbols}
    emas: dict[str, dict[int, float]] = {s: {} for s in symbols}
    counts: dict[str, int] = {s: 0 for s in symbols}

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    prev_targets: dict[str, float] = {s: 0.0 for s in symbols}
    nav_by_date: dict[str, float] = {}
    targets_by_ts: dict[datetime, dict[str, float]] = {}
    exposures: list[float] = []

    for ts in all_ts:
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        raw_scores: dict[str, float] = {}

        for sym in symbols:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is not None and cur.close > 0:
                counts[sym] += 1
                ohlc_hist[sym].append(OhlcBar(cur.open, cur.high, cur.low, cur.close))
                for span in (8, 16, 32, 64):
                    a = 2.0 / (span + 1.0)
                    emas[sym][span] = cur.close if span not in emas[sym] else (1.0 - a) * emas[sym][span] + a * cur.close
                yz = max(yang_zhang_volatility(ohlc_hist[sym][-20:]), 0.004)
                if counts[sym] >= warmup_bars and cur.entry_eligible:
                    t1 = (emas[sym][8] - emas[sym][32]) / (cur.close * yz * 5.0)
                    t2 = (emas[sym][16] - emas[sym][64]) / (cur.close * yz * 5.0)
                    trend = max(0.0, min(1.0, 0.5 * (t1 + t2)))
                    if trend > 0.05:
                        raw_scores[sym] = trend / yz
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

        tot_raw = sum(raw_scores.values())
        targets = {s: 0.0 for s in symbols}
        if tot_raw > 0:
            for s, val in raw_scores.items():
                targets[s] = min(max_weight, max_gross * (val / tot_raw))
            tot_w = sum(targets.values())
            if tot_w > max_gross:
                sc = max_gross / tot_w
                targets = {s: w * sc for s, w in targets.items()}

        if any(abs(targets[s] - prev_targets[s]) >= rebalance_band for s in symbols):
            ledger.rebalance_to_targets(ts, targets, exec_prices, tradable_symbols=tradable)
            prev_targets = dict(targets)

        targets_by_ts[ts] = dict(prev_targets)
        exposures.append(sum(prev_targets.values()))
        if exec_prices:
            nav_by_date[ts.date().isoformat()] = float(ledger.mark_nav(exec_prices))

    res = _summarize_macro_nav(
        label, symbols, nav_by_date, stress_iso, float(ledger.total_fees_quote_equiv), exposures,
    )
    return res, nav_by_date, targets_by_ts
