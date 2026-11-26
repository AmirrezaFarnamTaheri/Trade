"""Pure domain math for 33-market multi-asset sleeves, continuous ML tilt, 4h crash exit, and paper margin."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .strategy_sleeves import SleeveSignal, _CausalEwmacState, _clamp1, _trailing_beta
from .timeframe_panel import BarPoint
from .volatility_models import (
    OhlcBar,
    asymmetric_ewma_volatility,
    yang_zhang_volatility,
)

BASE_13_SYMBOLS = (
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
)

EXPANSION_20_SYMBOLS = (
    # Tier 1: Non-crypto commodities & metals (PAXG unlocks 2022-2024 gold)
    "PAXGUSDT",
    "SLVONUSDT",
    "USOONUSDT",
    "COPXONUSDT",
    "UNGONUSDT",
    # Tier 2: Deep 4-year crypto majors & DeFi/L1s
    "AVAXUSDT",
    "NEARUSDT",
    "UNIUSDT",
    "ATOMUSDT",
    "DOTUSDT",
    "XLMUSDT",
    "FILUSDT",
    "ETCUSDT",
    "FETUSDT",
    "ARBUSDT",
    # Tier 3: Newer leaders & parity twin
    "ONDOUSDT",
    "ENAUSDT",
    "RENDERUSDT",
    "SUIUSDT",
    "WBTCUSDT",
)

EXPANDED_33_SYMBOLS = BASE_13_SYMBOLS + EXPANSION_20_SYMBOLS
DEFENSIVE_GOLD_SYMBOLS = frozenset(("PAXGUSDT", "XAUTUSDT"))
COMMODITY_SYMBOLS = frozenset(("PAXGUSDT", "XAUTUSDT", "SLVONUSDT", "USOONUSDT", "COPXONUSDT", "UNGONUSDT"))


def depth_scaled_l2_impact(
    displayed_depth_usdt: float | None,
    *,
    base_impact: float = 0.0020,
    ref_depth_usdt: float = 2000.0,
    min_impact: float = 0.0005,
    max_impact: float = 0.0250,
) -> float:
    """Scale quadratic impact inversely with live 5-level displayed USDT depth."""
    if displayed_depth_usdt is None or displayed_depth_usdt <= 0:
        return max_impact
    scaled = base_impact * (ref_depth_usdt / max(displayed_depth_usdt, 100.0))
    return max(min_impact, min(max_impact, scaled))


def spread_aware_l1_cost(
    half_spread_bps: float | None,
    *,
    fee_rate: float = 0.0013,
    default_half_spread_bps: float = 10.0,
    max_half_spread_bps: float = 150.0,
) -> float:
    """Combine venue fee with half-spread friction for ADMM L1 no-trade band."""
    hs = default_half_spread_bps if half_spread_bps is None else max(0.0, min(max_half_spread_bps, half_spread_bps))
    return fee_rate + hs / 10000.0


def continuous_ml_tilt(
    prob: float,
    *,
    base_rate: float = 0.50,
    floor: float = 0.50,
    cap: float = 1.40,
) -> float:
    """Convert calibrated win probability into a smooth ADMM conviction multiplier (no binary veto)."""
    denom = max(0.05, base_rate)
    return max(floor, min(cap, prob / denom))


def compute_multi_asset_sleeves(
    panel_by_symbol: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    *,
    btc_symbol: str = "BTCUSDT",
    defensive_gold_symbols: frozenset[str] = DEFENSIVE_GOLD_SYMBOLS,
    non_crypto_symbols: frozenset[str] = COMMODITY_SYMBOLS,
    min_active_crypto: int = 4,
    warmup_bars: int = 128,
) -> dict[datetime, dict[str, SleeveSignal]]:
    """Compute causal S1 (all-asset trend), S2 (crypto residual), and S5 (dual-gold defensive switch).

    Commodities and metals are excluded from crypto breadth so non-crypto strength never masks crypto stress.
    When both PAXGUSDT and XAUTUSDT are eligible, S5 scores both (higher trend twin gets a small edge).
    """
    by_sym_ts = {s: {b.ts_avail: b for b in panel_by_symbol.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_sym_ts.values() for t in d})

    ewmac_state = {s: _CausalEwmacState(warmup=warmup_bars) for s in symbols}
    ohlc_hist: dict[str, list[OhlcBar]] = {s: [] for s in symbols}
    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}
    down_ratio_hist: list[float] = []
    output: dict[datetime, dict[str, SleeveSignal]] = {}

    for ts in all_ts:
        s1_map: dict[str, float | None] = {}
        above50_map: dict[str, bool | None] = {}
        vol_map: dict[str, float] = {}
        down_ratio_map: dict[str, float] = {}
        active_crypto: list[str] = []

        for sym in symbols:
            bar = by_sym_ts[sym].get(ts)
            if bar is None:
                continue
            ohlc_hist[sym].append(OhlcBar(bar.open, bar.high, bar.low, bar.close))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append((bar.close - prev_close[sym]) / prev_close[sym])
            prev_close[sym] = bar.close

            yz = yang_zhang_volatility(ohlc_hist[sym][-20:])
            dv = asymmetric_ewma_volatility(ret_hist[sym][-30:]) if len(ret_hist[sym]) >= 5 else yz
            vol_map[sym] = yz
            down_ratio_map[sym] = dv / max(yz, 1e-4)

            s1_val, above50 = ewmac_state[sym].update(bar.close, yz)
            s1_map[sym] = s1_val
            above50_map[sym] = above50
            if sym not in non_crypto_symbols and bar.entry_eligible and above50 is not None:
                active_crypto.append(sym)

        breadth: float | None = None
        if len(active_crypto) >= min_active_crypto:
            breadth = sum(1 for s in active_crypto if above50_map[s] is True) / len(active_crypto)

        avg_down_ratio = (
            sum(down_ratio_map[s] for s in active_crypto) / len(active_crypto) if active_crypto else 1.0
        )
        down_ratio_hist.append(avg_down_ratio)
        if len(down_ratio_hist) >= 30:
            trailing = sorted(down_ratio_hist[-180:])
            p90_down = trailing[int(0.90 * (len(trailing) - 1))]
            vol_spike = avg_down_ratio >= p90_down
        else:
            vol_spike = False

        s2_map: dict[str, float | None] = {s: None for s in symbols}
        btc_rets = ret_hist.get(btc_symbol, [])
        if len(active_crypto) >= min_active_crypto and len(btc_rets) >= 30:
            btc_30 = sum(btc_rets[-30:])
            raw_resid: list[tuple[str, float]] = []
            for sym in sorted(active_crypto):
                r_list = ret_hist[sym]
                if len(r_list) < 30:
                    continue
                beta = 1.0 if sym == btc_symbol else _trailing_beta(r_list[-60:], btc_rets[-60:])
                raw_resid.append((sym, sum(r_list[-30:]) - beta * btc_30))
            if len(raw_resid) >= min_active_crypto:
                vals = [v for _, v in raw_resid]
                mean_v = sum(vals) / len(vals)
                std_v = math.sqrt(sum((v - mean_v) ** 2 for v in vals) / len(vals))
                for sym, v in raw_resid:
                    z = (v - mean_v) / max(std_v, 1e-6)
                    own_pos = sum(ret_hist[sym][-30:]) >= 0.0
                    s2_map[sym] = _clamp1(z / 2.0) if (z > 0 and own_pos) else min(0.0, _clamp1(z / 2.0))

        defensive_intensity = 0.0
        if breadth is not None and breadth < 0.35:
            defensive_intensity = min(1.0, (0.35 - breadth) / 0.35 + (0.25 if vol_spike else 0.0))
        elif vol_spike:
            defensive_intensity = 0.40

        day_out: dict[str, SleeveSignal] = {}
        for sym in symbols:
            bar = by_sym_ts[sym].get(ts)
            if bar is None:
                continue
            s5_val: float | None = None
            if sym in defensive_gold_symbols and bar.entry_eligible and s1_map.get(sym) is not None:
                gold_trend_ok = (s1_map[sym] or 0.0) >= -0.25
                s5_val = defensive_intensity if gold_trend_ok else 0.0
            day_out[sym] = SleeveSignal(
                symbol=sym,
                as_of=ts,
                s1_trend=s1_map.get(sym),
                s2_residual_mom=s2_map.get(sym),
                s5_defensive_gold=s5_val,
                crypto_breadth=breadth,
                active_crypto_count=len(active_crypto),
                yang_zhang_vol=vol_map[sym],
                downside_vol_ratio=down_ratio_map[sym],
                eligible_for_entry=bar.entry_eligible and (s1_map.get(sym) is not None),
            )
        output[ts] = day_out

    return output


def compute_4h_crash_exit_dates(
    panel_4h: dict[str, list[BarPoint]],
    crypto_symbols: tuple[str, ...],
    *,
    breadth_threshold: float = 0.20,
    min_active: int = 4,
) -> set[str]:
    """Identify UTC dates where strictly causal 4h breadth collapse + downside-vol spike triggers early exit."""
    by_sym_ts = {s: {b.ts_avail: b for b in panel_4h.get(s, [])} for s in crypto_symbols}
    all_ts = sorted({t for d in by_sym_ts.values() for t in d})

    ema120: dict[str, float] = {}
    counts: dict[str, int] = {s: 0 for s in crypto_symbols}
    ret_hist: dict[str, list[float]] = {s: [] for s in crypto_symbols}
    ohlc_hist: dict[str, list[OhlcBar]] = {s: [] for s in crypto_symbols}
    prev_close: dict[str, float] = {}
    down_hist: list[float] = []
    crash_dates: set[str] = set()
    alpha = 2.0 / 121.0

    for ts in all_ts:
        above = 0
        active = 0
        ratios: list[float] = []
        for sym in crypto_symbols:
            bar = by_sym_ts[sym].get(ts)
            if bar is None:
                continue
            counts[sym] += 1
            ema120[sym] = bar.close if sym not in ema120 else (1.0 - alpha) * ema120[sym] + alpha * bar.close
            ohlc_hist[sym].append(OhlcBar(bar.open, bar.high, bar.low, bar.close))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append((bar.close - prev_close[sym]) / prev_close[sym])
            prev_close[sym] = bar.close
            if counts[sym] >= 120 and bar.entry_eligible:
                active += 1
                if bar.close > ema120[sym]:
                    above += 1
                yz = yang_zhang_volatility(ohlc_hist[sym][-24:])
                dv = asymmetric_ewma_volatility(ret_hist[sym][-36:]) if len(ret_hist[sym]) >= 6 else yz
                ratios.append(dv / max(yz, 1e-4))
        if active < min_active:
            continue
        breadth = above / active
        avg_r = sum(ratios) / len(ratios)
        down_hist.append(avg_r)
        if len(down_hist) >= 60:
            tr = sorted(down_hist[-180:])
            p92 = tr[int(0.92 * (len(tr) - 1))]
            if breadth < breadth_threshold and avg_r >= p92:
                daily_avail_date = (
                    ts.date().isoformat()
                    if (ts.hour == 0 and ts.minute == 0 and ts.second == 0)
                    else (ts + timedelta(days=1)).date().isoformat()
                )
                crash_dates.add(daily_avail_date)
    return crash_dates


@dataclass(frozen=True)
class MarginShortStats:
    name: str
    ending_nav: float
    ret_pct: float
    ann_sharpe: float
    max_dd_pct: float
    trades: int
    liquidations: int
    total_borrow_usdt: float
    total_fees_usdt: float


def simulate_wallex_margin_short_cascades(
    panel_1d: dict[str, list[BarPoint]],
    signals: dict[datetime, dict[str, SleeveSignal]],
    eval_dates: list[datetime],
    short_symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    *,
    starting_cash: float = 1000.0,
    leverage: float = 1.5,
    max_hold_days: int = 5,
    breadth_entry_max: float = 0.15,
    breadth_exit_min: float = 0.25,
    daily_borrow_rate: float = 0.0009,       # 0.015% / 4h = 0.09%/day (32.85%/yr)
    leg_fee_and_slip: float = 0.0028,        # 13 bps taker fee + 15 bps conservative half-spread
    liq_margin_ratio: float = 0.15,
) -> MarginShortStats:
    """Strictly causal short-cascade paper test charging exact Wallex 4h borrow fees and bar-high liquidations."""
    by_sym_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in short_symbols}
    by_sym_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in short_symbols}

    equity = starting_cash
    nav_series: list[float] = [equity]
    active: dict[str, dict] = {}
    trades = 0
    liquidations = 0
    total_borrow = 0.0
    total_fees = 0.0

    for idx in range(len(eval_dates) - 1):
        t_avail = eval_dates[idx]
        day_sigs = signals.get(t_avail, {})

        # Check bar-high liquidation and time/breadth exits on open shorts
        for sym in list(active):
            pos = active[sym]
            cur_bar = by_sym_avail[sym].get(t_avail)
            nxt_bar = by_sym_start[sym].get(t_avail)
            pos["age"] += 1
            borrow = pos["notional"] * daily_borrow_rate
            total_borrow += borrow
            equity -= borrow

            if cur_bar is not None and cur_bar.high >= pos["liq_price"]:
                # Liquidated: lose full posted collateral
                equity -= pos["collateral"]
                liquidations += 1
                del active[sym]
                continue

            sig = day_sigs.get(sym)
            br = sig.crypto_breadth if sig else None
            should_exit = pos["age"] >= max_hold_days or (br is not None and br >= breadth_exit_min)
            if should_exit and nxt_bar is not None and nxt_bar.open > 0:
                exit_px = nxt_bar.open * (1.0 + leg_fee_and_slip)
                pnl = pos["qty"] * (pos["entry_px"] - exit_px)
                fee_est = pos["notional"] * leg_fee_and_slip
                total_fees += fee_est
                equity += pnl
                del active[sym]

        # Open new short cascades only when breadth collapses AND downside vol spikes
        if equity > 100.0 and not active:
            sample_sig = next(iter(day_sigs.values()), None)
            breadth = sample_sig.crypto_breadth if sample_sig else None
            avg_down = (
                sum(day_sigs[s].downside_vol_ratio for s in short_symbols if s in day_sigs)
                / max(1, sum(1 for s in short_symbols if s in day_sigs))
            )
            if breadth is not None and breadth <= breadth_entry_max and avg_down >= 1.15:
                per_col = (equity * 0.60) / len(short_symbols)
                for sym in short_symbols:
                    sig = day_sigs.get(sym)
                    nxt_bar = by_sym_start[sym].get(t_avail)
                    if sig is None or nxt_bar is None or nxt_bar.open <= 0 or (sig.s1_trend or 0.0) >= 0.0:
                        continue
                    entry_px = nxt_bar.open * (1.0 - leg_fee_and_slip)
                    notional = per_col * leverage
                    qty = notional / entry_px
                    liq_move = (1.0 - liq_margin_ratio) / leverage
                    active[sym] = {
                        "collateral": per_col,
                        "notional": notional,
                        "qty": qty,
                        "entry_px": entry_px,
                        "liq_price": entry_px * (1.0 + liq_move),
                        "age": 0,
                    }
                    total_fees += notional * leg_fee_and_slip
                    trades += 1

        # Mark-to-market open shorts
        unreal = 0.0
        for sym, pos in active.items():
            cur_bar = by_sym_avail[sym].get(t_avail)
            if cur_bar is not None:
                unreal += pos["qty"] * (pos["entry_px"] - cur_bar.close)
        nav_series.append(max(0.0, equity + unreal))

    rets = [(nav_series[i] / nav_series[i - 1] - 1.0) for i in range(1, len(nav_series)) if nav_series[i - 1] > 0]
    mean_r = sum(rets) / max(1, len(rets))
    var_r = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
    sr = (mean_r / math.sqrt(var_r)) * math.sqrt(365.0) if var_r > 1e-14 else 0.0
    peak, max_dd = nav_series[0], 0.0
    for v in nav_series:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    return MarginShortStats(
        name="CRASH_CASCADE_SHORTS_1.5X",
        ending_nav=round(nav_series[-1], 2),
        ret_pct=round((nav_series[-1] / starting_cash - 1.0) * 100.0, 2),
        ann_sharpe=round(sr, 3),
        max_dd_pct=round(max_dd * 100.0, 2),
        trades=trades,
        liquidations=liquidations,
        total_borrow_usdt=round(total_borrow, 2),
        total_fees_usdt=round(total_fees, 2),
    )


def simulate_market_neutral_l1_pairs(
    panel_1d: dict[str, list[BarPoint]],
    signals: dict[datetime, dict[str, SleeveSignal]],
    eval_dates: list[datetime],
    crypto_symbols: tuple[str, ...],
    *,
    starting_cash: float = 1000.0,
    rebalance_days: int = 7,
    daily_borrow_rate: float = 0.0009,
    leg_fee_and_slip: float = 0.0028,
) -> MarginShortStats:
    """Dollar-neutral Long Top-2 S1 / Short Bottom-2 S1 crypto pairs with exact Wallex short borrow."""
    by_sym_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in crypto_symbols}
    by_sym_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in crypto_symbols}

    equity = starting_cash
    nav_series: list[float] = [equity]
    longs: dict[str, tuple[float, float]] = {}   # sym -> (qty, entry_px)
    shorts: dict[str, tuple[float, float]] = {}  # sym -> (qty, entry_px)
    trades = 0
    liquidations = 0
    total_borrow = 0.0
    total_fees = 0.0

    for idx in range(len(eval_dates) - 1):
        t_avail = eval_dates[idx]
        day_sigs = signals.get(t_avail, {})

        # Daily borrow on open short leg
        for sym, (qty, entry_px) in list(shorts.items()):
            borrow = qty * entry_px * daily_borrow_rate
            total_borrow += borrow
            equity -= borrow
            cur_bar = by_sym_avail[sym].get(t_avail)
            if cur_bar is not None and cur_bar.high >= entry_px * 1.55:
                equity -= qty * (cur_bar.high - entry_px)
                liquidations += 1
                del shorts[sym]

        if idx % rebalance_days == 0 and equity > 100.0:
            # Close existing legs at next open
            for sym, (qty, entry_px) in longs.items():
                nb = by_sym_start[sym].get(t_avail)
                if nb and nb.open > 0:
                    exit_px = nb.open * (1.0 - leg_fee_and_slip)
                    equity += qty * (exit_px - entry_px)
                    total_fees += qty * nb.open * leg_fee_and_slip
            for sym, (qty, entry_px) in shorts.items():
                nb = by_sym_start[sym].get(t_avail)
                if nb and nb.open > 0:
                    exit_px = nb.open * (1.0 + leg_fee_and_slip)
                    equity += qty * (entry_px - exit_px)
                    total_fees += qty * nb.open * leg_fee_and_slip
            longs.clear()
            shorts.clear()

            ranked = sorted(
                (
                    (s, day_sigs[s].s1_trend)
                    for s in crypto_symbols
                    if s in day_sigs
                    and day_sigs[s].eligible_for_entry
                    and day_sigs[s].s1_trend is not None
                    and by_sym_start[s].get(t_avail) is not None
                    and by_sym_start[s][t_avail].open > 0
                ),
                key=lambda kv: (-kv[1], kv[0]),
            )
            if len(ranked) >= 6:
                leg_notional = (equity * 0.45) / 2.0
                for sym, _ in ranked[:2]:
                    px = by_sym_start[sym][t_avail].open * (1.0 + leg_fee_and_slip)
                    longs[sym] = (leg_notional / px, px)
                    total_fees += leg_notional * leg_fee_and_slip
                    trades += 1
                for sym, _ in ranked[-2:]:
                    px = by_sym_start[sym][t_avail].open * (1.0 - leg_fee_and_slip)
                    shorts[sym] = (leg_notional / px, px)
                    total_fees += leg_notional * leg_fee_and_slip
                    trades += 1

        unreal = 0.0
        for sym, (qty, entry_px) in longs.items():
            cb = by_sym_avail[sym].get(t_avail)
            if cb:
                unreal += qty * (cb.close - entry_px)
        for sym, (qty, entry_px) in shorts.items():
            cb = by_sym_avail[sym].get(t_avail)
            if cb:
                unreal += qty * (entry_px - cb.close)
        nav_series.append(max(0.0, equity + unreal))

    rets = [(nav_series[i] / nav_series[i - 1] - 1.0) for i in range(1, len(nav_series)) if nav_series[i - 1] > 0]
    mean_r = sum(rets) / max(1, len(rets))
    var_r = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
    sr = (mean_r / math.sqrt(var_r)) * math.sqrt(365.0) if var_r > 1e-14 else 0.0
    peak, max_dd = nav_series[0], 0.0
    for v in nav_series:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    return MarginShortStats(
        name="MARKET_NEUTRAL_L1_PAIRS",
        ending_nav=round(nav_series[-1], 2),
        ret_pct=round((nav_series[-1] / starting_cash - 1.0) * 100.0, 2),
        ann_sharpe=round(sr, 3),
        max_dd_pct=round(max_dd * 100.0, 2),
        trades=trades,
        liquidations=liquidations,
        total_borrow_usdt=round(total_borrow, 2),
        total_fees_usdt=round(total_fees, 2),
    )
