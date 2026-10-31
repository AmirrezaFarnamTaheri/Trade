"""DATA-05 cross-check: internal LAST bars built from collected trades against the venue's own candles."""
from datetime import datetime, timedelta
from decimal import Decimal

from ..domain.bars import BarSpec, trade_bars
from ..domain.model import iso
from .data_portal import DataPortal

HEARTBEAT_COVERAGE = timedelta(seconds=70)  # collector heartbeat is 60 s: a row this close means it was listening


def bps(a: Decimal, b: Decimal) -> Decimal:
    return abs(a - b) / b * 10000


def candle_crosscheck(portal: DataPortal, symbol: str, start: datetime, end: datetime, *,
                      resolution: str = "1min", tolerance_bps: Decimal = Decimal(10)) -> dict:
    """Per period: AGREE / DIVERGENT (any OHLC beyond tolerance) / MISSING_INTERNAL (venue traded while we
    listened, we saw nothing) / MISSING_VENUE / NOT_COVERED (collector not running). Venue candles still forming
    when fetched, and zero-volume candles (carried prices), are not compared."""
    if not start < end:
        raise ValueError("inverted or empty cross-check range")
    spec = BarSpec(resolution, "LAST")
    internal = {b.start: b for b in trade_bars(symbol, spec, portal.trades_by_event(symbol, start, end), end)}
    venue = {k["t"]: k for k in portal.venue_candles(symbol, resolution, start, end)
             if k["v"] > 0 and k["t"] + spec.step <= k["fetched_at"]}
    rows = []
    for t in sorted(set(internal) | set(venue)):
        mine, theirs = internal.get(t), venue.get(t)
        row = {"t": iso(t)}
        if mine and theirs:
            diff = {k: bps(getattr(mine, f), theirs[k])
                    for k, f in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))}
            worst = max(diff.values())
            row |= {"status": "AGREE" if worst <= tolerance_bps else "DIVERGENT",
                    "worst_bps": str(worst.quantize(Decimal("0.01"))),
                    "internal": [str(mine.open), str(mine.high), str(mine.low), str(mine.close), str(mine.volume)],
                    "venue": [str(theirs[k]) for k in "ohlcv"]}
        elif theirs:
            covered = portal.observed(symbol, t - HEARTBEAT_COVERAGE, t + spec.step + HEARTBEAT_COVERAGE)
            row |= {"status": "MISSING_INTERNAL" if covered else "NOT_COVERED", "venue": [str(theirs[k]) for k in "ohlcv"]}
        else:
            row |= {"status": "MISSING_VENUE", "internal": [str(mine.open), str(mine.high), str(mine.low),
                                                           str(mine.close), str(mine.volume)]}
        rows.append(row)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"symbol": symbol, "resolution": resolution, "from": iso(start), "to_exclusive": iso(end),
            "tolerance_bps": str(tolerance_bps), "counts": counts, "periods": rows,
            "limitations": ["Internal bars use venue event time; trade identity is (time, price, qty, side), so identical "
                            "prints in one second collapse and internal volume can be lower.",
                            "MISSING_VENUE can be a venue candle not yet fetched, not only a venue omission."]}
