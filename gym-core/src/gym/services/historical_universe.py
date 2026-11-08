"""Causal top-volume research universe from trade receipts strictly before selection."""
import re
from datetime import timedelta
from decimal import Decimal

from ..domain.model import iso
from ..domain.strategy import digest


def select_universe(db, start, *, quote_currency, top_n, lookback_hours=24):
    """Select by historical observed trade quote-notional, never today's market list."""
    if quote_currency not in ("USDT", "TMN") or type(top_n) is not int or not 1 <= top_n <= 20:
        raise ValueError("need 1..20 historical markets and a known quote currency")
    if type(lookback_hours) is not int or not 1 <= lookback_hours <= 744:
        raise ValueError("historical universe lookback must be 1..744 hours")
    begin = start - timedelta(hours=lookback_hours)
    # Cap source rows before materializing. The receipt time is the information clock.
    records = db.c.execute(
        "SELECT instrument_id,ts_avail,price,qty FROM trades "
        "WHERE ts_avail>=? AND ts_avail<? ORDER BY ts_avail,rowid LIMIT 100001",
        (iso(begin), iso(start)),
    ).fetchall()
    if len(records) > 100000:
        raise ValueError("historical universe selection exceeds observation budget")
    volume, source_rows = {}, {}
    for iid, available, price, qty in records:
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
