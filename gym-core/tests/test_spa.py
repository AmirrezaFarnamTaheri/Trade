"""SPA-style familywise bootstrap controls misleading multi-strategy noise claims."""

from random import Random

import pytest

from gym.services import spa
from gym.services.spa import stationary_spa


def test_stationary_spa_null_families_are_seldom_significant():
    """Pure Gaussian noise must fail to reject the null in >=90% of seeded families."""
    abstained = 0
    for seed in range(20):
        rng = Random(seed)
        returns = {str(k): [rng.gauss(0, 1) for _ in range(100)] for k in range(4)}
        outcome = stationary_spa(returns, seed=seed)
        assert outcome["simulations"] == 199 and outcome["status"] == "EXPLORATORY"
        abstained += outcome["p_value"] > 0.1
    assert abstained >= 18


def test_stationary_spa_abstains_on_short_or_unchanging_samples():
    """Do not assign confidence to unobserved or zero-variance excess paths."""
    short = {"A": [0.001] * 10, "B": [0.002] * 10}
    assert stationary_spa(short)["status"] == "INSUFFICIENT_DATA"
    zero = {"A": [0.0] * 30, "B": [0.0] * 30}
    assert stationary_spa(zero)["status"] == "INSUFFICIENT_VARIATION"


@pytest.mark.parametrize("periods,candidates,seed", [(20, 2, 0), (100, 4, 3), (2000, 8, 42)])
def test_vector_gather_preserves_scalar_bootstrap_exactly(monkeypatch, periods, candidates, seed):
    rng = Random(seed)
    excess = {str(k): [rng.gauss(.001, .02) for _ in range(periods)] for k in range(candidates)}
    vector = stationary_spa(excess, simulations=100, seed=seed)
    # The original Python generator is the reference for the changed gather boundary.
    monkeypatch.setattr(spa, "itemgetter", lambda *indices: lambda values: (values[j] for j in indices))
    assert vector == stationary_spa(excess, simulations=100, seed=seed)


@pytest.mark.parametrize("values", [
    [0.0] * 40,
    [1e16, 1.0, -1e16, -1.0] * 10,
    [1e150, -1e150, 1e-150, -1e-150] * 10,
])
def test_vector_gather_preserves_ties_degeneracy_and_finite_extremes(monkeypatch, values):
    excess = {"second": values, "first": list(values)}
    vector = stationary_spa(excess, simulations=100, seed=4)
    monkeypatch.setattr(spa, "itemgetter", lambda *indices: lambda column: (column[j] for j in indices))
    assert vector == stationary_spa(excess, simulations=100, seed=4)


def test_vector_gather_keeps_validation_and_overflow_observable():
    with pytest.raises(ValueError, match="2..8 candidates"):
        stationary_spa({"only": [0.0] * 20})
    with pytest.raises(ValueError, match="budget"):
        stationary_spa({"A": [0.0] * 20, "B": [0.0] * 20}, simulations=99)
    assert stationary_spa({"A": [float("nan")] * 20, "B": [0.0] * 20})["status"] == "INSUFFICIENT_DATA"
    with pytest.raises(OverflowError):
        stationary_spa({"A": [1e308] * 20, "B": [1e308] * 20}, simulations=100)
