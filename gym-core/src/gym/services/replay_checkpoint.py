"""Restartable native replay recipes; rebuild state from verified history instead of loading objects."""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal

from ..adapters.run_store import load_verified_run
from ..domain.bars import BarSpec
from ..domain.market_models import fields, instant
from ..domain.model import iso
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .data_portal import DataPortal
from .paper import run, session_result
from .research_protocol import _engine_digest
from .rules import RuleService
from .session import ENGINE_VERSION, PaperSession


def _comparable(result):
    result = deepcopy(result)
    if result.get("end"):
        result["end"].pop("net_usdt_eq", None)
    return result


def _state(session):
    pending = session.pending
    return digest({"cursor": iso(session.cursor), "state": session.state, "decisions": session.decisions,
                   "orders": session.orders, "balances": session.book.balances, "postings": session.book.postings,
                   "curve": session.curve, "bar_events": session.bar_events, "rules": session.rule_snapshots,
                   "limit_trades": session.limit_trades,
                   "pending": None if pending is None else asdict(pending)})


def checkpoint_replay(registry, db, request, *, resume=False):
    fields(request, "checkpoint_id" if resume else "run_id quote_count")
    saved = registry.read(request["checkpoint_id"]) if resume else None
    if saved and (saved["kind"] not in ("REPLAY_CHECKPOINT", "PORTFOLIO_CHECKPOINT") or saved["engine_digest"] != _engine_digest()):
        raise ValueError("checkpoint engine is unavailable or changed")
    run_id = saved["run_id"] if saved else request["run_id"]
    if saved and saved["kind"] == "PORTFOLIO_CHECKPOINT" or not (registry.root / "runs" / (str(run_id) + ".json")).exists():
        return portfolio_checkpoint(registry, db, request, saved=saved)
    out = load_verified_run(registry.root / "runs", saved["run_id"] if saved else request["run_id"], store=registry.store)
    inputs = out["inputs"]
    if inputs["engine"] != ENGINE_VERSION or inputs.get("kind") or inputs["rules_mode"] != "point-in-time":
        raise ValueError("checkpoint requires a current native historical point-in-time run")
    if saved and (saved["outputs_digest"] != out["outputs_digest"] or saved["inputs_digest"] != digest(inputs)):
        raise ValueError("checkpoint saved evidence changed")
    start, end = instant(inputs["from"]), instant(inputs["to"])
    spec = BarSpec(inputs["resolution"])
    if end - start > timedelta(days=31) or spec.resolution == "session" or (end - start) // spec.step > 5000:
        raise ValueError("checkpoint requires at most 31 days and 5000 fixed bars")
    count = saved["quote_count"] if saved else request["quote_count"]
    if type(count) is not int or not 1 <= count <= 100000 or db.c.in_transaction:
        raise ValueError("checkpoint requires an independent snapshot and 1..100000 quotes")
    cost = inputs["cost"]
    if cost["fee_assumption"] != "fee-in-received-asset":
        raise ValueError("unsupported saved fee assumption")
    model = CostModel.from_description(cost)
    portal = DataPortal(db, excluded=[(instant(a), instant(b)) for a, b in inputs.get("modeled_feed_outages", [])])
    rules = RuleService(db)
    def rules_for(at):
        return rules.load(at)[1]
    cash, symbol = Decimal(inputs["cash"]), inputs["symbol"]
    def strategy():
        return create_strategy(inputs["strategy"], inputs["params"])
    db.c.execute("BEGIN")
    try:
        observations = db.c.execute("SELECT count(*) FROM book_top WHERE ts_avail>=? AND ts_avail<?", (iso(start), iso(end))).fetchone()[0]
        if observations > 100000:
            raise ValueError("checkpoint observation budget exceeded")
        tops = portal.tops(symbol, start, end)
        if not count <= len(tops):
            raise ValueError("checkpoint cursor exceeds observed quotes")
        session = PaperSession(portal, rules_for, strategy(), symbol, start, inputs["resolution"], cash, model,
                               inputs["subscriptions"], inputs.get("reference_symbol"))
        for top in tops[:count]:
            session.feed(top)
        state = _state(session)
        prefix = digest([(iso(t.ts_avail), t.bid, t.ask, t.bid_qty, t.ask_qty, sorted(t.flags)) for t in tops[:count]])
        if saved and (state != saved["state_digest"] or prefix != saved["prefix_digest"]):
            raise ValueError("checkpoint prefix, rules or metadata changed; create a new revision")
        pending = session.pending.record["ref"] if session.pending else None
        for top in tops[count:]:
            session.feed(top)
        session.finish(end)
        rebuilt = session_result(session, tops, cash)
        if digest(_comparable(rebuilt)) != digest(_comparable(out["result"])):
            raise ValueError("replay differs from saved output; source correction or engine behavior changed")
        # Separate one-shot construction catches chunk-boundary or pending-state errors.
        full = run(portal, rules_for, strategy(), symbol, start, end, inputs["resolution"], cash, model,
                   inputs["subscriptions"], inputs.get("reference_symbol"))
        if digest(rebuilt) != digest(full):
            raise ValueError("chunked replay and full replay differ")
    finally:
        db.c.rollback()
    if resume:
        return {"schema": "replay-resume/1", "checkpoint_id": saved["id"], "run_id": out["run_id"],
                "status": "EXACT_MATCH", "result_digest": digest(rebuilt), "source_outputs_digest": out["outputs_digest"],
                "rebuilt_prefix_quotes": count, "continued_quotes": len(tops) - count, "funded_authority": False,
                "method": "REBUILD_VERIFIED_PREFIX", "mutable_object_deserialization": False}
    record = registry.append("REPLAY_CHECKPOINT", None, {"run_id": out["run_id"], "outputs_digest": out["outputs_digest"],
        "inputs_digest": digest(inputs), "engine_digest": _engine_digest(), "quote_count": count,
        "cursor": iso(tops[count - 1].ts_avail), "prefix_digest": prefix, "state_digest": state,
        "pending_order": pending, "funded_authority": False})
    return {"schema": "replay-checkpoint/1", "record": record, "funded_authority": False}


