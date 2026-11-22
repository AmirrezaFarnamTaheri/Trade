"""Export bounded, point-in-time market features from a TradingGYM archive."""

import argparse
import json
from datetime import timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from gym.adapters.store import MarketDB
from gym.domain.bars import qualified
from gym.domain.market_models import instant
from gym.domain.model import BookTop, iso
from gym.domain.rules import is_closed
from gym.domain.strategy import digest
from gym.services.data_portal import DataPortal
from gym.services.historical_universe import universe_manifest
from gym.services.rules import RuleService

FEATURES = {
    "bid": "quote per base",
    "ask": "quote per base",
    "bid_size": "base",
    "ask_size": "base",
    "spread_bps": "bps of current midpoint",
    "momentum_bps": "bps of midpoint return in native quote currency",
}


def _latest_quote(db, symbol, cutoff, age):
    row = db.c.execute("""
        SELECT ts_avail, bid, ask, bid_qty, ask_qty, flags
        FROM book_top
        WHERE instrument_id = ? AND ts_avail >= ? AND ts_avail < ?
        ORDER BY ts_avail DESC, rowid DESC LIMIT 1
        """, (f"wallex:{symbol}", iso(cutoff - age), iso(cutoff))).fetchone()
    if row is None:
        return None
    at, bid, ask, bid_size, ask_size, flags = row
    return BookTop(symbol, instant(at), *(Decimal(value) if value is not None else None
                                         for value in (bid, ask, bid_size, ask_size)),
                   frozenset(filter(None, (flags or "").split(","))))


def _usable(quote):
    return quote is not None and qualified(quote) and "CLOSED" not in quote.flags


def _feature_row(inst, metadata, last_top, past, *, fresh, closed):
    top = last_top if fresh else None
    spec = metadata["raw"] if metadata else {}
    spot = spec.get("is_spot")
    reason = ("SPOT_NOT_CONFIRMED" if spot is not True else "CLOSED" if closed
              else "NO_FRESH_QUOTE" if top is None else "UNQUALIFIED_QUOTE" if not _usable(top)
              else "READY")
    bid = ask = bid_qty = ask_qty = spread = momentum = None
    if _usable(top) and not closed:
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
            "features": {key: str(value) if value is not None else None for key, value in values.items()}}


def _candidate_symbols(db, start, end, symbols):
    if symbols is not None:
        return [row["symbol"] for row in universe_manifest(
            db, {"as_of": iso(start), "lookback_seconds": 86400, "symbols": symbols}, store="live")["markets"]]
    rows = db.c.execute("""
        SELECT instrument_id FROM instrument_specs WHERE instrument_id GLOB 'wallex:*' AND valid_from < ?
        UNION
        SELECT instrument_id FROM book_top WHERE instrument_id GLOB 'wallex:*' AND ts_avail < ?
        ORDER BY instrument_id LIMIT 1001
        """, (iso(end), iso(end))).fetchall()
    if len(rows) > 1000:
        raise ValueError("market panel exceeds 1000 candidate instruments")
    return [row[0][7:] for row in rows]


def market_panel(db, start, end, *, step_seconds, age_seconds=120, symbols=None):
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
        candidates = _candidate_symbols(db, start, end, symbols)
        if count * len(candidates) > 250_000:
            raise ValueError("market panel exceeds 250000 instrument-cutoff pairs")
        portal, service = DataPortal(db), RuleService(db)
        instruments = {s: portal.instrument(s) for s in candidates}
        config = {"schema": "market-panel/1", "mode": "WHOLE" if symbols is None else "CURATED",
                  "from": iso(start), "to_exclusive": iso(end), "step_seconds": step_seconds,
                  "max_quote_age_seconds": age_seconds, "requested_symbols": sorted(symbols or []),
                  "features": FEATURES, "rank_score": "momentum_bps minus quoted spread_bps",
                  "catalogue_completeness": "UNKNOWN", "authority": "PAPER_ONLY"}
        yield {**config, "config_digest": digest(config)}
        for index in range(count):
            cutoff = start + index * step
            rules = service.load(cutoff)[1]
            past_rules = service.load(cutoff - step)[1]
            rows = []
            for symbol, inst in instruments.items():
                metadata = portal.metadata_at(symbol, cutoff)
                top = _latest_quote(db, symbol, cutoff, timedelta(days=1))
                if symbols is None and metadata is None and top is None:
                    continue
                fresh = top is not None and cutoff - top.ts_avail <= age
                past = _latest_quote(db, symbol, cutoff - step, age) if fresh and _usable(top) else None
                if past and is_closed(past_rules, inst, cutoff - step):
                    past = None
                rows.append(_feature_row(inst, metadata, top, past, fresh=fresh, closed=is_closed(rules, inst, cutoff)))
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
    parser.add_argument("--symbols", nargs="+")
    args = parser.parse_args()
    db = MarketDB(args.market_db, readonly=True)
    try:
        for item in market_panel(db, args.start, args.end, step_seconds=args.step_seconds,
                                 age_seconds=args.age_seconds, symbols=args.symbols):
            print(json.dumps(item, sort_keys=True, separators=(",", ":")))
    finally:
        db.c.close()


if __name__ == "__main__":
    main()
