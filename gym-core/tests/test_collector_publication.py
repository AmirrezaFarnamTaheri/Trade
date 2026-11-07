"""A prospective clock can advance only after the whole collector tick is visible."""
import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.store import MarketDB, SegmentWriter
from gym.domain.model import iso
from gym.services import live_paper
from gym.services.collector import Collector
from gym.services.data_portal import DataPortal
from tests.support import START, market_db, quote, quote_history


def test_tick_publishes_all_markets_and_watermark_in_one_transaction(tmp_path, monkeypatch):
    db = market_db(tmp_path, [])
    observer = MarketDB(tmp_path/"market.db", readonly=True)
    collector = Collector(db, SegmentWriter(tmp_path/"raw",db), ["BTCUSDT","ETHUSDT"])
    insert = db.add_book_top
    visible = []
    def append(top, ref, depth=None):
        insert(top, ref, depth)
        visible.append((observer.c.execute("SELECT count(*) FROM book_top").fetchone()[0],DataPortal(observer).publication()))
    monkeypatch.setattr(db,"add_book_top",append)
    try:
        collector.tick(START)
        assert visible == [(0,None),(0,None)]
        assert observer.c.execute("SELECT count(*) FROM book_top").fetchone()[0] == 2
        assert DataPortal(observer).publication() == START
        assert not db.c.in_transaction
        collector.tick(START-timedelta(seconds=1))  # clock stepped back: publication pauses, app keeps running
        assert DataPortal(observer).publication() == START
        assert observer.c.execute("SELECT count(*) FROM book_top").fetchone()[0] == 2
        assert collector.status["clock_paused"] is True
        assert [r[2] for r in db.quality(5)].count("CLOCK_REGRESSION") == 1
        collector.tick(START+timedelta(seconds=2))
        assert DataPortal(observer).publication() == START+timedelta(seconds=2) and not collector.status["clock_paused"]
    finally:
        observer.c.close()
        db.c.close()


def test_failed_tick_does_not_publish_partial_rows_or_advance_cached_state(tmp_path,monkeypatch):
    db = market_db(tmp_path, [])
    collector = Collector(db, SegmentWriter(tmp_path/"raw",db), ["BTCUSDT","ETHUSDT"])
    insert = db.add_book_top
    def fail(top,ref,depth=None):
        insert(top,ref,depth)
        if top.symbol == "ETHUSDT":
            raise OSError("write failed")
    monkeypatch.setattr(db,"add_book_top",fail)
    try:
        with pytest.raises(OSError):
            collector.tick(START)
        assert db.c.execute("SELECT count(*) FROM book_top").fetchone()[0] == 0
        assert DataPortal(db).publication() is None
        assert collector.tops == collector.written == {}
        assert not db.c.in_transaction
        monkeypatch.setattr(db,"add_book_top",insert)
        collector.tick(START)
        assert db.c.execute("SELECT count(*) FROM book_top").fetchone()[0] == 2
    finally:
        db.c.close()


def test_live_watch_waits_for_publication_and_accepts_a_row_after_an_earlier_wall_scan(tmp_path,monkeypatch):
    db = market_db(tmp_path,quote_history(n=13))
    db.c.execute("INSERT INTO collector_publication VALUES(1,?)",(iso(START+timedelta(seconds=130)),))
    times = iter([START,*[START+timedelta(seconds=value) for value in (130,150,260,310,311)]])
    monkeypatch.setattr(live_paper,"now_utc",lambda:next(times))
    polls = 0
    async def advance(_):
        nonlocal polls
        polls += 1
        if polls == 2:
            # It was absent at wall time 150 but lies after the committed watermark 130.
            db.add_book_top(quote(START+timedelta(seconds=135),"70100","70101"),None)
            db.c.execute("UPDATE collector_publication SET through=?",(iso(START+timedelta(seconds=260)),))
        elif polls == 3:
            db.c.execute("UPDATE collector_publication SET through=?",(iso(START+timedelta(seconds=310)),))
    monkeypatch.setattr(live_paper.asyncio,"sleep",advance)
    try:
        out = asyncio.run(live_paper.watch(db,tmp_path/"runs","BTCUSDT",180,"1min",1,2,Decimal(1000)))
        assert out["result"]["session"]["state"] == "ENDED"
        assert out["result"]["observations"] == 13  # The quote exactly at session start is not replayed.
        assert out["result"]["end"]["mark_time"] == iso(START+timedelta(seconds=135))
        assert "publication_policy" in out["inputs"]
        assert not any("watermark was unavailable" in warning for warning in out["warnings"])
    finally:
        db.c.close()


