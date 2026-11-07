"""Fixed numeric analyst roles; no prose inference, external tools or trading votes."""
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from ..domain.model import parse_ts
from ..domain.periods import instant
from ..domain.strategy import digest
from .research_grounding import MetricUnavailable, check_claims, resolve_run_metric


def review_runs(root, run_ids, *, as_of, store="live"):
    as_of = instant(as_of)
    if type(run_ids) is not list or not 1 <= len(run_ids) <= 4 or any(type(key) is not str for key in run_ids) or len(set(run_ids)) != len(run_ids):
        raise ValueError("review requires 1..4 distinct saved run IDs")
    roles = {"performance": ("net_quote",), "risk": ("sampled_drawdown_percent",),
             "benchmark": ("net_quote", "hold_cash_net_quote")}
    reports = []
    with localcontext() as context:
        context.prec = 160
        for key in run_ids:
            _, _, source, _ = resolve_run_metric(root, {"run_id": key, "metric": "starting_cash_quote"}, store=store)
            if parse_ts(source["period"]["to"]) > as_of:
                raise ValueError("review cannot use a run ending after its availability cutoff")
            for role, metrics in roles.items():
                references = [{"run_id": key, "metric": metric} for metric in metrics]
                try:
                    values = [resolve_run_metric(root, ref, store=store)[0] for ref in references]
                except MetricUnavailable:
                    reports.append({"role": role, "run_id": key, "status": "UNAVAILABLE", "reason": "METRIC_NOT_OBSERVED"})
                    continue
                value = values[0] - values[1] if len(values) == 2 else values[0]
                claim = {"id": role, "operation": "DIFFERENCE" if len(values) == 2 else "VALUE", "sources": references,
                         "value": str(value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN)), "decimal_places": 8}
                checked = check_claims(root, {"claims": [claim]}, store=store)
                reports.append({"role": role, "run_id": key, "status": "MISMATCH" if not checked["all_matched"] else "VERIFIED_NUMERIC" if source["valuation"]["status"] == "CURRENT" else "STALE_VALUATION",
                                "evidence": checked["claims"][0]})
    result = {"schema": "research-review/1", "authority": "PAPER_ONLY", "funded_authority": False,
              "order_submitted": False, "as_of": as_of.isoformat(), "reports": reports,
              "synthesis": "REVIEW_REQUIRED", "semantic_grounding_verified": False,
              "tools": ["resolve_run_metric", "check_claims"], "tool_call_bound": 48,
              "limitation": "Deterministic performance, risk and cash-benchmark views. Numeric artifact checks do not authenticate feeds, "
                            "validate prose/causality, predict returns or create an execution proposal. No vote overrides hard rules."}
    result["review_id"] = digest(result)[:16]
    return result
