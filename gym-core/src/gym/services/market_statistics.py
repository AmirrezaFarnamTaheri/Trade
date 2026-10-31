"""Observed spread distributions, grouped by pair and venue-local hour."""
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from math import ceil
from statistics import median

from ..adapters.store import MarketDB
from ..domain.bars import qualified
from ..domain.model import TEHRAN, iso
from .data_portal import DataPortal


def spread_report(db: MarketDB, start: datetime, end: datetime, *, symbol: str | None = None, store: str = "live") -> dict:
    if start >= end:
        raise ValueError("inverted or empty spread-report range")
    symbols = [symbol] if symbol else [row[0].removeprefix("wallex:") for row in db.c.execute(
        "select distinct instrument_id from book_top where ts_avail>=? and ts_avail<? order by instrument_id",
        (iso(start), iso(end)),
    )]
    samples = defaultdict(list)
    source_hash = hashlib.sha256()
    excluded = 0
    portal = DataPortal(db)
    for pair in symbols:
        for quote in portal.tops(pair, start, end):
            record = [pair, iso(quote.ts_avail), str(quote.bid), str(quote.ask), sorted(quote.flags)]
            source_hash.update((json.dumps(record) + "\n").encode())
            if not qualified(quote):
                excluded += 1
                continue
            hour = quote.ts_avail.astimezone(TEHRAN).hour
            mid = (quote.bid + quote.ask) / 2
            samples[pair, hour].append((quote.ask - quote.bid) / mid * 10000)
    groups = []
    for (pair, hour), values in sorted(samples.items()):
        values.sort()
        statistics = {"min": values[0], "median": median(values),
                      "p95": values[ceil(Decimal("0.95") * len(values)) - 1], "max": values[-1]}
        groups.append({"symbol": pair, "tehran_hour": hour, "samples": len(values),
                       "spread_bps": {name: str(value.quantize(Decimal("0.0001")))
                                      for name, value in statistics.items()}})
    return {
        "from": iso(start), "to_exclusive": iso(end), "store": store, "synthetic": store == "demo",
        "timezone": "Asia/Tehran", "data_digest": source_hash.hexdigest(),
        "samples": sum(group["samples"] for group in groups), "excluded": excluded, "groups": groups,
        "method": "Observation-weighted change-only snapshots plus heartbeats; p95 uses nearest rank. Missing hours have no group.",
        "limitations": ["Not time-weighted. Repeated unchanged snapshots depend on the collector heartbeat.",
                        "Spreads are not realized fees, depth slippage or transport latency.",
                        "Trading windows are not filtered; observed quotes are not proof of executability."]
                        + (["Synthetic DEMO observations are not venue-cost evidence."] if store == "demo" else []),
    }
