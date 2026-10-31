"""DATA-06 deterministic multi-timeframe close subscriptions."""
from datetime import timedelta
from decimal import Decimal

from gym.domain.bars import CloseSubscriptions
from gym.services.paper import paper
from tests.support import START, market_db, quote_history


def test_close_subscriptions_order_forming_and_replay_trace(tmp_path):
    closes = CloseSubscriptions("BTCUSDT", ("15min", "1min"))
    events = []
    for minute in range(16):
        events += closes.update(START + timedelta(minutes=minute), Decimal(100 + minute))
    simultaneous = [bar.spec.resolution for bar in events if bar.avail == START + timedelta(minutes=15)]
    assert simultaneous == ["1min", "15min"]
    assert all(bar.forming for bar in closes.forming(START + timedelta(minutes=15, seconds=1)).values())

    out = paper(market_db(tmp_path, quote_history()), "BTCUSDT", START, START + timedelta(hours=4),
                resolution="1min", fast=2, slow=3, subscriptions=("15min", "1h"))
    session = out["result"]["session"]
    assert session["subscriptions"] == ["1min", "15min", "1h"]
    assert {event["resolution"] for event in session["bar_events"]} == {"1min", "15min", "1h"}
    assert out["inputs"]["subscriptions"] == session["subscriptions"]
