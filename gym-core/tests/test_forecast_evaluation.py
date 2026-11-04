from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.market_models import evaluate_artifact
from tests.support import START


def row(key="one"):
    return {"forecast_id": key, "issued_at": START.isoformat(), "target_at": (START + timedelta(hours=1)).isoformat(),
            "resolved_at": (START + timedelta(hours=2)).isoformat(), "prediction": "110", "reference": "100",
            "actual": "120", "lower": "105", "upper": "115", "up_probability": "0.8"}


def evaluate(rows, at=START + timedelta(hours=3)):
    return evaluate_artifact({"model": "forecast-calibration", "parameters": {"as_of": at.isoformat(), "observations": rows}})["result"]


def test_real_resolved_arithmetic_and_future_outcomes_are_excluded():
    future = {**row("future"), "resolved_at": (START + timedelta(days=1)).isoformat(), "actual": "999999"}
    out = evaluate([row(), future])
    assert out["resolved_forecasts"] == out["pending_forecasts"] == 1
    assert out["mean_absolute_error"] == out["root_mean_squared_error"] == 10
    assert out["interval_coverage_fraction"] == 0 and out["brier_score"] == Decimal("0.04")
    assert not out["independent_evaluation_verified"]
    assert evaluate([row()], START)["status"] == "UNAVAILABLE"


def test_absent_interval_probability_and_outcome_stay_unavailable():
    item = {**row(), "lower": None, "upper": None, "up_probability": None}
    out = evaluate([item])
    assert out["interval_coverage_fraction"] is out["brier_score"] is None
    item.update(actual=None, resolved_at=None)
    out = evaluate([item])
    assert out["resolved_forecasts"] == 0 and out["mean_absolute_error"] is None


@pytest.mark.parametrize("change", [{"prediction": "NaN"}, {"resolved_at": START.isoformat()},
    {"up_probability": "1.1"}, {"lower": None}, {"actual": None}, {"target_at": START.isoformat()}])
def test_malformed_forecasts_do_not_receive_scores(change):
    with pytest.raises(ValueError):
        evaluate([{**row(), **change}])
