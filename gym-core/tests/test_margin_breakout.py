"""Breakouts open on a new 20-day extreme, use spot for a 1x long and margin otherwise, and close within the limit."""
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("margin_breakout", SCRIPTS / "margin_breakout.py")
breakout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(breakout)


def bars(closes, spread=0.0):
    days = [(date(2022, 1, 1) + timedelta(days=i)).isoformat() for i in range(len(closes))]
    return {"days": days, "close": closes, "low": [c * (1 - spread) for c in closes], "high": [c * (1 + spread) for c in closes],
            "open": closes, "volume": [1e9] * len(closes)}


def test_a_new_high_buys_on_spot_and_the_holding_limit_closes_it():
    closes = [100.0] * 25 + [110.0] + [110.0 * 1.01 ** k for k in range(1, 10)]
    rows = dict(breakout.coin_returns(bars(closes), [True] * len(closes), 5, 1))
    days = bars(closes)["days"]
    first = rows[days[26]]
    assert first == pytest.approx(1.01 * (1 - breakout.HALF_SPREAD) * (1 - breakout.SPOT_FEE) ** 2 / (1 + breakout.HALF_SPREAD) - 1)
    assert rows[days[31]] == 0.0  # closed after five days; the next day is flat


def test_a_new_low_shorts_on_margin_and_a_rally_liquidates_a_2x_short():
    closes = [100.0] * 25 + [90.0, 95.0, 140.0, 140.0]
    rows = breakout.coin_returns(bars(closes), [True] * len(closes), 10, 2)
    values = [r for _, r in rows]
    assert values[-2] < -0.5 and values[-1] == 0.0  # the rally to 140 wipes out a 2x short; the coin is flat after


def test_a_coin_that_stops_counting_is_closed_and_then_skipped():
    closes = [100.0] * 25 + [110.0, 111.0, 112.0, 113.0]
    counted = [True] * 27 + [False] * 2
    rows = breakout.coin_returns(bars(closes), counted, 10, 1)
    assert rows[-1][0] == bars(closes)["days"][27]
