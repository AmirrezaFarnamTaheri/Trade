"""Readiness uses both current book-side clocks, independently of heartbeat traffic."""
import asyncio
from datetime import timedelta

from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import SegmentWriter
from gym.api import server
from gym.domain.model import BookSide
from gym.services.collector import Collector
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history


def test_live_readiness_rechecks_stale_and_future_sides_without_a_collector_tick(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history(n=3))
    seg = SegmentWriter(tmp_path / "raw", db)
    col = Collector(db, seg, ["BTCUSDT", "ETHUSDT"])
    monkeypatch.setattr(server, "now_utc", lambda: START)
    col.status.update(connected=True, last_frame=START)
    from decimal import Decimal
    for symbol in col.books:
        col.books[symbol] = {
            "bid": BookSide([(Decimal("100"), Decimal("5"))], START),
            "ask": BookSide([(Decimal("101"), Decimal("5"))], START),
        }
    col.tick(START)

    async def check():
        async with TestClient(TestServer(server.make_app(col, RuleService(db), "tok"))) as client:
            response = await client.get("/api/ready")
            result = await response.json()
            assert response.status == 200 and result["ready"] is True
            assert result["funded_authority"] is False
            col.books["ETHUSDT"]["ask"] = BookSide(col.books["ETHUSDT"]["ask"].levels, START - timedelta(seconds=121))
            response = await client.get("/api/ready")
            result = await response.json()
            assert response.status == 200 and result["status"] == "DEGRADED"
            assert result["markets"][1]["state"] == "STALE"
            assert result["markets"][1]["ask_age_seconds"] == 121
            monkeypatch.setattr(server, "now_utc", lambda: START + timedelta(seconds=121))
            response = await client.get("/api/ready")
            assert response.status == 503
            assert (await response.json())["ready"] is False
            markets = await (await client.get("/api/markets")).json()
            assert all(not row["qualified"] and "STALE" in row["flags"] for row in markets["markets"])
            # A fresh WebSocket ping cannot make an old book current.
            assert (await client.get("/api/health")).status == 200
            monkeypatch.setattr(server, "now_utc", lambda: START - timedelta(seconds=1))
            result = await (await client.get("/api/ready")).json()
            assert result["markets"][0]["state"] == "FUTURE"
    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()
