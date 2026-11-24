"""Asset-family differentiated signal/optimizer specs, multi-timeframe crash breakers (2h/3h/6h), and rare ignition."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from .multi_asset_research import (
    BASE_13_SYMBOLS,
    DEFENSIVE_GOLD_SYMBOLS,
    EXPANDED_33_SYMBOLS,
)
from .paper_ledger import SelfFinancingLedger
from .strategy_sleeves import SleeveSignal, _CausalEwmacState
from .timeframe_panel import BarPoint
from .volatility_models import (
    OhlcBar,
    asymmetric_ewma_volatility,
    yang_zhang_volatility,
)

MACRO_18_SYMBOLS = BASE_13_SYMBOLS + (
    "PAXGUSDT",
    "SLVONUSDT",
    "USOONUSDT",
    "COPXONUSDT",
    "UNGONUSDT",
)

CRYPTO_CORE_12 = tuple(s for s in BASE_13_SYMBOLS if s != "XAUTUSDT")
COMMODITY_ETF_4 = frozenset(("SLVONUSDT", "USOONUSDT", "COPXONUSDT", "UNGONUSDT"))
SATELLITE_ALT_15 = frozenset(
    s for s in EXPANDED_33_SYMBOLS if s not in MACRO_18_SYMBOLS
)


@dataclass(frozen=True)
class AssetFamilyPolicy:
    family: str
    ewmac_pairs: tuple[tuple[int, int], ...]
    ic_prior: float
    max_weight: float
    min_breadth_for_entry: float
    breadth_exit_floor: float
    min_s1_entry: float
    exit_on_crypto_crash: bool


FAMILY_POLICIES: dict[str, AssetFamilyPolicy] = {
    "CRYPTO_CORE": AssetFamilyPolicy(
        family="CRYPTO_CORE",
        ewmac_pairs=((8, 32), (16, 64), (32, 128)),
        ic_prior=0.08,
        max_weight=0.30,
        min_breadth_for_entry=0.0,
        breadth_exit_floor=0.0,
        min_s1_entry=0.0,
        exit_on_crypto_crash=True,
    ),
    "PRECIOUS_METALS": AssetFamilyPolicy(
        family="PRECIOUS_METALS",
        ewmac_pairs=((16, 64), (32, 128)),
        ic_prior=0.09,
        max_weight=0.30,
        min_breadth_for_entry=0.0,
        breadth_exit_floor=0.0,
        min_s1_entry=0.0,
        exit_on_crypto_crash=False,
    ),
    "COMMODITY_ETFS": AssetFamilyPolicy(
        family="COMMODITY_ETFS",
        ewmac_pairs=((16, 64), (32, 128)),
        ic_prior=0.10,
        max_weight=0.18,
        min_breadth_for_entry=0.0,
        breadth_exit_floor=0.0,
        min_s1_entry=0.05,
        exit_on_crypto_crash=False,
    ),
    "ALT_SATELLITES": AssetFamilyPolicy(
        family="ALT_SATELLITES",
        ewmac_pairs=((8, 32), (16, 64)),
        ic_prior=0.06,
        max_weight=0.08,
        min_breadth_for_entry=0.55,
        breadth_exit_floor=0.45,
        min_s1_entry=0.25,
        exit_on_crypto_crash=True,
    ),
}


def family_of_symbol(symbol: str) -> str:
    if symbol in DEFENSIVE_GOLD_SYMBOLS:
        return "PRECIOUS_METALS"
    if symbol in COMMODITY_ETF_4:
        return "COMMODITY_ETFS"
    if symbol in SATELLITE_ALT_15:
        return "ALT_SATELLITES"
    return "CRYPTO_CORE"


def compute_family_differentiated_sleeves(
    panel_by_symbol: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    *,
    min_active_crypto: int = 4,
    warmup_bars: int = 128,
) -> dict[datetime, dict[str, SleeveSignal]]:
    """Compute causal signals using family-specific EMA horizons while keeping crypto breadth strictly pure."""
    by_sym_ts = {s: {b.ts_avail: b for b in panel_by_symbol.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_sym_ts.values() for t in d})

    ewmac_state = {
        s: _CausalEwmacState(pairs=FAMILY_POLICIES[family_of_symbol(s)].ewmac_pairs, warmup=warmup_bars)
        for s in symbols
    }
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
        active_core_crypto: list[str] = []

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
            # Measure macro crypto breadth on the liquid core crypto family so thin alts/commodities never distort it.
            if sym in CRYPTO_CORE_12 and bar.entry_eligible and above50 is not None:
                active_core_crypto.append(sym)

        breadth: float | None = None
        if len(active_core_crypto) >= min_active_crypto:
            breadth = sum(1 for s in active_core_crypto if above50_map[s] is True) / len(active_core_crypto)

        avg_down = (
            sum(down_ratio_map[s] for s in active_core_crypto) / len(active_core_crypto)
            if active_core_crypto
            else 1.0
        )
        down_ratio_hist.append(avg_down)
        if len(down_ratio_hist) >= 30:
            trailing = sorted(down_ratio_hist[-180:])
            vol_spike = avg_down >= trailing[int(0.90 * (len(trailing) - 1))]
        else:
            vol_spike = False

        defensive_intensity = 0.0
        if breadth is not None and breadth < 0.35:
            defensive_intensity = min(1.0, (0.35 - breadth) / 0.35 + (0.25 if vol_spike else 0.0))
        elif vol_spike:
            defensive_intensity = 0.40

        # Smart gold twin selection: if both PAXG and XAUT are active, give full S5 to the stronger/more-liquid twin.
        eligible_gold = [
            g for g in ("PAXGUSDT", "XAUTUSDT")
            if g in by_sym_ts and by_sym_ts[g].get(ts) is not None and by_sym_ts[g][ts].entry_eligible and s1_map.get(g) is not None
        ]
        preferred_gold = (
            max(eligible_gold, key=lambda g: (s1_map.get(g) or -9.0, g == "PAXGUSDT"))
            if eligible_gold
            else None
        )

        day_out: dict[str, SleeveSignal] = {}
        for sym in symbols:
            bar = by_sym_ts[sym].get(ts)
            if bar is None:
                continue
            s5_val: float | None = None
            if sym == preferred_gold:
                gold_ok = (s1_map[sym] or 0.0) >= -0.25
                s5_val = defensive_intensity if gold_ok else 0.0
            day_out[sym] = SleeveSignal(
                symbol=sym,
                as_of=ts,
                s1_trend=s1_map.get(sym),
                s2_residual_mom=None,
                s5_defensive_gold=s5_val,
                crypto_breadth=breadth,
                active_crypto_count=len(active_core_crypto),
                yang_zhang_vol=vol_map[sym],
                downside_vol_ratio=down_ratio_map[sym],
                eligible_for_entry=bar.entry_eligible and (s1_map.get(sym) is not None),
            )
        output[ts] = day_out

    return output


def compute_intraday_crash_exit_dates(
    panel_tf: dict[str, list[BarPoint]],
    crypto_symbols: tuple[str, ...],
    *,
    bucket_hours: int,
    ema_days: int = 20,
    breadth_threshold: float = 0.20,
    vol_quantile: float = 0.92,
    min_active: int = 4,
) -> set[str]:
    """Identify UTC dates where strictly causal intraday (2h/3h/4h/6h) breadth collapse + vol spike triggers exit."""
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
    crash_dates: set[str] = set()
    alpha = 2.0 / (ema_bars + 1.0)

    for ts in all_ts:
        above = 0
        active = 0
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
            q_val = tr[int(vol_quantile * (len(tr) - 1))]
            if breadth < breadth_threshold and avg_r >= q_val:
                # Map intraday ts_avail strictly to the first daily 00:00Z decision >= ts_avail (zero lookahead).
                daily_avail_date = (
                    ts.date().isoformat()
                    if (ts.hour == 0 and ts.minute == 0 and ts.second == 0)
                    else (ts + timedelta(days=1)).date().isoformat()
                )
                crash_dates.add(daily_avail_date)
    return crash_dates


@dataclass(frozen=True)
class IgnitionSleeveResult:
    label: str
    bucket_hours: int
    offset_hours: int
    fee_bps: float
    days: int
    ending_nav: float
    ret_pct: float
    ann_sharpe: float
    max_dd_pct: float
    entries: int
    win_rate_pct: float
    fees_usdt: float


def _ignition_candidate_z(
    bar: BarPoint,
    bar_ret: float,
    prior_highs: list[float],
    prior_rets: list[float],
    prior_vols: list[float],
    *,
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
    z = (bar_ret - mean_r) / max(std_r, 1e-4)
    if z >= z_threshold and med_v > 0 and bar.volume >= vol_mult * med_v and bar.close > max(prior_highs):
        return z, max(std_r, 0.005)
    return None


def _summarize_ignition_nav(
    label: str,
    bucket_hours: int,
    offset_hours: int,
    fee_rate: Decimal,
    nav_by_date: dict[str, float],
    entries: int,
    closed_wins: int,
    closed_total: int,
    total_fees: float,
) -> IgnitionSleeveResult:
    dates = sorted(nav_by_date)
    if len(dates) < 10:
        return IgnitionSleeveResult(label, bucket_hours, offset_hours, float(fee_rate) * 10000.0, len(dates), 1000.0, 0.0, 0.0, 0.0, entries, 0.0, 0.0)
    navs = [nav_by_date[d] for d in dates]
    rets = [(navs[i] / navs[i - 1] - 1.0) for i in range(1, len(navs)) if navs[i - 1] > 0]
    mean_r = sum(rets) / max(1, len(rets))
    var_r = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
    sr = (mean_r / math.sqrt(var_r)) * math.sqrt(365.0) if var_r > 1e-14 else 0.0
    peak, max_dd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    win_rate = (closed_wins / closed_total * 100.0) if closed_total > 0 else 0.0
    return IgnitionSleeveResult(
        label=label,
        bucket_hours=bucket_hours,
        offset_hours=offset_hours,
        fee_bps=round(float(fee_rate) * 10000.0, 1),
        days=len(dates),
        ending_nav=round(navs[-1], 2),
        ret_pct=round((navs[-1] / navs[0] - 1.0) * 100.0, 2),
        ann_sharpe=round(sr, 3),
        max_dd_pct=round(max_dd * 100.0, 2),
        entries=entries,
        win_rate_pct=round(win_rate, 1),
        fees_usdt=round(total_fees, 2),
    )


def _manage_ignition_exits(
    open_pos: dict[str, tuple[float, float, float, int]],
    by_avail: dict[str, dict[datetime, BarPoint]],
    by_start: dict[str, dict[datetime, BarPoint]],
    ts: datetime,
    *,
    max_hold_bars: int,
    trail_stop_mult: float,
    hard_stop_pct: float,
    fee_rate: Decimal,
) -> tuple[int, int]:
    wins, total = 0, 0
    for sym in list(open_pos):
        entry_px, peak_px, b_vol, age = open_pos[sym]
        cur = by_avail[sym].get(ts)
        age += 1
        if cur is not None and cur.close > 0:
            peak_px = max(peak_px, cur.close)
            hit_trail = cur.close < peak_px * (1.0 - trail_stop_mult * b_vol)
            hit_hard = cur.close < entry_px * (1.0 - hard_stop_pct)
            if age >= max_hold_bars or hit_trail or hit_hard:
                nxt = by_start[sym].get(ts)
                exit_px = nxt.open if (nxt and nxt.open > 0) else cur.close
                total += 1
                if exit_px > entry_px * (1.0 + 2.0 * float(fee_rate)):
                    wins += 1
                del open_pos[sym]
            else:
                open_pos[sym] = (entry_px, peak_px, b_vol, age)
        elif age >= max_hold_bars:
            total += 1
            del open_pos[sym]
    return wins, total


def simulate_rare_momentum_ignition(
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
) -> IgnitionSleeveResult:
    """Rare ultra-high-momentum ignition sleeve on 1h/2h/3h bars with strict causality and SelfFinancingLedger."""
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
    # sym -> (entry_px, peak_close, bar_vol, bars_held)
    open_pos: dict[str, tuple[float, float, float, int]] = {}
    nav_by_date: dict[str, float] = {}
    entries = 0
    closed_wins = 0
    closed_total = 0

    for ts in all_ts:
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        candidates: list[tuple[float, str, float]] = []

        for sym in symbols:
            cur = by_avail[sym].get(ts)
            nxt = by_start[sym].get(ts)
            if nxt is not None and nxt.open > 0:
                exec_prices[sym] = Decimal(str(nxt.open))
                last_mark[sym] = exec_prices[sym]
                if nxt.entry_eligible and cur is not None and cur.entry_eligible:
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

        # Open new ultra-strong ignitions only when macro daily crypto breadth is healthy
        prev_day = ts.date().isoformat()
        day_br = daily_breadth_by_date.get(prev_day, 0.0)
        if candidates and day_br >= min_daily_breadth and len(open_pos) < max_slots:
            candidates.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in candidates:
                if len(open_pos) >= max_slots:
                    break
                nxt = by_start[sym].get(ts)
                if nxt is None or nxt.open <= 0:
                    continue
                open_pos[sym] = (nxt.open, nxt.open, b_vol, 0)
                entries += 1

        targets = {s: (slot_weight if s in open_pos else 0.0) for s in symbols}
        if open_pos or any(q > 0 for q in ledger.units.values()):
            ledger.rebalance_to_targets(ts, targets, exec_prices, tradable_symbols=tradable)
        nav_by_date[ts.date().isoformat()] = float(ledger.mark_nav(exec_prices))

    return _summarize_ignition_nav(
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
