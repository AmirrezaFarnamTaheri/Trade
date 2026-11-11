"""Fixed paper promotion criteria as a non-authoritative paper review screen."""
from ..domain.market_models import decimal, fields
from ..domain.strategy import digest

EXTERNAL_GATES = (
    "INDEPENDENT_PREREGISTRATION_CUSTODY",
    "INDEPENDENT_PROSPECTIVE_FINAL_HOLDOUT",
    "AUTHENTICATED_VENUE_COSTS_AND_SETTLEMENT",
    "PROTECTED_EXECUTOR_ACCOUNT_READINESS",
    "EXPLICIT_OPERATOR_APPROVAL_AND_ZERO_TO_NONZERO_LOSS_BUDGET",
)


def promotion_screen(request):
    """Evaluate fixed thresholds without accepting self-certified funded authority.

    Supplied local evidence can fail a gate, but cannot be treated as an
    independently verified pass. The external executor approval path is
    never invoked and the initial authorized funded loss budget stays zero.
    """
    fields(request, "deflated_sharpe_probability closed_trades track_record_days "
           "spa_p_value prospective_status shadow_status shadow_days")
    dsr = decimal(request["deflated_sharpe_probability"], "deflated Sharpe probability")
    spa = decimal(request["spa_p_value"], "SPA p-value")
    if dsr > 1 or spa > 1:
        raise ValueError("promotion probabilities must be between zero and one")
    for key in ("closed_trades", "track_record_days", "shadow_days"):
        if type(request[key]) is not int or not 0 <= request[key] <= 10000000:
            raise ValueError("promotion history counts must be bounded integers")
    if (request["prospective_status"] not in ("PASS", "FAIL", "UNAVAILABLE")
            or request["shadow_status"] not in ("WITHIN_BAND", "PAPER_ONLY_DEMOTION",
                                                "INSUFFICIENT_HISTORY", "UNAVAILABLE")):
        raise ValueError("unknown paper promotion evidence status")
    checks = {
        "deflated_sharpe_probability_95pct": dsr >= decimal("0.95"),
        "closed_positions_300": request["closed_trades"] >= 300,
        "track_record_90_days": request["track_record_days"] >= 90,
        "spa_familywise_p_value_at_most_5pct": spa <= decimal("0.05"),
        "prospective_disjoint_pass": request["prospective_status"] == "PASS",
        "shadow_20_days_within_2sigma": (
            request["shadow_status"] == "WITHIN_BAND" and request["shadow_days"] >= 20),
    }
    all_local = all(checks.values())
    result = {
        "schema": "paper-promotion-gates/1", "criteria_version": 1,
        "fixed_thresholds": {"dsr": "0.95", "closed_trades": 300,
                             "track_record_days": 90, "spa_max_p": "0.05",
                             "shadow_days": 20, "shadow_lower_band_sigma": "-2"},
        "source": "UNATTESTED_LOCAL_RESEARCH_INPUT",
        "local_inputs": request, "checks": checks,
        "local_criteria_pass": all_local,
        "failed_checks": [key for key, passed in checks.items() if not passed],
        "status": ("INDEPENDENT_EVIDENCE_REQUIRED" if all_local else "BLOCKED_LOCAL_GATES"),
        "missing_external_gates": list(EXTERNAL_GATES),
        "independent_evidence_verified": False,
        "operator_approval": False, "promotion_eligible": False,
        "funded_authority": False, "submit_allowed": False, "funded_loss_budget": "0",
        "limitations": [
            "These are fixed prospective screening thresholds, not calculated DSR or SPA evidence.",
            "Self-supplied local numbers cannot demonstrate independent evaluation or venue fills.",
            "No action records a protected executor approval, changes a live strategy, or submits an order.",
            "Item 43 executor recovery/admission is an external prerequisite, not implemented here.",
        ],
    }
    result["report_id"] = digest(result)[:16]
    return result
