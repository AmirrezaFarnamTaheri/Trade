"""Frozen prospective paper comparisons: a one-attempt local evidence ledger.

Not independent custody. This does not authorize funded execution or certify an edge.
"""
import json
import re
from datetime import timedelta

from ..adapters.run_store import save_run
from ..domain.bars import BarSpec
from ..domain.market_models import decimal, fields, rate
from ..domain.model import iso, parse_ts
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .paper import paper
from .research_protocol import _engine_digest
from .trial_ledger import TrialLedger

REQUIRED = "symbol candidates selection_end test_from test_to resolution cash fee_rate"


def register_comparison(registry, request, *, now):
    """Freeze a unique future matched-paper window before observations occur."""
    fields(request, REQUIRED)
    if type(request["symbol"]) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", request["symbol"]):
        raise ValueError("invalid comparison symbol")
    candidates = request["candidates"]
    if type(candidates) is not list or not 2 <= len(candidates) <= 4:
        raise ValueError("prospective comparison requires 2..4 fixed candidates")
    frozen = []
    for candidate in candidates:
        fields(candidate, "strategy params")
        strategy = create_strategy(candidate["strategy"], candidate["params"])
        frozen.append({"strategy": candidate["strategy"], "params": strategy.params,
                       "config_hash": strategy.config_hash})
    if len({x["config_hash"] for x in frozen}) != len(frozen):
        raise ValueError("duplicate prospective strategy configuration")
    selected, start, end = (parse_ts(request[k]) for k in ("selection_end", "test_from", "test_to"))
    spec = BarSpec(request["resolution"])
    if (request["resolution"] == "session" or not selected <= now < start < end or
            start - selected < spec.step or end - start > timedelta(days=31)):
        raise ValueError("future comparison needs a disjoint complete fixed-bar window and purge")
    cash, fee = decimal(request["cash"], "cash", positive=True), rate(request["fee_rate"], "fee_rate")
    if (end - start) // spec.step > 1440:
        raise ValueError("prospective window exceeds 1440 fixed-bar decisions")
    body = {"symbol": request["symbol"], "candidates": frozen, "selection_end": iso(selected),
            "test_from": iso(start), "test_to": iso(end), "resolution": request["resolution"],
            "cash": str(cash), "fee_rate": str(fee), "engine_digest": _engine_digest(),
            "configuration_hash": digest({"candidates": frozen, "symbol": request["symbol"],
                                           "start": iso(start), "end": iso(end)})}
    # Serialize registrations so a second local window cannot reuse the same
    # held-out observations behind a different event identity.
    registry.conn.execute("BEGIN IMMEDIATE")
    try:
        record = None
        for prior_id, encoded in registry.conn.execute(
                "SELECT id,body FROM events WHERE kind='PROSPECTIVE_COMPARE'"):
            prior = json.loads(encoded)
            c = prior.get("configuration", {})
            if (prior.get("store") == registry.store and c.get("symbol") == body["symbol"]
                    and c.get("test_from", "") < body["test_to"]
                    and c.get("test_to", "") > body["test_from"]):
                if c == body:
                    record = {"id": prior_id, **prior}
                else:
                    raise ValueError("prospective comparison overlaps an already frozen window")
        if record is None:
            record = registry.append("PROSPECTIVE_COMPARE", None, {"configuration": body})
        # Count before commit; a failed ledger append cannot freeze an uncounted window.
        with TrialLedger(registry.root) as ledger:
            for index, candidate in enumerate(frozen):
                ledger.record(symbol=body["symbol"], start=start, end=end,
                              hypothesis="prospective", source="prospective",
                              config_hash=candidate["config_hash"], attempt_id=f"{record['id']}.{index}")
        registry.conn.commit()
    except BaseException:
        registry.conn.rollback()
        raise
    return {**record, "authority": "PAPER_ONLY", "funded_authority": False,
            "independent_custody": False, "held_out": False,
            "limitations": ["Future window and configuration are frozen in a local append-only journal.",
                            "The same filesystem user can alter the ledger, data or clock; not independent certification."]}


