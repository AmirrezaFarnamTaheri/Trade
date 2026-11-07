"""Prior-channel breakouts never include the bar being tested in their threshold."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.bars import Bar, BarSpec
from gym.domain.registry import create_strategy
from gym.domain.strategy import Snapshot
from tests.support import START


def snapshot(index, price, *, gap=0):
    at = START + timedelta(minutes=index + gap)
    value = Decimal(price)
    bar = Bar("BTCUSDT", BarSpec("1min"), at, at + timedelta(minutes=1), at + timedelta(minutes=1),
              value, value, value, value, Decimal(0), 1)
    return Snapshot(bar.avail, "BTCUSDT", bar, value - Decimal("0.01"), value + Decimal("0.01"), bar.avail)


def test_donchian_uses_prior_highs_and_actual_holdings_then_prior_lows():
    strategy = create_strategy("donchian-breakout", {"lookback": 3, "exit_lookback": 2})
    for i, price in enumerate((100, 101, 102)):
        assert strategy.decide(snapshot(i, price), False)[0] == "ABSTAIN_WARMUP"
    assert strategy.decide(snapshot(3, 103), False)[0] == "BUY_REQUEST"
    assert strategy.feature_values["prior_high"] == "102"
    assert strategy.decide(snapshot(4, 104), True)[0] == "HOLD"
    assert strategy.decide(snapshot(5, 101), True)[0] == "SELL_REQUEST"


def test_compression_gate_abstains_on_wide_history_and_resets_across_gaps():
    strategy = create_strategy("compression-breakout", {"lookback": 3, "exit_lookback": 2, "compression_bps": 50})
    for i, price in enumerate((100, 101, 102)):
        strategy.decide(snapshot(i, price), False)
    assert strategy.decide(snapshot(3, 103), False)[0] == "HOLD"
    assert strategy.decide(snapshot(4, 104, gap=10), False)[0] == "ABSTAIN_WARMUP"
    assert strategy.feature_values["observations"] == 0


@pytest.mark.parametrize("params", [{"lookback": 2, "exit_lookback": 3}, {"compression_bps": True}, {"regime": "BULLISH"}])
def test_invalid_channel_parameters_are_rejected(params):
    with pytest.raises(ValueError):
        create_strategy("compression-breakout", params)


def test_optional_shared_regime_gate_preserves_defaults_and_does_not_block_exits():
    assert create_strategy("ema-trend", {"regime_gate": "ANY"}).config_hash == create_strategy("ema-trend").config_hash
    strategy = create_strategy("ema-trend", {"fast": 2, "slow": 3, "regime_gate": "UP_TREND"})
    for i, price in enumerate((100, 101, 102, 103)):
        result = strategy.decide(snapshot(i, price), False)
    assert result[0] == "ABSTAIN_REGIME"
    assert strategy.feature_values["entry_regime"] == "WARMUP"
    assert strategy.decide(snapshot(4, 1), True)[0] == "SELL_REQUEST"


def test_shared_regime_readiness_cannot_hide_longer_underlying_warmup():
    strategy = create_strategy("ema-trend", {"fast": 2, "slow": 100, "regime_gate": "UP_TREND"})
    for i in range(60):
        action = strategy.decide(snapshot(i, 100 + i), False)[0]
    assert action == "ABSTAIN_WARMUP" and not strategy.ready
