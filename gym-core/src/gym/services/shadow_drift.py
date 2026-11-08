"""Causal, paper-only daily shadow drift against a disjoint prior replay."""
from datetime import timedelta
from decimal import Decimal, localcontext
from itertools import pairwise

from ..domain.model import iso, parse_ts
from ..domain.strategy import digest

MAX_CURVE_MARKS = 100000


def _daily_returns(run, *, before):
    """Retain last available UTC-equity mark per day and skip missing days."""
    observations = run["result"]["curve"]
    if type(observations) is not list or len(observations) > MAX_CURVE_MARKS:
        raise ValueError("shadow daily curve must be a bounded list")
    last_per_day, previous = {}, None
    for item in observations:
        if type(item) not in (tuple, list) or len(item) != 2:
            raise ValueError("malformed shadow equity mark")
        try:
            at, value = parse_ts(item[0]), Decimal(item[1])
        except (ArithmeticError, TypeError):
            raise ValueError("malformed shadow equity mark") from None
        if previous is not None and at <= previous:
            raise ValueError("shadow equity marks must be strictly chronological")
        previous = at
        if not value.is_finite() or value <= 0:
            raise ValueError("shadow equity mark must be positive and finite")
        if at < before:
            last_per_day[at.date()] = value
    rows = []
    ordered = sorted(last_per_day)
    for left, right in pairwise(ordered):
        if right - left != timedelta(days=1):
            continue
        p0, p1 = last_per_day[left], last_per_day[right]
        rows.append({"day": right.isoformat(), "return": +(p1 / p0 - 1)})
    return rows


def shadow_drift(historical, shadow, *, observed_at):
    """Evaluate daily shadow returns vs fixed prior mean and two-sigma bound.

    This produces an immutable candidate for a paper admission block, not a
    background monitor, venue order, portfolio mutation or funded demotion.
    """
    if observed_at.tzinfo is None or type(historical) is not dict or type(shadow) is not dict:
        raise ValueError("shadow drift requires verified chronological paper artifacts")
    original, forward = historical["inputs"], shadow["inputs"]
    same = ("symbol", "strategy", "config_hash", "resolution", "cash",
            "cost", "rules_mode", "store")
    if (forward.get("kind") != "live-session"
            or any(original.get(k) != forward.get(k) for k in same)
            or parse_ts(original["to"]) > parse_ts(forward["from"])
            or parse_ts(original["to"]) > observed_at
            or original.get("kind") == "live-session"):
        raise ValueError("shadow drift needs matching disjoint historical and prospective paper artifacts")
    past = _daily_returns(historical, before=parse_ts(original["to"]) + timedelta(microseconds=1))
    future = _daily_returns(shadow, before=observed_at)
    report = {
        "schema": "paper-shadow-drift/1", "historical_run_id": historical["run_id"],
        "historical_outputs_digest": historical["outputs_digest"],
        "shadow_run_id": shadow["run_id"], "shadow_outputs_digest": shadow["outputs_digest"],
        "config_hash": original["config_hash"], "observed_at": iso(observed_at),
        "historical_days": len(past), "shadow_days": len(future),
        "mean_prior_daily_return": None, "sigma_prior_daily_return": None,
        "status": "INSUFFICIENT_HISTORY", "alerts": [], "daily_scores": [],
        "promotion_blocked": True, "funded_authority": False,
        "monitoring_automatic": False, "entry_lock_recorded": False,
        "limitations": [
            "A matched local paper replay cannot validate future funded Sharpe or custody.",
            "Only consecutive UTC-day equity marks yield a complete return; gaps are omitted, not interpolated.",
            "One or more daily returns below the fixed two-sigma lower bound blocks local promotion.",
            "This is on-demand paper evidence, not an always-on monitor or protected-executor demotion.",
        ]}
    if len(past) < 20:
        report["report_id"] = digest(report)[:16]
        return report
    with localcontext() as context:
        context.prec = 60
        values = [row["return"] for row in past]
        mean = sum(values, Decimal(0)) / len(values)
        stdev = (sum(((value - mean) ** 2 for value in values), Decimal(0))
                 / (len(values) - 1)).sqrt()
        report["mean_prior_daily_return"] = str(+mean)
        report["sigma_prior_daily_return"] = str(+stdev)
        if stdev <= Decimal("1e-20"):
            # Finite-precision cumulative equity can leave sub-ULP noise
            # even when every economic daily return is identical.
            report["status"] = "UNIDENTIFIABLE_BASELINE"
        elif not future:
            report["status"] = "NO_COMPLETE_SHADOW_DAYS"
        else:
            for item in future:
                z = (item["return"] - mean) / stdev
                score = {"day": item["day"], "daily_return": str(+item["return"]),
                         "z_score": str(+z), "lower_bound_sigma": "-2"}
                report["daily_scores"].append(score)
                if z < -2:
                    report["alerts"].append({**score, "action": "PAPER_ONLY_DEMOTION"})
            report["status"] = "PAPER_ONLY_DEMOTION" if report["alerts"] else "WITHIN_BAND"
            report["promotion_blocked"] = bool(report["alerts"])
    report["report_id"] = digest(report)[:16]
    return report
