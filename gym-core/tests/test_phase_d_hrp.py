"""Phase D item 36: deterministic Decimal hierarchical risk parity."""
from decimal import Decimal

import pytest

from gym.domain.hrp import hierarchical_risk_parity
from gym.domain.portfolio_policy import PortfolioPolicy


def test_two_cluster_hrp_follows_correlated_neighbours_not_original_order():
    """Known high-within, low-between correlation yields adjacent cluster leaves."""
    cov = [[Decimal(v) for v in row] for row in
           ((4, "0.2", "3.6", "0.2"),
            ("0.2", 1, "0.2", "0.9"),
            ("3.6", "0.2", 4, "0.2"),
            ("0.2", "0.9", "0.2", 1))]
    weights, order = hierarchical_risk_parity(cov)
    pos = {leaf: i for i, leaf in enumerate(order)}
    assert abs(pos[0] - pos[2]) == 1
    assert abs(pos[1] - pos[3]) == 1
    assert sum(weights, Decimal(0)) == 1
    assert all(w > 0 for w in weights)
    assert weights[1] + weights[3] > weights[0] + weights[2]
    assert hierarchical_risk_parity(cov) == (weights, order)


def test_hrp_is_opt_in_and_reports_cluster_order():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    samples = (
        (100, 105, 104, 109),
        (100, 102, 97, 104),
        (100, 104, 103, 108),
        (100, 103, 98, 106),
    )
    observations = {symbol: [(i, Decimal(px)) for i, px in enumerate(series)]
                    for symbol, series in zip(symbols, samples)}
    policy = PortfolioPolicy({"method": "hierarchical-risk-parity", "lookback": 3}, symbols)
    result = policy.weights(observations)
    assert result["status"] == "READY"
    assert set(result["hierarchical_risk_parity"]["leaf_order"]) == set(symbols)
    assert sum(map(Decimal, result["weights"].values())) <= 1
    assert PortfolioPolicy({}, symbols).description["method"] == "equal"


def test_hrp_rejects_degenerate_matrix_and_unbounded_universe():
    with pytest.raises(ValueError):
        hierarchical_risk_parity([[Decimal(1), Decimal(2)], [Decimal(2), Decimal(1)]])
    with pytest.raises(ValueError):
        PortfolioPolicy({"method": "hierarchical-risk-parity"}, [f"A{i}USDT" for i in range(101)])
