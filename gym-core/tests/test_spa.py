"""SPA-style familywise bootstrap controls misleading multi-strategy noise claims."""

from random import Random

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
