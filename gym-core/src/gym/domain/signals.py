"""Causal bar signals and a signed blend: the shared vocabulary for long, short and flat research.

Every signal maps bar columns to one target per bar: +1 long condition, -1 short condition, 0 neutral, None while
warming up. Element i uses bars 0..i only. Prices are floats: these are research signals, not money.
"""
from collections import deque
from math import sqrt

TREND = ("ema-cross", "tsmom", "donchian", "efficiency", "obv")
REVERSION = ("rsi-reversion", "bollinger-reversion")


def ema_cross(bars, fast=8, slow=21):
    out, f, s = [], None, None
    for i, c in enumerate(bars["close"]):
        f = c if f is None else f + 2 / (fast + 1) * (c - f)
        s = c if s is None else s + 2 / (slow + 1) * (c - s)
        out.append(None if i + 1 < slow else 1 if f > s else -1)
    return out


def tsmom(bars, lookback=20, band_bps=100):
    """Time-series momentum: the sign of the lookback return, neutral inside +-band."""
    c, band = bars["close"], band_bps / 10000
    return [None if i < lookback else 1 if c[i] / c[i - lookback] - 1 > band else -1 if c[i] / c[i - lookback] - 1 < -band
            else 0 for i in range(len(c))]


def donchian(bars, lookback=20):
    """Last breakout direction: +1 after a close above the prior lookback closes, -1 after one below; held."""
    c, out, state = bars["close"], [], 0
    for i in range(len(c)):
        if i < lookback:
            out.append(None)
            continue
        window = c[i - lookback:i]
        state = 1 if c[i] > max(window) else -1 if c[i] < min(window) else state
        out.append(state)
    return out


def efficiency(bars, lookback=20, min_er_pct=40):
    """Kaufman efficiency ratio: trade the direction only when the path was mostly straight (filters chop)."""
    c, out = bars["close"], []
    for i in range(len(c)):
        if i < lookback:
            out.append(None)
            continue
        change = c[i] - c[i - lookback]
        path = sum(abs(c[k] - c[k - 1]) for k in range(i - lookback + 1, i + 1))
        er = abs(change) / path if path else 0.0
        out.append(0 if er * 100 < min_er_pct else 1 if change > 0 else -1)
    return out


class OnBalanceVolume:
    """Cumulative signed volume with a bounded window of levels for the comparison."""

    def __init__(self, lookback=20, *, require_volume=False):
        if lookback < 1:
            raise ValueError("OBV lookback must be positive")
        self.window = deque(maxlen=lookback)
        self.require_volume = require_volume
        self.total = 0.0
        self.previous = None

    def update(self, close, volume):
        if self.previous is not None and volume is not None:
            self.total += volume if close > self.previous else -volume if close < self.previous else 0.0
        self.previous = close
        self.window.append(self.total)
        if len(self.window) < self.window.maxlen or (self.require_volume and volume is None):
            return None
        if self.require_volume and volume == 0:
            return 0
        return 1 if self.total > sum(self.window) / len(self.window) else -1


def obv(bars, lookback=20, *, require_volume=False):
    """On-balance volume against its own mean, with optional neutral votes on zero-volume bars."""
    state = OnBalanceVolume(lookback, require_volume=require_volume)
    return [state.update(close, volume) for close, volume in zip(bars["close"], bars["volume"], strict=True)]


def rsi_reversion(bars, period=14, low=30, high=70):
    """Contrarian: long when oversold, short when overbought, neutral between."""
    c = bars["close"]
    if not len(c):
        return []
    out, gain, loss = [None], None, None
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        up, down = max(d, 0.0), max(-d, 0.0)
        gain = up if gain is None else (gain * (period - 1) + up) / period
        loss = down if loss is None else (loss * (period - 1) + down) / period
        if i < period:
            out.append(None)
            continue
        rsi = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
        out.append(1 if rsi < low else -1 if rsi > high else 0)
    return out


def bollinger_reversion(bars, lookback=20, k=2):
    """Enter against a close outside the band; hold until the close crosses back over the mean."""
    c, out, state = bars["close"], [], 0
    for i in range(len(c)):
        if i + 1 < lookback:
            out.append(None)
            continue
        w = c[i + 1 - lookback:i + 1]
        mean = sum(w) / lookback
        sd = sqrt(sum((x - mean) ** 2 for x in w) / lookback)
        if c[i] < mean - k * sd:
            state = 1
        elif c[i] > mean + k * sd:
            state = -1
        elif (state == 1 and c[i] >= mean) or (state == -1 and c[i] <= mean):
            state = 0
        out.append(state)
    return out


SIGNALS = {"ema-cross": ema_cross, "tsmom": tsmom, "donchian": donchian, "efficiency": efficiency, "obv": obv,
           "rsi-reversion": rsi_reversion, "bollinger-reversion": bollinger_reversion}
FORMS = ("vote", "confirm", "calm-vote", "regime-switch")


def _efficiency_ratio(c, i, lookback=20):
    if i < lookback:
        return None
    path = sum(abs(c[k] - c[k - 1]) for k in range(i - lookback + 1, i + 1))
    return abs(c[i] - c[i - lookback]) / path if path else 0.0


def blend(bars, names, *, form="vote", enter_pct=67, exit_pct=34, calm_bars=24, min_hold_bars=0, long_only=False):
    """Signed position per bar (+1, 0, -1; None while warming up) from named member signals.

    consensus c in [-1, 1]: long when c >= enter, short when c <= -enter; an open side closes when c falls back to
    the exit band, and may reverse in the same bar. confirm: member 0 sets the side, the others must agree.
    calm-vote: weights 1 / (1 + flips over calm_bars). regime-switch: trend members when the 20-bar efficiency
    ratio is at least 0.3, reversion members otherwise. long_only turns shorts into cash.
    """
    if form not in FORMS:
        raise ValueError(f"unknown blend form {form!r}")
    if not 0 <= exit_pct < enter_pct <= 100:
        raise ValueError("exit_pct must be below enter_pct")
    targets = [SIGNALS[n](bars) for n in names]
    enter, exit_ = enter_pct / 100, exit_pct / 100
    flips = [deque(maxlen=calm_bars) for _ in names]
    out, pos, held = [], 0, 0
    close = bars["close"]
    for i in range(len(close)):
        now = [t[i] for t in targets]
        for m, t in enumerate(targets):
            flips[m].append(i > 0 and t[i] is not None and t[i - 1] is not None and t[i] != t[i - 1])
        if any(x is None for x in now):
            out.append(None)
            continue
        members = range(len(names))
        if form == "regime-switch":
            trending = (_efficiency_ratio(close, i) or 0.0) >= 0.3
            members = [m for m, n in enumerate(names) if (n in TREND) == trending] or list(members)
        if form == "confirm":
            others = [now[m] for m in members][1:]
            agree = sum(x == now[0] for x in others) / len(others) if others else 1.0
            c = now[0] * agree
        elif form == "calm-vote":
            w = [1 / (1 + sum(flips[m])) for m in members]
            c = sum(wi * now[m] for wi, m in zip(w, members)) / sum(w)
        else:
            c = sum(now[m] for m in members) / len(members)
        want = pos
        if pos and held >= min_hold_bars and pos * c <= exit_:
            want = 0
        if want == 0:
            want = 1 if c >= enter else -1 if c <= -enter else 0
        if long_only and want < 0:
            want = 0
        held = held + 1 if want == pos and pos else 0
        pos = want
        out.append(pos)
    return out
