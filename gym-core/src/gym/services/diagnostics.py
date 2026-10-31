"""Reproducibility, lookahead, warmup and total-cost checks for paper replays."""
from datetime import timedelta
from decimal import Decimal

from ..domain.bars import BarSpec
from ..domain.model import iso, parse_ts
from ..domain.sim import CostModel
from ..domain.strategy import EmaTrend
from .data_portal import DataPortal
from .paper import run
from .rules import RuleService
from .session import PaperSession


def first_divergence(expected, actual, fields=("snapshot", "features", "action", "order")):
    for i in range(max(len(expected), len(actual))):
        a = expected[i] if i < len(expected) else {}
        b = actual[i] if i < len(actual) else {}
        for field in fields:
            if a.get(field) != b.get(field):
                return {"index": i, "watermark": a.get("t") or b.get("t"), "field": field,
                        "expected": a.get(field), "actual": b.get(field)}
    return None


def diagnostics(db, out):
    inp = out["inputs"]
    portal, svc = DataPortal(db), RuleService(db)
    t0, t1 = parse_ts(inp["from"]), parse_ts(inp["to"])
    c = inp["cost"]
    cost = CostModel(Decimal(c["fee_rate"]), timedelta(milliseconds=c["latency_ms"]),
                     timedelta(seconds=c["max_wait_s"]))
    today = svc.load()[1]
    rules = (lambda t: today) if inp["rules_mode"] == "today" else (lambda t: svc.load(t)[1])

    subscriptions = tuple(inp.get("subscriptions", ()))

    def replay(end=t1, model=cost):
        return run(portal, rules, EmaTrend(**inp["params"]), inp["symbol"], t0, end, inp["resolution"],
                   Decimal(inp["cash"]), model, subscriptions)

    main = out["result"]
    repeat = replay()
    checks = {"snapshot-repeatability": first_divergence(main["decisions"], repeat["decisions"])}
    midpoint = t0 + (t1 - t0) / 2
    prefix = replay(midpoint)
    expected = [d for d in main["decisions"] if parse_ts(d["t"]) <= midpoint]
    checks["lookahead-check"] = first_divergence(expected, prefix["decisions"])
    # Incremental stream vs replay uses the same engine; not an independent implementation oracle.
    stream = PaperSession(portal, rules, EmaTrend(**inp["params"]), inp["symbol"], t0, inp["resolution"],
                          Decimal(inp["cash"]), cost, subscriptions)
    for observation in portal.tops(inp["symbol"], t0, t1):
        stream.feed(observation)
    stream.finish(t1)
    checks["mode-parity"] = first_divergence(main["decisions"], stream.decisions)
    earlier = t0 - BarSpec(inp["resolution"]).step * inp["params"]["slow"] * 2
    prehistory = portal.tops(inp["symbol"], earlier, t0)
    warmup = {"status": "NOT_RUN", "reason": "No longer prehistory available.",
              "required_prefix_bars": inp["params"]["slow"] * 2, "prehistory_observations": len(prehistory)}
    if prehistory:
        longer = run(portal, rules, EmaTrend(**inp["params"]), inp["symbol"], earlier, t1, inp["resolution"],
                     Decimal(inp["cash"]), cost, subscriptions)
        lookup = {d["t"]: d for d in longer["decisions"]}
        ready = [d for d in main["decisions"] if d.get("feature_values", {}).get("trend") is not None and d["t"] in lookup]
        divergence = first_divergence([{"t": d["t"], "trend": d["feature_values"]["trend"]} for d in ready],
                                      [{"t": d["t"], "trend": lookup[d["t"]]["feature_values"]["trend"]} for d in ready], ("trend",))
        warmup = {"status": "FAIL" if divergence else "PASS" if ready else "NOT_RUN",
                  "first_divergence": divergence, "compared": len(ready), "prehistory_from": iso(earlier),
                  "prehistory_observations": len(prehistory), "required_prefix_bars": inp["params"]["slow"] * 2,
                  "scope": "EMA direction with twice-slow-length prehistory, not holding-dependent orders"}
    stress = []
    waterfall = (main.get("end") or {}).get("waterfall")
    for factor_text in ("0", "1", "1.25", "2", "3"):
        factor = Decimal(factor_text)
        if waterfall:
            drag = {name: -Decimal(waterfall[name]) for name in ("spread", "fees", "latency_drift")}
            stressed = Decimal(waterfall["directional"]) - sum((value * factor for value in drag.values()), Decimal(0))
            stress.append({"cost_multiplier": factor_text, "net": str(stressed),
                           "components": {name: str(value * factor) for name, value in drag.items()},
                           "fills": main["fills"]})
        else:
            stress.append({"cost_multiplier": factor_text, "net": None, "components": None, "fills": main["fills"]})
    return {"checks": {k: {"status": "FAIL" if v else "PASS", "first_divergence": v} for k, v in checks.items()},
            "warmup-stability": warmup, "cost_stress": stress,
            "limitation": "Mode parity shares an engine. Cost stress is matched-filled-path attribution; it scales observed spread, fees and latency drift without changing fills, depth or decisions."}


