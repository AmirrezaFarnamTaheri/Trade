"""Instruments, ticks, book tops and quality flags. Exact decimals only."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

UTC = timezone.utc
TEHRAN = ZoneInfo("Asia/Tehran")
QUOTES = ("TMN", "USDT")


def loads(text: str):
    """JSON with every number parsed exactly from its raw text, never through float."""
    return json.loads(text, parse_float=Decimal, parse_int=Decimal)


def dec(x) -> Decimal:
    if isinstance(x, float):
        raise TypeError("float rejected: prices and amounts must be exact decimals")
    return x if isinstance(x, Decimal) else Decimal(str(x))


def parse_ts(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"ambiguous timestamp without zone: {s!r}")
    return t.astimezone(UTC)


def iso(t: datetime | None) -> str | None:
    return None if t is None else t.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class InstrumentId:
    venue: str
    symbol: str
    base: str
    quote: str
    kind: str = "SPOT"

    @classmethod
    def wallex(cls, symbol: str, base: str | None = None, quote: str | None = None) -> InstrumentId:
        if base is None or quote is None:
            quote = next((q for q in QUOTES if symbol.endswith(q)), symbol[-3:])
            base = symbol[: -len(quote)]
        return cls("wallex", symbol, base, quote)


@dataclass(frozen=True)
class CurrencyUnit:
    code: str
    unit_epoch: int
    rials_per_unit: int
    effective_from: str
    evidence: str


# Wallex quotes IRT legs in toman. A redenomination opens a new epoch; it never rewrites stored rows.
TOMAN = CurrencyUnit("TMN", 1, 10, "2020-01-01T00:00:00Z", "Wallex quotes IRT legs in toman (1 TMN = 10 IRR)")


@dataclass(frozen=True)
class TradeTick:
    symbol: str
    ts_event: datetime
    ts_avail: datetime
    price: Decimal
    qty: Decimal
    aggressor: str  # BUY | SELL

    @classmethod
    def wallex(cls, symbol: str, d: dict, ts_avail: datetime) -> TradeTick:
        # isBuyOrder=true means the resting (maker) order was the buy, so the aggressor sold.
        return cls(symbol, parse_ts(d["timestamp"]), ts_avail, dec(d["price"]), dec(d["quantity"]),
                   "SELL" if d["isBuyOrder"] else "BUY")


Levels = list[tuple[Decimal, Decimal]]


def levels(rows: list[dict]) -> Levels:
    return [(dec(r["price"]), dec(r["quantity"])) for r in rows]


@dataclass(frozen=True)
class BookSide:
    levels: Levels
    ts: datetime  # receipt time of the full-side snapshot


@dataclass(frozen=True)
class BookTop:
    symbol: str
    ts_avail: datetime
    bid: Decimal | None
    ask: Decimal | None
    bid_qty: Decimal | None
    ask_qty: Decimal | None
    flags: frozenset[str]

    @property
    def spread(self) -> Decimal | None:
        return None if self.bid is None or self.ask is None else self.ask - self.bid

    @property
    def spread_bps(self) -> Decimal | None:
        s = self.spread
        if s is None or not (self.bid + self.ask) > 0:
            return None
        return (s / ((self.bid + self.ask) / 2) * 10000).quantize(Decimal("0.01"))

    def key(self):
        return (self.bid, self.ask, self.bid_qty, self.ask_qty, self.flags)


@dataclass(frozen=True)
class QualityLimits:
    stale_s: float = 120
    wide_bps: Decimal = Decimal(200)
    thin_levels: int = 3


def book_top(symbol: str, bid: BookSide | None, ask: BookSide | None, now: datetime,
             lim: QualityLimits = QualityLimits()) -> BookTop:
    flags: set[str] = set()
    best: dict[str, tuple[Decimal, Decimal] | None] = {}
    for name, side, pick in (("bid", bid, max), ("ask", ask, min)):
        if side is None or (now - side.ts).total_seconds() > lim.stale_s:
            flags.add("STALE")
        if side is None or not side.levels:
            best[name] = None
            continue
        if any(not (p.is_finite() and q.is_finite()) for p, q in side.levels):
            flags.add("NON_FINITE")
            best[name] = None
            continue
        if any(p <= 0 or q <= 0 for p, q in side.levels):
            flags.add("NON_POSITIVE")
        if len(side.levels) < lim.thin_levels:
            flags.add("THIN_BOOK")
        best[name] = pick(side.levels, key=lambda lv: lv[0])
    b, a = best["bid"], best["ask"]
    top = BookTop(symbol, now, b and b[0], a and a[0], b and b[1], a and a[1], frozenset())
    if b and a:
        if b[0] > a[0]:
            flags.add("CROSSED")
        elif b[0] == a[0]:
            flags.add("ZERO_SPREAD")
        elif top.spread_bps is not None and top.spread_bps > lim.wide_bps:
            flags.add("WIDE_SPREAD")
    return BookTop(symbol, now, top.bid, top.ask, top.bid_qty, top.ask_qty, frozenset(flags))
