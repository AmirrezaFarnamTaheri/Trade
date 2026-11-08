"""Causal bucket-level quote coverage; missing data is never assumed to be a venue closure."""
from bisect import bisect_right
from collections import defaultdict
from decimal import Decimal

from ..domain.bars import BarSpec, qualified
from ..domain.market_models import decimal
from ..domain.model import iso, parse_ts
from ..domain.rules import is_closed
from .data_portal import DataPortal
from .rules import RuleService


def quote_coverage(db, symbol, start, end, resolution, *, max_bad_share=None):
    """Count eligible open decision buckets, missing/invalid/stale receipts, and abstain."""
    spec = BarSpec(resolution)
    if spec.resolution == "session" or not start < end:
        raise ValueError("quality gate requires a positive fixed-bar historical window")
    if max_bad_share is not None:
        limit = decimal(max_bad_share, "maximum bad share")
        if limit > 1:
            raise ValueError("maximum bad share exceeds one")
    else:
        limit = None
    origin, buckets = spec.bucket(start), []
    at = origin
    while at < end:
        if len(buckets) >= 5000:
            raise ValueError("quality gate exceeds 5000 decision buckets")
        buckets.append(at)
        at += spec.step
    if not buckets:
        raise ValueError("quality gate has no eligible decision intervals")
    if db.c.execute("SELECT count(*) FROM (SELECT 1 FROM book_top WHERE instrument_id=? "
                    "AND ts_avail>=? AND ts_avail<? LIMIT 100001)",
                    ("wallex:" + symbol, iso(start), iso(end))).fetchone()[0] > 100000:
        raise ValueError("quality gate observation budget exceeded")
    portal, rules = DataPortal(db), RuleService(db)
    instrument = portal.instrument(symbol)
    rows = defaultdict(list)
    for quote in portal.tops(symbol, start, end):
        rows[spec.bucket(quote.ts_avail)].append(quote)
    counts = {"OBSERVED": 0, "MISSING": 0, "STALE_OR_INVALID": 0, "VENUE_CLOSED": 0}
    rule_times, rule_cache = [], {}
    for (stamp,) in db.c.execute("SELECT ts FROM regime_events ORDER BY seq"):
        at = parse_ts(stamp)
        rule_times.append(max(at, rule_times[-1]) if rule_times else at)

    def rules_at(at):
        """Load each causal rule-event prefix only once."""
        version = bisect_right(rule_times, at)
        if version not in rule_cache:
            rule_cache[version] = rules.load(at)[1]
        return rule_cache[version]

    for beginning in buckets:
        boundary = min(beginning + spec.step, end)
        # Only a causally effective venue rule can suppress an expected open-market bucket.
        if is_closed(rules_at(beginning), instrument, beginning):
            counts["VENUE_CLOSED"] += 1
            continue
        samples = rows[beginning]
        if not samples:
            counts["MISSING"] += 1
            continue
        recent = [q for q in samples if qualified(q) and boundary >= q.ts_avail
                  and (boundary - q.ts_avail).total_seconds() <= 120]
        if not recent:
            counts["STALE_OR_INVALID"] += 1
        else:
            counts["OBSERVED"] += 1
    eligible = sum(counts[k] for k in ("OBSERVED", "MISSING", "STALE_OR_INVALID"))
    missing = Decimal(counts["MISSING"]) / eligible if eligible else None
    stale = Decimal(counts["STALE_OR_INVALID"]) / eligible if eligible else None
    covered = Decimal(counts["OBSERVED"]) / eligible if eligible else None
    bad = missing + stale if eligible else None
    state = "INSUFFICIENT_DATA" if not eligible or limit is not None and bad > limit else "AVAILABLE"
    return {"schema": "quote-quality-gate/1", "symbol": symbol, "from": iso(start), "to_exclusive": iso(end),
            "resolution": resolution, "counts": counts, "eligible_buckets": eligible,
            "coverage_share": str(covered) if covered is not None else None,
            "missing_share": str(missing) if missing is not None else None,
            "stale_or_invalid_share": str(stale) if stale is not None else None,
            "maximum_bad_share": str(limit) if limit is not None else None,
            "status": state, "funded_authority": False,
            "limitation": "Bucket coverage is not continuous quote availability; only recorded venue closures are excluded. "
                          "Missingness or stale data never creates prices or an eligible paper fill."}



def recorded_bar_coverage(out):
    """Display archived closed-bar coverage, with limits explicit and no market DB reads."""
    from ..domain.model import parse_ts

    result, inputs = out["result"], out["inputs"]
    if inputs.get("kind") == "portfolio":
        rates = {}
        for symbol, market in result.get("markets", {}).items():
            observations, qualified_count = market.get("observations", 0), market.get("qualified", 0)
            rates[symbol] = (str(Decimal(qualified_count) / observations) if observations else None)
        return {"status": "RECEIPT_SHARE_ONLY", "per_market_qualified_receipt_share": rates,
                "limitation": "Not a bar coverage ratio; missing-time buckets require a market receipt snapshot."}
    if inputs.get("resolution") == "session":
        return {"status": "NOT_ASSESSED", "reason": "VARIABLE_SESSION_PERIOD"}
    try:
        start, end = parse_ts(inputs["from"]), parse_ts(inputs["to"])
        spec = BarSpec(inputs["resolution"])
    except (KeyError, ValueError, TypeError):
        return {"status": "NOT_ASSESSED", "reason": "NO_FIXED_BAR_WINDOW"}
    spans = [(parse_ts(row["from"]), parse_ts(row["to"]))
             for row in result.get("session", {}).get("skipped", [])
             if row.get("reason") == "VENUE_CLOSED"]
    expected = set()
    at = spec.bucket(start)
    while at < end and len(expected) <= 5000:
        boundary = at + spec.step
        if not any(a <= at and boundary <= b for a, b in spans):
            expected.add(iso(at))
        at = boundary
    if len(expected) > 5000 or not expected:
        return {"status": "NOT_ASSESSED", "reason": "INSUFFICIENT_OR_OVERSIZED_BAR_WINDOW"}
    observed = {d.get("bar_known", {}).get("start") for d in result.get("decisions", [])}
    count = len(expected & observed)
    return {"status": "DESCRIPTIVE", "eligible_buckets": len(expected),
            "observed_closed_buckets": count,
            "coverage_share": str(Decimal(count) / len(expected)),
            "limitation": "Frozen closed-bar presence only. Stale/invalid public quotes and intrabar gaps "
                          "require the optional market receipt quality gate."}
