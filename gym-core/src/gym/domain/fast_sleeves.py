"""Fast orthogonal sleeves S3 (Panic Reversion, no averaging down) and S4 (Vol-Compression Breakout) (v2 spec §3.2)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .timeframe_panel import BarPoint
from .volatility_models import OhlcBar, yang_zhang_volatility


@dataclass(frozen=True)
class FastSleeveSignal:
    symbol: str
    as_of: datetime
    s3_action: str                    # "ENTER_LONG" | "HOLD" | "EXIT_STOP" | "EXIT_TIME" | "FLAT"
    s3_episode_id: int | None
    s4_action: str                    # "ENTER_LONG" | "HOLD" | "EXIT_TRAIL" | "FLAT"
    yang_zhang_vol: float
    eligible_for_entry: bool


def _rsi(closes: list[float], period: int = 4) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        elif diff < 0:
            losses += -diff
    if gains == 0.0 and losses == 0.0:
        return 50.0  # deterministic flat-window RSI
    if losses == 0.0:
        return 100.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


def compute_fast_sleeves_s3_s4(
    bars: list[BarPoint],
    *,
    s3_max_hold_bars: int = 6,        # 6 x 6h = 36h matching 36h label horizon
    s3_cooldown_bars: int = 4,        # 24h cooldown after episode exit
    s3_stop_sigma: float = 2.5,
    s4_lookback_highs: int = 20,
    s4_compression_ratio: float = 0.65,
    s4_volume_z_min: float = 1.5,
    s4_max_hold_bars: int = 12,
) -> list[FastSleeveSignal]:
    """Compute strictly causal S3 (no averaging down / single entry per episode) and S4 (prior-20-high breakout)."""
    ordered = sorted(bars, key=lambda b: b.ts_avail)
    closes: list[float] = []
    highs: list[float] = []
    vols: list[float] = []
    rets: list[float] = []
    ohlcs: list[OhlcBar] = []

    # S3 episode state (PRODUCT.md: never average down on a subsequent drop!)
    s3_open = False
    s3_stop_px = 0.0
    s3_bars_held = 0
    s3_cooldown = 0
    s3_episode_seq = 0
    s3_active_ep: int | None = None

    # S4 state
    s4_open = False
    s4_bars_held = 0
    s4_peak_close = 0.0

    out: list[FastSleeveSignal] = []

    for idx, bar in enumerate(ordered):
        prev_close = closes[-1] if closes else None
        ret = (bar.close - prev_close) / prev_close if (prev_close and prev_close > 0) else 0.0
        # Capture strictly PRIOR 20 highs & pre-breakout vol compression BEFORE appending current bar!
        prior_20_high = max(highs[-s4_lookback_highs:]) if len(highs) >= s4_lookback_highs else None
        pre_vol_short = yang_zhang_volatility(ohlcs[-10:]) if len(ohlcs) >= 10 else None
        pre_vol_long = yang_zhang_volatility(ohlcs[-40:]) if len(ohlcs) >= 40 else None
        prior_vols = vols[-20:] if len(vols) >= 20 else []

        closes.append(bar.close)
        highs.append(bar.high)
        vols.append(bar.volume)
        rets.append(ret)
        ohlcs.append(OhlcBar(bar.open, bar.high, bar.low, bar.close))

        yz = yang_zhang_volatility(ohlcs[-20:]) if len(ohlcs) >= 5 else 0.01
        eligible = bar.entry_eligible and idx >= 40

        # --- S3 Panic / Oversold Reversion (strictly 1 entry from flat per episode) ---
        if s3_cooldown > 0:
            s3_cooldown -= 1
        s3_action = "FLAT"
        if s3_open:
            s3_bars_held += 1
            if bar.low <= s3_stop_px or bar.close <= s3_stop_px:
                s3_action = "EXIT_STOP"
                s3_open = False
                s3_active_ep = None
                s3_cooldown = s3_cooldown_bars
            elif s3_bars_held >= s3_max_hold_bars:
                s3_action = "EXIT_TIME"
                s3_open = False
                s3_active_ep = None
                s3_cooldown = s3_cooldown_bars
            else:
                s3_action = "HOLD"
        elif eligible and s3_cooldown == 0 and len(rets) >= 21:
            r_win = rets[-21:-1]
            m_r = sum(r_win) / len(r_win)
            std_r = math.sqrt(sum((x - m_r) ** 2 for x in r_win) / len(r_win))
            ret_z = (ret - m_r) / max(std_r, 1e-6)
            rsi4 = _rsi(closes, 4)
            bar_range = bar.high - bar.low
            upper_wick_ok = bar_range > 0 and ((bar.close - bar.low) / bar_range >= 0.40)
            if ret_z < -2.2 and rsi4 is not None and rsi4 < 20.0 and upper_wick_ok:
                s3_episode_seq += 1
                s3_active_ep = s3_episode_seq
                s3_open = True
                s3_stop_px = bar.close * (1.0 - s3_stop_sigma * max(yz, 0.005))
                s3_bars_held = 0
                s3_action = "ENTER_LONG"

        # --- S4 Volatility-Compression Breakout (strictly prior highs & pre-release compression) ---
        s4_action = "FLAT"
        if s4_open:
            s4_bars_held += 1
            s4_peak_close = max(s4_peak_close, bar.close)
            trail_stop = s4_peak_close * (1.0 - 2.0 * max(yz, 0.005))
            if bar.close <= trail_stop or s4_bars_held >= s4_max_hold_bars:
                s4_action = "EXIT_TRAIL"
                s4_open = False
            else:
                s4_action = "HOLD"
        elif eligible and prior_20_high is not None and pre_vol_short is not None and pre_vol_long is not None and prior_vols:
            compressed = (pre_vol_short / max(pre_vol_long, 1e-6)) < s4_compression_ratio
            v_mean = sum(prior_vols) / len(prior_vols)
            v_std = math.sqrt(sum((x - v_mean) ** 2 for x in prior_vols) / len(prior_vols))
            vol_z = (bar.volume - v_mean) / max(v_std, 1e-6)
            if compressed and bar.close > prior_20_high and vol_z > s4_volume_z_min:
                s4_open = True
                s4_bars_held = 0
                s4_peak_close = bar.close
                s4_action = "ENTER_LONG"

        out.append(FastSleeveSignal(bar.symbol, bar.ts_avail, s3_action, s3_active_ep, s4_action, yz, eligible))

    return out