def portfolio_checkpoint(registry, db, request, *, saved):
    from .portfolio import portfolio

    out = load_verified_run(registry.root / "runs" / "portfolios", saved["run_id"] if saved else request["run_id"], store=registry.store)
    inputs = out["inputs"]
    if inputs.get("kind") != "portfolio" or inputs.get("portfolio_version") != 5 or inputs["rules_mode"] != "point-in-time":
        raise ValueError("checkpoint requires a current point-in-time portfolio")
    if saved and (saved["outputs_digest"] != out["outputs_digest"] or saved["inputs_digest"] != digest(inputs)):
        raise ValueError("checkpoint saved portfolio evidence changed")
    count = saved["quote_count"] if saved else request["quote_count"]
    if type(count) is not int or not 1 <= count <= 100000:
        raise ValueError("portfolio checkpoint needs 1..100000 quotes")
    options = {"resolution": inputs["resolution"], "cash": Decimal(inputs["cash"]), "cost": CostModel.from_description(inputs["cost"]),
        "strategy_id": inputs["strategy"], "params": inputs["params"], "rules_mode": inputs["rules_mode"],
        "store": registry.store, "policy": inputs.get("policy")}
    checkpoint = {"quote_count": count}
    rebuilt = portfolio(db, inputs["symbols"], instant(inputs["from"]), instant(inputs["to"]), **options, checkpoint=checkpoint)
    if saved and any(checkpoint[key] != saved[key] for key in ("cursor", "prefix_digest", "state_digest", "pending_orders")):
        raise ValueError("portfolio checkpoint prefix, rules, risk or reservations changed")
    if rebuilt["run_id"] != out["run_id"] or rebuilt["outputs_digest"] != out["outputs_digest"]:
        raise ValueError("portfolio replay differs from saved evidence")
    if saved:
        return {"schema": "portfolio-resume/1", "checkpoint_id": saved["id"], "run_id": out["run_id"],
            "status": "EXACT_MATCH", "result_digest": rebuilt["outputs_digest"], "rebuilt_prefix_quotes": count,
            "method": "REBUILD_VERIFIED_PREFIX", "mutable_object_deserialization": False, "funded_authority": False}
    record = registry.append("PORTFOLIO_CHECKPOINT", None, {"run_id": out["run_id"], "outputs_digest": out["outputs_digest"],
        "inputs_digest": digest(inputs), "engine_digest": _engine_digest(), **checkpoint, "funded_authority": False})
    return {"schema": "portfolio-checkpoint/1", "record": record, "funded_authority": False}