@pytest.mark.parametrize("cancellation",[None,"Campaign wall limit reached"])
def test_wall_deadline_does_not_claim_completion_ahead_of_publication(tmp_path,monkeypatch,cancellation):
    db = market_db(tmp_path,quote_history(n=13))
    db.c.execute("INSERT INTO collector_publication VALUES(1,?)",(iso(START+timedelta(seconds=130)),))
    times = iter([START,*[START+timedelta(seconds=value) for value in (130,310,311)]])
    monkeypatch.setattr(live_paper,"now_utc",lambda:next(times))
    polls = 0
    async def stop_after_deadline(_):
        nonlocal polls
        polls += 1
        if polls == 2:
            raise asyncio.CancelledError(*([cancellation] if cancellation else []))
    monkeypatch.setattr(live_paper.asyncio,"sleep",stop_after_deadline)
    try:
        out = asyncio.run(live_paper.watch(db,tmp_path/"runs","BTCUSDT",180,"1min",1,2,Decimal(1000)))
        assert out["result"]["session"]["state"] == "ABORTED"
        assert out["result"]["session"]["events"][-1]["reason"] == (cancellation or "Session cancelled")
    finally:
        db.c.close()


def test_late_publication_keeps_decisions_before_the_requested_deadline(tmp_path,monkeypatch):
    db = market_db(tmp_path,quote_history(n=13))
    db.c.execute("INSERT INTO collector_publication VALUES(1,?)",(iso(START+timedelta(seconds=130)),))
    times = iter([START,*[START+timedelta(seconds=value) for value in (130,310,320,321)]])
    monkeypatch.setattr(live_paper,"now_utc",lambda:next(times))
    polls = 0
    async def publish_after_wall_deadline(_):
        nonlocal polls
        polls += 1
        if polls == 2:
            for second in (180,240,299):
                db.add_book_top(quote(START+timedelta(seconds=second),"70100","70101"),None)
            db.c.execute("UPDATE collector_publication SET through=?",(iso(START+timedelta(seconds=310)),))
    monkeypatch.setattr(live_paper.asyncio,"sleep",publish_after_wall_deadline)
    try:
        out = asyncio.run(live_paper.watch(db,tmp_path/"runs","BTCUSDT",180,"1min",1,2,Decimal(1000)))
        assert out["result"]["session"]["state"] == "ENDED"
        decisions = {row["t"] for row in out["result"]["decisions"]}
        assert {iso(START+timedelta(seconds=second)) for second in (180,240)} <= decisions
    finally:
        db.c.close()


def test_quiet_scan_cannot_add_decisions_after_the_running_deadline(tmp_path,monkeypatch):
    db = market_db(tmp_path,quote_history(n=13))
    db.c.execute("INSERT INTO collector_publication VALUES(1,?)",(iso(START+timedelta(seconds=123)),))
    times = iter([START,*[START+timedelta(seconds=value) for value in (123,201,202)]])
    monkeypatch.setattr(live_paper,"now_utc",lambda:next(times))
    async def publish_quiet(_):
        db.c.execute("UPDATE collector_publication SET through=?",(iso(START+timedelta(seconds=200)),))
    monkeypatch.setattr(live_paper.asyncio,"sleep",publish_quiet)
    try:
        out = asyncio.run(live_paper.watch(db,tmp_path/"runs","BTCUSDT",5,"1min",1,2,Decimal(1000)))
        assert out["result"]["session"]["state"] == "ENDED"
        assert max(row["t"] for row in out["result"]["decisions"]) <= iso(START+timedelta(seconds=125))
    finally:
        db.c.close()
