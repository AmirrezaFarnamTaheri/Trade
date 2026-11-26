import json
from contextlib import closing
from datetime import timedelta

import pytest

from gym.adapters.store import MarketDB, SegmentWriter
from scripts.verify_legacy_book_chain import verify
from tests.support import START, quote


@pytest.mark.parametrize("gap", [False, True])
@pytest.mark.parametrize("later_price", [None, "102", "101"])
def test_legacy_chain_crosses_segments_and_requires_all_sequences(tmp_path, gap, later_price):
    db = MarketDB(tmp_path / "market.db")
    root = tmp_path / "raw"
    next_hour = START + timedelta(hours=1)

    def message(side, price):
        return json.dumps({"push": {"channel": f"orderbook:BTCUSDT@{side}Depth",
                                    "pub": {"data": [{"price": price, "quantity": "1"}]}}})

    with closing(db.c), closing(SegmentWriter(root, db)) as writer:
        ask_ref = writer.write("ws", message("sell", "101"), next_hour - timedelta(seconds=1))
        if later_price is not None:
            latest = writer.write("ws", message("sell", later_price), next_hour - timedelta(microseconds=1))
        if gap:
            writer.seq += 1
        bid_ref = writer.write("ws", message("buy", "99"), next_hour)
        writer.close()
        db.add_book_top(quote(next_hour, "99", "101"), bid_ref)
        segments = [ref.split("#")[0] for ref in (ask_ref, bid_ref)]
        args = (db, [root], "BTCUSDT", next_hour, "ask", 1, segments)
        auto_args = (db, [root], "BTCUSDT", next_hour, "ask", None, segments)
        if later_price is not None:
            with pytest.raises(ValueError, match="later ask update"):
                verify(*args)
            if not gap and later_price == "101":
                assert verify(*auto_args)["candidate_ref"] == latest
                return
        if gap or later_price == "102":
            with pytest.raises(ValueError, match="raw chain gap|candidate does not match"):
                verify(*auto_args)
        else:
            assert verify(*args)["verified_frames"] == 2
            assert verify(*auto_args) == verify(*args)
