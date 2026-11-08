"""Phase B item 19: one strictly causal high-low Parkinson variance."""
from decimal import Decimal, localcontext

import pytest

from gym.domain.sim import CostModel
from gym.domain.volatility import ParkinsonEWMA, parkinson_ewma


def test_parkinson_matches_hand_worked_constant_range_and_ewma():
    with localcontext() as context:
        context.prec = 60
        ln2 = Decimal(2).ln()
        first_variance = ln2 / 4
        second_variance = Decimal("0.5") * first_variance
        sigma = parkinson_ewma([(Decimal(2), Decimal(1)), (Decimal(1), Decimal(1))],
                               decay=Decimal("0.5"))
        assert abs(sigma ** 2 - second_variance) < Decimal("1e-55")
        assert abs(parkinson_ewma([(2, 1)], decay=Decimal("0.5")) ** 2 - first_variance) < Decimal("1e-55")


def test_future_ranges_do_not_modify_past_volatility():
    process = ParkinsonEWMA()
    prefix = process.update("110", "100")
    process.update("150", "90")
    assert prefix == parkinson_ewma([("110", "100")])
    assert process.count == 2
    for high, low in (("0", "1"), ("NaN", "1"), ("1", "2")):
        with pytest.raises(ValueError):
            process.update(high, low)


def test_volatility_sizing_is_opt_in_and_requires_closed_ranges():
    default = CostModel(vol_target=Decimal("0.02"), vol_lookback=5)
    assert "volatility_model" not in default.describe()
    model = CostModel(vol_target=Decimal("0.02"), vol_lookback=5,
                      volatility_model="parkinson-ewma")
    assert model.describe()["volatility_model"] == "parkinson-ewma"
    assert CostModel.from_description(model.describe()) == model
    assert model.size(Decimal(1), [Decimal(100)] * 6) == 0
    ranges = [(Decimal(110), Decimal(100))] * 5
    value = model.size(Decimal(1), [Decimal(100)] * 6, ranges=ranges)
    assert Decimal(0) < value < Decimal(1)
    with pytest.raises(ValueError, match="unsupported volatility"):
        CostModel(volatility_model="invented")
