"""Hand-worked two-cluster hierarchical risk parity regression."""
from decimal import Decimal

from gym.domain.hrp import hierarchical_risk_parity


def test_equal_variance_two_cluster_case_has_calculable_exact_allocation():
    """Left cluster variance 3.8, right 0.95; divide their risk inversely."""
    cov = [[Decimal(v) for v in row] for row in (
        (4, "3.6", 0, 0),
        ("3.6", 4, 0, 0),
        (0, 0, 1, "0.9"),
        (0, 0, "0.9", 1),
    )]
    weights, order = hierarchical_risk_parity(cov)
    assert order == [0, 1, 2, 3]
    expected = [Decimal("0.1"), Decimal("0.1"),
                Decimal("0.4"), Decimal("0.4")]
    assert all(abs(actual - target) < Decimal("1e-25")
               for actual, target in zip(weights, expected))
    assert sum(weights, Decimal(0)) == 1
