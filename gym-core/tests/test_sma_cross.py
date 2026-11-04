"""Closed-bar crossover signals, actual holdings and shared paper-engine integration."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from gym.domain.registry import create_strategy
from gym.services.diagnostics import diagnostics
from gym.services.paper import paper
from tests.support import START, market_db, quote, quote_history


def snapshot(value, *, quoted=True):
    return SimpleNamespace(bar=SimpleNamespace(close=Decimal(value)), bid=Decimal(value) if quoted else None)


def test_crossover_needs_previous_closed_window_and_uses_actual_holdings():
    strategy = create_strategy("sma-cross", {"fast": 2, "slow": 3})
    actions = []
    holding = False
    for value in ("3", "2", "1", "2", "4", "3", "2"):
        action = strategy.decide(snapshot(value), holding)[0]
        actions.append(action)
        if action in ("BUY_REQUEST", "SELL_REQUEST"):
            holding = action == "BUY_REQUEST"
    assert actions == ["ABSTAIN_WARMUP"]*3 + ["HOLD", "BUY_REQUEST", "HOLD", "SELL_REQUEST"]
    assert strategy.feature_values["cross"] == "DOWN"


def test_equal_means_can_cross_but_missing_quote_is_not_an_assumed_fill():
    strategy = create_strategy("sma-cross", {"fast": 2, "slow": 3})
    for _ in range(3):
        strategy.decide(snapshot("1"), False)
    assert strategy.decide(snapshot("2", quoted=False), False)[0] == "ABSTAIN_NO_QUOTE"
    assert strategy.feature_values["cross"] == "UP"
    assert strategy.decide(snapshot("3"), False)[0] == "HOLD"
    assert strategy.feature_values["cross"] is None


def test_crossover_runs_through_native_fills_identity_and_parity(tmp_path):
    observations = [quote(q.ts_avail, str(Decimal(80000)-q.bid), str(Decimal(80010)-q.bid))
                    for q in quote_history(n=1200)]
    db = market_db(tmp_path, observations)
    try:
        options = {"resolution": "1min", "strategy_id": "sma-cross", "params": {"fast": 2, "slow": 3}}
        out = paper(db, "BTCUSDT", START, START + timedelta(hours=3), **options)
        assert out == paper(db, "BTCUSDT", START, START + timedelta(hours=3), **options)
        assert out["result"]["fills"] >= 1
        assert out["inputs"]["strategy"] == "sma-cross"
        assert all(check["status"] == "PASS" for check in diagnostics(db, out)["checks"].values())
    finally:
        db.c.close()
