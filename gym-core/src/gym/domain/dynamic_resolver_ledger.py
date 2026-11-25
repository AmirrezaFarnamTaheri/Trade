"""Strictly causal self-financing multi-instrument replay ledger for v3 Dynamic Resolver evaluation.

Supports simultaneous Spot, Isolated Margin Long/Short (Nobitex EOD UTC borrow or Wallex 4h borrow),
Idle USDT Liquidity Pool yield (+2.64% APR), and pluggable Perpetual Futures (two-way funding rate),
with exact bar-by-bar high/low stop-loss and liquidation checks. Pure domain (zero IO).
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .instrument_resolver import (
    InstrumentOffer,
    MarketView,
    PositionState,
    ResolvedAction,
    ResolverConfig,
    liquidation_distance_bps,
)
from .timeframe_panel import BarPoint

ResolverFn = Callable[
    [
        dict[str, MarketView],
        dict[str, tuple[InstrumentOffer, ...]],
        dict[str, PositionState],
        float,
        float,
        float,
        dict[tuple[str, str], float],
        ResolverConfig,
    ],
    dict[str, ResolvedAction],
]


@dataclass(frozen=True)
class DynamicResolverSummary:
    label: str
    days: int
    ending_nav: float
    ret_pct: float
    stress_ret_pct: float
    ann_sharpe: float
    max_dd_pct: float
    liquidations: int
    stop_outs: int
    total_fees_usdt: float
    total_borrow_usdt: float
    total_funding_net_usdt: float
    total_pool_yield_usdt: float
    spot_entries: int
    margin_long_entries: int
    margin_short_entries: int
    perp_long_entries: int
    perp_short_entries: int
    sell_reduces: int
    switches: int
    max_leverage_used: float
    avg_leverage_when_levered: float


@dataclass
class _OpenPos:
    symbol: str
    venue: str
    instrument_type: str
    direction: int
    leverage: float
    collateral: float
    notional: float
    qty: float
    entry_price: float
    stop_price: float
    liq_price: float
    carry_model: str
    carry_rate_bps: float
    exit_cost_bps: float
    entry_ts: datetime
    last_utc_date: str
    horizon_hours: float = 16.0


def _stop_and_liq_prices(
    entry_px: float,
    direction: int,
    stop_bps: float,
    offer: InstrumentOffer,
    leverage: float,
) -> tuple[float, float]:
    liq_bps = liquidation_distance_bps(offer, leverage)
    if direction > 0:
        stop_px = entry_px * max(0.05, 1.0 - stop_bps / 10_000.0) if stop_bps > 0 else 0.0
        liq_px = entry_px * max(0.0, 1.0 - liq_bps / 10_000.0) if leverage > 1.0 else 0.0
    else:
        stop_px = entry_px * (1.0 + stop_bps / 10_000.0) if stop_bps > 0 else entry_px * 3.0
        liq_px = entry_px * (1.0 + liq_bps / 10_000.0)
    return stop_px, liq_px


def _pos_equity(p: _OpenPos, mark_px: float) -> float:
    pnl = p.direction * p.qty * (mark_px - p.entry_price)
    return p.collateral + pnl


def _accrue_carry(p: _OpenPos, ts: datetime, bar_hours: float) -> tuple[float, float]:
    """Return (borrow_paid_usdt, funding_paid_usdt) for one bar; funding < 0 means funding earned."""
    if p.carry_model == "NONE":
        return 0.0, 0.0
    if p.carry_model == "FUNDING_RATE":
        f_paid = p.direction * p.notional * (p.carry_rate_bps / 10_000.0) * (bar_hours / 8.0)
        return 0.0, f_paid
    borrowed = p.notional if p.direction < 0 else max(0.0, p.notional - p.collateral)
    if borrowed <= 0.0:
        return 0.0, 0.0
    if p.carry_model == "EOD_DAILY_BORROW":
        cur_day = ts.date().isoformat()
        if cur_day != p.last_utc_date:
            p.last_utc_date = cur_day
            return borrowed * (p.carry_rate_bps / 10_000.0), 0.0
        return 0.0, 0.0
    if p.carry_model == "INTERVAL_4H_BORROW":
        return borrowed * (p.carry_rate_bps / 10_000.0) * (bar_hours / 4.0), 0.0
    return 0.0, 0.0


def _summarize_nav_dict(nav_by_date: dict[str, float], stress_iso: str) -> tuple[float, float, float, float, float]:
    dates = sorted(nav_by_date)
    if len(dates) < 2:
        return 1000.0, 0.0, 0.0, 0.0, 0.0
    navs = [nav_by_date[d] for d in dates]
    start_nav, end_nav = navs[0], navs[-1]
    ret_pct = ((end_nav / start_nav) - 1.0) * 100.0 if start_nav > 0 else 0.0
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
    return end_nav, ret_pct, st_ret, sharpe, max_dd * 100.0


def _close_position(p: _OpenPos, exit_px: float, fee_bps: float) -> tuple[float, float]:
    """Close position at exit_px and return (returned_cash_usdt, exit_fee_usdt)."""
    exit_notional = p.qty * exit_px
    fee = exit_notional * (fee_bps / 10_000.0)
    returned = max(0.0, _pos_equity(p, exit_px) - fee)
    return returned, fee


def _check_intrabar_exits(
    open_pos: dict[str, _OpenPos],
    bar_by_avail: dict[str, dict[datetime, BarPoint]],
    ts: datetime,
) -> tuple[float, float, int, int]:
    """Process exact intra-bar high/low liquidation and stop-loss checks before rebalance."""
    cash_delta, fees = 0.0, 0.0
    liqs, stops = 0, 0
    for sym in list(open_pos):
        p = open_pos[sym]
        bar = bar_by_avail.get(sym, {}).get(ts)
        if bar is None:
            continue
        if p.direction > 0:
            if p.liq_price > 0.0 and bar.low <= p.liq_price:
                liqs += 1
                del open_pos[sym]
                continue
            if p.stop_price > 0.0 and bar.low <= p.stop_price:
                exit_px = min(bar.open, p.stop_price) if bar.open < p.stop_price else p.stop_price
                ret_c, fee = _close_position(p, exit_px, p.exit_cost_bps + 8.0)
                cash_delta += ret_c
                fees += fee
                stops += 1
                del open_pos[sym]
        else:
            if p.liq_price > 0.0 and bar.high >= p.liq_price:
                liqs += 1
                del open_pos[sym]
                continue
            if p.stop_price > 0.0 and bar.high >= p.stop_price:
                exit_px = max(bar.open, p.stop_price) if bar.open > p.stop_price else p.stop_price
                ret_c, fee = _close_position(p, exit_px, p.exit_cost_bps + 8.0)
                cash_delta += ret_c
                fees += fee
                stops += 1
                del open_pos[sym]
    return cash_delta, fees, liqs, stops


def _resolve_bar_prices(
    symbols: tuple[str, ...],
    by_start: dict[str, dict[datetime, BarPoint]],
    by_avail: dict[str, dict[datetime, BarPoint]],
    ts: datetime,
    last_px: dict[str, float],
) -> tuple[dict[str, float], set[str]]:
    exec_px: dict[str, float] = {}
    tradable: set[str] = set()
    for sym in symbols:
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
    return exec_px, tradable


def _build_position_states(
    open_pos: dict[str, _OpenPos],
    exec_px: dict[str, float],
    ts: datetime,
) -> dict[str, PositionState]:
    states: dict[str, PositionState] = {}
    for sym, p in open_pos.items():
        px = exec_px.get(sym, p.entry_price)
        upnl_bps = p.direction * ((px / p.entry_price) - 1.0) * 10_000.0 if p.entry_price > 0 else 0.0
        states[sym] = PositionState(
            symbol=sym, venue=p.venue, instrument_type=p.instrument_type,
            direction=p.direction, leverage=p.leverage, collateral_usdt=p.collateral,
            notional_usdt=p.qty * px, entry_price=p.entry_price,
            stop_price=p.stop_price, liquidation_price=p.liq_price,
            held_hours=(ts - p.entry_ts).total_seconds() / 3600.0,
            unrealized_pnl_bps=upnl_bps, entry_ts=p.entry_ts,
            horizon_hours=p.horizon_hours,
        )
    return states


def _apply_closes_and_reduces(
    actions: dict[str, ResolvedAction],
    open_pos: dict[str, _OpenPos],
    exec_px: dict[str, float],
    tradable: set[str],
    stats: dict,
) -> float:
    freed = 0.0
    for sym, act in actions.items():
        p = open_pos.get(sym)
        if p is None or sym not in tradable or sym not in exec_px:
            continue
        px = exec_px[sym]
        if act.action in {"SELL_CLOSE", "PARK_POOL", "FLIP", "SWITCH_INSTRUMENT"}:
            ret_c, fee = _close_position(p, px, p.exit_cost_bps)
            freed += ret_c
            stats["fees"] += fee
            stats["reduces" if act.action == "SELL_CLOSE" else "switches"] += 1
            del open_pos[sym]
        elif act.action == "REDUCE" and act.target_notional_usdt < p.qty * px:
            frac_keep = max(0.0, min(1.0, act.target_notional_usdt / max(1e-9, p.qty * px)))
            frac_sell = 1.0 - frac_keep
            fee = (p.qty * px * frac_sell) * (p.exit_cost_bps / 10_000.0)
            freed += max(0.0, _pos_equity(p, px) * frac_sell - fee)
            stats["fees"] += fee
            stats["reduces"] += 1
            p.qty *= frac_keep
            p.notional *= frac_keep
            # Preserve exact cost-basis conservation: C' = f*C with unchanged entry_price
            p.collateral *= frac_keep
    return freed


def _apply_opens(
    actions: dict[str, ResolvedAction],
    views_now: dict[str, MarketView],
    offers_now: dict[str, tuple[InstrumentOffer, ...]],
    open_pos: dict[str, _OpenPos],
    exec_px: dict[str, float],
    tradable: set[str],
    free_cash: float,
    ts: datetime,
    stats: dict,
    lev_samples: list[float],
) -> float:
    for sym, act in actions.items():
        if sym not in tradable or sym not in exec_px or sym in open_pos:
            continue
        if act.action not in {"OPEN", "FLIP", "SWITCH_INSTRUMENT"} or act.target_collateral_usdt < 5.0:
            continue
        matched = [
            o for o in offers_now.get(sym, ())
            if o.venue == act.venue and o.instrument_type == act.instrument_type and o.direction == act.direction
        ]
        if not matched:
            continue
        offer = matched[0]
        px = exec_px[sym]
        col = min(act.target_collateral_usdt, max(0.0, free_cash - 1.0))
        notional = col * act.leverage
        entry_fee = notional * (offer.entry_cost_bps / 10_000.0)
        if col <= entry_fee + 2.0 or free_cash < col:
            continue
        free_cash -= col
        stats["fees"] += entry_fee
        stop_px, liq_px = _stop_and_liq_prices(px, act.direction, act.stop_distance_bps, offer, act.leverage)
        v_now = views_now.get(sym)
        horizon_h = min(48.0, v_now.horizon_hours) if (v_now and v_now.horizon_hours > 0) else 16.0
        open_pos[sym] = _OpenPos(
            symbol=sym, venue=offer.venue, instrument_type=offer.instrument_type,
            direction=act.direction, leverage=act.leverage, collateral=col - entry_fee,
            notional=notional, qty=notional / px, entry_price=px,
            stop_price=stop_px, liq_price=liq_px, carry_model=offer.carry_model,
            carry_rate_bps=offer.carry_rate_bps, exit_cost_bps=offer.exit_cost_bps,
            entry_ts=ts, last_utc_date=ts.date().isoformat(), horizon_hours=horizon_h,
        )
        _record_entry_stats(stats, lev_samples, offer.instrument_type, act.direction, act.leverage)
    return free_cash


def simulate_dynamic_resolver(
    panel_2h: dict[str, list[BarPoint]],
    views_by_ts: dict[datetime, dict[str, MarketView]],
    offers_by_ts: dict[datetime, dict[str, tuple[InstrumentOffer, ...]]],
    cov_by_ts: dict[datetime, dict[tuple[str, str], float]],
    resolver_fn: ResolverFn,
    *,
    label: str,
    cfg: ResolverConfig,
    bar_hours: float = 2.0,
    stress_iso: str = "2025-11-24",
) -> tuple[DynamicResolverSummary, dict[str, float]]:
    """Run one competing resolver through the exact multi-instrument causal replay ledger."""
    symbols = tuple(sorted(panel_2h))
    by_start = {s: {b.ts_start: b for b in panel_2h[s]} for s in symbols}
    by_avail = {s: {b.ts_avail: b for b in panel_2h[s]} for s in symbols}
    eval_ts = sorted(views_by_ts)

    free_cash, peak_nav = 1000.0, 1000.0
    open_pos: dict[str, _OpenPos] = {}
    last_px: dict[str, float] = {}
    nav_by_date: dict[str, float] = {}
    stats = {
        "fees": 0.0, "borrow": 0.0, "funding": 0.0, "pool_yield": 0.0,
        "liqs": 0, "stops": 0, "spot_in": 0, "ml_in": 0, "ms_in": 0,
        "pl_in": 0, "ps_in": 0, "reduces": 0, "switches": 0, "max_lev": 1.0,
    }
    lev_samples: list[float] = []
    bar_pool_rate = cfg.idle_pool_apr * (bar_hours / 8760.0)

    for ts in eval_ts:
        cd, cf, lq, st = _check_intrabar_exits(open_pos, by_avail, ts)
        free_cash += cd
        stats["fees"] += cf
        stats["liqs"] += lq
        stats["stops"] += st

        for sym in list(open_pos):
            p = open_pos[sym]
            brw, fnd = _accrue_carry(p, ts, bar_hours)
            p.collateral -= brw + fnd
            stats["borrow"] += brw
            stats["funding"] += fnd
            if p.collateral <= 0.0:
                stats["liqs"] += 1
                del open_pos[sym]
        if free_cash > 0.0 and bar_pool_rate > 0.0:
            yld = free_cash * bar_pool_rate
            free_cash += yld
            stats["pool_yield"] += yld

        exec_px, tradable = _resolve_bar_prices(symbols, by_start, by_avail, ts, last_px)
        equity = max(0.0, free_cash + sum(_pos_equity(p, exec_px.get(s, p.entry_price)) for s, p in open_pos.items()))
        peak_nav = max(peak_nav, equity)
        dd_pct = ((peak_nav - equity) / peak_nav * 100.0) if peak_nav > 0 else 0.0
        nav_by_date[ts.date().isoformat()] = equity
        if equity < 20.0:
            continue

        pos_states = _build_position_states(open_pos, exec_px, ts)
        hours_to_eod = 24.0 - (ts.hour + ts.minute / 60.0)
        offers_now = offers_by_ts[ts]
        actions = resolver_fn(
            views_by_ts[ts], offers_now, pos_states, equity, hours_to_eod, dd_pct, cov_by_ts.get(ts, {}), cfg,
        )
        free_cash += _apply_closes_and_reduces(actions, open_pos, exec_px, tradable, stats)
        free_cash = _apply_opens(
            actions, views_by_ts[ts], offers_now, open_pos, exec_px, tradable, free_cash, ts, stats, lev_samples,
        )
        nav_by_date[ts.date().isoformat()] = max(
            0.0, free_cash + sum(_pos_equity(p, exec_px.get(s, p.entry_price)) for s, p in open_pos.items())
        )

    end_nav, ret_p, st_p, sr, mdd = _summarize_nav_dict(nav_by_date, stress_iso)
    avg_lev = (sum(lev_samples) / len(lev_samples)) if lev_samples else 1.0
    return (
        DynamicResolverSummary(
            label=label, days=len(nav_by_date), ending_nav=round(end_nav, 2),
            ret_pct=round(ret_p, 2), stress_ret_pct=round(st_p, 2), ann_sharpe=round(sr, 3),
            max_dd_pct=round(mdd, 2), liquidations=int(stats["liqs"]), stop_outs=int(stats["stops"]),
            total_fees_usdt=round(float(stats["fees"]), 2), total_borrow_usdt=round(float(stats["borrow"]), 2),
            total_funding_net_usdt=round(float(stats["funding"]), 2),
            total_pool_yield_usdt=round(float(stats["pool_yield"]), 2),
            spot_entries=int(stats["spot_in"]), margin_long_entries=int(stats["ml_in"]),
            margin_short_entries=int(stats["ms_in"]), perp_long_entries=int(stats["pl_in"]),
            perp_short_entries=int(stats["ps_in"]), sell_reduces=int(stats["reduces"]),
            switches=int(stats["switches"]), max_leverage_used=round(float(stats["max_lev"]), 2),
            avg_leverage_when_levered=round(avg_lev, 2),
        ),
        nav_by_date,
    )


def _record_entry_stats(
    stats: dict,
    lev_samples: list[float],
    instrument_type: str,
    direction: int,
    leverage: float,
) -> None:
    if instrument_type == "SPOT":
        stats["spot_in"] += 1
    elif instrument_type == "ISOLATED_MARGIN":
        if direction > 0:
            stats["ml_in"] += 1
        else:
            stats["ms_in"] += 1
    elif instrument_type == "PERP_FUTURE":
        if direction > 0:
            stats["pl_in"] += 1
        else:
            stats["ps_in"] += 1
    if leverage > 1.0:
        lev_samples.append(leverage)
        stats["max_lev"] = max(float(stats["max_lev"]), leverage)
