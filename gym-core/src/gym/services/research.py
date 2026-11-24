"""Paired paper research over one SQLite read snapshot and independent simulated accounts."""
import re
from decimal import Decimal

from ..domain.model import iso, parse_ts
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .snapshot_comparison import compare_in_snapshot as _compare_in_snapshot


def saved_comparison(root, request, *, store, validation=False):
    from ..adapters.run_store import save_run
    from ..adapters.store import MarketDB
    from ..domain.market_models import decimal, fields, instant
    from ..domain.model import now_utc
    from .temporal_validation import validate
    from .trial_ledger import TrialLedger

    fields(request, "symbol from to resolution cash fee_rate latency_ms rules_mode candidates folds participation walk_depth carry_remainder max_fraction vol_target order_type maker_fee_rate")
    start, end = instant(request["from"]), instant(request["to"])
    latency, folds = request["latency_ms"], request["folds"]
    if (end > now_utc() or type(latency) is not int or not 0 <= latency <= 60000
            or type(folds) is not int or not 1 <= folds <= 5 or store not in ("live", "demo")):
        raise ValueError("invalid comparison bounds")
    participation = request["participation"]
    if type(request["walk_depth"]) is not bool or type(request["carry_remainder"]) is not bool:
        raise ValueError("walk_depth and carry_remainder must be booleans")
    from .cost_defaults import calibrated_cost
    cost = calibrated_cost(root, request["symbol"], fee=request["fee_rate"], now=start, latency_ms=latency,
                     max_participation=None if participation is None else decimal(participation, "participation", positive=True),
                     walk_depth=request["walk_depth"], carry_remainder=request["carry_remainder"],
                     **{key: decimal(request[key], key, positive=True) for key in ("max_fraction", "vol_target")
                        if request[key] is not None},
                     order_type=request["order_type"],
                     maker_fee=request["maker_fee_rate"])
    db = MarketDB(root / "market.db", readonly=True)
    try:
        symbol = request["symbol"]
        if type(symbol) is not str or not db.c.execute("SELECT 1 FROM book_top WHERE instrument_id=? LIMIT 1", ("wallex:" + symbol,)).fetchone():
            raise ValueError("comparison requires an observed symbol")
        runs = root / "runs"
        candidates = request["candidates"]
        if (type(candidates) is not list or not 2 <= len(candidates) <= 4
                or any(type(c) is not dict or c.keys() - {"strategy", "params"} for c in candidates)):
            raise ValueError("compare requires two to four valid candidates")
        # Invalid strategy definitions must not increment the immutable trial ledger.
        for candidate in candidates:
            create_strategy(candidate.get("strategy"), candidate.get("params"))
        with TrialLedger(root) as ledger:
            for candidate in candidates:
                ledger.record(symbol=symbol, start=start, end=end, hypothesis="ad-hoc",
                              source="validate" if validation else "compare", config_hash=digest(candidate))
            ledger_trials = ledger.count(symbol=symbol, start=start, end=end, hypothesis="ad-hoc")
        result = (validate if validation else compare)(db, symbol, start, end, request["candidates"],
            resolution=request["resolution"], cash=decimal(request["cash"], "cash", positive=True),
            cost=cost, rules_mode=request["rules_mode"], store=store,
            **({"folds": folds} if validation else {"prior_configs": tried_before(runs, symbol, request["resolution"]),
                                                "ledger_trials": ledger_trials}))
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
            cost=CostModel(), rules_mode="point-in-time", store="live", subscriptions=(), prior_configs=frozenset(), ledger_trials=0):
    if db.c.in_transaction:
        raise ValueError("comparison requires its own read snapshot")
    db.c.execute("BEGIN")
    try:
        return _compare_in_snapshot(db, symbol, t0, t1, candidates, resolution=resolution, cash=cash, cost=cost,
                                    rules_mode=rules_mode, store=store, subscriptions=subscriptions, prior_configs=prior_configs,
                                    ledger_trials=ledger_trials)
    finally:
        db.c.rollback()
