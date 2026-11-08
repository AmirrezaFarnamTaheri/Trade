"""Phase D item 37: paper margin liquidation respects observed executable depth."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.margin import replay_margin
from tests.support import START
from tests.test_margin import path, preview, rule


def test_opt_in_long_liquidation_walk_reduces_mark_against_mid():
    first, second = path()
    bid = ((Decimal(110), Decimal(1)), (Decimal(90), Decimal(3)))
    ask = ((Decimal(111), Decimal(5)),)
    marked = replace(second[0], bid_qty=Decimal(1), ask_qty=Decimal(5), depth=(bid, ask))
    result = replay_margin(preview(), rule(), [first, (marked, False)],
                           START + timedelta(hours=1, seconds=1), "0.001", None,
                           depth_valuation=True)
    assert result["state"] == "OPEN"
    liquidation = result["mark"]["liquidation"]
    assert liquidation["status"] == "AVAILABLE"
    assert Decimal(liquidation["gap_to_mid_quote"]) > 0
    assert Decimal(result["equity_quote"]) == Decimal(liquidation["liquidation_value_quote"])
    assert Decimal(liquidation["modeled_exit_fee_quote"]) > 0
    legacy = replay_margin(preview(), rule(), [first, (marked, False)],
                           START + timedelta(hours=1, seconds=1), "0.001", None)
    assert legacy["mark"].get("liquidation") is None
    assert Decimal(result["equity_quote"]) < Decimal(legacy["equity_quote"])


def test_unavailable_liquidation_depth_does_not_substitute_top_or_mid():
    first, second = path()
    result = replay_margin(preview(), rule(), [first, second],
                           START + timedelta(hours=1, seconds=1), "0.001", None,
                           depth_valuation=True)
    assert result["state"] == "OPEN"
    assert result["equity_quote"] is None
    assert result["mark"]["liquidation"]["status"] == "DEPTH_UNAVAILABLE"


def test_short_requires_enough_ask_depth_for_full_borrowed_base():
    first, second = path("short", end_price="90")
    ask = ((Decimal(90), Decimal(1)), (Decimal(95), Decimal(2)))
    marked = replace(second[0], bid_qty=Decimal(4), ask_qty=Decimal(1),
                     depth=(((Decimal(89), Decimal(4)),), ask))
    result = replay_margin(preview("short"), rule(), [first, (marked, False)],
                           START + timedelta(hours=1, seconds=1), "0.001", None,
                           depth_valuation=True)
    assert result["state"] == "OPEN"
    assert result["mark"]["liquidation"]["status"] == "AVAILABLE"
    assert Decimal(result["mark"]["liquidation"]["gap_to_mid_quote"]) > 0
    short_depth = replace(marked, depth=(((Decimal(89), Decimal(4)),),
                                          ((Decimal(90), Decimal(1)),)))
    unfillable = replay_margin(preview("short"), rule(), [first, (short_depth, False)],
                               START + timedelta(hours=1, seconds=1), "0.001", None,
                               depth_valuation=True)
    assert unfillable["equity_quote"] is None


@pytest.mark.parametrize("value", [None, 1, "yes"])
def test_liquidation_depth_flag_requires_boolean(value):
    with pytest.raises(ValueError):
        replay_margin(preview(), rule(), path(), START + timedelta(hours=1, seconds=1),
                      "0.001", None, depth_valuation=value)
