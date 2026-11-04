"""Availability-cut forecast scoring; scores supplied observations, never generates forecasts."""
from decimal import Decimal

from .market_models import decimal, fields, instant


def forecast_calibration(as_of, observations):
    cutoff = instant(as_of)
    if type(observations) is not list or not 1 <= len(observations) <= 1000:
        raise ValueError("need 1..1000 forecast observations")
    errors, coverage, briers, seen, pending = [], [], [], set(), 0
    for row in observations:
        fields(row, "forecast_id issued_at target_at resolved_at prediction reference actual lower upper up_probability")
        key = row["forecast_id"]
        if type(key) is not str or not 1 <= len(key) <= 96 or key in seen:
            raise ValueError("forecasts require distinct bounded IDs")
        seen.add(key)
        issued, target = instant(row["issued_at"]), instant(row["target_at"])
        if not issued < target:
            raise ValueError("forecast must be issued before its target")
        prediction = decimal(row["prediction"], "prediction", positive=True)
        reference = decimal(row["reference"], "reference", positive=True)
        lower, upper = row["lower"], row["upper"]
        if (lower is None) != (upper is None):
            raise ValueError("forecast intervals require both bounds")
        if lower is not None:
            lower, upper = decimal(lower, "lower"), decimal(upper, "upper")
            if lower > upper:
                raise ValueError("forecast interval bounds are reversed")
        probability = None if row["up_probability"] is None else decimal(row["up_probability"], "up_probability")
        if probability is not None and probability > 1:
            raise ValueError("probability must be between zero and one")
        if (row["actual"] is None) != (row["resolved_at"] is None):
            raise ValueError("actual values require a resolution timestamp")
        if issued > cutoff or row["resolved_at"] is None:
            pending += 1
            continue
        resolved = instant(row["resolved_at"])
        if resolved < target:
            raise ValueError("outcome cannot resolve before target time")
        if resolved > cutoff:
            pending += 1
            continue
        actual = decimal(row["actual"], "actual", positive=True)
        errors.append((prediction - actual, abs(prediction - actual) / actual))
        if lower is not None:
            coverage.append(lower <= actual <= upper)
        if probability is not None:
            briers.append((probability - int(actual > reference)) ** 2)
    count = len(errors)
    return {"status": "SCORED" if count else "UNAVAILABLE", "as_of": as_of, "resolved_forecasts": count,
            "pending_forecasts": pending, "mean_absolute_error": sum(abs(e) for e, _ in errors) / count if count else None,
            "root_mean_squared_error": (sum(e * e for e, _ in errors) / count).sqrt() if count else None,
            "mean_absolute_percentage_error": sum(p for _, p in errors) / count * 100 if count else None,
            "interval_samples": len(coverage), "interval_coverage_fraction": Decimal(sum(coverage)) / len(coverage) if coverage else None,
            "probability_samples": len(briers), "brier_score": sum(briers) / len(briers) if briers else None,
            "event_definition": "actual > reference", "inputs_verified": False,
            "independent_evaluation_verified": False,
            "limitation": "Supplied timestamped forecasts/outcomes only; future and unresolved outcomes are excluded. "
                          "Interval coverage is empirical, without an assumed nominal level; this is not proof of calibration, "
                          "independent selection, feed authenticity, forecast profitability or a trading recommendation."}
