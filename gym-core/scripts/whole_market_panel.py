"""Export bounded, point-in-time market features from a TradingGYM archive."""

import argparse
import json
from datetime import timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from gym.adapters.store import MarketDB
from gym.domain.bars import qualified
from gym.domain.market_models import instant
from gym.domain.model import BookTop, InstrumentId, iso
from gym.domain.rules import is_closed
from gym.domain.strategy import digest
from gym.services.data_portal import DataPortal
from gym.services.historical_universe import (
    catalogue_symbols_during,
    spot_entry_intervals,
    whole_window_spot_selection,
)
from gym.services.market_watchlists import load_watchlist
from gym.services.rules import RuleService

FEATURES = {
    "bid": "quote per base",
    "ask": "quote per base",
    "bid_size": "base",
    "ask_size": "base",
    "spread_bps": "bps of current midpoint",
    "momentum_bps": "bps of midpoint return in native quote currency",
}


def _latest_quote(portal, symbol, cutoff, age):
    row = portal.db.c.execute("""
        SELECT ts_avail, bid, ask, bid_qty, ask_qty, flags
        FROM book_top
        WHERE instrument_id = ? AND ts_avail >= ? AND ts_avail < ?
        ORDER BY ts_avail DESC, rowid DESC LIMIT 1
        """, (portal.instrument_key(symbol), iso(cutoff - age), iso(cutoff))).fetchone()
    if row is None:
        return None
    at, bid, ask, bid_size, ask_size, flags = row
    return BookTop(symbol, instant(at), *(Decimal(value) if value is not None else None
                                         for value in (bid, ask, bid_size, ask_size)),
                   frozenset(filter(None, (flags or "").split(","))))


def _usable(quote):
    return quote is not None and qualified(quote) and "CLOSED" not in quote.flags


def _feature_row(inst, metadata, last_top, past, *, fresh, closed, inactive, was_listed):
    top = last_top if fresh else None
    spec = metadata["raw"] if metadata else {}
    reason = (inactive if inactive else "CLOSED" if closed
              else "NO_FRESH_QUOTE" if top is None else "UNQUALIFIED_QUOTE" if not _usable(top)
              else "READY")
    bid = ask = bid_qty = ask_qty = spread = momentum = None
    if _usable(top) and not closed and inst.kind != "UNKNOWN":
        bid, ask = top.bid, top.ask
        bid_qty = top.bid_qty if top.bid_qty is not None and top.bid_qty.is_finite() and top.bid_qty > 0 else None
        ask_qty = top.ask_qty if top.ask_qty is not None and top.ask_qty.is_finite() and top.ask_qty > 0 else None
        with localcontext() as ctx:
            ctx.prec = 34
            spread = top.spread_bps
            if _usable(past):
                momentum = ((bid + ask) / (past.bid + past.ask) - 1) * 10_000
    values = dict(zip(FEATURES, (bid, ask, bid_qty, ask_qty, spread, momentum)))
    return {"symbol": inst.symbol, "base": inst.base, "quote": inst.quote,
            "spec_from": iso(metadata["valid_from"]) if metadata else None,
            "spec_digest": metadata["raw_digest"] if metadata else None,
            "products": {name: spec.get(f"is_{name}") for name in ("spot", "margin", "otc")},
            "receipt": iso(last_top.ts_avail) if last_top else None,
            "momentum_reference_receipt": iso(past.ts_avail) if past else None,
            "eligibility": reason,
            "exit_quote_available": was_listed and _usable(top) and not closed,
            "features": {key: str(value) if value is not None else None for key, value in values.items()},
            "validity": {key: value is not None for key, value in values.items()}}


def _instrument(portal, symbol):
    try:
        return portal.instrument(symbol)
    except ValueError:
        return InstrumentId(portal.venue, symbol, None, None, "UNKNOWN")


def _slice_rows(portal, instruments, windows, excluded, cutoff, age, rules, *, curated, previous):
    rows, current = [], {}
    for symbol, inst in instruments.items():
        metadata = portal.metadata_at(symbol, cutoff)
        top = _latest_quote(portal, symbol, cutoff, timedelta(days=1))
        if not curated and metadata is None and top is None:
            continue
        spans = windows.get(symbol, ())
        interval = next((span for span in spans if span[0] <= cutoff < span[1]), None)
        inactive = None if interval else excluded.get(symbol, "SPOT_NOT_CONFIRMED")
        fresh = top is not None and cutoff - top.ts_avail <= age
        closed = is_closed(rules, inst, cutoff)
        past = None
        if interval and fresh and top.ts_avail >= interval[0] and _usable(top) and not closed:
            prior_interval, prior_top = previous.get(symbol, (None, None))
            if prior_interval == interval:
                past = prior_top
            current[symbol] = (interval, top)
        row = _feature_row(inst, metadata, top, past, fresh=fresh, closed=closed, inactive=inactive,
                           was_listed=bool(spans and spans[0][0] <= cutoff))
        if interval and fresh and top.ts_avail < interval[0]:
            row["eligibility"] = "QUOTE_PRECEDES_SPOT_WINDOW"
        rows.append(row)
    return rows, current


