"""Phase B: the high-low estimator is shared by optional exits and regimes."""
from decimal import Decimal

import pytest

from gym.domain.regime import market_regime
from gym.domain.registry import create_strategy


def test_disabling_optional_volatility_models_preserves_strategy_identity():
    original = create_strategy("ema-trend", {"fast": 2, "slow": 5})
    disabled = create_strategy("ema-trend", {"fast": 2, "slow": 5,
                                           "regime_volatility_model": "atr",
                                           "exit_volatility_model": "atr"})
    assert disabled.config_hash == original.config_hash
    assert original.params == disabled.params


def test_opt_in_stop_uses_shared_parkinson_ewma_and_has_separate_identity():
    legacy = create_strategy("ema-trend", {"exit_atr_multiple": 2})
    new = create_strategy("ema-trend", {
        "exit_atr_multiple": 2, "exit_volatility_model": "parkinson-ewma"})
    assert new.params["exit_volatility_model"] == "parkinson-ewma"
    assert new.volatility is not None
    assert new.config_hash != legacy.config_hash
    with pytest.raises(ValueError, match="trailing stop"):
        create_strategy("ema-trend", {"exit_volatility_model": "parkinson-ewma"})


def test_regime_distance_can_use_explicit_volatility_instead_of_atr():
    features = {
        "ema_20": {"value": "105", "slope_5_bars": "0"},
        "ema_50": {"value": "100"},
        "adx_14": {"value": "10", "plus_di": "15", "minus_di": "15"},
        "atr_14": {"value": "1"},
    }
    assert market_regime(features) == "TRANSITION"
    assert market_regime(features, range_distance=Decimal(10)) == "RANGE"
    new = create_strategy("ema-trend", {
        "regime_gate": "RANGE", "regime_volatility_model": "parkinson-ewma"})
    assert new.params["regime_volatility_model"] == "parkinson-ewma"
    assert new.volatility is not None
    with pytest.raises(ValueError, match="regime_volatility_model"):
        create_strategy("ema-trend", {"regime_volatility_model": "parkinson-ewma"})
