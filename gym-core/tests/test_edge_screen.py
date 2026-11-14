"""The screen arithmetic on hand-computed cases."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("edge_screen", Path(__file__).resolve().parents[1] / "scripts/edge_screen.py")
screen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen)


def quote(at, bid, ask, size=10.0):
    return (at, bid, ask, size, size)


def test_maker_result_is_measured_against_the_later_mid_and_pays_two_fees():
    quotes = [quote(0, 99, 101), quote(290, 99, 101), quote(900, 109, 111)]
    # A taker buys at 101: the maker sold at 101 and the mid five minutes later is 100. A taker sells at 99: the same.
    results = screen.maker_results(quotes, [(10, 101.0, "BUY"), (20, 99.0, "SELL")], fee=0.001)
    assert results == pytest.approx([101 / 100 - 1 - 0.002, 100 / 99 - 1 - 0.002])
    # No quote within two minutes of the horizon, or none after the trade: the trade is left out, not guessed.
    assert screen.maker_results(quotes, [(400, 101.0, "BUY")], fee=0.001) == []
    assert screen.maker_results([quote(0, 99, 101)], [(10, 101.0, "BUY")], fee=0.001) == []


def test_triangle_gap_uses_executable_prices_in_both_directions_and_only_in_session():
    at = 10 * 3600  # 10:00 UTC, inside the session
    usdt_tmn = [quote(at - 30, 100.0, 101.0), quote(at + 200, 100.0, 101.0)]
    coin_usdt = [quote(at - 30, 10.0, 10.1), quote(at + 200, 10.0, 10.1)]
    cheap_coin = [quote(at - 30, 900.0, 950.0), quote(at + 200, 900.0, 950.0)]  # the coin is cheap in Toman
    gaps = screen.triangle_gaps(usdt_tmn, cheap_coin, coin_usdt, fees=0.003)
    assert [minute for minute, _ in gaps] == [at, at + 60]  # by the third minute the quotes are over two minutes old
    assert gaps[0][1] == pytest.approx(10.0 * 100.0 / 950.0 - 1 - 0.003)  # buy coin at 950, sell at 10 USDT, sell USDT at 100
    dear_coin = [quote(at - 30, 1100.0, 1150.0), quote(at + 200, 1100.0, 1150.0)]
    assert screen.triangle_gaps(usdt_tmn, dear_coin, coin_usdt, 0.0)[0][1] == pytest.approx(1100.0 / (101.0 * 10.1) - 1)
    night = 2 * 3600
    closed = [[quote(night - 30, *q[1:3]), quote(night + 200, *q[1:3])] for q in (usdt_tmn[0], cheap_coin[0], coin_usdt[0])]
    assert screen.triangle_gaps(*closed, 0.0) == []
    stale = [quote(at - 500, 900.0, 950.0), quote(at + 200, 900.0, 950.0)]
    assert screen.triangle_gaps(usdt_tmn, stale, coin_usdt, 0.0) == []  # one stale leg: the minute is left out


def test_trend_holds_only_above_the_average_and_pays_on_each_change():
    closes = [10.0, 10.0, 12.0, 15.0, 9.0, 9.0]
    # Window 2. Day 1: 10 is not above 10, flat. Day 2: 12 > 11, buy: 15/12-1 less cost. Day 3: 15 > 13.5, hold: 9/15-1.
    # Day 4: 9 is not above 12, sell: only the cost.
    assert screen.trend_returns(closes, 2, cost=0.01) == pytest.approx([0.0, 15 / 12 - 1 - 0.01, 9 / 15 - 1, -0.01])


def test_best_round_trip_buys_at_an_earlier_ask_and_sells_at_a_later_bid():
    day = [quote(0, 0.99, 1.00), quote(1, 0.97, 0.98), quote(2, 1.01, 1.02), quote(3, 0.95, 0.96)]
    assert screen.best_round_trip(day) == pytest.approx(1.01 / 0.98 - 1)
    assert screen.best_round_trip([quote(0, 0.99, 1.00)]) is None


def test_unusable_flags_are_dropped_and_a_market_needs_every_condition_to_pass():
    assert screen.usable("") and screen.usable("WIDE_SPREAD") and not screen.usable("WIDE_SPREAD,STALE")
    quotes = [quote(60 * i, 99.0, 101.0, size=5.0) for i in range(8 * 1440)]  # 2% spread for eight days
    trades = [(60 * i + 5, 101.0 if i % 2 else 99.0, "BUY" if i % 2 else "SELL") for i in range(0, 8 * 1440 - 10, 10)]
    row = screen.t2_row("XUSDT", "USDT", quotes, trades, usdt_rate=1.0)
    assert row["spread"] == pytest.approx(0.02) and row["days"] == 8 and row["trades_per_day"] == pytest.approx(len(trades) / 8)
    assert row["touch_usdt"] == pytest.approx(500.0)
    assert row["account"]["n"] == len(trades) and row["account"]["mean"] == pytest.approx(0.008, abs=2e-4)
    assert row["pass_account"] is False  # every result is the same, so there is no spread of results to test against
    thin = screen.t2_row("XTMN", "TMN", quotes, trades, usdt_rate=100000.0)
    assert thin["touch_usdt"] == pytest.approx(0.005) and thin["pass_account"] is False
