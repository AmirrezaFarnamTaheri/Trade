"""Step 0 statistics on a hand-computed session."""
import importlib.util
from datetime import datetime
from decimal import Decimal
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "usdttmn_range", Path(__file__).resolve().parents[1] / "scripts/usdttmn_range.py")
usdttmn_range = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usdttmn_range)


def quote(hour, minute, bid, ask):
    at = datetime(2026, 11, 12, hour, minute, tzinfo=usdttmn_range.TEHRAN)
    return (at, Decimal(bid), Decimal(ask), Decimal(100), Decimal(300))


def test_range_spread_and_the_foresight_round_trip_match_hand_arithmetic():
    session = [quote(11, 40, "1000", "1002"), quote(15, 0, "1020", "1022"), quote(23, 20, "999", "1001")]
    stats = usdttmn_range.day_stats(session, fee=Decimal(0))
    assert stats["complete"] is True
    assert stats["range_percent"] == Decimal("2.100")  # mids 1001, 1021, 1000
    assert stats["median_spread_percent"] == Decimal("0.200")  # 2 / 1001, 2 / 1021, 2 / 1000
    assert stats["median_bid_size_usdt"] == 100 and stats["median_ask_size_usdt"] == 300
    assert stats["foresight_round_trip_percent"] == Decimal("1.898")  # sell at 1020, buy back at 1001


def test_fees_reduce_the_round_trip_and_a_falling_only_bid_cannot_profit():
    rising = [quote(12, 0, "1000", "1001"), quote(13, 0, "1010", "1011"), quote(14, 0, "1020", "1021")]
    assert usdttmn_range.day_stats(rising)["foresight_round_trip_percent"] < 0
    flat = [quote(12, 0, "1000", "1000"), quote(13, 0, "1000", "1000")]
    assert usdttmn_range.day_stats(flat)["foresight_round_trip_percent"] == Decimal("-0.200")  # two 0.1% fees


def test_a_session_that_starts_late_is_not_complete():
    late = [quote(14, 0, "1000", "1001"), quote(23, 25, "1000", "1001")]
    assert usdttmn_range.day_stats(late)["complete"] is False
