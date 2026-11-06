"""Canonical streaming features and the first deterministic strategy (spec §4.3.5, §7.1)."""
from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .bars import Bar
from .model import BookTop


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


class EMA:
    """Incremental EMA; ready after `n` inputs (its declared warmup)."""

    def __init__(self, n: int):
        if n < 1:
            raise ValueError("EMA length must be >= 1")
        self.n, self.k, self.value, self.count = n, Decimal(2) / (n + 1), None, 0

    def update(self, x: Decimal) -> Decimal:
        self.value = x if self.value is None else self.value + self.k * (x - self.value)
        self.count += 1
        return self.value

    @property
    def ready(self) -> bool:
        return self.count >= self.n


@dataclass(frozen=True)
class Snapshot:
    """One immutable cut a decision sees: the last closed bar and the last qualified quote, both available by as_of."""
    as_of: datetime
    symbol: str
    bar: Bar
    bid: Decimal | None
    ask: Decimal | None
    quote_time: datetime | None
    context_bars: tuple[Bar, ...] = ()
    reference: BookTop | None = None
    execution: dict | None = None

    @property
    def id(self) -> str:
        cut = [self.as_of, self.symbol, self.bar.start, self.bar.close, self.bid, self.ask, self.quote_time]
        if self.context_bars or self.reference:
            reference = self.reference
            cut += [[(b.spec.resolution, b.start, b.avail, b.open, b.close) for b in self.context_bars],
                    [reference.symbol, reference.ts_avail, reference.bid, reference.ask] if reference else None]
        return digest(cut)[:16]


@dataclass(frozen=True)
class Proposal:
    snapshot_id: str
    decision_time: datetime
    valid_until: datetime
    symbol: str
    action: str  # HOLD | BUY_REQUEST | SELL_REQUEST | ABSTAIN_<REASON>
    fraction: Decimal  # BudgetFraction of the strategy budget, not an order amount
    reasons: tuple[str, ...]
    feature_hash: str


class EmaTrend:
    """Long the base asset while the fast EMA of MID closes is above the slow one; otherwise hold quote cash."""
    name = "ema-trend"

    def __init__(self, fast: int = 8, slow: int = 21):
        if not 1 <= fast < slow:
            raise ValueError("need 1 <= fast < slow")
        self.params = {"fast": fast, "slow": slow}
        self.fast, self.slow = EMA(fast), EMA(slow)

    @property
    def feature_values(self) -> dict:
        return {"fast_ema": str(self.fast.value), "slow_ema": str(self.slow.value),
                "trend": self.fast.value > self.slow.value if self.slow.ready else None}

    def decide(self, snap: Snapshot, holding: bool) -> tuple[str, Decimal, tuple[str, ...], str]:
        f, s = self.fast.update(snap.bar.close), self.slow.update(snap.bar.close)
        fh = digest([str(f), str(s)])[:16]
        if not self.slow.ready:
            return "ABSTAIN_WARMUP", Decimal(0), (f"slow EMA {self.slow.count}/{self.slow.n} bars",), fh
        if snap.bid is None:
            return "ABSTAIN_NO_QUOTE", Decimal(0), ("no qualified quote at decision time",), fh
        up = f > s
        if up and not holding:
            return "BUY_REQUEST", Decimal(1), ("fast EMA crossed above slow",), fh
        if not up and holding:
            return "SELL_REQUEST", Decimal(1), ("fast EMA crossed below slow",), fh
        return "HOLD", Decimal(0), ("trend up, already long" if up else "trend down, already flat",), fh


def long_flat(snap, holding, trend, features):
    fingerprint = digest(features)[:16]
    if trend is None:
        return "ABSTAIN_WARMUP", Decimal(0), ("required closed history unavailable",), fingerprint
    if snap.bid is None:
        return "ABSTAIN_NO_QUOTE", Decimal(0), ("no qualified quote at decision time",), fingerprint
    action = "BUY_REQUEST" if trend and not holding else "SELL_REQUEST" if not trend and holding else "HOLD"
    return action, Decimal(int(action != "HOLD")), ("long condition" if trend else "flat condition",), fingerprint


class SmaCross:
    """Closed-bar SMA crossovers; decisions use actual holding state, never assumed fills."""
    name = "sma-cross"

    def __init__(self, fast=8, slow=21):
        if not 1 <= fast < slow:
            raise ValueError("need 1 <= fast < slow")
        self.params = {"fast": fast, "slow": slow}
        self.closes = deque(maxlen=slow + 1)
        self.feature_values = {}

    def decide(self, snap, holding):
        self.closes.append(snap.bar.close)
        values = list(self.closes)
        fast, slow = self.params["fast"], self.params["slow"]
        self.feature_values = {"observations": len(values), "required": slow + 1, "trend": None}
        if len(values) < slow + 1:
            return long_flat(snap, holding, None, self.feature_values)
        f, s = sum(values[-fast:]) / fast, sum(values[-slow:]) / slow
        pf, ps = sum(values[-fast-1:-1]) / fast, sum(values[-slow-1:-1]) / slow
        cross = "UP" if pf <= ps and f > s else "DOWN" if pf >= ps and f < s else None
        self.feature_values.update(fast_sma=str(f), slow_sma=str(s),
                                   previous_fast_sma=str(pf), previous_slow_sma=str(ps), cross=cross, trend=f > s)
        target = True if cross == "UP" else False if cross == "DOWN" else holding
        return long_flat(snap, holding, target, self.feature_values)


