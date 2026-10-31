"""Decimal parsing, quote quality, raw segments and point-in-time bars."""
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from gym.adapters.store import SegmentWriter
from gym.domain.bars import BarSpec, Consolidator, quote_bars
from gym.domain.model import TEHRAN, UTC, BookSide, book_top, levels, loads, dec
from gym.services.collector import Collector
from gym.services.data_portal import DataPortal
from gym.services.paper import paper
from tests.support import START, market_db, quote, quote_history
from gym.adapters.store import MarketDB, read_segment


# Real frames captured from wss://api.wallex.ir/connection/websocket on 2026-10-30.
WS_DEPTH = ('{"push":{"channel":"orderbook:BTCTMN@buyDepth","pub":{"data":{"message":[{"price":21038000010,'
            '"quantity":0.05229445,"sum":1100170639.6229446},{"price":21038000000,"quantity":0.00001245,"sum":261923.1},'
            '{"price":21022500222,"quantity":0.004329,"sum":91006403.461038}]}}}}')
WS_ASK = ('{"push":{"channel":"orderbook:BTCTMN@sellDepth","pub":{"data":{"message":[{"price":21079999645,'
          '"quantity":0.000919,"sum":19372519.673755},{"price":21079999646,"quantity":0.00474383,"sum":99999934.72068419},'
          '{"price":21079999647,"quantity":0.004,"sum":84319998.588}]}}}}')
WS_TRADE = ('{"push":{"channel":"public:BTCTMN@trade","pub":{"data":{"isBuyOrder":true,"price":"21038000010",'
            '"quantity":"0.00001399","timestamp":"2026-10-30T20:53:00Z"}}}}')


def test_exact_decimals_never_float():
    lv = levels(loads(WS_DEPTH)["push"]["pub"]["data"]["message"])
    assert lv[0] == (Decimal("21038000010"), Decimal("0.05229445"))
    assert str(loads('{"x":1100170639.6229446}')["x"]) == "1100170639.6229446"
    with pytest.raises(TypeError):
        dec(0.1)


def test_book_quality_flags():
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    side = lambda p: BookSide([(Decimal(p), Decimal(1))] * 3, now)  # noqa: E731
    assert book_top("X", side("101"), side("100"), now).flags == {"CROSSED"}
    assert book_top("X", side("100"), side("100"), now).flags == {"ZERO_SPREAD"}
    assert "WIDE_SPREAD" in book_top("X", side("100"), side("110"), now).flags
    ok = book_top("X", side("100"), side("100.5"), now)
    assert ok.flags == set() and ok.spread_bps == Decimal("49.88")
    assert "STALE" in book_top("X", side("100"), side("100.5"), now + timedelta(seconds=121)).flags
    assert "STALE" in book_top("X", None, side("100.5"), now).flags
    assert "NON_FINITE" in book_top("X", BookSide([(Decimal("NaN"), Decimal(1))], now), side("1"), now).flags


def test_collector_segments_and_change_only_tops(tmp_path):
    db = MarketDB(tmp_path / "m.db")
    seg = SegmentWriter(tmp_path / "raw", db)
    col = Collector(db, seg, ["BTCTMN"])
    now = datetime(2026, 10, 30, 20, 53, 1, tzinfo=UTC)
    for f in (WS_DEPTH, WS_ASK, WS_TRADE, "{}", "not json"):
        col.handle_frame(f, now)
    col.tick(now)
    col.tick(now + timedelta(seconds=2))  # unchanged top: not written again
    assert db.c.execute("select count(*) from book_top").fetchone()[0] == 1
    assert db.c.execute("select bid, ask from book_top").fetchone() == ("21038000010", "21079999645")
    assert db.c.execute("select price, aggressor from trades").fetchall() == [("21038000010", "SELL")]
    assert db.c.execute("select count(*) from quality_events where flag='SOURCE_ERROR'").fetchone()[0] == 1
    seg.close()
    sid, path, a, b, sha, n = db.c.execute("select seg_id, path, seq_from, seq_to, sha256, bytes from segments").fetchone()
    lines = read_segment(Path(path))
    assert (a, b) == (1, 4) and [x["raw"] for x in lines] == [WS_DEPTH, WS_ASK, WS_TRADE, "not json"]
    import hashlib
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha


def test_invalid_ranges_and_resolutions_fail_explicitly(tmp_path):
    with pytest.raises(ValueError, match="unsupported resolution"):
        BarSpec("5min")
    with pytest.raises(ValueError, match="inverted"):
        DataPortal(market_db(tmp_path, [])).tops("BTCUSDT", START, START - timedelta(hours=1))
    with pytest.raises(ValueError, match="no qualified"):
        paper(market_db(tmp_path, []), "BTCUSDT", START, START + timedelta(hours=1))


def test_bars_are_closed_point_in_time_and_match_streaming():
    rows = quote_history(400) + [quote(START + timedelta(seconds=4005), "1", "2", ["STALE"])]
    spec = BarSpec("15min", "MID")
    c, live = Consolidator("BTCUSDT", spec), []
    for x in rows[:-1]:
        live += c.update(x.ts_avail, spec.price(x))
    assert live == quote_bars("BTCUSDT", spec, rows)  # streaming == batch, and STALE quotes never become bars
    assert all(b.avail == b.end and not b.forming for b in live)
    assert all(b.start.minute % 15 == 0 and b.end - b.start == spec.step for b in live)
    f = c.forming(START + timedelta(seconds=3995))
    assert f.forming and f not in live
    assert c.scan(f.end) and c.forming(f.end) is None  # quiet market: the clock closes the bar
    bid, ask = quote_bars("X", BarSpec("15min", "BID"), rows), quote_bars("X", BarSpec("15min", "ASK"), rows)
    assert all(a.close - b.close == 10 for a, b in zip(ask, bid))  # separate bid and ask series
    day = BarSpec("1day").bucket(datetime(2026, 10, 29, 22, tzinfo=UTC))
    assert day.astimezone(TEHRAN).hour == 0 and day.astimezone(TEHRAN).day == 30  # Tehran midnight
