"""Chronological paper selection and evaluation diagnostics.

Uses native paper accounts and one read snapshot. Repeated historical evaluation
is not independent final evidence, and this service never grants capital authority.
"""
from datetime import timedelta
from decimal import Decimal

from ..domain.bars import BarSpec
from ..domain.model import iso
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .paper import PaperDataUnavailable, paper
from .reports import economic_report
from .research import _compare_in_snapshot


def validate(db, symbol, start, end, candidates, *, resolution="15min", cash=Decimal(1000),
             cost=CostModel(), rules_mode="point-in-time", store="live", subscriptions=(), folds=1):
    """One or several disjoint 70/30 diagnostics over a single database snapshot."""
    if type(folds) is not int or not 1 <= folds <= 5:
        raise ValueError("folds must be an integer from 1 to 5")
    if not start < end or end - start > timedelta(days=31):
        raise ValueError("validation window must be positive and at most 31 days")
    if resolution == "session":
        raise ValueError("chronological validation requires fixed-duration decision bars")
    spec = BarSpec(resolution)
    cuts = [start, *(spec.bucket(start + (end - start) * i // folds) for i in range(1, folds)), end]
    if db.c.in_transaction:
        raise ValueError("validation requires its own read snapshot")
    db.c.execute("BEGIN")
    try:
        reports = [_validate_in_snapshot(db, symbol, first, last, candidates, resolution=resolution,
                   cash=cash, cost=cost, rules_mode=rules_mode, store=store, subscriptions=subscriptions)
                   for first, last in zip(cuts, cuts[1:])]
        if folds == 1:
            return reports[0]
        evaluated = sum(report["status"] == "EVALUATED" for report in reports)
        result = {"mode": "MULTI_WINDOW_VALIDATION", "authority": "PAPER_ONLY", "funded_authority": False,
                  "order_submitted": False, "independent_final_evidence": False,
                  "status": "EVALUATED" if evaluated == folds else "INCOMPLETE",
                  "fold_count": folds, "evaluated_windows": evaluated,
                  "trial_count": sum(report["trial_count"] for report in reports),
                  "folds": [{key: value for key, value in report.items() if key != "runs"} for report in reports],
                  "limitation": "Disjoint successive windows, each with its own 70/30 selection, one-period purge "
                                "and flat-account warmup. No state or cash is carried between windows. "
                                "Missing selection data rejects the request; stale and abstaining outcomes remain "
                                "explicit, with no zero-return substitution "
                                "or compounded portfolio return. This is repeated historical research, not "
                                "expanding training or independent final evidence."}
        result["validation_id"] = digest(result)[:16]
        result["runs"] = [run for report in reports for run in report["runs"]]
        return result
    finally:
        db.c.rollback()


def _validate_in_snapshot(db, symbol, start, end, candidates, *, resolution="15min", cash=Decimal(1000),
             cost=CostModel(), rules_mode="point-in-time", store="live", subscriptions=()):
    spec = BarSpec(resolution)
    split = spec.bucket(start + (end - start) * 7 // 10)
    holdout_start = split + spec.step
    if split - start < 3 * spec.step or end - holdout_start < 3 * spec.step:
        raise ValueError("selection and holdout each require at least three decision periods")
    selection = _compare_in_snapshot(db, symbol, start, split, candidates, resolution=resolution,
                                     cash=cash, cost=cost, rules_mode=rules_mode, store=store,
                                     subscriptions=subscriptions)
    runs = selection["runs"]
    eligible = [run for run in runs if run["result"]["fills"] > 0
                and economic_report(run)["valuation"]["status"] == "CURRENT"]
    selected = max(eligible, key=lambda run: (Decimal(run["result"]["end"]["net"]),
                                             run["inputs"]["config_hash"])) if eligible else None
    winner = None if selected is None else {key: selected["inputs"][key]
                                            for key in ("strategy", "strategy_version", "params", "config_hash")}
    holdout = None
    status, reason = "ABSTAIN", "NO_CURRENT_ACTIVE_SELECTION_RESULT"
    if selected is not None:
        try:
            holdout = paper(db, symbol, holdout_start, end, resolution=resolution, cash=cash, cost=cost,
                            rules_mode=rules_mode, store=store, strategy_id=winner["strategy"], params=winner["params"],
                            subscriptions=selection["shared_inputs"]["subscriptions"],
                            reference_symbol=selection["shared_inputs"]["reference_symbol"])
        except PaperDataUnavailable:
            status, reason = "UNAVAILABLE", "HOLDOUT_REPLAY_UNAVAILABLE"
        else:
            runs = [*runs, holdout]
            status = "EVALUATED" if economic_report(holdout)["valuation"]["status"] == "CURRENT" else "STALE_HOLDOUT"
            reason = None
    report = {"mode": "TEMPORAL_VALIDATION", "authority": "PAPER_ONLY", "funded_authority": False,
              "order_submitted": False, "independent_final_evidence": False,
              "status": status, "reason": reason, "selected": winner,
              "windows": {"selection": {"from": iso(start), "to": iso(split)},
                          "holdout": {"from": iso(holdout_start), "to": iso(end)},
                          "purge_seconds": spec.step.total_seconds()},
              "selection": {"comparison_id": selection["comparison_id"],
                            "metric": "net_quote_after_modeled_costs",
                            "run_ids": [run["run_id"] for run in selection["runs"]]},
              "holdout_run_id": None if holdout is None else holdout["run_id"],
              "trial_count": len(runs), "runs": runs,
              "limitation": "First 70% selects a fixed registered candidate; one decision period is purged. "
                            "The remaining window starts a separate flat paper account with its own warmup. "
                            "Same engine; repeatable historical diagnostic, not a consume-once or independent final test. "
                            "A negative selection result can still win; selection is not evidence of profitability."}
    report["validation_id"] = digest({key: value for key, value in report.items() if key != "runs"})[:16]
    return report
