"""Observed depth only: neither full-book completeness nor executable capacity."""
from decimal import Decimal

from ..domain.bars import qualified
from ..domain.model import book_top, iso
from ..domain.market_models import fields, decimal, instant
from ..domain.strategy import digest


def liquidity_snapshot(sides, now, limits):
    top = book_top("", sides["bid"], sides["ask"], now, limits)
    report = {"status": "UNAVAILABLE", "bands": [], "funded_authority": False,
              "scope": "OBSERVED_LEVELS_ONLY", "flags": sorted(top.flags),
              "side_times": {name: iso(side.ts) if side else None for name, side in sides.items()},
              "level_counts": {name: len(side.levels) if side else 0 for name, side in sides.items()}}
    if not qualified(top):
        return report
    if any(len({p for p, _ in side.levels}) != len(side.levels) for side in sides.values()):
        report["flags"].append("DUPLICATE_PRICE")
        return report
    mid = (top.bid + top.ask) / 2
    for width in (10, 25, 50):
        band = Decimal(width) / 10000
        bids = [(p, q) for p, q in sides["bid"].levels if p >= mid * (1 - band)]
        asks = [(p, q) for p, q in sides["ask"].levels if p <= mid * (1 + band)]
        b = sum((q for _, q in bids), Decimal(0))
        a = sum((q for _, q in asks), Decimal(0))
        report["bands"].append({"width_bps": width, "bid_base": str(b), "ask_base": str(a),
                                "bid_quote": str(sum((p*q for p, q in bids), Decimal(0))),
                                "ask_quote": str(sum((p*q for p, q in asks), Decimal(0))),
                                "imbalance": str(((b-a)/(b+a)).quantize(Decimal("0.00000001"))) if b+a else None})
    report["status"] = "AVAILABLE"
    return report


def audit_depth(request):
    """Validate supplied sequenced depth; Wallex's unsequenced side snapshots are not relabeled."""
    fields(request, "source_id as_of max_age_seconds max_levels frames")
    source, frames = request["source_id"], request["frames"]
    if type(source) is not str or not 1 <= len(source) <= 96:
        raise ValueError("need a bounded source identity")
    for name, low, high in (("max_age_seconds", 1, 3600), ("max_levels", 1, 200)):
        if type(request[name]) is not int or not low <= request[name] <= high:
            raise ValueError(f"{name} must be {low}..{high}")
    if type(frames) is not list or not 1 <= len(frames) <= 500:
        raise ValueError("need 1..500 supplied depth frames")
    cutoff = instant(request["as_of"])
    bids, asks, events = {}, {}, []
    sequence = last_seen = None
    last_receipt = valid_at = None
    previous_digest = None
    updates, future = 0, 0
    for frame in frames:
        fields(frame, "kind sequence previous_sequence event_at observed_at bids asks")
        seq, prior, kind = frame["sequence"], frame["previous_sequence"], frame["kind"]
        if type(seq) is not int or not 0 <= seq <= 2**63 - 1 or kind not in ("SNAPSHOT", "DELTA"):
            raise ValueError("invalid depth sequence or kind")
        if (kind == "SNAPSHOT" and prior is not None) or (kind == "DELTA" and (type(prior) is not int or not 0 <= prior < seq)):
            raise ValueError("snapshot has no predecessor; delta needs an earlier sequence")
        event_at, receipt = instant(frame["event_at"]), instant(frame["observed_at"])
        if event_at > receipt or (last_receipt is not None and receipt < last_receipt):
            raise ValueError("depth receipt clocks must be monotone and follow event time")
        last_receipt = receipt
        sides = []
        for name in ("bids", "asks"):
            levels = frame[name]
            if type(levels) is not list or len(levels) > 400:
                raise ValueError("depth frame side exceeds update bound")
            parsed = {}
            for level in levels:
                if type(level) is not list or len(level) != 2:
                    raise ValueError("depth level requires price and quantity")
                price, quantity = decimal(level[0], "price", positive=True), decimal(level[1], "quantity")
                if price in parsed or (kind == "SNAPSHOT" and not quantity):
                    raise ValueError("duplicate price or zero snapshot quantity")
                parsed[price] = quantity
            sides.append(parsed)
            updates += len(levels)
        if updates > 50000:
            raise ValueError("depth update budget exceeded")
        if receipt >= cutoff:
            future += 1
            continue
        fingerprint = digest(frame)
        if seq == sequence and fingerprint == previous_digest:
            events.append({"sequence": seq, "status": "DUPLICATE_IGNORED"})
            continue
        reason = ("NONINCREASING_SEQUENCE" if last_seen is not None and seq <= last_seen else
                  "MISSING_PREDECESSOR" if kind == "DELTA" and (sequence is None or prior != sequence) else None)
        last_seen = max(seq, last_seen) if last_seen is not None else seq
        left, right = ({}, {}) if kind == "SNAPSHOT" else (bids.copy(), asks.copy())
        if reason is None:
            for book, changes in zip((left, right), sides):
                for price, quantity in changes.items():
                    if quantity:
                        book[price] = quantity
                    else:
                        book.pop(price, None)
            reason = ("LEVEL_BOUND_EXCEEDED" if max(len(left), len(right)) > request["max_levels"] else
                      "EMPTY_OR_CROSSED_BOOK" if not left or not right or max(left) >= min(right) else None)
        if reason:
            bids, asks, sequence, valid_at, previous_digest = {}, {}, None, None, None
            events.append({"sequence": seq, "status": "NEEDS_SNAPSHOT", "reason": reason})
        else:
            bids, asks, sequence, valid_at, previous_digest = left, right, seq, receipt, fingerprint
            events.append({"sequence": seq, "status": "ACCEPTED", "kind": kind})
    age = (cutoff - valid_at).total_seconds() if valid_at else None
    status = "NEEDS_SNAPSHOT" if sequence is None else "STALE" if age > request["max_age_seconds"] else "AVAILABLE"
    return {"schema": "depth-audit/1", "source_id": source, "as_of_exclusive": iso(cutoff), "status": status,
            "events": events, "future_frames_excluded": future, "sequence": sequence, "age_seconds": age,
            "best_bid": str(max(bids)) if status == "AVAILABLE" else None,
            "best_ask": str(min(asks)) if status == "AVAILABLE" else None,
            "bid_levels": len(bids), "ask_levels": len(asks), "input_digest": digest(request),
            "observations_authenticated": False, "funded_authority": False,
            "limitations": ["Supplied sequenced frames only; no source authentication, full-book or queue-position proof.",
                           "No level truncation or stale carry; invalid continuity requires a strictly newer snapshot.",
                           "Current Wallex side snapshots expose no verified sequence and are not treated as deltas."]}
