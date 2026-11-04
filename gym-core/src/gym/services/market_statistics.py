"""Observed spreads and trade flow, grouped by pair and venue-local hour."""
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, localcontext
from math import ceil
import re
from statistics import median

from ..adapters.store import MarketDB
from ..domain.bars import qualified
from ..domain.market_models import decimal
from ..domain.model import TEHRAN, InstrumentId, iso, parse_ts
from .data_portal import DataPortal


def trade_flow_report(db: MarketDB, start: datetime, end: datetime, *, symbol: str | None = None, store: str = "live") -> dict:
    """Recorded events in [start, end), using only receipts strictly before end."""
    if start >= end:
        raise ValueError("inverted or empty trade-flow range")
    if symbol is not None and (not isinstance(symbol, str) or not re.fullmatch("[A-Z0-9]{2,24}", symbol)):
        raise ValueError("invalid market symbol")
    # Older stored UTC timestamps omit fractional seconds; apply exact cuts after parsing.
    query = ("select instrument_id, ts_event, ts_avail, price, qty, aggressor from trades "
             "where substr(ts_event,1,10)>=? and substr(ts_event,1,10)<=? and substr(ts_avail,1,10)<=?")
    args = [iso(start)[:10], iso(end)[:10], iso(end)[:10]]
    if symbol:
        query += " and instrument_id=?"
        args.append("wallex:" + symbol)
    groups, source_hash, excluded = {}, hashlib.sha256(), 0
    with localcontext() as context:
        context.prec = 160
        for row in db.c.execute(query + " order by instrument_id, ts_event, ts_avail, rowid", args):
            try:
                at, received = parse_ts(row[1]), parse_ts(row[2])
                if not start <= at < end or received >= end:
                    continue
                source_hash.update((json.dumps(list(row)) + "\n").encode())
                if not isinstance(row[0], str) or not row[0].startswith("wallex:"):
                    raise ValueError("invalid venue identity")
                pair = row[0].removeprefix("wallex:")
                price, qty = (decimal(Decimal(raw), name, positive=True)
                              for raw, name in ((row[3], "price"), (row[4], "qty")))
                if not start <= at <= received < end or not re.fullmatch("[A-Z0-9]{2,24}", pair):
                    raise ValueError("invalid recorded trade")
            except (ArithmeticError, ValueError, TypeError):
                excluded += 1
                continue
            key = pair, at.astimezone(TEHRAN).hour
            if key not in groups:
                groups[key] = {"symbol": pair, "quote_currency": InstrumentId.wallex(pair).quote,
                               "tehran_hour": key[1], "samples": 0, "base_volume": Decimal(0),
                               "quote_notional": Decimal(0), "buy_base": Decimal(0),
                               "sell_base": Decimal(0), "unknown_base": Decimal(0)}
            group = groups[key]
            group["samples"] += 1
            group["base_volume"] += qty
            group["quote_notional"] += price * qty
            group[{"BUY": "buy_base", "SELL": "sell_base"}.get(row[5], "unknown_base")] += qty
        for group in groups.values():
            group["vwap"] = group["quote_notional"] / group["base_volume"]
            group["average_trade_quote"] = group["quote_notional"] / group["samples"]
            group["aggressor_imbalance"] = (None if group["unknown_base"] else
                (group["buy_base"] - group["sell_base"]) / group["base_volume"])
    return {"status": "AVAILABLE" if groups else "UNAVAILABLE", "from": iso(start), "to_exclusive": iso(end),
            "store": store, "synthetic": store == "demo", "timezone": "Asia/Tehran",
            "authority": "PUBLIC_OBSERVATIONS", "funded_authority": False, "order_submitted": False,
            "complete_tape_verified": False, "data_digest": source_hash.hexdigest(), "excluded": excluded,
            "samples": sum(group["samples"] for group in groups.values()),
            "groups": [{k: str(v) if isinstance(v, Decimal) else v for k, v in groups[key].items()}
                       for key in sorted(groups)],
            "limitations": ["Recorded rows only; gaps, repeats and venue-wide tape completeness are not certified.",
                            "Event-time hours pool all dates in the range; receipts at or after the cutoff are excluded.",
                            "Unknown aggressor direction makes imbalance unavailable, not neutral.",
                            "VWAP and flow are descriptive, not executable prices, signals or fill guarantees."]
                            + (["Synthetic DEMO trades are not venue evidence."] if store == "demo" else [])}


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
