"""Verify a candidate legacy bid or ask against a contiguous raw frame chain."""
import argparse
import hashlib
import json
from pathlib import Path

from gym.adapters.store import MarketDB, iter_segment
from gym.domain.model import iso, parse_ts
from gym.services.market_quality import _find_segment_file
from gym.services.replay_input_audit import _depth_messages, _matches_side


def verify(db, roots, symbol, receipt, side, first, segments):
    if side not in {"bid", "ask"} or len(set(segments)) != len(segments) or not 1 <= len(segments) <= 8:
        raise ValueError("expected one side and distinct ordered archive segments")
    rows = db.c.execute(
        "SELECT ts_avail, bid, bid_qty, ask, ask_qty, depth, depth_ref FROM book_top "
        "WHERE instrument_id=? AND ts_avail=? LIMIT 2", (f"wallex:{symbol}", iso(receipt))).fetchall()
    if len(rows) != 1 or not rows[0][-1]:
        raise ValueError("expected one legacy book receipt with an archive pointer")
    at, bid, bid_qty, ask, ask_qty, depth, ref = rows[0]
    anchor_segment, anchor_number = ref.rsplit("#", 1)
    anchor = int(anchor_number)
    if (first is not None and (not 0 <= first <= anchor or anchor - first >= 100_000)) or segments[-1] != anchor_segment:
        raise ValueError("invalid chain bounds or anchor segment")
    scan_start = max(0, anchor - 99_999) if first is None else first
    expected = first
    price, qty = (bid, bid_qty) if side == "bid" else (ask, ask_qty)
    candidate_ref = None
    candidate_matches = False
    first_candidate = first
    previous_sequence = None
    for segment in segments:
        path = _find_segment_file(segment, roots)
        record = db.c.execute("SELECT sha256,closed_at FROM segments WHERE seg_id=?", (segment,)).fetchone()
        if path is None or not record or not record[1]:
            raise ValueError(f"missing closed segment {segment}")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != record[0]:
                raise ValueError(f"segment digest mismatch {segment}")
        for frame in iter_segment(path):
            sequence = frame["seq"]
            if sequence < scan_start:
                continue
            if sequence > anchor:
                break
            if previous_sequence is not None and sequence <= previous_sequence:
                raise ValueError("raw frames must have strictly increasing sequence numbers")
            previous_sequence = sequence
            stamp = parse_ts(frame["t"])
            if stamp > receipt:
                raise ValueError("frame arrived after the saved book receipt")
            decoded = _depth_messages(frame, symbol)
            if first is None:
                if side in decoded:
                    first_candidate = sequence
                    expected = sequence
                elif expected is None:
                    continue
            if sequence != expected or hashlib.sha256(frame["raw"].encode()).hexdigest() != frame["sha256"]:
                raise ValueError(f"raw chain gap or bad frame at sequence {expected}")
            if sequence == first_candidate:
                candidate_matches = _matches_side(decoded, side, stamp, (at, price, qty, depth))
                candidate_ref = f"{segment}#{sequence}"
            elif side in decoded:
                raise ValueError(f"later {side} update at sequence {sequence}")
            if sequence == anchor:
                opposite = "ask" if side == "bid" else "bid"
                op_price, op_qty = (ask, ask_qty) if opposite == "ask" else (bid, bid_qty)
                if segment != anchor_segment or not _matches_side(decoded, opposite, stamp, (at, op_price, op_qty, depth)):
                    raise ValueError("legacy pointer does not verify the opposite book side")
            expected += 1
    if expected != anchor + 1:
        raise ValueError(f"raw chain ends before legacy pointer at sequence {anchor}")
    if not candidate_matches:
        raise ValueError("candidate does not match the stored book side")
    return {"symbol": symbol, "book_receipt_at": at, "side": side, "candidate_ref": candidate_ref,
            "legacy_ref": ref, "verified_frames": expected - first_candidate, "status": "VERIFIED_FRAME_CHAIN"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market_db", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("symbol")
    parser.add_argument("receipt", type=parse_ts)
    parser.add_argument("side", choices=("bid", "ask"))
    parser.add_argument("first", type=lambda value: None if value == "auto" else int(value))
    parser.add_argument("segments", nargs="+")
    args = parser.parse_args()
    db = MarketDB(args.market_db, readonly=True)
    try:
        db.c.execute("BEGIN")
        result = verify(db, [args.archive], args.symbol, args.receipt, args.side, args.first, args.segments)
    finally:
        db.c.close()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
