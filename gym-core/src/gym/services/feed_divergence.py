"""Causal, bounded feed-divergence screen for paper entry-lock decisions."""
import re
from datetime import timedelta
from decimal import Decimal, localcontext

from ..domain.market_models import decimal
from ..domain.model import iso, parse_ts
from ..domain.strategy import digest

MAX_SAMPLES = 100000


def _quotes(rows, *, as_of):
    """Index strictly prior qualified public midpoints, preserving source gaps."""
    if type(rows) is not list or len(rows) > MAX_SAMPLES:
        raise ValueError("feed observations must be bounded")
    known, previous = {}, None
    for row in rows:
        if type(row) is not dict or set(row) != {"at", "mid", "qualified"}:
            raise ValueError("invalid reference feed row")
        at = parse_ts(row["at"])
        if previous is not None and at <= previous:
            raise ValueError("feed quotes must be strictly chronological")
        previous = at
        if type(row["qualified"]) is not bool:
            raise ValueError("feed quality must be explicitly boolean")
        if at < as_of and row["qualified"]:
            price = decimal(row["mid"], "feed midpoint", positive=True)
            known[at] = price
    return known


def evaluate_divergence(wallex, reference, *, symbol, as_of, training_samples=20,
                        alert_sigma=3, max_age_seconds=120):
    """Compare a fixed prior spread baseline with the latest matched quote.

    A mismatch *requires* an entry block in the paper advisory result but
    never changes a live order or claims that manually supplied feeds were
    independently authenticated.
    """
    if (type(symbol) is not str or re.fullmatch(r"[A-Z0-9]{2,24}", symbol) is None
            or as_of.tzinfo is None
            or type(training_samples) is not int or not 16 <= training_samples <= 10000
            or type(alert_sigma) is not int or not 2 <= alert_sigma <= 10
            or type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 600):
        raise ValueError("invalid bounded feed-divergence controls")
    base = _quotes(wallex, as_of=as_of)
    other = _quotes(reference, as_of=as_of)
    result = {
        "schema": "paper-feed-divergence/1", "symbol": symbol,
        "as_of_exclusive": iso(as_of), "training_samples_requested": training_samples,
        "status": "STALE_OR_UNAVAILABLE", "block_entry": True,
        "source_authenticated": False, "funded_authority": False,
        "deviation_bps": None, "threshold_bps": None,
        "current_matched_at": None, "baseline_samples": 0,
        "enforcement": "REQUIRES_SEPARATE_OPERATOR_ENTRY_LOCK",
        "limitations": [
            "Both sources must be independently authenticated to qualify a real feed-disagreement claim.",
            "The threshold comes from prior aligned available quotes, never the latest held-out pair.",
            "Missing/stale feeds fail closed as a recommended paper entry block, not a venue cancellation.",
            "An on-demand result alone is not an always-on authenticated monitor or a persisted trading rule.",
        ],
    }
    if (not base or not other
            or as_of - max(base) > timedelta(seconds=max_age_seconds)
            or as_of - max(other) > timedelta(seconds=max_age_seconds)):
        result["report_id"] = digest(result)[:16]
        return result
    pairs = sorted(set(base) & set(other))
    if len(pairs) < training_samples + 1:
        result["status"] = "INSUFFICIENT_MATCHED_HISTORY"
        result["report_id"] = digest(result)[:16]
        return result
    with localcontext() as context:
        context.prec = 70
        history = pairs[-(training_samples + 1):-1]
        current = pairs[-1]
        differences = [abs(base[at] - other[at]) / base[at] * 10000
                       for at in history]
        mu = sum(differences, Decimal(0)) / len(differences)
        stdev = (sum(((value - mu) ** 2 for value in differences), Decimal(0))
                 / (len(differences) - 1)).sqrt()
        threshold = max(Decimal(30), mu + alert_sigma * stdev)
        actual = abs(base[current] - other[current]) / base[current] * 10000
        result.update(
            status="DIVERGENT" if actual > threshold else "ALIGNED",
            block_entry=actual > threshold,
            current_matched_at=iso(current), baseline_samples=len(history),
            deviation_bps=str(+actual), threshold_bps=str(+threshold),
            baseline_mean_bps=str(+mu), baseline_stdev_bps=str(+stdev),
            alert_sigma=alert_sigma,
        )
    result["report_id"] = digest(result)[:16]
    return result
