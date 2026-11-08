"""Phase E item 38: point-in-time volume-aware paper execution proposals."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import InstrumentId, TradeTick
from gym.domain.sim import Spec
from gym.services.adaptive_twap import adaptive_twap
from tests.support import START, quote


def top(seconds, bid="99", ask="101", qty="10"):
    """One timestamped public quote with symmetric displayed capacity."""
    return replace(quote(START + timedelta(seconds=seconds), bid, ask),
                   bid_qty=Decimal(qty), ask_qty=Decimal(qty))


def trade(seconds, quantity):
    """One public print whose event and receipt times agree."""
    at = START + timedelta(seconds=seconds)
    return TradeTick("BTCUSDT", at, at, Decimal(100), Decimal(quantity), "BUY")


def preview(quotes, trades, **changes):
    """Run an isolated proposal with no venue authority or credential access."""
    arguments = {"side": "BUY", "quantity": Decimal(4), "slices": 2,
                 "participation": Decimal("0.5"), "fee_rate": Decimal("0.001"),
                 "available_quote": Decimal(1000), "available_base": Decimal(0),
                 "max_delay_seconds": 10, "store": "demo",
                 "volume_lookback_seconds": 120, "max_spread_bps": Decimal(50)}
    return adaptive_twap(InstrumentId.wallex("BTCUSDT"), quotes, trades, Spec(qty_decimals=2),
                         START, START + timedelta(minutes=2), **{**arguments, **changes})


def test_slices_capped_by_strictly_prior_public_volume_and_cash():
    """A future print can never increase a decision-time child target."""
    quotes = [top(-1), top(1), top(59), top(61), top(119)]
    earlier = [trade(-30, "4"), trade(50, "2")]
    report = preview(quotes, earlier)
    later = preview(quotes, [*earlier, trade(90, "1000")])
    assert report["schema"] == "paper-volume-twap/1"
    assert report["children"][0]["requested_quantity"] == "2.00"
    assert report["children"][1]["requested_quantity"] == "2.00"
    assert [r["requested_quantity"] for r in report["children"]] == [
        r["requested_quantity"] for r in later["children"]]
    assert sum(Decimal(r["filled_quantity"]) for r in report["children"]) <= Decimal(4)
    assert report["funded_authority"] is False
    assert report["order_submitted"] is False and report["cancel_submitted"] is False
    assert report["equal_slice_reference"]["schema"] == "paper-twap/1"


def test_wide_spread_prefers_unfilled_limit_then_urgency_triggers_market():
    """An unmodeled maker queue is not counted as a filled order."""
    rows = [top(-1, "90", "110"), top(1, "90", "110"),
            top(59, "90", "110"), top(61, "90", "110")]
    report = preview(rows, [trade(-20, "8"), trade(40, "8")],
                     max_spread_bps=Decimal(20), urgency="FINISH")
    assert [c["order_type"] for c in report["children"]] == ["LIMIT", "MARKET"]
    assert report["children"][0]["filled_quantity"] == "0"
    assert report["children"][0]["status"] == "NONFILL_LIMIT_QUEUE_UNKNOWN"
    assert report["children"][1]["filled_quantity"] != "0"


def test_no_available_prints_or_prior_quote_blocks_child_plan():
    report = preview([top(1), top(61)], [trade(90, "100")])
    assert all(c["filled_quantity"] == "0" for c in report["children"])
    assert report["children"][0]["status"] == "NO_PRIOR_QUOTE"
    assert report["children"][1]["status"] == "NO_PRIOR_VOLUME"


@pytest.mark.parametrize("change", [
    {"urgency": "NOW"}, {"max_spread_bps": Decimal("NaN")},
    {"volume_lookback_seconds": -1}, {"participation": Decimal("1.1")},
])
def test_invalid_adaptive_controls_fail_closed(change):
    with pytest.raises(ValueError):
        preview([top(-1), top(1), top(61)], [trade(-20, "10")], **change)
