"""Bars derived from raw observations (spec §4.3). One streaming consolidator for live, replay and research."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .model import TEHRAN, UTC, BookTop

# ponytail: fixed time bars only; session/volume/Jalali-calendar PeriodSpecs come when a strategy needs one.
RESOLUTIONS = {"1min": 60, "15min": 900, "1h": 3600, "1day": 86400}
PRICE_TYPES = ("BID", "ASK", "MID", "LAST")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# A quote that fails these checks never becomes a bar or a fill.
DISQUALIFY = frozenset({"STALE", "CROSSED", "ZERO_SPREAD", "NON_FINITE", "NON_POSITIVE"})


def qualified(top: BookTop) -> bool:
    return top.bid is not None and top.ask is not None and not (top.flags & DISQUALIFY)


@dataclass(frozen=True)
class BarSpec:
    resolution: str
    price_type: str = "MID"

    def __post_init__(self):
        if self.resolution not in RESOLUTIONS:
            raise ValueError(f"unsupported resolution {self.resolution!r}; have {list(RESOLUTIONS)}")
        if self.price_type not in PRICE_TYPES:
            raise ValueError(f"unsupported price type {self.price_type!r}; have {PRICE_TYPES}")

    @property
    def step(self) -> timedelta:
        return timedelta(seconds=RESOLUTIONS[self.resolution])

    def bucket(self, t: datetime) -> datetime:
        """Period start. Daily bars align to Tehran midnight, the venue's calendar; the rest to UTC."""
        off = t.astimezone(TEHRAN).utcoffset() if self.resolution == "1day" else timedelta(0)
        n = (t + off - EPOCH) // self.step
        return EPOCH + n * self.step - off

    def price(self, top: BookTop) -> Decimal:
        return {"BID": top.bid, "ASK": top.ask}.get(self.price_type) or (top.bid + top.ask) / 2


@dataclass(frozen=True)
class Bar:
    symbol: str
    spec: BarSpec
    start: datetime
    end: datetime
    avail: datetime  # visible to a decision at t only if avail <= t
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    count: int
    forming: bool = False


class Consolidator:
    """Feed observations in availability order; get closed bars. Empty periods produce no bar (missingness)."""

    def __init__(self, symbol: str, spec: BarSpec):
        self.symbol, self.spec, self.cur = symbol, spec, None

    def scan(self, now: datetime) -> list[Bar]:
        """Clock scan: close the working bar once its period is over, even in a quiet market."""
        if self.cur and now >= self.cur["end"]:
            c, self.cur = self.cur, None
            return [Bar(self.symbol, self.spec, c["start"], c["end"], c["end"], c["o"], c["h"], c["l"], c["c"], c["v"], c["n"])]
        return []

    def update(self, t: datetime, price: Decimal, qty: Decimal = Decimal(0)) -> list[Bar]:
        out = self.scan(t)
        if not self.cur:
            start = self.spec.bucket(t)
            self.cur = {"start": start, "end": start + self.spec.step, "o": price, "h": price, "l": price, "c": price,
                        "v": Decimal(0), "n": 0}
        c = self.cur
        c["h"], c["l"], c["c"], c["v"], c["n"] = max(c["h"], price), min(c["l"], price), price, c["v"] + qty, c["n"] + 1
        return out

    def forming(self, now: datetime) -> Bar | None:
        """The working bar, flagged. Never part of closed-bar history."""
        c = self.cur
        return c and Bar(self.symbol, self.spec, c["start"], c["end"], now, c["o"], c["h"], c["l"], c["c"], c["v"], c["n"], True)


def quote_bars(symbol: str, spec: BarSpec, tops: list[BookTop]) -> list[Bar]:
    """Batch form of the same consolidator (DATA-05 parity: identical input, identical bars)."""
    c, out = Consolidator(symbol, spec), []
    for top in tops:
        if qualified(top):
            out += c.update(top.ts_avail, spec.price(top))
    return out
