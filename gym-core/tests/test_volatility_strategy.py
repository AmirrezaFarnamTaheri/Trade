"""Closed-price volatility bands and shared-engine execution contracts."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from gym.domain.registry import create_strategy
from gym.services.diagnostics import diagnostics
from gym.services.paper import paper
from tests.support import START, market_db, quote, quote_history


def snapshot(value, bid=True):
    return SimpleNamespace(bar=SimpleNamespace(close=Decimal(value)), bid=Decimal(value) if bid else None)


def test_volatility_bands_warmup_and_flat_prices_do_not_invent_entries():
    strategy = create_strategy("bollinger-reversion", {"lookback": 6, "deviations": 2})
    assert [strategy.decide(snapshot("10"), False)[0] for _ in range(5)] == ["ABSTAIN_WARMUP"] * 5
    assert strategy.decide(snapshot("10"), False)[0] == "HOLD"
    assert strategy.feature_values["standard_deviation"] == "0"
    assert strategy.decide(snapshot("1"), False)[0] == "BUY_REQUEST"
    assert Decimal(strategy.feature_values["lower_band"]) < Decimal(strategy.feature_values["mean"])
    assert strategy.decide(snapshot("2"), True)[0] == "HOLD"
    assert strategy.decide(snapshot("10"), True)[0] == "SELL_REQUEST"


def test_unqualified_quote_is_not_an_assumed_bollinger_fill():
    strategy = create_strategy("bollinger-reversion", {"lookback": 6, "deviations": 2})
    for _ in range(5):
        strategy.decide(snapshot("10"), False)
    assert strategy.decide(snapshot("1", bid=False), False)[0] == "ABSTAIN_NO_QUOTE"
    assert strategy.decide(snapshot("10"), False)[0] == "HOLD"


def test_band_parameters_are_bounded_and_change_the_saved_identity():
    default = create_strategy("bollinger-reversion")
    assert default.config_hash != create_strategy("bollinger-reversion", {"deviations": 1}).config_hash
    for params in ({"deviations": True}, {"deviations": 0}, {"deviations": 6}, {"lookback": 1}):
        with pytest.raises(ValueError):
            create_strategy("bollinger-reversion", params)


def test_bollinger_native_fills_identity_and_lookahead_parity(tmp_path):
    observations = [quote(q.ts_avail, str(Decimal(80000)-q.bid), str(Decimal(80010)-q.bid))
                    for q in quote_history(n=1200)]
    db = market_db(tmp_path, observations)
    try:
        options = {"resolution": "1min", "strategy_id": "bollinger-reversion",
                   "params": {"lookback": 6, "deviations": 1}}
        out = paper(db, "BTCUSDT", START, START + timedelta(hours=3), **options)
        assert out == paper(db, "BTCUSDT", START, START + timedelta(hours=3), **options)
        assert out["result"]["fills"] > 0
        assert all(check["status"] == "PASS" for check in diagnostics(db, out)["checks"].values())
    finally:
        db.c.close()
