"""Point-in-time market-data access and valuation rates over the local market database."""
import hashlib
import json
from bisect import bisect_right
from datetime import datetime
from decimal import Decimal

from ..adapters.store import MarketDB
from ..domain.bars import qualified
from ..domain.model import BookTop, InstrumentId, TradeTick, dec, iso, parse_ts
from ..domain.sim import Spec


class DataPortal:
    """Point-in-time reads: quotes in availability order; specs and rules as they were known at a time."""

    def __init__(self, db: MarketDB):
        self.db = db

    def tops(self, symbol: str, t0: datetime, t1: datetime) -> list[BookTop]:
        if not t0 < t1:
            raise ValueError(f"inverted or empty range {iso(t0)} .. {iso(t1)}")
        rows = self.db.c.execute("select ts_avail, bid, ask, bid_qty, ask_qty, flags from book_top where instrument_id=? "
                                 "and ts_avail>=? and ts_avail<? order by ts_avail, rowid", (f"wallex:{symbol}", iso(t0), iso(t1)))
        def optional_decimal(value):
            return None if value is None else dec(value)

        return [BookTop(symbol, parse_ts(r[0]), optional_decimal(r[1]), optional_decimal(r[2]), optional_decimal(r[3]), optional_decimal(r[4]), frozenset(filter(None, r[5].split(","))))
                for r in rows]

    def trades_by_event(self, symbol: str, t0: datetime, t1: datetime) -> list[TradeTick]:
        rows = self.db.c.execute("select ts_event, ts_avail, price, qty, aggressor from trades where instrument_id=? "
                                 "and ts_event>=? and ts_event<? order by ts_event, rowid", (f"wallex:{symbol}", iso(t0), iso(t1)))
        return [TradeTick(symbol, parse_ts(r[0]), parse_ts(r[1]), dec(r[2]), dec(r[3]), r[4]) for r in rows]

    def venue_candles(self, symbol: str, resolution: str, t0: datetime, t1: datetime) -> list[dict]:
        rows = self.db.c.execute("select t, o, h, l, c, v, fetched_at from venue_candles where instrument_id=? and "
                                 "resolution=? and t>=? and t<? order by t", (f"wallex:{symbol}", resolution, iso(t0), iso(t1)))
        return [{"t": parse_ts(r[0]), **{k: dec(x) for k, x in zip("ohlcv", r[1:6])}, "fetched_at": parse_ts(r[6])}
                for r in rows]

    def observed(self, symbol: str, t0: datetime, t1: datetime) -> bool:
        """Whether the collector was writing this pair's book (change-only rows plus heartbeats) in [t0, t1)."""
        return self.db.c.execute("select 1 from book_top where instrument_id=? and ts_avail>=? and ts_avail<? limit 1",
                                 (f"wallex:{symbol}", iso(t0), iso(t1))).fetchone() is not None

    def instrument(self, symbol: str) -> InstrumentId:
        r = self.db.c.execute("select base, quote from instruments where symbol=?", (symbol,)).fetchone()
        return InstrumentId.wallex(symbol, *r) if r else InstrumentId.wallex(symbol)

    def metadata_at(self, symbol: str, t: datetime) -> dict | None:
        r = self.db.c.execute("select rowid, valid_from, valid_to, spec, source from instrument_specs where "
                              "instrument_id=? and valid_from<=? and (valid_to is null or valid_to>?) "
                              "order by valid_from desc limit 1",
                              (f"wallex:{symbol}", iso(t), iso(t))).fetchone()
        if not r:
            return None
        return {"valid_from": parse_ts(r[1]), "valid_to": parse_ts(r[2]) if r[2] else None,
                "source": r[4], "version": r[0],
                "raw_digest": hashlib.sha256(r[3].encode()).hexdigest(), "raw": json.loads(r[3])}

    def spec_at(self, symbol: str, t: datetime) -> Spec:
        r = self.db.c.execute("select spec from instrument_specs where instrument_id=? and valid_from<=? and "
                              "(valid_to is null or valid_to>?) order by valid_from desc limit 1",
                              (f"wallex:{symbol}", iso(t), iso(t))).fetchone()
        if not r:
            return Spec()  # unknown at that time: not enforced, and the report says so
        s = json.loads(r[0])
        def optional_constraint(name):
            return None if s.get(name) in (None, "") else dec(s[name])

        return Spec(None if s.get("stepSize") is None else int(s["stepSize"]),
                    optional_constraint("minQty"), optional_constraint("minNotional"))


def rate_at(tops: list[BookTop], t: datetime) -> tuple[Decimal, datetime] | None:
    """Derived valuation rate: MID of the last qualified quote at or before t. Not an executable price."""
    q = [x for x in tops[: bisect_right([x.ts_avail for x in tops], t)] if qualified(x)]
    return ((q[-1].bid + q[-1].ask) / 2, q[-1].ts_avail) if q else None


