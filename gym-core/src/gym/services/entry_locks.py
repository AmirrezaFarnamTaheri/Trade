"""Evidence-linked paper entry locks reuse the existing persistent rule ledger."""
from datetime import timedelta

from ..adapters.run_store import load_verified_run
from ..domain.market_models import decimal, fields, instant
from ..domain.model import iso
from ..domain.strategy import digest
from .collector import now_utc
from .research_grounding import resolve_run_metric
from .rules import RuleService


def add_entry_lock(root, db, request, *, store):
    fields(request, "run_id scope reason duration_seconds threshold_percent")
    scope, reason, duration = request["scope"], request["reason"], request["duration_seconds"]
    if scope not in ("PAIR", "GLOBAL") or reason not in ("COOLDOWN", "DRAWDOWN"):
        raise ValueError("need pair/global scope and cooldown/drawdown trigger")
    if type(duration) is not int or not 60 <= duration <= 604800:
        raise ValueError("entry lock must last 60..604800 seconds")
    now = now_utc()
    out = load_verified_run(root / "runs", request["run_id"], store=store)
    if instant(out["inputs"]["to"]) > now:
        raise ValueError("lock evidence cannot end in the future")
    metric = "fills" if reason == "COOLDOWN" else "sampled_drawdown_percent"
    value, unit, evidence, _ = resolve_run_metric(root / "runs", {"run_id": request["run_id"], "metric": metric}, store=store)
    threshold = decimal(request["threshold_percent"], "threshold", positive=True) if reason == "DRAWDOWN" else None
    if (reason == "COOLDOWN" and request["threshold_percent"] is not None) or (threshold is not None and threshold > 100):
        raise ValueError("cooldown threshold must be null; drawdown threshold must be <=100 percent")
    if value < (threshold if threshold is not None else 1):
        return {"status": "NOT_TRIGGERED", "metric": metric, "value": str(value), "funded_authority": False}
    key = "entry-lock-" + digest({**request, "store": store, "outputs_digest": out["outputs_digest"]})[:24]
    service = RuleService(db)
    db.c.execute("BEGIN IMMEDIATE")
    try:
        existing = db.rules_as_of()[1].get(key)
        if existing is None:
            existing = {"id": key, "name": f"{reason} {scope} paper entry lock", "family": "Custom", "class": "POLICY",
                "action": "BLOCK_ENTRY", "scope": {"symbols": [out["result"]["symbol"]] if scope == "PAIR" else []},
                "params": {"entry_lock": True, "trigger": reason, "metric": metric, "value": str(value), "unit": unit,
                           "threshold_percent": request["threshold_percent"], "evidence": evidence},
                "effective_from": iso(now), "effective_until": iso(now + timedelta(seconds=duration)),
                "source": "operator", "status": "REPORTED", "last_confirmed_at": iso(now), "review_hours": 24,
                "exit_confirmed": False, "disabled": False, "note": "Paper evidence; blocks entry only. No venue protection or funded authority."}
            service.put(existing, now, actor="operator-research")
        db.c.commit()
    except BaseException:
        db.c.rollback()
        raise
    return {"status": "RECORDED", "rule": existing, "funded_authority": False, "cancellation_blocked": False, "exit_blocked": False}
