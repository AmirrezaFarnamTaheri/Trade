"""Read-only verification of every stored trade and book side in a bounded receipt window."""
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal

from ..adapters.wallex import parse_channel
from ..domain.model import iso, levels, loads, parse_ts
from .market_quality import _raw_trade_keys, _verified_frames


def _depth_messages(frame, symbol):
    src = frame["src"]
    if src == f"rest:/v1/depth?symbol={symbol}":
        data = loads(frame["raw"])["result"]
        return {side: levels(data[side]) for side in ("bid", "ask")}
    sides = {}
    if src == "ws":
        for line in frame["raw"].splitlines():
            if not line.strip():
                continue
            push = loads(line).get("push") or {}
            channel = parse_channel(push.get("channel", ""))
            if channel and channel[:2] == ("depth", symbol) and "pub" in push:
                payload = push["pub"]["data"]
                sides[channel[2]] = levels(payload["message"] if isinstance(payload, dict) else payload)
    return sides


def _matches_side(raw, side, receipt, row):
    at, price, qty, depth = row
    if side not in raw or receipt > parse_ts(at):
        return False
    ordered = sorted(raw[side], key=lambda value: value[0], reverse=side == "bid")
    best = ordered[0] if ordered else (None, None)
    if best != (Decimal(price) if price is not None else None, Decimal(qty) if qty is not None else None):
        return False
    if depth is None:
        return True
    saved = json.loads(depth)[0 if side == "bid" else 1]
    return [(Decimal(p), Decimal(q)) for p, q in saved] == ordered[:len(saved)]


def audit_replay_inputs(db, roots, symbol, start, end, *, max_rows=10000):
    if not re.fullmatch(r"[A-Z0-9]{2,24}", symbol) or end <= start:
        raise ValueError("need a symbol and a nonempty receipt-time window")
    params = (f"wallex:{symbol}", iso(start), iso(end), max_rows + 1)
    where = "WHERE instrument_id=? AND ts_avail>=? AND ts_avail<? ORDER BY ts_avail,rowid LIMIT ?"
    trades = db.c.execute("SELECT seg_ref,instrument_id,ts_event,ts_avail,price,qty,aggressor FROM trades " + where, params).fetchall()
    side_columns = "NULL,NULL" if db.c.execute("PRAGMA user_version").fetchone()[0] == 6 else "bid_ref,ask_ref"
    tops = db.c.execute(f"SELECT ts_avail,bid,bid_qty,ask,ask_qty,depth,depth_ref,{side_columns} FROM book_top " + where,
                        params).fetchall()
    if max(len(trades), len(tops)) > max_rows:
        raise ValueError("window exceeds row bound; divide the receipt interval")
    expected_trades, expected_sides = defaultdict(Counter), defaultdict(list)
    for ref, *key in trades:
        expected_trades[ref][tuple(key)] += 1
    for at, bid, bid_qty, ask, ask_qty, depth, depth_ref, bid_ref, ask_ref in tops:
        # The old pointer tracked the last update across both sides. Count only sides found in
        # that exact instrument-labelled frame. Keep explicit side references authoritative.
        legacy_ref = depth_ref if bid_ref is None and ask_ref is None else None
        expected_sides[bid_ref or legacy_ref].append(("bid", (at, bid, bid_qty, depth), legacy_ref is not None))
        expected_sides[ask_ref or legacy_ref].append(("ask", (at, ask, ask_qty, depth), legacy_ref is not None))
    sequences, broken, unclosed = defaultdict(set), [], []
    for ref in expected_trades.keys() | expected_sides.keys():
        parts = re.fullmatch(r"([^#]+)#([0-9]{1,18})", ref or "")
        if not parts or str(int(parts[2])) != parts[2]:
            broken.append({"reason": "MISSING_OR_INVALID_REFERENCE"})
            continue
        sequences[parts[1]].add(int(parts[2]))
    manifest = {}
    for seg_id in sequences:
        row = db.c.execute("SELECT sha256,closed_at FROM segments WHERE seg_id=?", (seg_id,)).fetchone()
        if row:
            manifest[seg_id] = dict(sha256=row[0], closed_at=row[1])
    matched_trades = matched_sides = matched_legacy_sides = 0
    side_matches = {side: {"explicit": 0, "legacy": 0} for side in ("bid", "ask")}
    side_mismatches = []
    for seg_id, seq, frame in _verified_frames(roots, manifest, sequences, broken, unclosed):
        ref = f"{seg_id}#{seq}"
        try:
            if expected := expected_trades.get(ref):
                raw_trades = Counter(_raw_trade_keys(frame))
                matched_trades += (expected & raw_trades).total()
                if expected - raw_trades:
                    broken.append({"reason": "TRADE_CONTENT_MISMATCH", "ref": ref})
            if sides := expected_sides.get(ref):
                raw = _depth_messages(frame, symbol)
                receipt = parse_ts(frame["t"])
                prior_mismatches = len(side_mismatches)
                for side, row, legacy in sides:
                    if _matches_side(raw, side, receipt, row):
                        matched_sides += 1
                        matched_legacy_sides += legacy
                        side_matches[side]["legacy" if legacy else "explicit"] += 1
                    else:
                        side_mismatches.append({"ref": ref, "side": side, "book_receipt_at": row[0],
                                                "side_present_in_frame": side in raw})
                if len(side_mismatches) != prior_mismatches:
                    reason = "UNBOUND_REST_SYMBOL" if frame["src"] == "rest:/v1/depth" else "BOOK_SIDE_MISMATCH"
                    broken.append({"reason": reason, "ref": ref})
        except (ValueError, KeyError, IndexError, TypeError, ArithmeticError, AttributeError):
            broken.append({"reason": "INVALID_FRAME_CONTENT", "ref": ref})
    verified = bool(tops or trades) and not (broken or unclosed) and matched_trades == len(trades) and matched_sides == 2 * len(tops)
    return dict(schema="replay-input-audit/1", symbol=symbol, start=iso(start), end_exclusive=iso(end),
                scope="STORED_TRADES_AND_BOOK_SIDES_BY_RECEIPT", trade_rows=len(trades), book_rows=len(tops),
                trade_rows_matched=matched_trades, book_sides_matched=matched_sides,
                legacy_book_sides_matched=matched_legacy_sides, book_side_matches=side_matches,
                book_side_mismatches=side_mismatches, broken=broken,
                unclosed_segments=unclosed, verified=verified, qualified_for_replay=False)
