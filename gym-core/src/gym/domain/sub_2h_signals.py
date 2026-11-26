"""Pure domain models for sub-2h (30m/1h) resampling, intraday entry geometries, and lot simulation.

Implements epoch-aligned strictly causal 1min -> 30m/1h/2h/4h OHLCV resampling, intraday bear/long
signal detectors (N1 pullback rejection, N2 deep-bear cascade, N4 coiled-down, sub-2h ignition long),
and a conservation-verified MultiHorizonBook simulator. Strictly pure (zero IO).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from .bellman_stopping import NonlinearBellmanModel
from .in_position_and_execution import tehran_execution_cost_bps
from .instrument_resolver import ResolverConfig, build_local_venue_offers
from .multi_horizon_book import (
    MultiHorizonBook,
    check_lot_intrabar_exit,
    resolve_safe_ignition_leverage,
)
from .optimal_exits import (
    ClosedTradeCapture,
    OptimalExitConfig,
    OptimalStoppingState,
    decide_optimal_stopping_action,
    summarize_exit_efficiency,
    trim_lot_fraction,
)
from .timeframe_panel import BarPoint
from .venue_leverage_models import NOBITEX_MARGIN_ELIGIBLE_USDT


def resample_1min_to_minutes(
    bars_1m: list[BarPoint],
    minutes: int = 30,
    *,
    min_bars_per_bucket: int = 18,
) -> list[BarPoint]:
    """Strictly causal epoch-aligned aggregation of 1min bars into 30m, 60m, 120m, or 240m OHLCV bars."""
    if not bars_1m or minutes <= 0:
        return []
    buckets: dict[datetime, list[BarPoint]] = {}
    step_sec = minutes * 60
    for b in bars_1m:
        epoch = int(b.ts_start.timestamp())
        slot_epoch = (epoch // step_sec) * step_sec
        b_start = datetime.fromtimestamp(slot_epoch, tz=b.ts_start.tzinfo)
        buckets.setdefault(b_start, []).append(b)
    out: list[BarPoint] = []
    span = timedelta(minutes=minutes)
    for b_start in sorted(buckets):
        grp = sorted(buckets[b_start], key=lambda x: x.ts_start)
        if len(grp) < min_bars_per_bucket:
            continue
        out.append(
            BarPoint(
                symbol=grp[0].symbol,
                ts_start=b_start,
                ts_avail=b_start + span,
                open=grp[0].open,
                high=max(x.high for x in grp),
                low=min(x.low for x in grp),
                close=grp[-1].close,
                volume=sum(x.volume for x in grp),
                bar_source=f"resampled_{minutes}m",
                clock_complete=len(grp) >= int(minutes * 0.85),
                nonzero_volume_fraction=sum(1 for x in grp if x.volume > 0) / len(grp),
                last_trade_age_bars=0,
                entry_eligible=True,
                mark_status="LIVE",
            )
        )
    return out


def compute_ema_series(closes: list[float], span: int) -> list[float]:
    """Compute causal exponential moving average over close series."""
    if not closes:
        return []
    alpha = 2.0 / (span + 1.0)
    out = [closes[0]]
    for c in closes[1:]:
        out.append(alpha * c + (1.0 - alpha) * out[-1])
    return out


@dataclass(frozen=True)
class IntradaySignal:
    """Strictly causal intraday signal emitted at bar close ts_avail."""

    symbol: str
    ts_avail: datetime
    direction: int  # 1 long, -1 short
    bar_vol: float
    stop_bps: float
    score: float
    family: str


def detect_n1_pullback_rejection_short(
    bars: list[BarPoint],
    ema_fast: list[float],
    ema_slow: list[float],
    vols: list[float],
    rets: list[float],
    i: int,
    *,
    breadth: float,
    s1_daily: float | None,
) -> IntradaySignal | None:
    """N1: In confirmed bear (breadth <= 0.20, 1d trend < -0.25), short failed dead-cat rallies rejecting EMA."""
    if i < 36 or i + 1 >= len(bars) or breadth > 0.20:
        return None
    if s1_daily is not None and s1_daily > -0.25:
        return None
    b = bars[i]
    if not b.entry_eligible or bars[i + 1].open <= 0:
        return None
    if not (ema_fast[i] < ema_slow[i] * 0.997 and ema_slow[i] < ema_slow[i - 6]):
        return None
    touched_ema = b.high >= ema_fast[i] * 0.998 or bars[i - 1].high >= ema_fast[i - 1] * 0.998
    rejected = b.close < ema_fast[i] and b.close < b.open
    span = max(b.high - b.low, 1e-9)
    upper_wick = max(0.0, b.high - max(b.open, b.close)) / span
    if not (touched_ema and rejected and (upper_wick >= 0.22 or (b.open - b.close) / span >= 0.45)):
        return None
    pr = rets[i - 36 : i]
    mr = sum(pr) / 36.0
    b_vol = max(0.004, math.sqrt(sum((r - mr) ** 2 for r in pr) / 35.0))
    raw_stop_bps = ((b.high - b.close) / max(b.close, 1e-9)) * 10_000.0 + 45.0
    stop_bps = max(140.0, min(420.0, max(raw_stop_bps, 2.0 * b_vol * 10_000.0)))
    mv = median(vols[i - 36 : i])
    vol_boost = min(2.0, b.volume / max(mv, 1e-9)) if mv > 0 else 1.0
    score = abs(s1_daily or -0.4) + 0.35 * upper_wick + 0.15 * vol_boost
    return IntradaySignal(b.symbol, b.ts_avail, -1, b_vol, stop_bps, score, "n1_pullback_short")


def detect_n4_coiled_down_short(
    bars: list[BarPoint],
    ema_slow: list[float],
    vols: list[float],
    rets: list[float],
    i: int,
    *,
    breadth: float,
    s1_daily: float | None,
) -> IntradaySignal | None:
    """N4: Downside mirror of coiled-spring ignition — tight vol compression breaking down on volume."""
    if i < 40 or i + 1 >= len(bars) or breadth > 0.25:
        return None
    if s1_daily is not None and s1_daily > -0.20:
        return None
    b = bars[i]
    if not b.entry_eligible or bars[i + 1].open <= 0:
        return None
    if not (b.close < ema_slow[i] and ema_slow[i] < ema_slow[i - 8]):
        return None
    hls = [(bars[j].high - bars[j].low) / max(bars[j].close, 1e-9) for j in range(i - 36, i)]
    vol_comp = (sum(hls[-6:]) / 6.0) / max(sum(hls) / 36.0, 1e-5)
    if vol_comp > 0.85:
        return None
    pr = rets[i - 36 : i]
    mr = sum(pr) / 36.0
    b_vol = max(0.004, math.sqrt(sum((r - mr) ** 2 for r in pr) / 35.0))
    z = (rets[i] - mr) / b_vol
    mv = median(vols[i - 36 : i])
    if z <= -1.65 and mv > 0 and b.volume >= 1.45 * mv and b.close < min(bars[j].low for j in range(i - 12, i)):
        coil_hi = max(bars[j].high for j in range(i - 6, i + 1))
        raw_stop = ((coil_hi - b.close) / max(b.close, 1e-9)) * 10_000.0 + 35.0
        stop_bps = max(150.0, min(480.0, max(raw_stop, 2.2 * b_vol * 10_000.0)))
        return IntradaySignal(b.symbol, b.ts_avail, -1, b_vol, stop_bps, abs(z) * (1.2 - vol_comp), "n4_coiled_down")
    return None


def detect_sub2h_ignition_long(
    bars: list[BarPoint],
    vols: list[float],
    rets: list[float],
    i: int,
    *,
    lookback_high: int = 48,
) -> IntradaySignal | None:
    """Causal 0.5h / 1h upward breakout trigger."""
    if i < max(48, lookback_high) or i + 1 >= len(bars):
        return None
    b = bars[i]
    if not b.entry_eligible or bars[i + 1].open <= 0:
        return None
    pr = rets[i - 36 : i]
    mr = sum(pr) / 36.0
    b_vol = max(0.004, math.sqrt(sum((r - mr) ** 2 for r in pr) / 35.0))
    z = (rets[i] - mr) / b_vol
    mv = median(vols[i - 36 : i])
    prev_hi = max(bars[j].high for j in range(i - lookback_high, i))
    if z >= 2.0 and mv > 0 and b.volume >= 1.8 * mv and b.close > prev_hi:
        stop_bps = max(140.0, min(520.0, 2.4 * b_vol * 10_000.0))
        return IntradaySignal(b.symbol, b.ts_avail, 1, b_vol, stop_bps, z * 0.01, "sub2h_ignition_long")
    return None


def is_deep_bear_cascade_active(
    btc_close: float,
    btc_ema20: float,
    btc_ema50: float,
    btc_ema20_prev: float,
    breadth: float,
    *,
    breadth_max: float = 0.15,
) -> bool:
    """N2 gate: active only during confirmed deep bear cascade; kills shorts immediately on BTC EMA20 reclaim."""
    return (
        breadth <= breadth_max
        and btc_close < btc_ema20
        and btc_ema20 < btc_ema50
        and btc_ema20 < btc_ema20_prev
    )


def rank_deep_bear_short_targets(
    symbols: tuple[str, ...],
    day_sigs: dict,
    ret_24h: dict[str, float],
    ema_fast_now: dict[str, float],
    ema_slow_now: dict[str, float],
    px_now: dict[str, float],
    *,
    top_k: int = 4,
    margin_eligible: frozenset[str] = NOBITEX_MARGIN_ELIGIBLE_USDT,
) -> list[tuple[str, float]]:
    """Select top-K weakest cascading margin-eligible crypto symbols (excluding metals)."""
    scored: list[tuple[str, float]] = []
    for sym in symbols:
        if sym not in margin_eligible or sym in {"XAUTUSDT", "PAXGUSDT", "SLVONUSDT"}:
            continue
        px = px_now.get(sym, 0.0)
        ef, es = ema_fast_now.get(sym, 0.0), ema_slow_now.get(sym, 0.0)
        if px <= 0 or ef <= 0 or es <= 0 or px >= ef or ef >= es:
            continue
        sig = day_sigs.get(sym)
        s1 = sig.s1_trend if (sig and sig.s1_trend is not None) else -0.35
        if s1 > -0.25:
            continue
        r24 = ret_24h.get(sym, 0.0)
        weakness = abs(s1) + max(0.0, -r24 * 6.0) + max(0.0, (es - px) / es * 5.0)
        scored.append((sym, weakness))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


@dataclass(frozen=True)
class Sub2hSimConfig:
    """Simulation parameters for sub-2h/intraday signal streams."""

    label: str
    bar_hours: float = 1.0
    max_leverage: float = 3.0
    max_slots: int = 3
    risk_per_trade_pct: float = 0.015
    max_col_per_pos_pct: float = 0.25
    entry_fee_bps: float = 16.0
    exit_fee_bps: float = 16.0
    max_hold_bars: int = 18
    trail_vol_mult: float = 2.4
    idle_pool_apr: float = 0.0264
    kill_shorts_on_btc_reclaim: bool = True
    use_bellman_exit: bool = False


def simulate_sub2h_signal_strategy(
    panel: dict[str, list[BarPoint]],
    signals_by_ts: dict[datetime, list[IntradaySignal]],
    btc_bear_active_by_ts: dict[datetime, bool],
    *,
    cfg: Sub2hSimConfig,
    bellman_model_fn=None,
    vrat_map: dict[str, dict[datetime, float]] | None = None,
    bret_map: dict[str, dict[datetime, float]] | None = None,
) -> tuple[dict, dict[datetime, float]]:
    """Run any 0.5h/1h/2h/4h signal stream through MultiHorizonBook with exact EOD borrow & pool yield."""
    symbols = tuple(sorted(panel))
    by_start = {s: {b.ts_start: b for b in panel[s]} for s in symbols}
    by_avail = {s: {b.ts_avail: b for b in panel[s]} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    offers_by_sym = {
        s: build_local_venue_offers(s, nobitex_leg_bps=cfg.entry_fee_bps, idle_pool_apr=cfg.idle_pool_apr)
        for s in symbols
    }
    r_cfg = ResolverConfig(max_venue_leverage=cfg.max_leverage, idle_pool_apr=cfg.idle_pool_apr)
    exit_cfg = OptimalExitConfig(use_e3_optimal_stopping=cfg.use_bellman_exit)

    book = MultiHorizonBook(free_cash=1000.0)
    trimmed: set[tuple[str, str]] = set()
    trades_log: list[ClosedTradeCapture] = []
    last_px: dict[str, float] = {}
    nav_by_ts: dict[datetime, float] = {}
    peak_nav, entries = 1000.0, 0

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, cfg.bar_hours, idle_pool_apr=cfg.idle_pool_apr, eod_borrow_bps=5.0)
        exec_px, tradable = _resolve_prices(symbols, by_start, by_avail, ts, last_px)
        btc_bear_on = btc_bear_active_by_ts.get(ts, True)
        hrs_eod = 24.0 - (ts.hour + ts.minute / 60.0)
        bm = bellman_model_fn(ts) if (cfg.use_bellman_exit and bellman_model_fn) else None

        _manage_sub2h_lots(
            book, by_avail, exec_px, tradable, ts, btc_bear_on, hrs_eod,
            vrat_map or {}, bret_map or {}, bm, trimmed, trades_log, cfg, exit_cfg,
        )

        equity = book.mark_equity(exec_px)
        peak_nav = max(peak_nav, equity)
        dd_pct = ((peak_nav - equity) / peak_nav * 100.0) if peak_nav > 0 else 0.0
        if equity < 20.0:
            nav_by_ts[ts] = equity
            continue

        for sig in sorted(signals_by_ts.get(ts, []), key=lambda x: x.score, reverse=True):
            if len(book.lots) >= cfg.max_slots or book.free_cash < 25.0:
                break
            if sig.symbol not in tradable or sig.symbol not in exec_px or any(k[0] == sig.symbol for k in book.lots):
                continue
            matched = [
                o for o in offers_by_sym.get(sig.symbol, ())
                if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == sig.direction
            ]
            if not matched:
                continue
            lev = resolve_safe_ignition_leverage(matched[0], sig.stop_bps, min(0.95, 0.55 + sig.score * 0.30), dd_pct, r_cfg)
            stop_frac = max(0.012, (sig.stop_bps + 35.0) / 10_000.0)
            tgt_col = min(cfg.max_col_per_pos_pct * equity, (cfg.risk_per_trade_pct * equity / stop_frac) / lev, max(0.0, book.free_cash - 5.0))
            if book.open_fast_margin_lot(
                symbol=sig.symbol, thesis_id=sig.family, direction=sig.direction, leverage=lev,
                target_collateral=tgt_col, entry_px=exec_px[sig.symbol], stop_bps=sig.stop_bps,
                take_profit_bps=0.0, offer=matched[0], ts=ts, entry_bar_vol=sig.bar_vol,
                entry_gru_score=sig.score, allow_internal_short_offset=False,
            ):
                entries += 1
        nav_by_ts[ts] = book.mark_equity(exec_px)

    return {
        "label": cfg.label,
        "entries": entries,
        "fees": round(book.total_fees, 2),
        "borrow": round(book.total_borrow, 2),
        "pool_yield": round(book.total_pool_yield, 2),
        "liqs": book.liquidations,
        "stops": book.stop_outs,
        "ml_exits": book.early_ml_exits,
        "pyramids": book.pyramids,
        "max_lev": round(book.max_leverage_used, 2),
        "eff": summarize_exit_efficiency(trades_log),
    }, nav_by_ts


def _resolve_prices(symbols, by_start, by_avail, ts, last_px) -> tuple[dict[str, float], set[str]]:
    exec_px: dict[str, float] = {}
    tradable: set[str] = set()
    for sym in symbols:
        nxt, cur = by_start[sym].get(ts), by_avail[sym].get(ts)
        if nxt is not None and nxt.open > 0:
            exec_px[sym], last_px[sym] = nxt.open, nxt.open
            if cur is not None and cur.entry_eligible:
                tradable.add(sym)
        elif cur is not None and cur.close > 0:
            exec_px[sym], last_px[sym] = cur.close, cur.close
        elif sym in last_px:
            exec_px[sym] = last_px[sym]
    return exec_px, tradable


def _manage_sub2h_lots(
    book: MultiHorizonBook,
    by_avail: dict[str, dict[datetime, BarPoint]],
    exec_px: dict[str, float],
    tradable: set[str],
    ts: datetime,
    btc_bear_on: bool,
    hrs_eod: float,
    vrat_map: dict[str, dict[datetime, float]],
    bret_map: dict[str, dict[datetime, float]],
    bm: NonlinearBellmanModel | None,
    trimmed: set[tuple[str, str]],
    trades_log: list[ClosedTradeCapture],
    cfg: Sub2hSimConfig,
    exit_cfg: OptimalExitConfig,
) -> None:
    btc_r = bret_map.get("BTCUSDT", {}).get(ts, 0.0)
    exit_fee = cfg.exit_fee_bps if cfg.exit_fee_bps < 12.0 else tehran_execution_cost_bps(ts.hour)
    for key in list(book.lots):
        lot = book.lots[key]
        lot.age_bars += 1
        bar = by_avail.get(lot.symbol, {}).get(ts)
        if bar is not None:
            evt, px, fbps = check_lot_intrabar_exit(lot, bar, taker_exit_bps=exit_fee, oco_maker_exit_bps=4.5, use_oco_maker_tp=False)
            if evt == "LIQ":
                _record_trade(trades_log, lot, px, ts, "LIQ")
                book.liquidations += 1
                del book.lots[key]
                trimmed.discard(key)
                continue
            if evt == "STOP":
                _record_trade(trades_log, lot, px, ts, "STOP")
                book.close_lot(key, px, fbps)
                book.stop_outs += 1
                trimmed.discard(key)
                continue
            lot.peak_price = max(lot.peak_price, bar.close) if lot.direction > 0 else min(lot.peak_price, bar.close)

        if lot.symbol not in tradable or lot.symbol not in exec_px or bar is None:
            continue
        px_now = exec_px[lot.symbol]
        if lot.direction < 0 and cfg.kill_shorts_on_btc_reclaim and not btc_bear_on:
            _record_trade(trades_log, lot, px_now, ts, "BTC_RECLAIM_KILL")
            book.close_lot(key, px_now, exit_fee)
            trimmed.discard(key)
            continue
        trail_hit = (
            bar.close < lot.peak_price * (1.0 - cfg.trail_vol_mult * lot.entry_bar_vol)
            if lot.direction > 0
            else bar.close > lot.peak_price * (1.0 + cfg.trail_vol_mult * lot.entry_bar_vol)
        )
        if lot.age_bars >= cfg.max_hold_bars or trail_hit:
            _record_trade(trades_log, lot, px_now, ts, "TRAIL" if trail_hit else "TIMEOUT")
            book.close_lot(key, px_now, exit_fee)
            trimmed.discard(key)
            continue
        if bm is not None:
            upnl = lot.direction * (bar.close - lot.entry_price) / max(lot.entry_price, 1e-9)
            mfe = max(0.0, lot.direction * (lot.peak_price - lot.entry_price) / max(lot.entry_price, 1e-9))
            gb_r = (mfe - upnl) / max(mfe, 1e-4) if mfe > 1e-4 else 0.0
            span = max(bar.high - bar.low, 1e-9)
            wick = (max(0.0, bar.high - bar.close) if lot.direction > 0 else max(0.0, bar.close - bar.low)) / span
            st = OptimalStoppingState(
                age_bars=lot.age_bars, unrealized_ret=upnl, peak_mfe=mfe, giveback_ratio=gb_r,
                upper_wick_ratio=wick, volume_ratio=vrat_map.get(lot.symbol, {}).get(ts, 1.0),
                bar_ret_z=lot.direction * bret_map.get(lot.symbol, {}).get(ts, 0.0) / max(lot.entry_bar_vol, 1e-4),
                rel_btc_ret=lot.direction * (bret_map.get(lot.symbol, {}).get(ts, 0.0) - btc_r),
                hours_to_utc_eod=hrs_eod, entry_gru_score=lot.entry_gru_score,
            )
            act = decide_optimal_stopping_action(
                bm.predict_wait_value_bps(st), st, already_pyramided=lot.pyramided,
                already_trimmed=(key in trimmed), cfg=exit_cfg,
            )
            if act == "OPTIMAL_EXIT":
                _record_trade(trades_log, lot, px_now, ts, "BELLMAN_EXIT")
                book.close_lot(key, px_now, exit_fee)
                book.early_ml_exits += 1
                trimmed.discard(key)
            elif act == "OPTIMAL_TRIM_50":
                trim_lot_fraction(book, key, 0.50, px_now, 4.5)
                trimmed.add(key)
            elif act == "FREE_ROLL_PYRAMID":
                book.pyramid_lot_on_house_money(key, px_now, add_fraction=0.40, entry_fee_bps=exit_fee)


def _record_trade(trades_log: list[ClosedTradeCapture], lot, exit_px: float, ts: datetime, reason: str) -> None:
    if lot.entry_price <= 0:
        return
    real_bps = lot.direction * ((exit_px / lot.entry_price) - 1.0) * 10_000.0
    mfe_bps = max(0.0, lot.direction * ((lot.peak_price - lot.entry_price) / lot.entry_price) * 10_000.0)
    held_h = max(0.5, (ts - lot.entry_ts).total_seconds() / 3600.0)
    trades_log.append(
        ClosedTradeCapture(
            realized_ret_bps=real_bps, peak_mfe_bps=mfe_bps, giveback_bps=max(0.0, mfe_bps - real_bps),
            held_hours=held_h, exit_reason=reason, closed_before_eod_borrow=(lot.entry_ts.date() == ts.date()),
        )
    )
