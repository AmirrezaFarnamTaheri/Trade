"""A venue stop order activates on the last trade, then behaves as a market or limit order."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import BookTop, InstrumentId, TradeTick, iso
from gym.domain.sim import Spec
from gym.services.paper_stop import simulate_stop
from tests.support import START

INSTRUMENT = InstrumentId.wallex("USDTTMN", "USDT", "TMN")


def trade(second, price):
    at = START + timedelta(seconds=second)
    return TradeTick("USDTTMN", at, at, Decimal(price), Decimal(1), "SELL")


def quote(second, bid, ask, size="100", depth=None):
    return BookTop("USDTTMN", START + timedelta(seconds=second), Decimal(bid), Decimal(ask), Decimal(size), Decimal(size),
                   frozenset(), depth)


def stop(trades, quotes, **order):
    order = {"side": "SELL", "quantity": Decimal(10), "stop_price": Decimal(250), "order_type": "STOP_MARKET",
             "limit_price": None, "fee_rate": Decimal("0.001"), "store": "demo"} | order
    return simulate_stop(INSTRUMENT, Decimal(258), trades, quotes, Spec(qty_decimals=2), START,
                         START + timedelta(minutes=5), **order)


def test_stop_below_the_last_trade_activates_when_a_trade_falls_to_it_and_sells_at_the_bid():
    report = stop([trade(10, 255), trade(20, 250), trade(30, 240)],
                  [quote(5, 256, 257), quote(21, 248, 251), quote(31, 239, 241)])
    assert report["activates"] == "AT_OR_BELOW"
    assert report["activation"] == {"time": iso(START + timedelta(seconds=20)), "price": "250"}
    assert report["status"] == "FILLED"
    assert (report["fill"]["price"], report["fill"]["qty"]) == ("248", "10.00")
    assert Decimal(report["slippage_from_stop_bps"]) == 80  # sold 2 below a stop of 250
    assert report["order_submitted"] is False


def test_stop_above_the_last_trade_activates_on_a_rise_and_never_before():
    report = stop([trade(10, 250), trade(20, 262)], [quote(21, 261, 263)], side="BUY", stop_price=Decimal(260))
    assert report["activates"] == "AT_OR_ABOVE" and report["fill"]["price"] == "263"
    quiet = stop([trade(10, 255), trade(20, 251)], [quote(21, 250, 252)])
    assert quiet["status"] == "NOT_ACTIVATED" and quiet["fill"] is None


def test_stop_limit_waits_for_its_price_and_reports_an_unfilled_gap():
    quotes = [quote(21, 200, 201), quote(40, 249, 250)]
    trades = [trade(20, 201)]
    gapped = stop(trades, quotes[:1], order_type="STOP_LIMIT", limit_price=Decimal(249))
    assert gapped["status"] == "ACTIVATED_UNFILLED" and gapped["fill"] is None
    recovered = stop(trades, quotes, order_type="STOP_LIMIT", limit_price=Decimal(249))
    assert recovered["status"] == "FILLED" and recovered["fill"]["price"] == "249"
    market = stop(trades, quotes, order_type="STOP_MARKET")
    assert market["fill"]["price"] == "200"


def test_fill_is_capped_at_the_displayed_touch_size():
    report = stop([trade(20, 250)], [quote(21, 248, 251, size="4")])
    assert report["status"] == "PARTIAL" and report["fill"]["qty"] == "4.00"
    assert report["unfilled_quantity"] == "6.00"


def test_stop_market_walks_stored_depth_and_the_venue_cancels_a_two_percent_move():
    depth = (((Decimal(248), Decimal(4)), (Decimal(240), Decimal(50))), ((Decimal(251), Decimal(50)),))
    report = stop([trade(20, 250)], [quote(21, 248, 251, depth=depth)])
    assert report["status"] == "ACTIVATED_UNFILLED" and report["fill"]["reason"] == "VENUE_PRICE_GUARD"


@pytest.mark.parametrize("order", [{"stop_price": Decimal(258)}, {"order_type": "LIMIT"}, {"limit_price": Decimal(249)},
                                   {"order_type": "STOP_LIMIT"}, {"side": "HOLD"}, {"quantity": Decimal(0)}])
def test_invalid_stop_orders_are_refused(order):
    with pytest.raises(ValueError):
        stop([trade(20, 250)], [quote(21, 248, 251)], **order)
