"""Bars derived from raw observations (spec §4.3). One streaming consolidator for live, replay and research."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .model import TEHRAN, UTC, BookTop
from .periods import Calendar, Count, DirectionalChange, Fixed, Mixed, Volume, instant

# "session" is bounded by TradingWindow closures and Tehran midnight; 86400 s is only its nominal step.
RESOLUTIONS = {"1min": 60, "3min": 180, "5min": 300, "15min": 900, "30min": 1800,
               "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200,
               "1day": 86400, "session": 86400}
FIXED_RESOLUTIONS = tuple(name for name in RESOLUTIONS if name != "session")
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
        t = instant(t)
        if self.resolution == "1day":
            return datetime.combine(t.astimezone(TEHRAN).date(), datetime.min.time(), TEHRAN).astimezone(UTC)
        return EPOCH + ((t - EPOCH) // self.step) * self.step

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
    """Availability-ordered observations; one working bar and lagged closed bars.

    Count/Volume consume trade prints, not quote changes. Mixed closes at the first
    limit, retaining whole trades (no splitting or carry). DC uses log reversals,
    starts in a down-trend, and never backdates a confirmation to its extreme.
    An unbounded forming event bar uses datetime.max (UTC) until confirmation.
    """

    def __init__(self, symbol: str, spec: BarSpec, period=None, *, publication_lag=timedelta(0)):
        if spec.resolution == "session" and period is None:
            raise ValueError("session bars need a period function from the trading-window rules")
        if not isinstance(publication_lag, timedelta) or publication_lag < timedelta(0):
            raise ValueError("publication lag must be nonnegative")
        if period is not None and not isinstance(period, (Fixed, Count, Volume, Mixed, Calendar, DirectionalChange)) and not callable(period):
            raise ValueError("unsupported period")
        self.symbol, self.spec, self.period, self.cur = symbol, spec, period, None
        self.publication_lag, self.pending, self.watermark = publication_lag, [], None
        self.direction, self.extreme = -1, None

    def period_of(self, t: datetime) -> tuple[datetime, datetime]:
        t = instant(t)
        if self.period is not None:
            limits = self.period.periods if isinstance(self.period, Mixed) else (self.period,)
            bounds = [(instant(a), instant(b)) for a, b in (p(t) for p in limits if callable(p))]
            if not bounds:
                return t, datetime.max.replace(tzinfo=UTC)
            if any(not a <= t < b for a, b in bounds):
                raise ValueError("calendar period must contain the observation in [start, end)")
            return max(a for a, _ in bounds), min(b for _, b in bounds)
        start = self.spec.bucket(t)
        if self.spec.resolution == "1day":
            end = datetime.combine(t.astimezone(TEHRAN).date() + timedelta(days=1), datetime.min.time(), TEHRAN)
            return start, end.astimezone(UTC)
        return start, start + self.spec.step

    def _close(self, end):
        c, self.cur = self.cur, None
        self.pending.append(Bar(self.symbol, self.spec, c["start"], end, end + self.publication_lag,
                                c["o"], c["h"], c["l"], c["c"], c["v"], c["n"]))

    def scan(self, now: datetime) -> list[Bar]:
        """Close quiet time periods; release only bars available by this watermark."""
        now = instant(now)
        if self.watermark is not None and now < self.watermark:
            raise ValueError("observations and scans must follow availability order")
        self.watermark = now
        if self.cur and now >= self.cur["end"]:
            self._close(self.cur["end"])
        ready = [bar for bar in self.pending if bar.avail <= now]
        self.pending = [bar for bar in self.pending if bar.avail > now]
        return ready

    def update(self, t: datetime, price: Decimal, qty: Decimal = Decimal(0), *, bid=None, ask=None) -> list[Bar]:
        if not isinstance(price, Decimal) or not price.is_finite() or price <= 0 or not isinstance(qty, Decimal) or not qty.is_finite() or qty < 0:
            raise ValueError("bar price must be positive and finite; quantity must be nonnegative and finite")
        t = instant(t)
        dc = self.period if isinstance(self.period, DirectionalChange) else None
        if dc:
            bid, ask = (price if bid is None else bid), (price if ask is None else ask)
            if any(not isinstance(p, Decimal) or not p.is_finite() or p <= 0 for p in (bid, ask)) or bid > ask:
                raise ValueError("directional quotes must be finite, positive and uncrossed")
        start, end = self.period_of(t)
        out = self.scan(t)
        if not self.cur:
            if isinstance(self.period, Mixed):
                start = t
            self.cur = {"start": start, "end": end, "o": price, "h": price, "l": price, "c": price,
                        "v": Decimal(0), "n": 0}
        c = self.cur
        c["h"], c["l"], c["c"], c["v"], c["n"] = max(c["h"], price), min(c["l"], price), price, c["v"] + qty, c["n"] + 1
        limits = self.period.periods if isinstance(self.period, Mixed) else (self.period,)
        close = any((isinstance(p, Count) and c["n"] >= p.n) or
                    (isinstance(p, Volume) and c["v"] >= p.q) for p in limits)
        if dc:
            observed = bid if self.direction < 0 else ask
            if self.extreme is None:
                self.extreme = observed
            self.extreme = min(self.extreme, observed) if self.direction < 0 else max(self.extreme, observed)
            move = (observed / self.extreme).ln()
            close = move >= dc.delta_up if self.direction < 0 else move <= -dc.delta_down
            if close:
                self.direction *= -1
                self.extreme = ask if self.direction > 0 else bid
        if close:
            self._close(t)
            out += self.scan(t)
        return out

    def update_trade(self, trade) -> list[Bar]:
        """Decision bars use receipt/availability time, never a delayed print's event time."""
        if trade.symbol != self.symbol or instant(trade.ts_event) > instant(trade.ts_avail):
            raise ValueError("trade symbol or event/availability times are invalid")
        return self.update(trade.ts_avail, trade.price, trade.qty)

    def update_quote(self, top: BookTop) -> list[Bar]:
        limits = self.period.periods if isinstance(self.period, Mixed) else (self.period,)
        if any(isinstance(p, (Count, Volume)) for p in limits):
            raise ValueError("count and volume periods require trade prints, not quote changes")
        if not qualified(top):
            return []
        return self.update(top.ts_avail, self.spec.price(top), bid=top.bid, ask=top.ask)

    def forming(self, now: datetime) -> Bar | None:
        """Flagged partial only; never included in closed-bar history."""
        now = instant(now)
        if self.watermark is not None and now < self.watermark:
            raise ValueError("forming query precedes the availability watermark")
        c = self.cur
        return c and Bar(self.symbol, self.spec, c["start"], c["end"], now, c["o"], c["h"], c["l"], c["c"], c["v"], c["n"], True)


