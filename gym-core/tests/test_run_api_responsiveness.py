"""Saved report reads must leave the collector's event loop available."""
import asyncio
import threading
from datetime import timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.run_store import save_run
from gym.adapters.store import SegmentWriter
from gym.api import server
from gym.services.collector import Collector
from gym.services.paper import paper
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history


@pytest.mark.parametrize("suffix", ["", "/summary", "/summary.html"])
def test_saved_run_loading_does_not_block_health_requests(tmp_path, monkeypatch, suffix):
    db = market_db(tmp_path, quote_history(n=180))
    try:
        record = paper(db, "BTCUSDT", START, START + timedelta(minutes=29),
                       resolution="1min", fast=2, slow=3)
        runs = tmp_path / "runs"
        save_run(record, runs)
        collector = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        entered, release = threading.Event(), threading.Event()
        threads = []
        original = server.load_run

        def held_load(*args):
            threads.append(threading.get_ident())
            entered.set()
            assert threads[-1] != loop_thread, "saved run loaded on the collector event loop"
            assert release.wait(5), "test did not release saved run reader"
            return original(*args)

        monkeypatch.setattr(server, "load_run", held_load)

        async def scenario():
            nonlocal loop_thread
            loop_thread = threading.get_ident()
            app = server.make_app(collector, RuleService(db), "tok", runs)
            async with TestClient(TestServer(app)) as client:
                pending = asyncio.create_task(client.get("/api/runs/" + record["run_id"] + suffix,
                                                        headers={"X-Gym-Token": "tok"}))
                try:
                    assert await asyncio.to_thread(entered.wait, 5), "saved run reader never started"
                    assert threads != [loop_thread]
                    assert not pending.done()
                    assert not release.is_set()
                    health = await client.get("/api/ready")
                    assert health.status in (200, 503)
                    assert not pending.done()
                finally:
                    release.set()
                    response = await pending
                assert response.status == 200, await response.text()
                assert response.content_type == ("text/html" if suffix.endswith(".html") else "application/json")

        loop_thread = None
        asyncio.run(scenario())
    finally:
        db.c.close()