def market_panel(db, start, end, *, step_seconds, age_seconds=120, symbols=None, watchlist=None,
                 venue="wallex", store="live"):
    """Yield immutable slices with strict receipt cutoffs and explicit missing feature values."""
    if not start < end or type(step_seconds) is not int or not 60 <= step_seconds <= 86400:
        raise ValueError("invalid panel window or step")
    if type(age_seconds) is not int or not 1 <= age_seconds <= min(3600, step_seconds):
        raise ValueError("quote age must be within one panel step and no more than an hour")
    step, age = timedelta(seconds=step_seconds), timedelta(seconds=age_seconds)
    count = (end - start - timedelta(microseconds=1)) // step + 1
    if count > 500:
        raise ValueError("market panel exceeds 500 cutoffs")
    db.c.execute("BEGIN")
    try:
        selection = whole_window_spot_selection(db, start, end, store=store, symbols=symbols, watchlist=watchlist, venue=venue)
        requested = watchlist["symbols"] if watchlist is not None else symbols
        candidates = sorted(requested) if requested is not None else catalogue_symbols_during(db, start, end, venue=venue)
        if len(candidates) > 1000 or count * len(candidates) > 250_000:
            raise ValueError("market panel exceeds 250000 instrument-cutoff pairs")
        portal, service = DataPortal(db, venue=venue), RuleService(db)
        instruments = {s: _instrument(portal, s) for s in candidates}
        windows = spot_entry_intervals(selection, start, end)
        config = {"schema": "market-panel/2", "mode": "WHOLE" if requested is None else "CURATED",
                  "from": iso(start), "to_exclusive": iso(end), "step_seconds": step_seconds,
                  "max_quote_age_seconds": age_seconds, "requested_symbols": sorted(requested or []),
                  "venue": venue, "store": store, "universe_selection": selection,
                  "features": FEATURES, "feature_availability": "Current fields use receipt. Momentum also uses momentum_reference_receipt.",
                  "rank_score": "momentum_bps minus quoted spread_bps",
                  "catalogue_completeness": "UNKNOWN", "authority": "PAPER_ONLY"}
        yield {**config, "config_digest": digest(config)}
        previous = {}
        for index in range(count):
            cutoff = start + index * step
            rows, previous = _slice_rows(portal, instruments, windows, selection["excluded"], cutoff, age,
                                         service.load(cutoff)[1], curated=requested is not None, previous=previous)
            with localcontext() as ctx:
                ctx.prec = 34
                ranked = sorted((Decimal(row["features"]["spread_bps"]) - Decimal(row["features"]["momentum_bps"]),
                                 row["symbol"]) for row in rows if row["eligibility"] == "READY"
                                and row["features"]["momentum_bps"] is not None
                                and row["features"]["ask_size"] is not None)
            slice_ = {"cutoff": iso(cutoff), "rows": rows, "ranked_spot_symbols": [s for _, s in ranked]}
            yield {**slice_, "slice_digest": digest(slice_)}
    finally:
        db.c.rollback()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market_db", type=Path)
    parser.add_argument("start", type=instant)
    parser.add_argument("end", type=instant)
    parser.add_argument("--step-seconds", type=int, default=3600)
    parser.add_argument("--age-seconds", type=int, default=120)
    curated = parser.add_mutually_exclusive_group()
    curated.add_argument("--symbols", nargs="+")
    curated.add_argument("--watchlist-id")
    parser.add_argument("--watchlist-root", type=Path, help="data root containing saved watchlists; defaults to market_db parent")
    parser.add_argument("--venue", default="wallex")
    parser.add_argument("--store", choices=("live", "demo"), default="live")
    args = parser.parse_args()
    if args.watchlist_root is not None and args.watchlist_id is None:
        parser.error("--watchlist-root requires --watchlist-id")
    db = MarketDB(args.market_db, readonly=True)
    try:
        watchlist = load_watchlist(args.watchlist_root or args.market_db.parent, args.watchlist_id) if args.watchlist_id else None
        for item in market_panel(db, args.start, args.end, step_seconds=args.step_seconds, age_seconds=args.age_seconds,
                                 symbols=args.symbols, watchlist=watchlist, venue=args.venue, store=args.store):
            print(json.dumps(item, sort_keys=True, separators=(",", ":")))
    finally:
        db.c.close()


if __name__ == "__main__":
    main()
