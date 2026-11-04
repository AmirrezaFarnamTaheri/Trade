"""Slow public REST refresh cannot suspend freshness checks and raw-book heartbeats."""
import asyncio
import itertools
from types import SimpleNamespace

import pytest

from gym.adapters.store import SegmentWriter
from gym.services import collector
from gym.services.collector import Collector
from tests.support import market_db, quote_history


def test_maintenance_ticks_continue_during_a_blocked_reseed(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history(n=3))
    seg = SegmentWriter(tmp_path / "raw", db)
    col = Collector(db, seg, ["BTCUSDT"])
    original_sleep = asyncio.sleep
    clock = itertools.count(0, 61)
    monkeypatch.setattr(collector, "time", SimpleNamespace(monotonic=lambda: next(clock)))

    async def check():
        blocked, reached = asyncio.Event(), asyncio.Event()
        ticks = []

        async def sleep(_):
            await original_sleep(0)

        async def seed(*args, **kwargs):
            blocked.set()
            await asyncio.Event().wait()

        def tick(now):
            ticks.append(now)
            if blocked.is_set() and len(ticks) >= 3:
                reached.set()

        monkeypatch.setattr(collector.asyncio, "sleep", sleep)
        monkeypatch.setattr(col, "seed", seed)
        monkeypatch.setattr(col, "tick", tick)
        # Missing tops need reseeding too, including while WS is disconnected.
        tasks = [asyncio.create_task(col._housekeeping()), asyncio.create_task(col._refresh_rest(object()))]
        try:
            await asyncio.wait_for(reached.wait(), 1)
            assert blocked.is_set() and len(ticks) >= 3
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()


def test_collector_failure_cancels_maintenance_before_returning(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history(n=3))
    seg = SegmentWriter(tmp_path / "raw", db)
    col = Collector(db, seg, ["BTCUSDT"], demo=True)

    async def check():
        started, stopped = asyncio.Event(), asyncio.Event()
        async def housekeeping():
            await started.wait()
            raise RuntimeError("maintenance failed")
        async def feed():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                stopped.set()
        monkeypatch.setattr(col, "_housekeeping", housekeeping)
        monkeypatch.setattr(col, "_demo", feed)
        with pytest.raises(ExceptionGroup):
            await col.run()
        assert stopped.is_set()
    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()
