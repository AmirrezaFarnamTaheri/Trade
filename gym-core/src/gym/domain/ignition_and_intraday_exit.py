"""Pure domain engines for ignition spread stress, single-ledger 1h blend, and true intraday 3h crash exit."""
from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal

from .family_and_ignition import (
    IgnitionSleeveResult,
    _ignition_candidate_z,
    _manage_ignition_exits,
    _summarize_ignition_nav,
)
from .paper_ledger import SelfFinancingLedger
from .timeframe_panel import BarPoint
from .volatility_models import (
    OhlcBar,
    asymmetric_ewma_volatility,
    yang_zhang_volatility,
)


def pearson_correlation(series_a: dict[str, float], series_b: dict[str, float]) -> float:
    """Compute exact Pearson correlation over overlapping dates."""
    dates = sorted(set(series_a) & set(series_b))
    n = len(dates)
    if n < 5:
        return 0.0
    xs = [series_a[d] for d in dates]
    ys = [series_b[d] for d in dates]
    mx = sum(xs) / n
    my = sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 1e-15 or vy <= 1e-15:
        return 0.0
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return round(cov / math.sqrt(vx * vy), 4)


def simulate_ignition_detailed(
    panel_tf: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth_by_date: dict[str, float],
    *,
    label: str,
    bucket_hours: int,
    offset_hours: int = 0,
    fee_rate: Decimal = Decimal("0.0013"),
    z_threshold: float = 3.0,
    vol_mult: float = 2.5,
    breakout_hours: int = 144,
    hold_hours: int = 48,
    trail_stop_mult: float = 2.5,
    hard_stop_pct: float = 0.04,
    min_daily_breadth: float = 0.45,
    max_slots: int = 3,
    slot_weight: float = 0.30,
) -> tuple[IgnitionSleeveResult, dict[str, float], dict[datetime, dict[str, float]]]:
    """Run rare high-momentum ignition and return (summary, nav_by_date, target_weights_by_ts)."""
    breakout_bars = max(12, breakout_hours // bucket_hours)
    max_hold_bars = max(4, hold_hours // bucket_hours)
    vol_lookback = max(24, 72 // bucket_hours)

    by_avail = {s: {b.ts_avail: b for b in panel_tf.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_tf.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    vol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    high_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    open_pos: dict[str, tuple[float, float, float, int]] = {}
    nav_by_date: dict[str, float] = {}
    targets_by_ts: dict[datetime, dict[str, float]] = {}
    entries, closed_wins, closed_total = 0, 0, 0

    for ts in all_ts:
        exec_prices, tradable, candidates = _step_ignition_bars(
            ts,
            symbols,
            by_avail,
            by_start,
            last_mark,
            open_pos,
            prev_close,
            ret_hist,
            vol_hist,
            high_hist,
            breakout_bars=breakout_bars,
            vol_lookback=vol_lookback,
            z_threshold=z_threshold,
            vol_mult=vol_mult,
        )
        w_inc, t_inc = _manage_ignition_exits(
            open_pos,
            by_avail,
            by_start,
            ts,
            max_hold_bars=max_hold_bars,
            trail_stop_mult=trail_stop_mult,
            hard_stop_pct=hard_stop_pct,
            fee_rate=fee_rate,
        )
        closed_wins += w_inc
        closed_total += t_inc

        day_br = daily_breadth_by_date.get(ts.date().isoformat(), 0.0)
        if candidates and day_br >= min_daily_breadth and len(open_pos) < max_slots:
            candidates.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in candidates:
                if len(open_pos) >= max_slots:
                    break
                nxt = by_start[sym].get(ts)
                if nxt is not None and nxt.open > 0:
                    open_pos[sym] = (nxt.open, nxt.open, b_vol, 0)
                    entries += 1

        targets = {s: (slot_weight if s in open_pos else 0.0) for s in symbols}
        targets_by_ts[ts] = targets
        if open_pos or any(q > 0 for q in ledger.units.values()):
            ledger.rebalance_to_targets(ts, targets, exec_prices, tradable_symbols=tradable)
        nav_by_date[ts.date().isoformat()] = float(ledger.mark_nav(exec_prices))

    res = _summarize_ignition_nav(
        label,
        bucket_hours,
        offset_hours,
        fee_rate,
        nav_by_date,
        entries,
        closed_wins,
        closed_total,
        float(ledger.total_fees_quote_equiv),
    )
    return res, nav_by_date, targets_by_ts


def _step_ignition_bars(
    ts: datetime,
    symbols: tuple[str, ...],
    by_avail: dict[str, dict[datetime, BarPoint]],
    by_start: dict[str, dict[datetime, BarPoint]],
    last_mark: dict[str, Decimal],
    open_pos: dict[str, tuple[float, float, float, int]],
    prev_close: dict[str, float],
    ret_hist: dict[str, list[float]],
    vol_hist: dict[str, list[float]],
    high_hist: dict[str, list[float]],
    *,
    breakout_bars: int,
    vol_lookback: int,
    z_threshold: float,
    vol_mult: float,
) -> tuple[dict[str, Decimal], set[str], list[tuple[float, str, float]]]:
    exec_prices: dict[str, Decimal] = {}
    tradable: set[str] = set()
    candidates: list[tuple[float, str, float]] = []
    for sym in symbols:
        cur = by_avail[sym].get(ts)
        nxt = by_start[sym].get(ts)
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

        if cur is None or cur.close <= 0:
            continue
        bar_ret = ((cur.close - prev_close[sym]) / prev_close[sym]) if (sym in prev_close and prev_close[sym] > 0) else 0.0
        if sym in tradable and sym not in open_pos:
            hit = _ignition_candidate_z(
                cur,
                bar_ret,
                high_hist[sym][-breakout_bars:],
                ret_hist[sym][-vol_lookback:],
                vol_hist[sym][-vol_lookback:],
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
    return exec_prices, tradable, candidates


def compute_intraday_crash_timestamps(
    panel_tf: dict[str, list[BarPoint]],
    crypto_symbols: tuple[str, ...],
    *,
    bucket_hours: int = 3,
    ema_days: int = 20,
    breadth_threshold: float = 0.20,
    vol_quantile: float = 0.92,
    min_active: int = 4,
) -> set[datetime]:
    """Return exact intraday bar-close timestamps ts_avail when breadth collapse + vol spike triggers."""
    bars_per_day = max(1, 24 // bucket_hours)
    ema_bars = max(20, ema_days * bars_per_day)
    yz_win = max(12, 6 * bars_per_day)
    dv_win = max(18, 9 * bars_per_day)
    hist_win = max(90, 45 * bars_per_day)
    min_hist = max(30, 15 * bars_per_day)

    by_sym_ts = {s: {b.ts_avail: b for b in panel_tf.get(s, [])} for s in crypto_symbols}
    all_ts = sorted({t for d in by_sym_ts.values() for t in d})

    ema: dict[str, float] = {}
    counts: dict[str, int] = {s: 0 for s in crypto_symbols}
    ret_hist: dict[str, list[float]] = {s: [] for s in crypto_symbols}
    ohlc_hist: dict[str, list[OhlcBar]] = {s: [] for s in crypto_symbols}
    prev_close: dict[str, float] = {}
    down_hist: list[float] = []
    crash_ts: set[datetime] = set()
    alpha = 2.0 / (ema_bars + 1.0)

    for ts in all_ts:
        above, active = 0, 0
        ratios: list[float] = []
        for sym in crypto_symbols:
            bar = by_sym_ts[sym].get(ts)
            if bar is None:
                continue
            counts[sym] += 1
            ema[sym] = bar.close if sym not in ema else (1.0 - alpha) * ema[sym] + alpha * bar.close
            ohlc_hist[sym].append(OhlcBar(bar.open, bar.high, bar.low, bar.close))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append((bar.close - prev_close[sym]) / prev_close[sym])
            prev_close[sym] = bar.close
            if counts[sym] >= ema_bars and bar.entry_eligible:
                active += 1
                if bar.close > ema[sym]:
                    above += 1
                yz = yang_zhang_volatility(ohlc_hist[sym][-yz_win:])
                dv = asymmetric_ewma_volatility(ret_hist[sym][-dv_win:]) if len(ret_hist[sym]) >= 6 else yz
                ratios.append(dv / max(yz, 1e-4))
        if active < min_active:
            continue
        breadth = above / active
        avg_r = sum(ratios) / len(ratios)
        down_hist.append(avg_r)
        if len(down_hist) >= min_hist:
            tr = sorted(down_hist[-hist_win:])
            if breadth < breadth_threshold and avg_r >= tr[int(vol_quantile * (len(tr) - 1))]:
                crash_ts.add(ts)
    return crash_ts


def run_shared_ledger_1h_blend(
    panel_1h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_targets_by_ts: dict[datetime, dict[str, float]],
    ignition_targets_by_ts: dict[datetime, dict[str, float]],
    *,
    slow_weight: float = 0.70,
    ignition_weight: float = 0.30,
    fee_rate: Decimal = Decimal("0.0013"),
    max_asset_weight: float = 0.35,
    max_gross_weight: float = 0.95,
) -> dict:
    """Single shared SelfFinancingLedger netting daily S1+S5 targets with 1h rare ignition on 1h next-bar opens."""
    by_avail = {s: {b.ts_avail: b for b in panel_1h.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_1h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    cur_slow: dict[str, float] = {s: 0.0 for s in symbols}
    prev_ign: dict[str, float] = {s: 0.0 for s in symbols}
    nav_by_date: dict[str, float] = {}

    for ts in all_ts:
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        for sym in symbols:
            nxt = by_start[sym].get(ts)
            cur = by_avail[sym].get(ts)
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

        slow_changed = ts in daily_targets_by_ts
        if slow_changed:
            cur_slow = daily_targets_by_ts[ts]
        ign_now = ignition_targets_by_ts.get(ts, prev_ign)
        ign_changed = any(abs(ign_now.get(s, 0.0) - prev_ign.get(s, 0.0)) > 1e-6 for s in symbols)
        prev_ign = ign_now

        if slow_changed or ign_changed:
            raw = {
                s: min(max_asset_weight, slow_weight * cur_slow.get(s, 0.0) + ignition_weight * ign_now.get(s, 0.0))
                for s in symbols
            }
            tot = sum(raw.values())
            if tot > max_gross_weight and tot > 0:
                scale = max_gross_weight / tot
                raw = {s: w * scale for s, w in raw.items()}
            ledger.rebalance_to_targets(ts, raw, exec_prices, tradable_symbols=tradable)

        nav_by_date[ts.date().isoformat()] = float(ledger.mark_nav(exec_prices))

    return {
        "nav_by_date": nav_by_date,
        "fills": len(ledger.fills),
        "total_fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "turnover_multiple": round(float(ledger.cumulative_turnover_quote / ledger.starting_cash), 2),
    }


def run_true_intraday_3h_exit(
    panel_3h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_targets_by_ts: dict[datetime, dict[str, float]],
    crash_timestamps: set[datetime],
    *,
    fee_rate: Decimal = Decimal("0.0013"),
    gold_symbol: str = "XAUTUSDT",
) -> dict:
    """True intraday 3h execution: rebalance daily targets at 00:00Z, exit crypto immediately at next 3h open on crash."""
    by_avail = {s: {b.ts_avail: b for b in panel_3h.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_3h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    nav_by_date: dict[str, float] = {}
    intraday_exits = 0
    in_crash_halt = False

    for ts in all_ts:
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        for sym in symbols:
            nxt = by_start[sym].get(ts)
            cur = by_avail[sym].get(ts)
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

        if ts in crash_timestamps:
            # Immediate strictly-causal intraday liquidation of crypto at next 3h bar open (ts_start == ts).
            has_crypto = any(ledger.units.get(s, Decimal(0)) > 0 for s in symbols if s != gold_symbol)
            if has_crypto:
                targets = {s: (0.25 if s == gold_symbol else 0.0) for s in symbols}
                ledger.rebalance_to_targets(ts, targets, exec_prices, tradable_symbols=tradable)
                intraday_exits += 1
            in_crash_halt = True
        elif ts in daily_targets_by_ts:
            # Daily 00:00Z rebalance clears intraday crash halt only if this 00:00Z bar itself is not crashing.
            in_crash_halt = False
            ledger.rebalance_to_targets(ts, daily_targets_by_ts[ts], exec_prices, tradable_symbols=tradable)
        elif in_crash_halt:
            pass

        nav_by_date[ts.date().isoformat()] = float(ledger.mark_nav(exec_prices))

    return {
        "nav_by_date": nav_by_date,
        "intraday_exits": intraday_exits,
        "fills": len(ledger.fills),
        "total_fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "turnover_multiple": round(float(ledger.cumulative_turnover_quote / ledger.starting_cash), 2),
    }
