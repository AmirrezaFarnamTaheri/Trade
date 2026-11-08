"""Phase E item 39: observed post-fill price moves and causal cost feedback."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.execution_costs import modeled_execution_cost
from gym.domain.model import iso
from gym.domain.sim import CostModel
from gym.services.postfill import post_fill_checks
from tests.support import START, quote


def top(seconds, bid, ask):
    """One qualified quote available at the supplied offset."""
    return replace(quote(START + timedelta(seconds=seconds), bid, ask), symbol="BTCUSDT")


def test_postfill_markouts_use_first_qualified_quote_at_each_horizon():
    """A BUY suffers when subsequent midpoint falls; a SELL suffers when it rises."""
    trades = [
        {"status": "FILLED", "side": "BUY", "qty": "1", "price": "100",
         "fill_time": iso(START), "ref": "a"},
        {"status": "FILLED", "side": "SELL", "qty": "1", "price": "100",
         "fill_time": iso(START), "ref": "b"},
    ]
    marks = [top(59, "200", "202"), top(60, "97", "99"),
             top(300, "100", "102"), top(1800, "94", "96")]
    report = post_fill_checks(trades, marks, symbol="BTCUSDT",
                              strategy="ema-trend", order_type="market",
                              cutoff=START + timedelta(minutes=31))
    assert report["schema"] == "paper-postfill-markouts/1"
    assert report["funded_authority"] is False
    buy, sell = report["rows"]
    assert Decimal(buy["markouts_bps"]["60"]) == Decimal(-200)
    assert Decimal(sell["markouts_bps"]["60"]) == Decimal(200)
    assert Decimal(buy["markouts_bps"]["300"]) == Decimal(100)
    assert Decimal(buy["markouts_bps"]["1800"]) == Decimal(-500)
    assert report["groups"][0]["strategy"] == "ema-trend"
    assert report["groups"][0]["order_type"] == "market"


def test_postfill_gaps_do_not_backfill_or_use_later_quotes():
    """Missing 1/5/30-minute marks stay unavailable when no timely quote exists."""
    orders = [{"status": "FILLED", "side": "BUY", "qty": "1", "price": "100",
               "fill_time": iso(START), "ref": "a"}]
    report = post_fill_checks(orders, [top(260, "50", "52")],
                              symbol="BTCUSDT", strategy="ema-trend",
                              order_type="limit", cutoff=START + timedelta(minutes=31))
    assert all(mark is None for mark in report["rows"][0]["markouts_bps"].values())
    assert all(s["available"] == 0 for s in report["groups"][0]["horizons"].values())


def test_opt_in_adverse_markout_cost_is_bounded_and_causal():
    """A profile only fitted before replay start adds an explicit simulation penalty."""
    profile = {"BTCUSDT": {"schema": "postfill-adverse/1", "symbol": "BTCUSDT",
                           "trained_until": iso(START), "penalty_bps": "12",
                           "sample_count": 30, "source": "PAPER_MARKOUT_DIAGNOSTIC"}}
    cost = CostModel(postfill_costs=profile)
    later = START + timedelta(minutes=60)
    cost.assert_causal(later)
    assert cost.describe()["postfill_costs"] == profile
    assert CostModel.from_description(cost.describe()).postfill_costs == profile
    priced = modeled_execution_cost(cost, "BTCUSDT", later, Decimal(1),
                                    Decimal(99), Decimal(101))
    assert priced["uplift_bps"] == Decimal(12)
    assert priced["pricing"]["postfill_adverse_bps"] == "12"
    with pytest.raises(ValueError, match="future"):
        cost.assert_causal(START - timedelta(seconds=1))
    with pytest.raises(ValueError):
        CostModel(postfill_costs={"BTCUSDT": {**profile["BTCUSDT"], "penalty_bps": "500"}})
