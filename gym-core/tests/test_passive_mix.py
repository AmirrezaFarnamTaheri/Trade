"""The passive mix carries prices over closed days, sizes by inverse volatility within a cap, and rebalances only past its band."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("passive_mix", SCRIPTS / "passive_mix.py")
mix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mix)


def test_the_calmer_asset_gets_more_weight_and_the_total_never_exceeds_one():
    returns = {"calm": [0.0] + [0.001 * (-1) ** k for k in range(100)], "wild": [0.0] + [0.03 * (-1) ** k for k in range(100)]}
    weights = mix.targets(returns, 80)
    assert weights["calm"] > weights["wild"] and sum(weights.values()) <= 1 + 1e-12


def test_closed_days_carry_the_last_close_and_the_series_starts_when_every_asset_has_one():
    days, table = mix.aligned({"a": {"2016-11-18": 1.0, "2016-11-21": 2.0}, "b": {"2016-11-19": 5.0}})
    assert days[0] == "2016-11-19" and table["a"][:3] == [1.0, 1.0, 2.0] and table["b"][:3] == [5.0, 5.0, 5.0]


def test_a_flat_market_after_the_first_rebalance_costs_only_the_entry():
    days = [f"2020-{1 + k // 28:02d}-{1 + k % 28:02d}" for k in range(200)]
    prices = {"a": [100.0 * (1 + 0.01 * ((k % 2) - 0.5)) for k in range(200)], "b": [50.0] * 200}
    rows, turnover = mix.run(days, prices)
    assert turnover > 0 and rows[0][1] == pytest.approx(-mix.COST * turnover, abs=0.02)