class CloseSubscriptions:
    """Deterministic on-close fan-out over the existing availability-safe consolidator."""

    def __init__(self, symbol: str, resolutions, periods=None):
        ordered = tuple(dict.fromkeys(resolutions))
        if not ordered:
            raise ValueError("at least one close subscription is required")
        periods = periods or {}
        self.order = {resolution: i for i, resolution in enumerate(ordered)}
        self.by_resolution = {
            resolution: Consolidator(symbol, BarSpec(resolution, "MID"), periods.get(resolution))
            for resolution in ordered
        }

    def _ordered(self, bars):
        rank = {resolution: i for i, resolution in enumerate(RESOLUTIONS)}
        return sorted(bars, key=lambda bar: (bar.avail, rank[bar.spec.resolution], self.order[bar.spec.resolution]))

    def scan(self, now: datetime) -> list[Bar]:
        return self._ordered([bar for consolidator in self.by_resolution.values() for bar in consolidator.scan(now)])

    def update(self, t: datetime, price: Decimal, qty: Decimal = Decimal(0)) -> list[Bar]:
        return self._ordered([
            bar
            for consolidator in self.by_resolution.values()
            for bar in consolidator.update(t, price, qty)
        ])

    def forming(self, now: datetime) -> dict[str, Bar | None]:
        return {resolution: consolidator.forming(now) for resolution, consolidator in self.by_resolution.items()}


@dataclass(frozen=True)
class ClockEvent:
    kind: str
    name: str
    timestamp: datetime
    avail: datetime
    sequence: int
    payload: object = None

    def __post_init__(self):
        object.__setattr__(self, "timestamp", instant(self.timestamp))
        object.__setattr__(self, "avail", instant(self.avail))
        if self.kind not in ("close", "event", "regime") or not isinstance(self.name, str) or not self.name:
            raise ValueError("unsupported clock event")
        if self.kind == "close" and self.name not in RESOLUTIONS:
            raise ValueError("unsupported close resolution")
        if self.kind == "regime" and self.name not in ("window_open", "window_close"):
            raise ValueError("unsupported regime transition")
        if isinstance(self.payload, Bar) and (self.payload.forming or self.payload.avail > self.avail):
            raise ValueError("forming or unpublished bars cannot trigger decisions")
        if self.avail < self.timestamp:
            raise ValueError("event cannot be available before confirmation")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("event sequence must be a nonnegative source sequence")


class EventClock:
    """Merge close/event/regime triggers at an explicit complete-input watermark.

    Producers may arrive in any order BEFORE drain(now), which asserts all inputs
    available through now have arrived. Late arrivals are errors, never revisions.
    Sequence is a stable producer sequence, not an arrival-order counter.
    """

    def __init__(self):
        self.subscriptions, self.pending, self.watermark = [], {}, None

    def _subscribe(self, kind, name):
        # Reuse event validation for subscription names without publishing anything.
        ClockEvent(kind, name, EPOCH, EPOCH, 0)
        self.subscriptions.append((kind, name))
        return len(self.subscriptions) - 1

    def on_close(self, resolution):
        return self._subscribe("close", resolution)

    def on_event(self, kind):
        return self._subscribe("event", kind)

    def on_regime(self, transition):
        return self._subscribe("regime", transition)

    def publish(self, event: ClockEvent):
        if not isinstance(event, ClockEvent):
            raise ValueError("publish requires a ClockEvent")
        if self.watermark is not None and event.avail <= self.watermark:
            raise ValueError("late event crosses the committed availability watermark")
        key = event.kind, event.name, event.sequence
        if key in self.pending:
            raise ValueError("duplicate source event sequence")
        self.pending[key] = event

    def publish_close(self, bar: Bar, sequence: int):
        self.publish(ClockEvent("close", bar.spec.resolution, bar.end, bar.avail, sequence, bar))

    def drain(self, now: datetime) -> list[tuple[int, ClockEvent]]:
        now = instant(now)
        if self.watermark is not None and now < self.watermark:
            raise ValueError("clock watermark cannot move backwards")
        ready = [e for e in self.pending.values() if e.avail <= now]
        rank = {name: i for i, name in enumerate(RESOLUTIONS)}
        deliveries = [(i, e) for e in ready for i, sub in enumerate(self.subscriptions) if sub == (e.kind, e.name)]
        deliveries.sort(key=lambda pair: (pair[1].avail, rank.get(pair[1].name, len(rank)) if pair[1].kind == "close" else len(rank),
                                          pair[0], pair[1].sequence))
        self.pending = {key: e for key, e in self.pending.items() if e.avail > now}
        self.watermark = now
        return deliveries


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
        out += c.update_quote(top)
    return out
