"""Venue candles against internal LAST bars built from collected trades."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.wallex import parse_udf
from gym.domain.bars import BarSpec, trade_bars
from gym.domain.model import TradeTick
from gym.services.data_portal import DataPortal
from gym.services.feed_crosscheck import candle_crosscheck
from tests.support import START, market_db, quote

# Shape captured from GET https://api.wallex.ir/v1/udf/history?symbol=BTCUSDT&resolution=1 on 2026-10-31.
UDF = ('{"s":"ok","t":[%d,%d],"o":["100","200"],"h":["110","210"],"l":["90","190"],"c":["105","205"],'
       '"v":["0.00593456","0"]}' % (START.timestamp(), START.timestamp() + 60))


def trade(seconds, price, qty="0.1"):
    at = START + timedelta(seconds=seconds)
    return TradeTick("BTCUSDT", at, at + timedelta(seconds=1), Decimal(price), Decimal(qty), "BUY")


def test_udf_history_parses_exact_decimals_and_rejects_malformed_columns():
    candles = parse_udf(UDF)
    assert candles[0]["t"] == START and candles[0]["v"] == Decimal("0.00593456") and candles[1]["c"] == Decimal("205")
    assert parse_udf('{"s":"no_data"}') == []
    with pytest.raises(ValueError, match="length"):
        parse_udf('{"s":"ok","t":[1],"o":[],"h":[],"l":[],"c":[],"v":[]}')
    with pytest.raises(ValueError, match="status"):
        parse_udf('{"s":"error"}')


def test_trade_bars_bucket_by_event_time_and_emit_closed_bars_only():
    trades = [trade(30, "105"), trade(0, "100"), trade(61, "200")]
    bars = trade_bars("BTCUSDT", BarSpec("1min", "LAST"), trades, START + timedelta(seconds=90))
    assert len(bars) == 1  # the second minute is still open at 09:01:30
    assert len(trade_bars("BTCUSDT", BarSpec("1min", "LAST"), trades, START + timedelta(minutes=2))) == 2
    b = bars[0]
    assert (b.start, b.open, b.close, b.volume, b.count) == (START, Decimal(100), Decimal(105), Decimal("0.2"), 2)


def crosscheck_db(tmp_path, trades, candles, fetched_late=True, listening=True):
    db = market_db(tmp_path, [quote(START + timedelta(seconds=s), "100", "101") for s in range(0, 600, 60)] if listening else [])
    for t in trades:
        db.add_trade(t, "ws:test")
    fetched = START + timedelta(minutes=10 if fetched_late else 0, seconds=30)
    db.upsert_candles("BTCUSDT", "1min", candles, fetched)
    return DataPortal(db)


def candle(minute, o, h, l, c, v="1"):
    return {"t": START + timedelta(minutes=minute), **{k: Decimal(x) for k, x in zip("ohlcv", (o, h, l, c, v))}}


def test_agreeing_divergent_and_missing_periods_are_classified(tmp_path):
    trades = [trade(0, "100"), trade(30, "110"), trade(40, "90"), trade(50, "105"),  # minute 0 matches the venue
              trade(60, "300"), trade(90, "300"),  # minute 1 differs wildly
              trade(240, "100"), trade(300, "100")]  # minute 4 the venue lacks; minute 5 still open
    candles = [candle(0, "100", "110", "90", "105"), candle(1, "200", "210", "190", "205"),
               candle(2, "100", "100", "100", "100"),  # venue traded while we listened and saw nothing
               candle(3, "100", "100", "100", "100", "0")]  # zero volume: carried price, not compared
    report = candle_crosscheck(crosscheck_db(tmp_path, trades, candles), "BTCUSDT", START, START + timedelta(minutes=10))
    status = {row["t"][11:16]: row["status"] for row in report["periods"]}
    assert status == {"09:00": "AGREE", "09:01": "DIVERGENT", "09:02": "MISSING_INTERNAL", "09:04": "MISSING_VENUE",
                      "09:05": "MISSING_VENUE"}
    assert report["counts"]["AGREE"] == 1 and report["periods"][1]["worst_bps"] == "5789.47"  # low: |300 - 190| / 190


def test_venue_candles_still_forming_when_fetched_are_not_compared(tmp_path):
    portal = crosscheck_db(tmp_path, [trade(0, "100")], [candle(0, "999", "999", "999", "999")], fetched_late=False)
    assert candle_crosscheck(portal, "BTCUSDT", START, START + timedelta(minutes=2))["counts"] == {"MISSING_VENUE": 1}


def test_venue_trading_while_the_collector_was_off_is_not_a_divergence(tmp_path):
    portal = crosscheck_db(tmp_path, [], [candle(0, "100", "100", "100", "100")], listening=False)
    assert candle_crosscheck(portal, "BTCUSDT", START, START + timedelta(minutes=2))["counts"] == {"NOT_COVERED": 1}