def evaluate_comparison(registry, key, db, *, now):
    """Consume a frozen registration exactly once, then run its paper candidates."""
    record = registry.read(key)
    if record["kind"] != "PROSPECTIVE_COMPARE":
        raise ValueError("not a prospective comparison")
    config = record["configuration"]
    if now < parse_ts(config["test_to"]):
        raise ValueError("future window has not completed")
    if any(event["kind"] == "PROSPECTIVE_ATTEMPT" for event in record["events"]):
        raise ValueError("prospective comparison already consumed")
    if _engine_digest() != config["engine_digest"]:
        raise ValueError("engine changed since frozen registration")
    for candidate in config["candidates"]:
        if create_strategy(candidate["strategy"], candidate["params"]).config_hash != candidate["config_hash"]:
            raise ValueError("strategy changed since frozen registration")
    # Commit attempt before reading any future observations; failed attempts remain consumed.
    registry.conn.execute("BEGIN IMMEDIATE")
    try:
        claimed = registry.conn.execute(
            "SELECT 1 FROM events WHERE kind='PROSPECTIVE_ATTEMPT' AND parent=? LIMIT 1", (key,)
        ).fetchone()
        if claimed:
            raise ValueError("prospective comparison already consumed")
        attempt = registry.append("PROSPECTIVE_ATTEMPT", key, {"status": "CONSUMED",
                                  "frozen_configuration_digest": digest(config)})
        registry.conn.commit()
    except BaseException:
        registry.conn.rollback()
        raise
    try:
        if db is None or db.c.in_transaction:
            raise ValueError("independent market read snapshot required")
        results = []
        db.c.execute("BEGIN")
        try:
            for candidate in config["candidates"]:
                strategy = create_strategy(candidate["strategy"], candidate["params"])
                run = paper(db, config["symbol"], parse_ts(config["test_from"]), parse_ts(config["test_to"]),
                            resolution=config["resolution"], cash=decimal(config["cash"], "cash", positive=True),
                            cost=CostModel(fee_rate=rate(config["fee_rate"])), store=registry.store,
                            strategy_id=candidate["strategy"], params=candidate["params"],
                            subscriptions=getattr(strategy, "required_resolutions", ()),
                            reference_symbol=getattr(strategy, "reference_symbol", None))
                save_run(run, registry.root / "runs")
                end = run["result"]["end"]
                results.append({"run_id": run["run_id"], "config_hash": candidate["config_hash"],
                                "fills": run["result"]["fills"], "observations": run["result"]["observations"],
                                "qualified": run["result"]["qualified"],
                                "net": end["net"] if end else None,
                                "net_available": end is not None,
                                "no_trade": run["result"]["fills"] == 0,
                                "last_mark_at": end["mark_time"] if end else None})
        finally:
            db.c.rollback()
        report = {"schema": "prospective-comparison/1", "attempt_id": attempt["id"],
                  "configuration": config, "rows": results, "cash_baseline_net": "0",
                  "data_gaps": [r["run_id"] for r in results if not r["net_available"]],
                  "no_trade_count": sum(r["no_trade"] for r in results),
                  "comparable": all(r["net_available"] for r in results),
                  "authority": "PAPER_ONLY", "funded_authority": False, "order_submitted": False,
                  "independent_custody": False, "established_edge": False,
                  "limitations": ["Matched windows, nominal quote cash and fees, but only modeled outcomes.",
                                  "Quote coverage, stale terminal marks and zero-trade attempts remain explicit.",
                                  "Comparison is locally preregistered, not independently sealed or statistically validated."]}
        report["report_id"] = digest(report)[:16]
        return registry.append("PROSPECTIVE_RESULT", key, {"report": report})
    except Exception as error:
        registry.append("PROSPECTIVE_FAILURE", key, {"attempt_id": attempt["id"], "error_type": type(error).__name__})
        raise
