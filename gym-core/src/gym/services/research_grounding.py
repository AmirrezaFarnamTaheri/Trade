"""Bounded numeric claim checks against native paper artifacts, never prose approval."""
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import re

from ..adapters.run_store import load_verified_run
from ..domain.market_models import fields
from .reports import economic_report, sampled_drawdown


class MetricUnavailable(ValueError):
    """The artifact is present but its requested metric is not observed."""


def _number(value):
    if type(value) is not str or len(value) > 64 or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        raise ValueError("claim values must be bounded finite decimal strings")
    return Decimal(value)


def _source(root, reference, store):
    fields(reference, "run_id metric")
    if type(reference["run_id"]) is not str or type(reference["metric"]) is not str:
        raise ValueError("claim run ID and metric must be strings")
    out = load_verified_run(root, reference["run_id"], store=store)
    result, metric = out["result"], reference["metric"]
    unit = result["quote"]
    if metric in ("net_quote", "equity_quote"):
        raw = result["end"]["net" if metric == "net_quote" else "equity"] if result.get("end") else None
    elif metric == "starting_cash_quote":
        raw = result["start_cash"]
    elif metric == "hold_cash_net_quote":
        raw = out["baselines"]["hold " + unit]["end"]["net"]
    elif metric in ("fills", "qualified_observations"):
        raw, unit = str(result["fills" if metric == "fills" else "qualified"]), "count"
    elif metric == "sampled_drawdown_percent":
        raw, unit = sampled_drawdown(out).get("maximum_percent"), "percent"
    else:
        raise ValueError("unsupported numeric research metric")
    if raw is None:
        raise MetricUnavailable("claimed metric is unavailable")
    value = _number(raw)
    provenance = {**reference, "outputs_digest": out["outputs_digest"],
                  "config_hash": out["inputs"]["config_hash"], "data_digest": out["inputs"]["data"],
                  "store": store, "period": {k: out["inputs"][k] for k in ("from", "to")},
                  "value": str(value), "unit": unit, "valuation": economic_report(out)["valuation"]}
    matched = {k: out["inputs"][k] for k in ("symbol", "from", "to", "resolution", "cash", "cost", "data", "snapshots", "rules_mode", "store")}
    return value, unit, provenance, matched


def resolve_run_metric(root, reference, *, store):
    try:
        return _source(root, reference, store)
    except (KeyError, TypeError, AttributeError, RecursionError):
        raise ValueError("invalid run artifact structure") from None


def check_claims(root, request, *, store):
    fields(request, "claims")
    if store not in ("live", "demo") or type(request["claims"]) is not list or not 1 <= len(request["claims"]) <= 32:
        raise ValueError("need 1..32 claims in the selected store")
    rows, seen = [], set()
    with localcontext() as context:
        context.prec = 160
        for claim in request["claims"]:
            fields(claim, "id operation sources value decimal_places")
            key, operation, places = claim["id"], claim["operation"], claim["decimal_places"]
            if type(key) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key) or key in seen:
                raise ValueError("claim IDs must be unique bounded identifiers")
            seen.add(key)
            if type(operation) is not str or operation not in ("VALUE", "DIFFERENCE", "RATIO"):
                raise ValueError("unsupported claim operation")
            if type(places) is not int or not 0 <= places <= 12:
                raise ValueError("decimal_places must be an integer from 0 to 12")
            references = claim["sources"]
            if type(references) is not list or len(references) != (1 if operation == "VALUE" else 2):
                raise ValueError("claim operation has the wrong number of sources")
            sources = [resolve_run_metric(root, reference, store=store) for reference in references]
            value, unit = sources[0][:2]
            if len(sources) == 2:
                other, other_unit, _, other_inputs = sources[1]
                if unit != other_unit or sources[0][3] != other_inputs:
                    raise ValueError("arithmetic requires matched inputs and units")
                if operation == "RATIO" and not other:
                    raise ValueError("claim ratio denominator is zero")
                value = value - other if operation == "DIFFERENCE" else value / other
                unit = unit if operation == "DIFFERENCE" else "ratio"
            computed = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)
            status = "MATCHED" if _number(claim["value"]) == computed else "MISMATCH"
            rows.append({"id": key, "operation": operation, "status": status,
                         "claimed_value": claim["value"], "computed_value": str(computed), "unit": unit,
                         "decimal_places": places, "rounding": "ROUND_HALF_EVEN",
                         "sources": [source[2] for source in sources]})
    return {"mode": "PAPER_ONLY", "funded_authority": False, "order_submitted": False,
            "all_matched": all(row["status"] == "MATCHED" for row in rows), "claims": rows,
            "source_authenticity_verified": False, "semantic_grounding_verified": False,
            "limitation": "Checks only allowlisted numeric artifact facts and matched-input arithmetic. "
                          "Digests detect inconsistent artifacts, not a malicious writer who can replace all hashes. "
                          "Prose, causality, forecasts, current executable prices and model reasoning are not verified."}
