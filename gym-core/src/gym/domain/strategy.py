"""Canonical streaming features and the first deterministic strategy (spec §4.3.5, §7.1)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .bars import Bar


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

    @property
    def id(self) -> str:
        return digest([self.as_of, self.symbol, self.bar.start, self.bar.close, self.bid, self.ask, self.quote_time])[:16]


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


class BuyAndHold:
    """Baseline: buy once at the first qualified decision, then hold. Same simulator, same costs."""
    name = "buy-and-hold"
    params: dict = {}

    def decide(self, snap: Snapshot, holding: bool):
        if holding:
            return "HOLD", Decimal(0), ("baseline holds",), ""
        if snap.bid is None:
            return "ABSTAIN_NO_QUOTE", Decimal(0), ("no qualified quote at decision time",), ""
        return "BUY_REQUEST", Decimal(1), ("baseline entry",), ""
