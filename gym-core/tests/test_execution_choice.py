"""Matched historical spread-aware execution-choice diagnostics."""
import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import BookTop, InstrumentId, iso
from gym.domain.sim import Spec
from gym.services.execution_choice import compare_execution_previews
from gym.services.paper_twap import simulate_twap
from gym.services.research_actions import research_action
from gym.services.research_process import HEAVY_ACTIONS, calculate
from tests.support import START, market_db


def quote(minute, bid, ask, capacity="10"):
    """Return a qualified, past top quote at the next observable child slot."""
    return BookTop("BTCUSDT", START + timedelta(minutes=minute, seconds=1),
                   Decimal(bid), Decimal(ask), Decimal(capacity),
                   Decimal(capacity), frozenset())


def preview(quotes, *, slices, side="BUY", quantity=Decimal(3), base=None):
    """Execute one historical paper scenario without any venue side effect."""
    return simulate_twap(
        InstrumentId.wallex("BTCUSDT"), quotes, Spec(qty_decimals=8),
        START, START + timedelta(minutes=3), side=side, quantity=quantity,
        slices=slices, participation=Decimal(1), fee_rate="0.001",
        available_quote=Decimal(1000), available_base=base if base is not None else Decimal(3),
        max_delay_seconds=10, store="demo")


def test_historical_buy_choice_uses_matched_net_price_and_disclaims_authority():
    quotes = [quote(0, 100, 101), quote(1, 99, 100), quote(2, 98, 99)]
    immediate = preview(quotes, slices=1)
    sliced = preview(quotes, slices=3)
    report = compare_execution_previews(immediate, sliced)
    assert report["schema"] == "historical-execution-choice/1"
    assert report["status"] == "FULL_FILL_HISTORICAL"
    assert report["retrospective_lower_cost"] == "TWAP"
    assert Decimal(report["twap_advantage_bps"]) > 0
    assert Decimal(report["immediate_effective_quote_per_base"]) > Decimal(
        report["twap_effective_quote_per_base"])
    assert report["funded_authority"] is False
    assert report["order_submitted"] is False
    assert report["autonomous_execution"] is False
    assert report["immediate"]["children"][0]["status"] == "FILLED"
    assert all(x["status"] == "FILLED" for x in report["twap"]["children"])


def test_historical_sell_choice_compares_fee_adjusted_quote_proceeds():
    quotes = [quote(0, 99, 100), quote(1, 100, 101), quote(2, 101, 102)]
    result = compare_execution_previews(preview(quotes, slices=1, side="SELL"),
                                        preview(quotes, slices=3, side="SELL"))
    assert result["status"] == "FULL_FILL_HISTORICAL"
    assert result["retrospective_lower_cost"] == "TWAP"
    assert Decimal(result["twap_advantage_bps"]) > 0


def test_unmatched_partial_fills_cannot_be_ranked_as_cheaper_execution():
    quotes = [quote(0, 100, 101, "1"), quote(1, 99, 100, "1"),
              quote(2, 98, 99, "1")]
    report = compare_execution_previews(preview(quotes, slices=1),
                                        preview(quotes, slices=3))
    assert report["status"] == "NOT_COMPARABLE"
    assert report["reason"] == "UNMATCHED_FILLED_QUANTITY"
    assert report["retrospective_lower_cost"] is None
    assert report["twap_advantage_bps"] is None


def test_mismatched_scenarios_and_malformed_prices_fail_closed():
    quotes = [quote(0, 100, 101), quote(1, 99, 100), quote(2, 98, 99)]
    immediate, sliced = preview(quotes, slices=1), preview(quotes, slices=3)
    with pytest.raises(ValueError):
        compare_execution_previews(immediate, {**sliced, "side": "SELL"})
    with pytest.raises(ValueError):
        compare_execution_previews(immediate, {**sliced, "requested_quantity": "4"})
    with pytest.raises(ValueError):
        compare_execution_previews({**immediate, "spent_quote": "NaN"}, sliced)


def test_choice_action_uses_single_read_snapshot_and_is_supervised(tmp_path):
    assert "execution-choice-preview" in HEAVY_ACTIONS
    db = market_db(tmp_path, [quote(0, 100, 101), quote(1, 99, 100),
                              quote(2, 98, 99)])
    db.c.close()
    request = {"symbol": "BTCUSDT", "from": iso(START),
               "to": iso(START + timedelta(minutes=3)), "side": "BUY",
               "quantity": "3", "slices": 3, "participation": "1",
               "fee_rate": "0.001", "available_quote": "1000",
               "available_base": "0", "max_delay_seconds": 10}
    report = research_action(tmp_path, "execution-choice-preview", request, store="demo")
    assert report["status"] == "FULL_FILL_HISTORICAL"
    assert report["retrospective_lower_cost"] == "TWAP"
    supervised = asyncio.run(calculate(tmp_path, "execution-choice-preview", request,
                                       store="demo", timeout_seconds=30))
    assert supervised["status"] == report["status"]
    assert supervised["twap_advantage_bps"] == report["twap_advantage_bps"]
    assert supervised["funded_authority"] is False
    with pytest.raises(ValueError):
        research_action(tmp_path, "execution-choice-preview",
                        {**request, "slices": 1}, store="demo")


@pytest.mark.parametrize(("change", "field"), [
    ("aggregate_spend", "spent_quote"),
    ("aggregate_fee", "fee_base"),
    ("aggregate_receipt", "received_base"),
    ("remaining_quote", "remaining_quote"),
    ("child_price", "children"),
])
def test_execution_choice_rejects_child_aggregate_monetary_mismatch(change, field):
    """Tampering with an apparent cheaper path must not alter its ranking."""
    import copy

    quotes = [quote(0, 100, 101), quote(1, 99, 100), quote(2, 98, 99)]
    immediate = preview(quotes, slices=1)
    sliced = copy.deepcopy(preview(quotes, slices=3))
    if change == "child_price":
        sliced["children"][0]["price"] = "1"
    else:
        sliced[field] = str(Decimal(sliced[field]) + Decimal(1))
    with pytest.raises(ValueError, match="conserv|economic|amount|quote|child"):
        compare_execution_previews(immediate, sliced)
