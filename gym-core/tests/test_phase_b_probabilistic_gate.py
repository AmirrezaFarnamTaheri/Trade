"""Phase B 24: fail-closed probabilistic regime *research*, never a live gate."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import iso
from gym.domain.registry import catalog
from gym.services.experimental_probabilistic_regime import (
    fit_regime_experiment,
    regime_probabilities,
    review_regime_prospective_evidence,
)
from tests.support import START


def training():
    return [{"available_at": iso(START + timedelta(minutes=i)),
             "trend": str(Decimal(-2) if i < 20 else Decimal(0) if i < 40 else Decimal(2)),
             "volatility": str(Decimal("1.2") if i % 2 else Decimal("0.8"))}
            for i in range(60)]


def test_experimental_three_state_probabilities_are_causal_and_sum_to_one():
    cutoff = START + timedelta(minutes=61)
    model = fit_regime_experiment(training(), training_end=cutoff)
    assert model["schema"] == "probabilistic-regime-research/1"
    assert model["selectable"] is False
    up = regime_probabilities(model, trend=Decimal(2), volatility=Decimal(1),
                              at=cutoff + timedelta(minutes=1))
    down = regime_probabilities(model, trend=Decimal(-2), volatility=Decimal(1),
                                at=cutoff + timedelta(minutes=1))
    assert up["UP_TREND"] > up["RANGE"]
    assert down["DOWN_TREND"] > down["RANGE"]
    assert abs(sum(up.values()) - 1) < Decimal("1e-20")
    with pytest.raises(ValueError, match="future"):
        regime_probabilities(model, trend=Decimal(2), volatility=Decimal(1),
                             at=START + timedelta(minutes=10))


def test_training_rejects_future_or_insufficient_measurements():
    with pytest.raises(ValueError):
        fit_regime_experiment(training()[:10],
                              training_end=START + timedelta(minutes=61))
    with pytest.raises(ValueError, match="future"):
        fit_regime_experiment(training(),
                              training_end=START + timedelta(minutes=50))


def test_apparent_in_sample_win_cannot_promote_a_new_regime_gate():
    candidate = [Decimal(10)] * 30
    baseline = [Decimal(1)] * 30
    rejection = review_regime_prospective_evidence(
        candidate, baseline, independent_final_evidence=False,
        prospective_registration_ids=[], spa_p_value=Decimal("0.001"))
    assert rejection["status"] == "NOT_PROMOTED"
    assert rejection["funded_authority"] is False
    assert all("probabilistic" not in entry["id"] for entry in catalog())


def test_unproven_or_weak_oos_candidate_is_not_retained():
    candidate = [Decimal(1)] * 30
    baseline = [Decimal(2)] * 30
    report = review_regime_prospective_evidence(
        candidate, baseline, independent_final_evidence=True,
        prospective_registration_ids=["prospective-1"], spa_p_value=Decimal("0.2"))
    assert report["status"] == "NOT_PROMOTED"
    assert report["decision"] == "REMOVE_EXPERIMENTAL_GATE"