class SmaReversion:
    """Buy below a closed-bar rolling mean; exit at the mean. No shorts or leverage."""
    name = "sma-reversion"

    def __init__(self, lookback=20, entry_bps=50):
        self.params = {"lookback": lookback, "entry_bps": entry_bps}
        self.closes = deque(maxlen=lookback)
        self.feature_values = {}

    def decide(self, snap, holding):
        self.closes.append(snap.bar.close)
        mean = sum(self.closes) / len(self.closes)
        ready = len(self.closes) == self.closes.maxlen
        threshold = mean if holding else mean * (1 - Decimal(self.params["entry_bps"]) / 10000)
        trend = snap.bar.close < threshold if ready else None
        self.feature_values = {"mean": str(mean), "threshold": str(threshold), "trend": trend}
        return long_flat(snap, holding, trend, self.feature_values)


class BollingerReversion:
    """Long below a closed-price population-deviation band; exit at the rolling mean."""
    name = "bollinger-reversion"

    def __init__(self, lookback=20, deviations=2):
        self.params = {"lookback": lookback, "deviations": deviations}
        self.closes = deque(maxlen=lookback)
        self.feature_values = {}

    def decide(self, snap, holding):
        self.closes.append(snap.bar.close)
        mean = sum(self.closes) / len(self.closes)
        deviation = (sum((value - mean)**2 for value in self.closes) / len(self.closes)).sqrt()
        lower = mean - self.params["deviations"] * deviation
        ready = len(self.closes) == self.closes.maxlen
        trend = snap.bar.close < (mean if holding else lower) if ready else None
        self.feature_values = {"mean": str(mean), "standard_deviation": str(deviation),
                               "lower_band": str(lower), "trend": trend}
        return long_flat(snap, holding, trend, self.feature_values)


class ConfirmedTrend(EmaTrend):
    """Trade fast/slow EMA direction only while the last higher-timeframe bar is positive."""
    name = "ema-confirmed"

    def __init__(self, fast=8, slow=21, confirmation="1h"):
        super().__init__(fast, slow)
        self.params["confirmation"] = confirmation
        self.required_resolutions = (confirmation,)
        self.confirmation_bar = None

    @property
    def feature_values(self):
        values = super().feature_values
        bar = self.confirmation_bar
        values.update(confirmation_open=str(bar.open) if bar else None,
                      confirmation_close=str(bar.close) if bar else None,
                      trend=values["trend"] and bar.close > bar.open if bar and self.slow.ready else None)
        return values

    def decide(self, snap, holding):
        self.confirmation_bar = next((b for b in snap.context_bars if b.spec.resolution == self.params["confirmation"]), None)
        super().decide(snap, holding)
        return long_flat(snap, holding, self.feature_values["trend"], self.feature_values)


class RelativeMomentum:
    """Buy the traded asset only when its trailing return is positive and exceeds the reference asset's."""
    name = "relative-momentum"

    def __init__(self, lookback=20, reference="ETHUSDT"):
        self.params = {"lookback": lookback, "reference": reference}
        self.reference_symbol = reference
        self.history = deque(maxlen=lookback + 1)
        self.feature_values = {}

    def decide(self, snap, holding):
        if snap.reference is None:
            self.feature_values = {"trend": None, "reference": self.reference_symbol}
            return "ABSTAIN_NO_REFERENCE", Decimal(0), ("no fresh qualified reference quote",), digest(self.feature_values)[:16]
        reference = (snap.reference.bid + snap.reference.ask) / 2
        self.history.append((snap.bar.close, reference))
        primary_return = snap.bar.close / self.history[0][0] - 1
        reference_return = reference / self.history[0][1] - 1
        ready = len(self.history) == self.history.maxlen
        trend = primary_return > 0 and primary_return > reference_return if ready else None
        self.feature_values = {"primary_return": str(primary_return), "reference_return": str(reference_return),
                               "reference": self.reference_symbol, "trend": trend}
        return long_flat(snap, holding, trend, self.feature_values)


class BuyAndHold:
    """Baseline: buy once at the first qualified decision, then hold. Same simulator, same costs."""
    name = "buy-and-hold"
    params: dict = {}
    feature_values: dict = {}

    def decide(self, snap: Snapshot, holding: bool):
        if holding:
            return "HOLD", Decimal(0), ("baseline holds",), ""
        if snap.bid is None:
            return "ABSTAIN_NO_QUOTE", Decimal(0), ("no qualified quote at decision time",), ""
        return "BUY_REQUEST", Decimal(1), ("baseline entry",), ""
