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

    def __init__(self, db: MarketDB, *, excluded=()):
        self.db = db
        self.excluded = tuple(excluded)
        # Read-only snapshots of older stores predate the depth column.
        self.has_depth = any(row[1] == "depth" for row in db.c.execute("pragma table_info(book_top)"))

    def tops(self, symbol: str, t0: datetime, t1: datetime) -> list[BookTop]:
        if not t0 < t1:
            raise ValueError(f"inverted or empty range {iso(t0)} .. {iso(t1)}")
        rows = self.db.c.execute("select ts_avail, bid, ask, bid_qty, ask_qty, flags, " + ("depth" if self.has_depth else "null") +
                                 " from book_top where instrument_id=? and ts_avail>=? and ts_avail<? order by ts_avail, rowid",
                                 (f"wallex:{symbol}", iso(t0), iso(t1)))
        def optional_decimal(value):
            return None if value is None else dec(value)

        def depth(text):
            if text is None:
                return None
            return tuple(tuple((dec(p), dec(q)) for p, q in side) for side in json.loads(text))

        return [BookTop(symbol, parse_ts(r[0]), optional_decimal(r[1]), optional_decimal(r[2]), optional_decimal(r[3]),
                        optional_decimal(r[4]), frozenset(filter(None, r[5].split(","))), depth(r[6]))
                for r in rows if not any(start <= parse_ts(r[0]) < end for start, end in self.excluded)]

    def publication(self):
        if not self.db.c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='collector_publication'").fetchone():
            return None
        row = self.db.c.execute("SELECT through FROM collector_publication WHERE singleton=1").fetchone()
        return parse_ts(row[0]) if row else None

    def trades_by_event(self, symbol: str, t0: datetime, t1: datetime) -> list[TradeTick]:
        rows = self.db.c.execute("select ts_event, ts_avail, price, qty, aggressor from trades where instrument_id=? "
                                 "and ts_event>=? and ts_event<? order by ts_event, rowid", (f"wallex:{symbol}", iso(t0), iso(t1)))
        return [TradeTick(symbol, parse_ts(r[0]), parse_ts(r[1]), dec(r[2]), dec(r[3]), r[4]) for r in rows]

    def venue_candles(self, symbol: str, resolution: str, t0: datetime, t1: datetime, *, as_of=None) -> list[dict]:
        history = self.db.c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='candle_vintages'").fetchone()
        table = "candle_vintages" if history else "venue_candles"
        rows = self.db.c.execute(f"""SELECT t,o,h,l,c,v,fetched_at FROM (
            SELECT t,o,h,l,c,v,fetched_at,ROW_NUMBER() OVER(PARTITION BY t ORDER BY fetched_at DESC) AS position
            FROM {table} WHERE instrument_id=? AND resolution=? AND t>=? AND t<? AND (? IS NULL OR fetched_at<?))
            WHERE position=1 ORDER BY t""", (f"wallex:{symbol}", resolution, iso(t0), iso(t1), iso(as_of), iso(as_of)))
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


POOR_DATA_SHARE = 0.2  # more flagged rows than this and paper entries on the market are not trusted


def quality_report(db: MarketDB, since: datetime) -> dict[str, dict]:
    """Per market since `since`: stored quote rows, share carrying a disqualifying flag, and the longest silence."""
    out = {}
    for instrument, rows, flagged, longest in db.c.execute("""
            SELECT instrument_id, count(*), sum(flags != ''), coalesce(max(gap), 0) FROM (
                SELECT instrument_id, flags,
                       (julianday(ts_avail) - julianday(lag(ts_avail) OVER (PARTITION BY instrument_id ORDER BY ts_avail))) * 86400 AS gap
                FROM book_top WHERE ts_avail >= ?) GROUP BY instrument_id""", (iso(since),)):
        share = flagged / rows if rows else 1.0
        out[instrument.split(":", 1)[1]] = {"rows": rows, "flagged_share": round(share, 4), "longest_gap_s": round(longest, 1),
                                            "grade": "POOR" if share > POOR_DATA_SHARE or longest > 3600 else "OK"}
    return out


def quote_gaps(db: MarketDB, symbol: str, t0: datetime, t1: datetime, min_seconds: float = 120) -> list[tuple[datetime, datetime]]:
    """Stretches with no stored quote longer than `min_seconds`, inside [t0, t1)."""
    rows = db.c.execute("""SELECT prev, ts_avail FROM (
        SELECT ts_avail, lag(ts_avail) OVER (ORDER BY ts_avail) AS prev FROM book_top
        WHERE instrument_id=? AND ts_avail>=? AND ts_avail<?)
        WHERE prev IS NOT NULL AND (julianday(ts_avail) - julianday(prev)) * 86400 > ?""",
                        (f"wallex:{symbol}", iso(t0), iso(t1), min_seconds)).fetchall()
    return [(parse_ts(a), parse_ts(b)) for a, b in rows]


def rate_at(tops: list[BookTop], t: datetime) -> tuple[Decimal, datetime] | None:
    """Derived valuation rate: MID of the last qualified quote at or before t. Not an executable price."""
    q = [x for x in tops[: bisect_right([x.ts_avail for x in tops], t)] if qualified(x)]
    return ((q[-1].bid + q[-1].ask) / 2, q[-1].ts_avail) if q else None


