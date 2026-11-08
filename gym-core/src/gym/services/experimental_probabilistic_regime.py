"""Research-only, causal three-state regime probabilities with no strategy promotion.

The baseline fixed ADX gate remains in production paper registry. This module
is intentionally separate from the live/paper strategy factory and cannot
submit orders or grant trading permissions.
"""
from datetime import datetime
from decimal import Decimal, localcontext

from ..domain.model import iso, parse_ts
from ..domain.strategy import digest

_STATES = ("DOWN_TREND", "RANGE", "UP_TREND")


def _strict_decimal(value, label, *, positive=False):
    if type(value) not in (str, int, Decimal):
        raise ValueError("invalid regime " + label)
    try:
        number = Decimal(value)
    except (ValueError, ArithmeticError):
        raise ValueError("invalid regime " + label) from None
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError("invalid regime " + label)
    return number


def fit_regime_experiment(training, *, training_end: datetime):
    """Learn three descriptive trend/volatility states from past observations only.

    This is a bounded empirical Gaussian-discriminant baseline, not an HMM.
    It is fit with chronological observations and cannot be selected as a
    trading gate without independently verified, preregistered OOS evidence.
    """
    if (type(training) not in (list, tuple) or not 30 <= len(training) <= 10000
            or not isinstance(training_end, datetime) or training_end.tzinfo is None):
        raise ValueError("regime training needs 30..10000 historical observations and an aware cutoff")
    readings, previous = [], None
    for item in training:
        if type(item) is not dict or set(item) != {"available_at", "trend", "volatility"}:
            raise ValueError("invalid regime observation fields")
        at = parse_ts(item["available_at"])
        if at >= training_end:
            raise ValueError("future observation unavailable at regime training cutoff")
        if previous is not None and at <= previous:
            raise ValueError("regime observations must be strictly chronological")
        previous = at
        readings.append((at, _strict_decimal(item["trend"], "trend"),
                         _strict_decimal(item["volatility"], "volatility", positive=True)))
    with localcontext() as context:
        context.prec = 60
        ranks = sorted(readings, key=lambda row: row[1])
        n = len(ranks)
        splits = (ranks[:n // 3], ranks[n // 3:2 * n // 3], ranks[2 * n // 3:])
        centers, variances = {}, {}
        for name, group in zip(_STATES, splits):
            m = Decimal(len(group))
            mt = sum((r[1] for r in group), Decimal(0)) / m
            mv = sum((r[2] for r in group), Decimal(0)) / m
            vt = sum(((r[1] - mt) ** 2 for r in group), Decimal(0)) / m
            vv = sum(((r[2] - mv) ** 2 for r in group), Decimal(0)) / m
            centers[name] = {"trend": str(+mt), "volatility": str(+mv)}
            # A fixed, declared ridge prevents pretending zero variance yields
            # certainty. It is research calibration, not a learned confidence.
            variances[name] = {"trend": str(+(vt + Decimal("0.01"))),
                               "volatility": str(+(vv + Decimal("0.01")))}
        result = {"schema": "probabilistic-regime-research/1", "states": list(_STATES),
                  "training_end": iso(training_end), "observations": n,
                  "centers": centers, "variances": variances,
                  "selection": "three equal-count trend terciles; diagonal Gaussian likelihood with fixed 0.01 ridge",
                  "selectable": False, "funded_authority": False,
                  "status": "EXPERIMENTAL_NOT_PROMOTED",
                  "limitations": [
                      "These descriptive probabilities are not calibrated predictive probabilities.",
                      "The fixed ADX gate remains the only regime gate in the strategy catalog.",
                      "No model is eligible without separate prospective, preregistered out-of-sample evidence."]}
        result["model_id"] = digest(result)[:16]
        return result


def regime_probabilities(model, *, trend: Decimal, volatility: Decimal, at: datetime):
    """Score an available observation with an already-fit research model."""
    if (type(model) is not dict or model.get("schema") != "probabilistic-regime-research/1"
            or model.get("selectable") is not False or
            not isinstance(at, datetime) or at.tzinfo is None):
        raise ValueError("invalid experimental regime model or scoring time")
    if at < parse_ts(model["training_end"]):
        raise ValueError("future-trained regime model cannot score past observations")
    trend = _strict_decimal(trend, "trend")
    volatility = _strict_decimal(volatility, "volatility", positive=True)
    with localcontext() as context:
        context.prec = 60
        scores = {}
        for state in _STATES:
            center, variance = model["centers"][state], model["variances"][state]
            scores[state] = -(
                (trend - Decimal(center["trend"])) ** 2 / Decimal(variance["trend"])
                + (volatility - Decimal(center["volatility"])) ** 2 / Decimal(variance["volatility"])
            ) / 2
        highest = max(scores.values())
        likelihoods = {state: (score - highest).exp() for state, score in scores.items()}
        total = sum(likelihoods.values())
        return {state: +(likelihoods[state] / total) for state in _STATES}


def review_regime_prospective_evidence(candidate, baseline, *,
                                       independent_final_evidence,
                                       prospective_registration_ids, spa_p_value):
    """Reject promotion without a verified registered OOS test against fixed ADX.

    Supplied arrays/labels are not trustworthy evidence of independent
    registration or provenance. A promising exploratory result only triggers
    a manual review; it never adds a strategy or grants funded authority.
    """
    if (type(candidate) not in (list, tuple) or type(baseline) not in (list, tuple)
            or len(candidate) != len(baseline) or len(candidate) > 10000
            or type(prospective_registration_ids) is not list
            or any(type(r) is not str or not r for r in prospective_registration_ids)):
        raise ValueError("invalid prospective regime comparison")
    probability = _strict_decimal(spa_p_value, "SPA p-value")
    if probability > 1:
        raise ValueError("invalid SPA p-value")
    verified = (independent_final_evidence is True and len(candidate) >= 20
                and bool(prospective_registration_ids)
                and all(type(v) is Decimal and v.is_finite() for v in (*candidate, *baseline)))
    better = verified and sum(candidate) > sum(baseline) and probability < Decimal("0.05")
    return {"schema": "regime-promotion-review/1", "status": "NOT_PROMOTED",
            "decision": "MANUAL_INDEPENDENT_REVIEW_REQUIRED" if better else "REMOVE_EXPERIMENTAL_GATE",
            "candidate_observations": len(candidate), "matched_oos_claim": verified,
            "fixed_adx_baseline": True, "probabilistic_gate_selectable": False,
            "funded_authority": False,
            "reason": ("User-supplied registrations and outcomes do not independently certify provenance"
                       if better else "Independent preregistration, sufficient observations, and a positive corrected OOS comparison are required")}
