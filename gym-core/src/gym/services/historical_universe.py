"""Causal top-volume research universe from trade receipts strictly before selection."""
import json
import re
from datetime import timedelta
from decimal import Decimal

from ..domain.market_models import fields, instant
from ..domain.model import iso
from ..domain.strategy import digest


def universe_manifest(db, request, *, store):
    """Resolve one decision cutoff from effective specs and observed receipt history."""
    fields(request, "as_of lookback_seconds" + (" symbols" if isinstance(request, dict) and "symbols" in request else ""))
    cutoff = instant(request["as_of"])
    seconds = request["lookback_seconds"]
    if type(seconds) is not int or not 1 <= seconds <= 86400:
        raise ValueError("lookback_seconds must be 1..86400")
    curated = request.get("symbols", [])
    if "symbols" in request and (type(curated) is not list or not 1 <= len(curated) <= 1000
            or any(type(s) is not str or not re.fullmatch(r"[A-Z0-9]{2,32}", s) for s in curated)
            or len(set(curated)) != len(curated)):
        raise ValueError("symbols must be a nonempty list of distinct market symbols")
    end, begin = iso(cutoff), iso(cutoff - timedelta(seconds=seconds))
    specs = {}
    for instrument, version, raw in db.c.execute(
            "SELECT instrument_id, valid_from, spec FROM instrument_specs WHERE instrument_id GLOB 'wallex:*' "
            "AND valid_from<=? AND (valid_to IS NULL OR valid_to>?) ORDER BY instrument_id, valid_from DESC",
            (end, end)):
        specs.setdefault(instrument[7:], (version, raw))
    observed = {instrument[7:]: received for instrument, received in db.c.execute(
        "SELECT instrument_id, max(ts_avail) FROM book_top WHERE instrument_id GLOB 'wallex:*' "
        "AND ts_avail>=? AND ts_avail<=? GROUP BY instrument_id", (begin, end))}
    known = specs.keys() | observed.keys()
    unknown = sorted(set(curated) - known)
    if unknown:
        raise ValueError(f"unknown markets at cutoff: {', '.join(unknown)}")
    rows = []
    for symbol in sorted(curated or known):
        version, raw = specs.get(symbol, (None, "{}"))
        terms = json.loads(raw)
        products = {product: terms.get(f"is_{product}") for product in ("spot", "margin", "otc")}
        rows.append({"symbol": symbol, "spec_effective_from": version, "spec_digest": digest(terms) if version else None,
                     "last_quote_receipt": observed.get(symbol), "products": products,
                     "status": "OBSERVED" if symbol in observed else "NO_RECENT_QUOTE"})
    result = {"schema": "universe-manifest/1", "as_of": end, "receipt_from": begin, "store": store,
              "mode": "CURATED" if curated else "WHOLE", "requested_symbols": sorted(curated),
              "coverage": {"resolved": len(rows), "with_effective_spec": sum(r["spec_effective_from"] is not None for r in rows),
                           "observed": sum(r["status"] == "OBSERVED" for r in rows), "catalogue_completeness": "UNKNOWN"},
              "markets": rows, "funded_authority": False}
    return {**result, "manifest_id": digest(result)}


def whole_spot_selection(db, cutoff, *, store):
    """Resolve the whole discovered universe to the spot ledger's supported inputs."""
    from .data_portal import DataPortal

    manifest = universe_manifest(db, {"as_of": iso(cutoff), "lookback_seconds": 86400}, store=store)
    portal = DataPortal(db)
    symbols, excluded = [], {}
    for row in manifest["markets"]:
        symbol = row["symbol"]
        if row["products"]["spot"] is not True:
            excluded[symbol] = "SPOT_NOT_CONFIRMED"
        elif portal.instrument(symbol).quote not in ("TMN", "USDT"):
            excluded[symbol] = "UNSUPPORTED_QUOTE"
        else:
            symbols.append(symbol)
    return {"schema": "whole-spot-universe/1", "manifest_id": manifest["manifest_id"],
            "coverage": manifest["coverage"], "excluded": excluded, "symbols": symbols, "store": store}


def select_universe(db, start, *, quote_currency, top_n, lookback_hours=24):
    """Select by historical observed trade quote-notional, never today's market list."""
    if quote_currency not in ("USDT", "TMN") or type(top_n) is not int or not 1 <= top_n <= 20:
        raise ValueError("need 1..20 historical markets and a known quote currency")
    if type(lookback_hours) is not int or not 1 <= lookback_hours <= 744:
        raise ValueError("historical universe lookback must be 1..744 hours")
    begin = start - timedelta(hours=lookback_hours)
    # Filter venue and quote before applying the observation budget.
    records = db.c.execute(
        "SELECT instrument_id,ts_avail,price,qty FROM trades "
        "WHERE instrument_id GLOB ? AND ts_avail>=? AND ts_avail<? "
        "ORDER BY ts_avail,rowid LIMIT 100001",
        ("wallex:*" + quote_currency, iso(begin), iso(start)),
    )
    volume, source_rows = {}, {}
    for index, (iid, available, price, qty) in enumerate(records):
        if index >= 100000:
            raise ValueError("historical universe selection exceeds observation budget")
        if not iid.startswith("wallex:"):
            continue
        symbol = iid[7:]
        if (not re.fullmatch(r"[A-Z0-9]{2,24}", symbol)
                or not symbol.endswith(quote_currency) or len(symbol) <= len(quote_currency)):
            continue
        try:
            px, quantity = Decimal(price), Decimal(qty)
        except (ValueError, TypeError, ArithmeticError):
            continue
        if not px.is_finite() or not quantity.is_finite() or px <= 0 or quantity <= 0:
            continue
        volume[symbol] = volume.get(symbol, Decimal(0)) + px * quantity
        source_rows.setdefault(symbol, []).append((available, price, qty))
    ranked = sorted(volume, key=lambda symbol: (-volume[symbol], symbol))
    chosen = ranked[:top_n]
    selection = {"schema": "as-of-volume-universe/1", "as_of_exclusive": iso(start),
                 "receipt_from": iso(begin), "quote_currency": quote_currency,
                 "lookback_hours": lookback_hours, "requested_top_n": top_n,
                 "status": "AVAILABLE" if len(chosen) == top_n else "INSUFFICIENT_DATA",
                 "symbols": chosen,
                 "ranked": [{"symbol": s, "volume_quote": str(volume[s]),
                             "trade_receipts": len(source_rows[s])} for s in chosen],
                 "source_digest": digest([(s, source_rows[s]) for s in ranked]),
                 "basis": "Observed trade price * quantity from receipts strictly before the start.",
                 "survivorship_free_listing_census": False, "funded_authority": False}
    return selection


def collection_status(db, symbols, end, *, max_age_seconds=120):
    """Flag stopped/gapped collection without claiming a venue delisted a market."""
    result = {}
    for symbol in symbols:
        row = db.c.execute(
            "SELECT MAX(ts_avail) FROM book_top WHERE instrument_id=? AND ts_avail<?",
            ("wallex:" + symbol, iso(end)),
        ).fetchone()
        last = row[0]
        from ..domain.model import parse_ts

        age = (end - parse_ts(last)).total_seconds() if last else None
        result[symbol] = {"last_receipt_before_end": last, "age_seconds": age,
                          "status": "CURRENT" if age is not None and age <= max_age_seconds
                          else "COLLECTION_GAP_OR_STOPPED",
                          "delisted": None}
    return result
