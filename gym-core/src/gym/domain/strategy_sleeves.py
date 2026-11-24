"""Slow orthogonal strategy sleeves (S1 Trend, S2 BTC-Residual Momentum, S5 Defensive Gold/Cash) (v2 spec §3.1)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .timeframe_panel import BarPoint
from .volatility_models import (
    OhlcBar,
    asymmetric_ewma_volatility,
    yang_zhang_volatility,
)


@dataclass(frozen=True)
class SleeveSignal:
    symbol: str
    as_of: datetime
    s1_trend: float | None              # [-1, +1] or None during explicit 128-bar warmup
    s2_residual_mom: float | None       # [-1, +1] cross-sectional BTC-beta-neutral residual momentum
    s5_defensive_gold: float | None     # [0, +1] defensive gold signal (for gold symbol only)
    crypto_breadth: float | None        # fraction of active eligible crypto symbols above 50-bar EMA
    active_crypto_count: int
    yang_zhang_vol: float
    downside_vol_ratio: float
    eligible_for_entry: bool


def _clamp1(val: float) -> float:
    return max(-1.0, min(1.0, val))


class _CausalEwmacState:
    """Explicit 128-bar warmup multi-horizon EWMAC normalized strictly to [-1, +1]."""

    def __init__(self, pairs: tuple[tuple[int, int], ...] = ((8, 32), (16, 64), (32, 128)), warmup: int = 128) -> None:
        self.pairs = pairs
        self.warmup = warmup
        self.spans = sorted({s for pair in pairs for s in pair} | {50})
        self.emas: dict[int, float] = {}
        self.count = 0

    def update(self, close: float, yz_vol: float) -> tuple[float | None, bool | None]:
        self.count += 1
        for span in self.spans:
            alpha = 2.0 / (span + 1.0)
            self.emas[span] = close if span not in self.emas else (1.0 - alpha) * self.emas[span] + alpha * close
        above_ema50 = (close > self.emas[50]) if self.count >= 50 else None
        if self.count < self.warmup:
            return None, above_ema50
        vol = max(yz_vol, 1e-4)
        parts = []
        for fast, slow in self.pairs:
            raw = (self.emas[fast] - self.emas[slow]) / (close * vol)
            parts.append(_clamp1(raw / 5.0))
        return _clamp1(sum(parts) / len(parts)), above_ema50


def _trailing_beta(asset_rets: list[float], btc_rets: list[float]) -> float:
    n = min(len(asset_rets), len(btc_rets))
    if n < 15:
        return 1.0
    a = asset_rets[-n:]
    b = btc_rets[-n:]
    ma = sum(a) / n
    mb = sum(b) / n
    var_b = sum((x - mb) ** 2 for x in b)
    if var_b <= 1e-12:
        return 1.0
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    return max(-0.5, min(3.0, cov / var_b))


def compute_slow_sleeves(
    panel_by_symbol: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    *,
    btc_symbol: str = "BTCUSDT",
    gold_symbol: str = "XAUTUSDT",
    min_active_crypto: int = 4,
    warmup_bars: int = 128,
) -> dict[datetime, dict[str, SleeveSignal]]:
    """Compute strictly causal S1 (Trend), S2 (BTC-Residual Momentum), and S5 (Defensive Gold/Cash)."""
    by_sym_ts = {s: {b.ts_avail: b for b in panel_by_symbol.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_sym_ts.values() for t in d})

    ewmac_state = {s: _CausalEwmacState(warmup=warmup_bars) for s in symbols}
    ohlc_hist: dict[str, list[OhlcBar]] = {s: [] for s in symbols}
    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}
    down_ratio_hist: list[float] = []

    output: dict[datetime, dict[str, SleeveSignal]] = {}

    for ts in all_ts:
        # 1. Update per-symbol causal features
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
            if sym != gold_symbol and bar.entry_eligible and above50 is not None:
                active_crypto.append(sym)

        # 2. Cross-market crypto breadth (strictly excluding gold & cash)
        breadth: float | None = None
        if len(active_crypto) >= min_active_crypto:
            breadth = sum(1 for s in active_crypto if above50_map[s] is True) / len(active_crypto)

        avg_down_ratio = (
            sum(down_ratio_map[s] for s in active_crypto) / len(active_crypto)
            if active_crypto else 1.0
        )
        down_ratio_hist.append(avg_down_ratio)
        # Trailing top-decile downside vol spike (causal)
        if len(down_ratio_hist) >= 30:
            trailing = sorted(down_ratio_hist[-180:])
            p90_down = trailing[int(0.90 * (len(trailing) - 1))]
            vol_spike = avg_down_ratio >= p90_down
        else:
            vol_spike = False

        # 3. S2: BTC-beta-neutral 30-day residual momentum ranked across eligible crypto symbols
        s2_map: dict[str, float | None] = {s: None for s in symbols}
        btc_rets = ret_hist.get(btc_symbol, [])
        if len(active_crypto) >= min_active_crypto and len(btc_rets) >= 30:
            btc_30 = sum(btc_rets[-30:])
            raw_resid: list[tuple[str, float]] = []
            for sym in sorted(active_crypto):  # deterministic tie ordering by symbol name
                r_list = ret_hist[sym]
                if len(r_list) < 30:
                    continue
                beta = 1.0 if sym == btc_symbol else _trailing_beta(r_list[-60:], btc_rets[-60:])
                r30 = sum(r_list[-30:])
                resid = r30 - beta * btc_30
                raw_resid.append((sym, resid))
            if len(raw_resid) >= min_active_crypto:
                vals = [v for _, v in raw_resid]
                mean_v = sum(vals) / len(vals)
                std_v = math.sqrt(sum((v - mean_v) ** 2 for v in vals) / len(vals))
                for sym, v in raw_resid:
                    z = (v - mean_v) / max(std_v, 1e-6)
                    # Only emit positive S2 conviction if coin's own 30d return is non-negative
                    own_pos = sum(ret_hist[sym][-30:]) >= 0.0
                    s2_map[sym] = _clamp1(z / 2.0) if (z > 0 and own_pos) else min(0.0, _clamp1(z / 2.0))

        # 4. S5: Portfolio-wide defensive gold/cash rotation when breadth < 0.35 or downside vol spikes
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
            if sym == gold_symbol and bar.entry_eligible and s1_map.get(sym) is not None:
                # Gold gets positive defensive allocation only when gold itself is not in severe downtrend
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
