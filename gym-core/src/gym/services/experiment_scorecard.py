"""Every registered trial stays visible beside verified native paper metrics."""
from collections import Counter
from math import ceil

from ..adapters.run_store import load_verified_run
from ..domain.market_models import fields
from ..domain.model import parse_ts
from ..domain.performance import sampled_drawdown
from ..domain.strategy import digest
from .reports import run_valuation


def run_card(out):
    inputs, result = out["inputs"], out["result"]
    curve = [(inputs["from"], result["start_cash"]), *result["curve"]]
    if result.get("end"):
        curve.append((inputs["to"], result["end"]["equity"]))
    curve = list(dict(curve).items())
    stride = max(1, ceil(len(curve) / 999))
    selected = curve[::stride]
    if curve and selected[-1] != curve[-1]:
        selected.append(curve[-1])
    return {"run_id": out["run_id"], "outputs_digest": out["outputs_digest"],
        "strategy": inputs["strategy"], "params": inputs["params"], "config_hash": inputs["config_hash"],
        "period": {k: inputs[k] for k in ("from", "to")}, "cost": inputs["cost"],
        "quote": result["quote"], "fills": result["fills"], "ready": result["session"].get("running_at") is not None,
        "net_quote": result.get("end") and result["end"]["net"],
        "net_usdt_equivalent": result.get("end") and result["end"].get("net_usdt_eq"),
        "valuation": run_valuation(out), "fx": out.get("fx"), "sampled_drawdown": sampled_drawdown(out),
        "baselines": out["baselines"], "curve": selected, "curve_source_marks": len(curve),
        "curve_downsample_stride": stride, "kind": inputs.get("kind", "historical-replay")}


def experiment_scorecard(registry, request):
    fields(request, "experiment_id shadow_run_ids")
    shadow_ids = request["shadow_run_ids"]
    if (type(shadow_ids) is not list or len(shadow_ids) > 4 or any(type(key) is not str for key in shadow_ids)
            or len(set(shadow_ids)) != len(shadow_ids)):
        raise ValueError("need at most four distinct native prospective run IDs")
    experiment = registry.read(request["experiment_id"])
    if experiment["kind"] != "EXPERIMENT":
        raise ValueError("scorecard requires a saved experiment")
    definition, events = experiment["definition"], experiment["events"]
    if experiment.get("workflow") is not None or any(type(definition.get(k)) is not list for k in ("trials", "windows", "scenarios")):
        raise ValueError("scorecard supports strategy-trial experiments; use the saved walk-forward report for fold selection")
    attempts = [e for e in events if e["kind"] == "ATTEMPT"]
    if len(events) >= 500 or len(attempts) > 32:
        raise ValueError("scorecard requires one complete bounded experiment")
    results = {e["attempt_id"]: e for e in events if e["kind"] == "RESULT"}
    rows, runs = [], []
    for attempt in attempts:
        receipt = results.get(attempt["id"], {})
        row = {"attempt_id": attempt["id"], **{k: attempt[k] for k in ("trial", "window", "scenario")},
               "state": receipt.get("state", "RESULT_PENDING"), "reason": receipt.get("reason"), "run": None}
        if receipt.get("run_id"):
            try:
                out = load_verified_run(registry.root / "runs", receipt["run_id"], store=registry.store)
                if out["outputs_digest"] != receipt["outputs_digest"]:
                    raise ValueError("saved run differs from experiment receipt")
                row["run"] = run_card(out)
                runs.append(out)
            except (OSError, ValueError):
                row["verification"] = "UNAVAILABLE_OR_CHANGED"
        rows.append(row)
    shadows = []
    for key in shadow_ids:
        out = load_verified_run(registry.root / "runs", key, store=registry.store)
        if out["inputs"].get("kind") != "live-session":
            raise ValueError("shadow overlays require a saved native prospective session")
        matched = [r for r in runs if all(out["inputs"].get(k) == r["inputs"].get(k)
                   for k in ("symbol", "config_hash", "resolution", "cash", "cost", "rules_mode"))]
        if not matched or any(parse_ts(out["inputs"]["from"]) < parse_ts(r["inputs"]["to"]) for r in matched):
            raise ValueError("shadow must follow a matched historical configuration, cash and costs")
        shadows.append(run_card(out))
    result = {"schema": "experiment-scorecard/1", "experiment_id": experiment["id"], "store": registry.store,
        "definition": definition, "registered_trials": len(definition["trials"]), "registered_attempts": len(attempts),
        "states": dict(Counter(r["state"] for r in rows)), "rows": rows, "shadows": shadows,
        "funded_authority": False, "independent_final_evidence": False,
        "limits": ["Every registered attempt is retained, including failed, missing, unready and zero-trade runs; no winner is selected.",
            "Heatmap cells use each run's quote currency. USDT-equivalent values depend on the displayed FX status.",
            "Historical and prospective traces retain actual timestamps; they are not matched-calendar evidence.",
            "A prospective session is an observation, not proof of preregistration or statistical independence.",
            "Display curves retain at most 1000 observed marks, without interpolation; exact full curves remain in native artifacts.",
            "Final account valuation is shown at the run cutoff using its separately disclosed price timestamp and valuation age.",
            "No correction for trial search and no future edge or funded authority is established."]}
    result["report_id"] = digest(result)[:16]
    return result
