"""Bars derived from raw observations (spec §4.3). One streaming consolidator for live, replay and research."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .model import TEHRAN, UTC, BookTop

# ponytail: time and trading-session bars only; volume/count/Jalali-calendar periods come when a strategy needs one.
# "session" is bounded by TradingWindow closures and Tehran midnight; 86400 s is only its nominal step.
RESOLUTIONS = {"1min": 60, "15min": 900, "1h": 3600, "1day": 86400, "session": 86400}
PRICE_TYPES = ("BID", "ASK", "MID", "LAST")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# A quote that fails these checks never becomes a bar or a fill.
DISQUALIFY = frozenset({"STALE", "CROSSED", "ZERO_SPREAD", "NON_FINITE", "NON_POSITIVE"})


def qualified(top: BookTop) -> bool:
    return (top.bid is not None and top.ask is not None
            and top.bid.is_finite() and top.ask.is_finite()
            and 0 < top.bid < top.ask and not (top.flags & DISQUALIFY))


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
        if self.resolution == "session":
            raise ValueError("session periods come from the trading-window rules, not a fixed grid")
        off = t.astimezone(TEHRAN).utcoffset() if self.resolution == "1day" else timedelta(0)
        n = (t + off - EPOCH) // self.step
        return EPOCH + n * self.step - off

    def price(self, top: BookTop) -> Decimal:
        if self.price_type == "LAST":
            raise ValueError("LAST bars require trade prices, not book quotes")
        return {"BID": top.bid, "ASK": top.ask, "MID": (top.bid + top.ask) / 2}[self.price_type]


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

    def __init__(self, symbol: str, spec: BarSpec, period=None):
        """`period(t) -> (start, end)` overrides the fixed grid; session bars require one."""
        if spec.resolution == "session" and period is None:
            raise ValueError("session bars need a period function from the trading-window rules")
        self.symbol, self.spec, self.period, self.cur = symbol, spec, period, None

    def period_of(self, t: datetime) -> tuple[datetime, datetime]:
        if self.period:
            return self.period(t)
        start = self.spec.bucket(t)
        return start, start + self.spec.step

    def scan(self, now: datetime) -> list[Bar]:
        """Clock scan: close the working bar once its period is over, even in a quiet market."""
        if self.cur and now >= self.cur["end"]:
            c, self.cur = self.cur, None
            return [Bar(self.symbol, self.spec, c["start"], c["end"], c["end"], c["o"], c["h"], c["l"], c["c"], c["v"], c["n"])]
        return []

    def update(self, t: datetime, price: Decimal, qty: Decimal = Decimal(0)) -> list[Bar]:
        if not price.is_finite() or price <= 0 or not qty.is_finite() or qty < 0:
            raise ValueError("bar price must be positive and finite; quantity must be nonnegative and finite")
        out = self.scan(t)
        if not self.cur:
            start, end = self.period_of(t)
            self.cur = {"start": start, "end": end, "o": price, "h": price, "l": price, "c": price,
                        "v": Decimal(0), "n": 0}
        c = self.cur
        c["h"], c["l"], c["c"], c["v"], c["n"] = max(c["h"], price), min(c["l"], price), price, c["v"] + qty, c["n"] + 1
        return out

    def forming(self, now: datetime) -> Bar | None:
        """The working bar, flagged. Never part of closed-bar history."""
        c = self.cur
        return c and Bar(self.symbol, self.spec, c["start"], c["end"], now, c["o"], c["h"], c["l"], c["c"], c["v"], c["n"], True)


def trade_bars(symbol: str, spec: BarSpec, trades, until: datetime) -> list[Bar]:
    """LAST bars from trade prints, bucketed by venue event time (the venue candle's clock); bars closed by
    `until`. For cross-checks against venue candles; decisions use availability-ordered quote bars."""
    c, out = Consolidator(symbol, spec), []
    for t in sorted(trades, key=lambda x: x.ts_event):
        out += c.update(t.ts_event, t.price, t.qty)
    return out + c.scan(until)


def quote_bars(symbol: str, spec: BarSpec, tops: list[BookTop], period=None) -> list[Bar]:
    """Batch form of the same consolidator (DATA-05 parity: identical input, identical bars)."""
    c, out = Consolidator(symbol, spec, period), []
    for top in tops:
        if qualified(top):
            out += c.update(top.ts_avail, spec.price(top))
    return out
