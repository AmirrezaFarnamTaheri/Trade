"""Paired paper research over one SQLite read snapshot and independent simulated accounts."""
import re
from datetime import timedelta
from decimal import Decimal

from ..domain.model import iso, parse_ts
from ..domain.performance import performance, selection_check
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .paper import paper, ranking
from .reports import sampled_drawdown


def saved_comparison(root, request, *, store, validation=False):
    from ..adapters.run_store import save_run
    from ..adapters.store import MarketDB
    from ..domain.market_models import decimal, fields, instant, rate
    from .collector import now_utc
    from .temporal_validation import validate

    fields(request, "symbol from to resolution cash fee_rate latency_ms rules_mode candidates folds participation walk_depth carry_remainder max_fraction vol_target order_type maker_fee_rate")
    start, end = instant(request["from"]), instant(request["to"])
    latency, folds = request["latency_ms"], request["folds"]
    if (end > now_utc() or type(latency) is not int or not 0 <= latency <= 60000
            or type(folds) is not int or not 1 <= folds <= 5 or store not in ("live", "demo")):
        raise ValueError("invalid comparison bounds")
    participation = request["participation"]
    if type(request["walk_depth"]) is not bool or type(request["carry_remainder"]) is not bool:
        raise ValueError("walk_depth and carry_remainder must be booleans")
    cost = CostModel(rate(request["fee_rate"]), timedelta(milliseconds=latency),
                     max_participation=None if participation is None else decimal(participation, "participation", positive=True),
                     walk_depth=request["walk_depth"], carry_remainder=request["carry_remainder"],
                     **{key: decimal(request[key], key, positive=True) for key in ("max_fraction", "vol_target")
                        if request[key] is not None},
                     order_type=request["order_type"],
                     maker_fee_rate=None if request["maker_fee_rate"] is None else rate(request["maker_fee_rate"]))
    db = MarketDB(root / "market.db", readonly=True)
    try:
        symbol = request["symbol"]
        if type(symbol) is not str or not db.c.execute("SELECT 1 FROM book_top WHERE instrument_id=? LIMIT 1", ("wallex:" + symbol,)).fetchone():
            raise ValueError("comparison requires an observed symbol")
        runs = root / "runs"
        result = (validate if validation else compare)(db, symbol, start, end, request["candidates"],
            resolution=request["resolution"], cash=decimal(request["cash"], "cash", positive=True),
            cost=cost, rules_mode=request["rules_mode"], store=store,
            **({"folds": folds} if validation else {"prior_configs": tried_before(runs, symbol, request["resolution"])}))
        for record in result["runs"]:
            save_run(record, runs)
        if validation:
            save_run({"run_id": result["validation_id"], **{k: v for k, v in result.items() if k != "runs"}}, runs / "validations")
        result["runs"] = [{"run_id": record["run_id"], "inputs": record["inputs"],
                           "result": {key: record["result"][key] for key in ("strategy", "quote", "end", "fills", "observations", "qualified")},
                           "performance": result.get("performance", {}).get(record["run_id"]), "warnings": record["warnings"]} for record in result["runs"]]
        return result
    finally:
        db.c.close()


def tried_before(runs, symbol, resolution) -> frozenset:
    """Strategy configurations already saved for this market and decision close: earlier selection trials."""
    from ..adapters.run_store import list_runs
    rows = list_runs(runs, limit=100_000, symbol=symbol)
    return frozenset(row["inputs"]["config_hash"] for row in rows
                     if row["inputs"].get("resolution") == resolution and row["inputs"].get("config_hash"))


def coverage(db, symbol):
    """Observation coverage computed inside SQLite; the quote table grows by millions of rows a week."""
    if not isinstance(symbol, str) or not re.fullmatch("[A-Z0-9]{2,24}", symbol):
        raise ValueError("invalid market symbol")
    count, first, last, gaps, longest = db.c.execute("""
        SELECT count(*), min(ts_avail), max(ts_avail), coalesce(sum(gap > 120), 0), coalesce(max(gap), 0) FROM (
            SELECT ts_avail, (julianday(ts_avail) - julianday(lag(ts_avail) OVER (ORDER BY ts_avail))) * 86400 AS gap
            FROM book_top WHERE instrument_id=?)""", ("wallex:" + symbol,)).fetchone()
    days = [row[0] for row in db.c.execute(
        "SELECT DISTINCT substr(ts_avail, 1, 10) FROM book_top WHERE instrument_id=? ORDER BY 1", ("wallex:" + symbol,))]
    first, last = (parse_ts(first), parse_ts(last)) if count else (None, None)
    # TMN results are valued in USDT only from the first stored USDTTMN quote; earlier starts cannot be ranked.
    rate_from = db.c.execute("SELECT min(ts_avail) FROM book_top WHERE instrument_id='wallex:USDTTMN' AND bid IS NOT NULL "
                             "AND ask IS NOT NULL").fetchone()[0] if symbol.endswith("TMN") else None
    return {"symbol": symbol, "observations": count, "from": iso(first), "to": iso(last), "valuation_from": rate_from,
            "span_seconds": (last - first).total_seconds() if count else 0, "days": days,
            "gaps_over_120s": gaps, "longest_gap_seconds": round(longest, 3),
            "note": "Observation coverage is not proof of a continuous paper session or capital authority."}


def compare(db, symbol, t0, t1, candidates, *, resolution="15min", cash=Decimal(1000),
            cost=CostModel(), rules_mode="point-in-time", store="live", subscriptions=(), prior_configs=frozenset()):
    if db.c.in_transaction:
        raise ValueError("comparison requires its own read snapshot")
    db.c.execute("BEGIN")
    try:
        return _compare_in_snapshot(db, symbol, t0, t1, candidates, resolution=resolution, cash=cash, cost=cost,
                                    rules_mode=rules_mode, store=store, subscriptions=subscriptions, prior_configs=prior_configs)
    finally:
        db.c.rollback()


def _compare_in_snapshot(db, symbol, t0, t1, candidates, *, resolution="15min", cash=Decimal(1000),
                         cost=CostModel(), rules_mode="point-in-time", store="live", subscriptions=(), prior_configs=frozenset()):
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
    measured = {label: performance(r, sampled_drawdown(r)) for label, r in zip(labels, runs)}
    new = {r["inputs"]["config_hash"] for r in runs}
    return {"comparison_id": digest({"shared": shared, "runs": [r["run_id"] for r in runs]})[:16],
            "mode": "COMPARE", "authority": "PAPER_ONLY",
            "shared_inputs": shared, "runs": runs, "ranking": ranked, "selection": selection_check(measured, len(prior_configs | new)),
            # Kept beside, never inside, saved run records so identical reruns stay byte-identical.
            "performance": {r["run_id"]: {k: v for k, v in measured[label].items() if k != "ledger"} for label, r in zip(labels, runs)},
            "limitation": "Independent paper accounts; one traded asset with optional reference signal, not a shared portfolio or execution proposals."}
