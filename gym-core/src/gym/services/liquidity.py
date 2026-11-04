"""Observed depth only: neither full-book completeness nor executable capacity."""
from decimal import Decimal

from ..domain.bars import qualified
from ..domain.model import book_top, iso


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
