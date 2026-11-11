"""Population-stability drift between a reference window and a recent window of one market (paper research only).

A paper result describes the market it was measured on. When a market's spread or one-minute return
distribution moves away from that window, the result stops describing it. The population stability index
(PSI) compares the two distributions over ten bins cut at the reference window's deciles:

    PSI = sum over bins of (recent share - reference share) * ln(recent share / reference share)

The bands are a common convention, not a law: below 0.10 stable, 0.10 to 0.25 moderate, above 0.25 shifted.
Quotes are qualified tops only; minutes with no quote are skipped, never filled.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from datetime import datetime
from itertools import pairwise

from ..domain.model import iso
from .data_portal import DataPortal

BINS = 10
FLOOR = 1e-4  # a share that is zero in one window would make the log infinite
BANDS = ((0.10, "STABLE"), (0.25, "MODERATE"))


def psi(reference: list[float], recent: list[float]) -> float | None:
    if len(reference) < 5 * BINS or len(recent) < 5 * BINS:
        return None  # too few points for ten bins to mean anything
    ordered = sorted(reference)
    cuts = sorted({ordered[int(len(ordered) * k / BINS)] for k in range(1, BINS)})

    def shares(values):
        counts = [0] * (len(cuts) + 1)
        for v in values:
            counts[bisect_right(cuts, v)] += 1
        return [max(c / len(values), FLOOR) for c in counts]
    return sum((b - a) * math.log(b / a) for a, b in zip(shares(reference), shares(recent)))


def band(value: float | None) -> str:
    if value is None:
        return "INSUFFICIENT_DATA"
    return next((name for limit, name in BANDS if value < limit), "SHIFTED")


def _features(portal: DataPortal, symbol: str, t0: datetime, t1: datetime) -> dict[str, list[float]]:
    spreads, minute_mid = [], {}
    for top in portal.tops(symbol, t0, t1):
        if top.bid is None or top.ask is None or top.bid <= 0 or top.ask <= top.bid or top.flags:
            continue
        mid = (top.bid + top.ask) / 2
        spreads.append(float((top.ask - top.bid) / mid * 10000))
        minute_mid[top.ts_avail.replace(second=0, microsecond=0)] = float(mid)  # last quote of each minute
    minutes = sorted(minute_mid)
    returns = [math.log(minute_mid[b] / minute_mid[a]) * 10000 for a, b in pairwise(minutes)
               if (b - a).total_seconds() == 60]
    return {"spread_bps": spreads, "return_bps_1min": returns}


def drift(portal: DataPortal, symbol: str, reference: tuple[datetime, datetime], recent: tuple[datetime, datetime]) -> dict:
    if not reference[0] < reference[1] <= recent[0] < recent[1]:
        raise ValueError("reference window must end before the recent window starts")
    ref, now = _features(portal, symbol, *reference), _features(portal, symbol, *recent)
    metrics = {}
    for name in ref:
        value = psi(ref[name], now[name])
        metrics[name] = {"psi": None if value is None else round(value, 4), "band": band(value),
                         "reference_points": len(ref[name]), "recent_points": len(now[name])}
    worst = max((m["psi"] for m in metrics.values() if m["psi"] is not None), default=None)
    return {"symbol": symbol, "reference": [iso(t) for t in reference], "recent": [iso(t) for t in recent],
            "metrics": metrics, "status": band(worst), "mode": "PAPER_ONLY",
            "note": "PSI bands are a convention; a SHIFTED market means earlier paper results may no longer describe it."}
