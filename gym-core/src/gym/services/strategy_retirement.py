"""Evidence-gated retirement and meta-label eligibility.

A cherry-picked list of local paper results cannot alter the strategy
catalog or independently certify a prospective comparison. This module
produces a review candidate, never a hidden strategy or funding permission.
"""
import re

from ..domain.strategy import digest


def assess_retirement(rows, universe, *, independent_final=False):
    """Check complete frozen market coverage and 200-seed random-entry baselines.

    Independent final evidence cannot be asserted using an untrusted Boolean.
    Locally verified paper results can trigger review, not catalog retirement.
    """
    if independent_final is not False:
        raise ValueError("independent final evidence cannot be caller-declared")
    if (type(universe) is not list or not 3 <= len(universe) <= 100
            or any(type(s) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", s) for s in universe)
            or len(universe) != len(set(universe))
            or type(rows) is not list or len(rows) > 100):
        raise ValueError("invalid retired-strategy universe or evidence bounds")
    if any(type(row) is not dict or
           set(row) != {"strategy", "symbol", "closed_trades", "random_entry_status",
                        "random_entry_percentile", "valuation", "run_id", "store",
                        "locally_verified"} for row in rows):
        raise ValueError("invalid retirement evidence fields")
    symbols = [row["symbol"] for row in rows]
    if len(set(symbols)) != len(symbols) or any(symbol not in universe for symbol in symbols):
        raise ValueError("duplicate or out-of-universe strategy evidence")
    strategies = {row["strategy"] for row in rows}
    if len(strategies) > 1:
        raise ValueError("cannot screen multiple strategies in one retirement assessment")
    complete = len(rows) == len(universe) and set(symbols) == set(universe)
    safe_rows = all(
        type(row["closed_trades"]) is int and row["closed_trades"] >= 30
        and row["locally_verified"] is True and row["store"] == "live"
        and row["valuation"] == "CURRENT"
        and row["random_entry_status"] == "EXPLORATORY"
        and type(row["random_entry_percentile"]) in (int, float)
        and 0 <= row["random_entry_percentile"] <= 100
        and type(row["run_id"]) is str and re.fullmatch(r"[0-9a-f]{16}", row["run_id"])
        and type(row["strategy"]) is str and re.fullmatch(r"[a-z][a-z0-9-]{1,40}", row["strategy"])
        for row in rows)
    failed = safe_rows and complete and all(row["random_entry_percentile"] < 50 for row in rows)
    if not complete or not safe_rows:
        status = "INSUFFICIENT_EVIDENCE"
    elif failed:
        status = "REVIEW_REQUIRED"
    else:
        status = "NOT_RETIRED"
    result = {"schema": "strategy-retirement-screen/1",
              "strategy": next(iter(strategies), None), "frozen_market_count": len(universe),
              "observed_market_count": len(rows), "universe": sorted(universe),
              "status": status, "all_tested_markets_failed": failed,
              "hidden_by_default": False, "catalog_mutated": False,
              "independent_evidence": False, "funded_authority": False,
              "limitations": [
                  "A requested market universe is not proof of an independently preregistered complete universe.",
                  "Local verified saved runs and a 200-seed random-entry diagnostic do not authenticate independent final results.",
                  "No strategy is hidden solely by selected paper backtests; independent evaluation must precede catalog policy changes.",
                  "Insufficient closed trades, stale valuation, demo or unready rows are not failures against the baseline."]}
    result["report_id"] = digest(result)[:16]
    return result


def meta_label_eligibility(closed_trades):
    """Enforce the deferred logistic meta-label experiment's 300-trade minimum."""
    if type(closed_trades) is not int or not 0 <= closed_trades <= 10**9:
        raise ValueError("meta-label counts need a nonnegative bounded integer")
    return {"schema": "meta-label-eligibility/1", "closed_trades": closed_trades,
            "minimum_closed_trades": 300,
            "status": "DEFERRED" if closed_trades < 300 else "RESEARCH_ELIGIBLE_NOT_TRAINED",
            "calibration_evaluated": False, "model_trained": False,
            "automatically_selectable": False, "funded_authority": False,
            "reason": ("Fewer than 300 verified closed trades"
                       if closed_trades < 300 else
                       "Count alone cannot establish labels, calibration, prospective results or independent custody")}


def screen_verified_retirement(root, request, *, store):
    """Read verified native runs and refuse selective retrospective catalog edits."""
    from pathlib import Path

    from ..adapters.run_store import load_verified_run
    from ..domain.market_models import fields
    from ..domain.performance import trade_ledger
    from .random_entry import random_entry_report
    from .reports import run_valuation

    fields(request, "run_ids universe")
    ids = request["run_ids"]
    if (type(ids) is not list or not 3 <= len(ids) <= 100
            or any(type(s) is not str or not re.fullmatch(r"[0-9a-f]{16}", s) for s in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("retirement screen needs 3..100 distinct verified run IDs")
    runs = [load_verified_run(Path(root) / "runs", rid, store=store) for rid in ids]
    inp = runs[0]["inputs"]
    if (inp.get("kind") != "live-session" or store != "live"
            or any(run["inputs"].get("kind") != "live-session"
                   or run["inputs"]["config_hash"] != inp["config_hash"]
                   or any(run["inputs"].get(key) != inp.get(key)
                          for key in ("resolution", "cash", "cost", "rules_mode"))
                   for run in runs)):
        raise ValueError("retirement needs matched live-session configuration and costs")
    rows = []
    for run in runs:
        result = run["result"]
        baseline = random_entry_report(run)
        trades = trade_ledger(result.get("orders", []), result.get("base") or "")
        valuation = run_valuation(run)
        rows.append({"strategy": inp["strategy"], "symbol": run["inputs"]["symbol"],
                     "closed_trades": len(trades["trades"]),
                     "random_entry_status": baseline["status"],
                     "random_entry_percentile": baseline.get("percentile"),
                     "valuation": valuation.get("status", "UNAVAILABLE"),
                     "run_id": run["run_id"], "store": store, "locally_verified": True})
    report = assess_retirement(rows, request["universe"], independent_final=False)
    report["evidence_digest"] = digest([(row["run_id"], row["symbol"]) for row in rows])
    report["source"] = "VERIFIED_LOCAL_PAPER_RUNS_NOT_INDEPENDENT"
    return report
