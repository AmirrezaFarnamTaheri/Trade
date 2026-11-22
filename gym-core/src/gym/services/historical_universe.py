"""Causal top-volume research universe from trade receipts strictly before selection."""
import json
import re
from datetime import timedelta
from decimal import Decimal

from ..domain.market_models import fields, instant
from ..domain.model import iso
from ..domain.strategy import digest
from .data_portal import DataPortal, validate_venue


def _observed_receipts(db, prefix, begin, end):
    # Seek each instrument key and then its latest receipt instead of scanning all of its book rows.
    return {key[len(prefix):]: receipt for key, receipt in db.c.execute("""
        WITH RECURSIVE keys(symbol_key) AS (
            SELECT min(instrument_id) FROM book_top WHERE instrument_id >= :prefix
            UNION ALL
            SELECT (SELECT min(instrument_id) FROM book_top WHERE instrument_id > keys.symbol_key)
            FROM keys WHERE symbol_key GLOB :scope
        ), recent AS (
            SELECT symbol_key, (SELECT max(ts_avail) FROM book_top
                WHERE instrument_id = keys.symbol_key AND ts_avail >= :begin AND ts_avail <= :end) AS receipt
            FROM keys WHERE symbol_key GLOB :scope
        )
        SELECT symbol_key, receipt FROM recent WHERE receipt IS NOT NULL
        """, {"prefix": prefix, "scope": prefix + "*", "begin": begin, "end": end})}


def universe_manifest(db, request, *, store, watchlist=None, venue="wallex"):
    """Resolve one decision cutoff from effective specs and observed receipt history."""
    fields(request, "as_of lookback_seconds" + (" symbols" if isinstance(request, dict) and "symbols" in request else ""))
    cutoff = instant(request["as_of"])
    prefix = validate_venue(venue) + ":"
    if watchlist is not None:
        from .market_watchlists import watchlist_at

        if "symbols" in request:
            raise ValueError("watchlist_id and symbols are mutually exclusive")
        request = {**request, "symbols": watchlist_at(watchlist, cutoff)["symbols"]}
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
            "SELECT instrument_id, valid_from, spec FROM instrument_specs WHERE instrument_id GLOB ? "
            "AND valid_from<=? AND (valid_to IS NULL OR valid_to>?) ORDER BY instrument_id, valid_from DESC",
            (prefix + "*", end, end)):
        specs.setdefault(instrument[len(prefix):], (version, raw))
    observed = _observed_receipts(db, prefix, begin, end)
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
              "markets": rows, "funded_authority": False, **({"venue": venue} if venue != "wallex" else {}),
              **({"watchlist": watchlist} if watchlist is not None else {})}
    return {**result, "manifest_id": digest(result)}


def whole_spot_selection(db, cutoff, *, store, watchlist=None, venue="wallex"):
    """Resolve the discovered universe to the spot ledger's supported inputs."""
    manifest = universe_manifest(db, {"as_of": iso(cutoff), "lookback_seconds": 86400}, store=store,
                                 watchlist=watchlist, venue=venue)
    portal = DataPortal(db, venue=venue)
    symbols, excluded = [], {}
    for row in manifest["markets"]:
        symbol = row["symbol"]
        if row["products"]["spot"] is not True:
            excluded[symbol] = "SPOT_NOT_CONFIRMED"
        elif venue == "wallex" and portal.instrument(symbol).quote not in ("TMN", "USDT"):
            excluded[symbol] = "UNSUPPORTED_QUOTE"
        elif venue != "wallex" and not db.c.execute(
                "SELECT 1 FROM instruments WHERE instrument_id=? AND kind='SPOT'", (portal.instrument_key(symbol),)).fetchone():
            excluded[symbol] = "MISSING_SPOT_INSTRUMENT_TERMS"
        else:
            symbols.append(symbol)
    return {"schema": "whole-spot-universe/1", "manifest_id": manifest["manifest_id"],
            "coverage": manifest["coverage"], "excluded": excluded, "symbols": symbols, "store": store,
            **({"venue": venue} if venue != "wallex" else {})}


def whole_window_spot_selection(db, start, end, *, store, watchlist=None, venue="wallex"):
    """Freeze all confirmed spot availability intervals within the replay window."""
    opening = whole_spot_selection(db, start, store=store, watchlist=watchlist, venue=venue)
    requested = set(watchlist["symbols"]) if watchlist is not None else None
    start_at, end_at = iso(start), iso(end)
    windows, previous_end = {}, {}
    rows = db.c.execute("""SELECT s.instrument_id, s.valid_from, s.valid_to, json_type(s.spec, '$.is_spot')
        FROM instrument_specs s LEFT JOIN instruments i USING (instrument_id)
        WHERE s.instrument_id GLOB ?
          AND ((?='wallex' AND (i.quote IN ('TMN','USDT') OR (i.quote IS NULL AND
               (s.instrument_id GLOB '*TMN' OR s.instrument_id GLOB '*USDT'))))
               OR (?<>'wallex' AND i.kind='SPOT'))
          AND s.valid_from<? AND (s.valid_to IS NULL OR s.valid_to>?)
        ORDER BY s.instrument_id,s.valid_from,s.rowid""", (venue + ":*", venue, venue, end_at, start_at))
    for instrument, begin, through, spot in rows:
        symbol = instrument[len(venue) + 1:]
        if requested is not None and symbol not in requested:
            continue
        begin, through = max(start_at, begin), min(end_at, through or end_at)
        if through <= begin:
            continue
        if previous_end.get(symbol, start_at) > begin:
            raise ValueError(f"overlapping catalogue revisions for {symbol}")
        previous_end[symbol] = through
        if spot != "true":
            continue
        intervals = windows.setdefault(symbol, [])
        if intervals and intervals[-1][1] == begin:
            intervals[-1][1] = through
        else:
            intervals.append([begin, through])
    symbols = sorted(windows)
    if venue == "wallex" and watchlist is None and symbols == opening["symbols"] and all(
            value == [[start_at, end_at]] for value in windows.values()):
        return opening
    return {**opening, "schema": "whole-spot-universe/2" if watchlist is None else "watchlist-spot-universe/1",
            **({"watchlist": watchlist} if watchlist is not None else {}), "symbols": symbols,
            "start_symbols": opening["symbols"], "coverage": {**opening["coverage"], "spot_during_window": len(symbols)},
            "excluded": {s: reason for s, reason in opening["excluded"].items() if s not in windows},
            "entry_windows": {s: value for s, value in windows.items() if value != [[start_at, end_at]]}}


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
