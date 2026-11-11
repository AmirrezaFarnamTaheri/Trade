"""Causal Ledoit-Wolf constant-correlation shrinkage, off by default."""
from decimal import Decimal, localcontext

import pytest

from gym.domain.covariance_models import ledoit_wolf_constant_correlation
from gym.domain.portfolio_policy import PortfolioPolicy


@pytest.mark.parametrize("second", [("-1", "-2", "-3"), ("1", "2", "3.000000000000000000000000000001")])
def test_minimum_sample_retains_exact_covariance_and_column_order(second):
    observations = [[Decimal(i + 1), Decimal(value)] for i, value in enumerate(second)]
    with localcontext() as context:
        context.prec = 60
        columns = list(zip(*observations))
        means = [sum(column) / 3 for column in columns]
        expected = [[sum((row[i] - means[i]) * (row[j] - means[j]) for row in observations) / 2
                     for j in range(2)] for i in range(2)]
        result = ledoit_wolf_constant_correlation(observations)
        assert result["sample"] == expected
        reversed_result = ledoit_wolf_constant_correlation([list(reversed(row)) for row in observations])
        for key in ("sample", "target", "covariance"):
            assert reversed_result[key] == [list(reversed(row)) for row in reversed(result[key])]
        assert reversed_result["intensity"] == result["intensity"]


def test_constant_correlation_shrinkage_has_bounded_intensity_and_preserves_variances():
    # Each column is a return series; no future observations are supplied.
    observations = [
        [Decimal(x) / 100 for x in row]
        for row in ((2, 1, -1), (-1, 2, 2), (3, 0, -2), (-2, -1, 3),
                    (1, 3, -2), (0, -3, 1), (2, 2, 0), (-1, -2, -1))
    ]
    result = ledoit_wolf_constant_correlation(observations)
    s, f, c, shrink = (result[key] for key in ("sample", "target", "covariance", "intensity"))
    assert Decimal(0) <= shrink <= Decimal(1)
    assert len(c) == 3
    for i in range(3):
        assert c[i][i] == s[i][i] == f[i][i]
        for j in range(3):
            assert c[i][j] == c[j][i]
            assert abs(c[i][j] - (1 - shrink) * s[i][j] - shrink * f[i][j]) < Decimal("1e-24")
    assert shrink > 0  # short/noisy sample must shrink toward target


def test_empty_short_and_degenerate_inputs_are_explicit():
    for data in ([], [[Decimal(1), Decimal(2)]],
                 [[Decimal(1)] for _ in range(8)],
                 [[Decimal(0), Decimal(0)] for _ in range(8)]):
        with pytest.raises(ValueError):
            ledoit_wolf_constant_correlation(data)


def test_shrinkage_reports_actual_target_turnover_against_raw_counterfactual():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    r = [
        (2, 1, -1), (-1, 2, 2), (3, 0, -2), (-2, -1, 3),
        (1, 3, -2), (0, -3, 1), (2, 2, 0), (-1, -2, -1),
        (3, -2, 1), (-2, 2, 0), (1, -1, 2),
    ]
    prices = [[Decimal(100)] for _ in symbols]
    for bar in r:
        for i, pct in enumerate(bar):
            prices[i].append(prices[i][-1] * (1 + Decimal(pct) / 100))
    all_rows = {symbol: [(i, value) for i, value in enumerate(prices[k])]
                for k, symbol in enumerate(symbols)}
    model = PortfolioPolicy({"method": "inverse-volatility", "lookback": 8,
                             "covariance_shrinkage": "ledoit-wolf-constant-correlation"},
                            symbols)
    first = model.weights({s: rows[:9] for s, rows in all_rows.items()})
    second = model.weights({s: rows[1:10] for s, rows in all_rows.items()})
    shrink = second["covariance_shrinkage"]
    assert first["status"] == second["status"] == "READY"
    assert shrink["target"] == "constant-correlation"
    assert shrink["turnover_raw"] is not None
    assert shrink["turnover_shrunk"] is not None
    assert Decimal(shrink["turnover_raw"]) >= 0
    assert Decimal(shrink["turnover_shrunk"]) >= 0
    assert Decimal(0) < Decimal(shrink["intensity"]) <= 1
    # Shrinkage preserves the sample covariance diagonal by construction. Pure
    # inverse-volatility weights therefore stay identical; risk-parity and
    # correlation decisions can change when off-diagonal structure changes.
    assert second["weights"] == PortfolioPolicy(
        {"method": "inverse-volatility", "lookback": 8}, symbols
    ).weights({s: rows[1:10] for s, rows in all_rows.items()})["weights"]


def test_shrinkage_invalid_option_and_legacy_identity_are_unchanged():
    with pytest.raises(ValueError, match="shrinkage"):
        PortfolioPolicy({"covariance_shrinkage": "invented"}, ["A", "B"])
    policy = PortfolioPolicy({"method": "equal"}, ["A", "B"])
    assert "covariance_shrinkage" not in policy.description
    assert "covariance_shrinkage" not in policy.weights({})
