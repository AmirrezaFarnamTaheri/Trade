"""Configurable rules retain legacy defaults and causal readiness."""
from decimal import Decimal

import pytest

from gym.domain.registry import catalog, create_strategy
from gym.domain.strategy import Snapshot, digest
from tests.test_technical_features import bar


@pytest.mark.parametrize("name,params,key,required", [
    ("rsi-rebound", {"period": 3, "entry_threshold": 35, "exit_threshold": 65}, "rsi_3", 4),
    ("macd-cross", {"fast": 2, "slow": 4, "signal": 2}, "macd_2_4_2", 5),
    ("trix-cross", {"period": 3, "signal": 2}, "trix_3_2", 9),
    ("keltner-breakout", {"ema_period": 3, "range_period": 3, "multiplier": 3, "adx_threshold": 20}, "keltner_3_3_3", 4),
])
def test_custom_rules_publish_parameters_readiness_and_identity(name, params, key, required):
    strategy = create_strategy(name, params)
    assert strategy.params == params and strategy.version == 2
    assert strategy.config_hash != create_strategy(name).config_hash
    for i in range(40):
        b = bar(i, str(100 + i % 7))
        strategy.decide(Snapshot(b.avail, b.symbol, b, b.close - 1, b.close + 1, b.avail), False)
        feature = strategy.feature_values[key]
        assert feature["required_bars"] == required
        assert (feature["status"] == "AVAILABLE") == (i + 1 >= required)
    b = bar(100, "110")
    assert strategy.decide(Snapshot(b.avail, b.symbol, b, b.close - 1, b.close + 1, b.avail), False)[0] == "ABSTAIN_WARMUP"
    assert key in strategy.feature_values


def test_default_parameter_forms_keep_prior_configuration_hashes():
    for item in catalog():
        if item["id"] not in ("rsi-rebound", "macd-cross", "trix-cross", "keltner-breakout"):
            continue
        defaults = {key: spec["default"] for key, spec in item["parameters"]["properties"].items()}
        assert defaults
        legacy = digest({"strategy": item["id"], "version": 1, "params": {}})
        assert create_strategy(item["id"]).config_hash == legacy == create_strategy(item["id"], defaults).config_hash


@pytest.mark.parametrize("name,params", [
    ("rsi-rebound", {"period": True}), ("rsi-rebound", {"period": 0}),
    ("rsi-rebound", {"entry_threshold": 80, "exit_threshold": 20}),
    ("macd-cross", {"fast": 30, "slow": 12}), ("macd-cross", {"signal": 501}),
    ("trix-cross", {"signal": 0}), ("keltner-breakout", {"multiplier": Decimal("NaN")}),
])
def test_invalid_indicator_parameters_fail(name, params):
    with pytest.raises(ValueError):
        create_strategy(name, params)
