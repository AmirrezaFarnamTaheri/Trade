"""Pure domain detectors for the Rare Micro-Signal Portfolio (zero I/O).

Implements three independently-triggered causal bar detectors from
docs/architecture/rare-micro-signal-research-design.md:
  1. MOMENTUM_IGNITION (incumbent 2h breakout)
  2. FAILED_DOWNSIDE_AUCTION (rare breakdown below 24-bar low reclaimed within 2 closed bars)
  3. PEER_RELATIVE_CATCHUP (liquid peer basket jumps, laggard holds & fresh close turns up)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from statistics import median

from .short_and_levered_ignition import _breakdown_or_breakout_z
from .timeframe_panel import BarPoint


@dataclass(frozen=True)
class MicroSignalIntent:
    """Timestamped paper intent emitted strictly at bar close ts_avail for next-bar execution."""

    ts_avail: datetime
    symbol: str
    mechanism: str  # MOMENTUM_IGNITION | FAILED_DOWNSIDE_AUCTION | PEER_RELATIVE_CATCHUP
    direction: int  # 1 (long)
    strength: float
    invalidation_px: float
    max_hold_bars: int
    bar_vol: float


def detect_failed_downside_auction(
    bars: list[BarPoint],
    idx: int,
    rets: list[float],
    *,
    lookback_low: int = 24,
    vol_lookback: int = 36,
    z_floor: float = -2.0,
) -> MicroSignalIntent | None:
    """Detect a rare breakdown below the 24-bar low (z <= z_floor) reclaimed within 2 closed bars."""
    if idx < max(lookback_low + 3, vol_lookback + 2):
        return None
    cur = bars[idx]
    if not cur.entry_eligible or cur.close <= 0:
        return None
    pr = rets[idx - vol_lookback : idx]
    mr = sum(pr) / len(pr)
    sr = math.sqrt(sum((r - mr) ** 2 for r in pr) / max(1, len(pr) - 1))
    if sr <= 1e-4:
        return None

    # Check if bar idx-1 or idx-2 breached its prior 24-bar low in a bottom-tail move
    for lag in (1, 2):
        shock_i = idx - lag
        prior_low = min(b.low for b in bars[shock_i - lookback_low : shock_i])
        shock_z = (rets[shock_i] - mr) / sr
        if bars[shock_i].low < prior_low and shock_z <= z_floor and cur.close > prior_low:
            # Ensure no lower low on bar idx itself after the reclaim setup
            if cur.close > cur.open and cur.low >= bars[shock_i].low * 0.995:
                return MicroSignalIntent(
                    ts_avail=cur.ts_avail,
                    symbol=cur.symbol,
                    mechanism="FAILED_DOWNSIDE_AUCTION",
                    direction=1,
                    strength=abs(shock_z),
                    invalidation_px=bars[shock_i].low,
                    max_hold_bars=6,
                    bar_vol=sr,
                )
    return None


def detect_peer_relative_catchup(
    sym: str,
    cur: BarPoint,
    prev_bar: BarPoint | None,
    sym_ret: float,
    sym_prev_ret: float,
    peer_rets_cur: list[float],
    peer_rets_prev: list[float],
    *,
    bar_vol: float,
) -> MicroSignalIntent | None:
    """Detect a peer-basket jump on bar t-1 where target lagged, then target turns up while basket holds."""
    if not cur.entry_eligible or prev_bar is None or len(peer_rets_prev) < 5 or len(peer_rets_cur) < 5:
        return None
    basket_prev = median(peer_rets_prev)
    basket_cur = median(peer_rets_cur)
    pos_frac_prev = sum(1 for r in peer_rets_prev if r > 0) / len(peer_rets_prev)
    # Top-tail peer basket jump (>= +1.5% median with >= 70% broad participation)
    if basket_prev < 0.015 or pos_frac_prev < 0.70:
        return None
    # Target lagged materially on the shock bar (residual <= -1.2%)
    lag_residual = sym_prev_ret - basket_prev
    if lag_residual > -0.012:
        return None
    # Basket holds at least half its shock (does not reverse > 50%) AND target fresh bar starts rising
    if basket_cur < -0.5 * basket_prev or sym_ret <= 0.002 or cur.close <= cur.open:
        return None
    return MicroSignalIntent(
        ts_avail=cur.ts_avail,
        symbol=sym,
        mechanism="PEER_RELATIVE_CATCHUP",
        direction=1,
        strength=abs(lag_residual) / max(bar_vol, 1e-4),
        invalidation_px=min(prev_bar.low, cur.low),
        max_hold_bars=6,
        bar_vol=max(bar_vol, 0.005),
    )


def scan_micro_signal_intents(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth: dict[str, float],
) -> dict[str, list[MicroSignalIntent]]:
    """Scan all three mechanisms causally on one shared 2h bar stream."""
    out: dict[str, list[MicroSignalIntent]] = {
        "MOMENTUM_IGNITION": [],
        "FAILED_DOWNSIDE_AUCTION": [],
        "PEER_RELATIVE_CATCHUP": [],
    }
    by_sym_rets: dict[str, list[float]] = {}
    by_sym_ts_ret: dict[str, dict[datetime, float]] = {}
    by_sym_ts_bar: dict[str, dict[datetime, BarPoint]] = {}

    for sym in symbols:
        bars = panel_2h.get(sym, [])
        rets = [0.0] + [
            (bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0
            for i in range(1, len(bars))
        ]
        by_sym_rets[sym] = rets
        by_sym_ts_ret[sym] = {bars[i].ts_avail: rets[i] for i in range(len(bars))}
        by_sym_ts_bar[sym] = {b.ts_avail: b for b in bars}

    for sym in symbols:
        bars = panel_2h.get(sym, [])
        rets = by_sym_rets[sym]
        if len(bars) < 80:
            continue
        vols = [b.volume for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        for i in range(72, len(bars) - 1):
            cur = bars[i]
            if not cur.entry_eligible or cur.close <= 0:
                continue
            # 1. Incumbent Momentum Ignition
            if daily_breadth.get(cur.ts_avail.date().isoformat(), 0.0) >= 0.45:
                hit = _breakdown_or_breakout_z(
                    cur, rets[i], highs[i - 72 : i], lows[i - 72 : i], rets[i - 36 : i], vols[i - 36 : i],
                    side="LONG", breakout_bars=72, vol_lookback=36, z_threshold=3.0, vol_mult=2.5,
                )
                if hit is not None:
                    out["MOMENTUM_IGNITION"].append(
                        MicroSignalIntent(
                            ts_avail=cur.ts_avail, symbol=sym, mechanism="MOMENTUM_IGNITION",
                            direction=1, strength=hit[0], invalidation_px=cur.close * 0.96,
                            max_hold_bars=24, bar_vol=hit[1],
                        )
                    )
            # 2. Failed Downside Auction
            fda = detect_failed_downside_auction(bars, i, rets)
            if fda is not None:
                out["FAILED_DOWNSIDE_AUCTION"].append(fda)
            # 3. Peer-Relative Catch-Up (exclude target from peer basket)
            t_cur, t_prev = cur.ts_avail, bars[i - 1].ts_avail
            p_cur = [by_sym_ts_ret[o][t_cur] for o in symbols if o != sym and t_cur in by_sym_ts_ret[o]]
            p_prev = [by_sym_ts_ret[o][t_prev] for o in symbols if o != sym and t_prev in by_sym_ts_ret[o]]
            pr = rets[i - 36 : i]
            mr = sum(pr) / len(pr)
            sr = math.sqrt(sum((r - mr) ** 2 for r in pr) / max(1, len(pr) - 1))
            prc = detect_peer_relative_catchup(
                sym, cur, bars[i - 1], rets[i], rets[i - 1], p_cur, p_prev, bar_vol=sr,
            )
            if prc is not None:
                out["PEER_RELATIVE_CATCHUP"].append(prc)

    for k in out:
        out[k].sort(key=lambda x: (x.ts_avail, -x.strength, x.symbol))
    return out
