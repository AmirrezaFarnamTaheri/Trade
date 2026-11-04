"""Paired paper research over one SQLite read snapshot and independent simulated accounts."""
import re
from datetime import timedelta
from decimal import Decimal

from ..domain.model import iso, parse_ts
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .paper import paper, ranking


def coverage(db, symbol):
    if not isinstance(symbol, str) or not re.fullmatch("[A-Z0-9]{2,24}", symbol):
        raise ValueError("invalid market symbol")
    rows = db.c.execute("select ts_avail from book_top where instrument_id=? order by ts_avail", ("wallex:" + symbol,)).fetchall()
    times = [parse_ts(row[0]) for row in rows]
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    return {"symbol": symbol, "observations": len(rows), "from": iso(times[0]) if times else None,
            "to": iso(times[-1]) if times else None,
            "span_seconds": (times[-1] - times[0]).total_seconds() if times else 0,
            "days": sorted({t.date().isoformat() for t in times}),
            "gaps_over_120s": sum(g > 120 for g in gaps), "longest_gap_seconds": max(gaps, default=0),
            "note": "Observation coverage is not proof of a continuous paper session or capital authority."}


def compare(db, symbol, t0, t1, candidates, *, resolution="15min", cash=Decimal(1000),
            cost=CostModel(), rules_mode="point-in-time", store="live", subscriptions=()):
    if db.c.in_transaction:
        raise ValueError("comparison requires its own read snapshot")
    db.c.execute("BEGIN")
    try:
        return _compare_in_snapshot(db, symbol, t0, t1, candidates, resolution=resolution, cash=cash,
                                    cost=cost, rules_mode=rules_mode, store=store, subscriptions=subscriptions)
    finally:
        db.c.rollback()


def _compare_in_snapshot(db, symbol, t0, t1, candidates, *, resolution="15min", cash=Decimal(1000),
                         cost=CostModel(), rules_mode="point-in-time", store="live", subscriptions=()):
    if not isinstance(symbol, str) or not re.fullmatch("[A-Z0-9]{2,24}", symbol):
        raise ValueError("invalid market symbol")
    if not t0 < t1 or t1 - t0 > timedelta(days=31):
        raise ValueError("comparison window must be positive and at most 31 days")
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= 4:
        raise ValueError("compare requires two to four candidates")
    if any(not isinstance(c, dict) or c.keys() - {"strategy", "params"} for c in candidates):
        raise ValueError("invalid comparison candidate")
    strategies = [create_strategy(c.get("strategy"), c.get("params")) for c in candidates]
    resolutions = tuple(dict.fromkeys((resolution, *subscriptions,
                        *(r for s in strategies for r in getattr(s, "required_resolutions", ())))))
    references = {s.reference_symbol for s in strategies if hasattr(s, "reference_symbol")}
    if len(references) > 1:
        raise ValueError("paired comparison supports one common reference asset")
    reference = next(iter(references), None)
    runs = [paper(db, symbol, t0, t1, resolution=resolution, cash=cash, cost=cost,
                  rules_mode=rules_mode, store=store, subscriptions=resolutions,
                  strategy_id=s.name, params=s.params, reference_symbol=reference) for s in strategies]
    if len({(r["inputs"]["data"], r["inputs"]["snapshots"]) for r in runs}) != 1:
        raise ValueError("comparison data or decision snapshots diverged")
    labels = [f"{chr(65 + i)}: {r['inputs']['strategy']}" for i, r in enumerate(runs)]
    ranked = ranking(runs[0]["result"], {**{label: r["result"] for label, r in zip(labels[1:], runs[1:])},
                                      **runs[0]["baselines"]}, labels[0])
    shared = {k: runs[0]["inputs"][k] for k in ("engine", "symbol", "from", "to", "resolution", "subscriptions",
              "cash", "cost", "rules_mode", "store", "data", "snapshots", "reference_symbol")}
    return {"comparison_id": digest({"shared": shared, "runs": [r["run_id"] for r in runs]})[:16],
            "mode": "COMPARE", "authority": "PAPER_ONLY", "funded_authority": False, "order_submitted": False,
            "shared_inputs": shared, "runs": runs, "ranking": ranked,
            "limitation": "Independent paper accounts; one traded asset with optional reference signal, not a shared portfolio or execution proposals."}
