"""The GUI journal uses canonical previews and the server's actual review clock."""
import asyncio
from datetime import datetime, timezone

from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import SegmentWriter
from gym.api import offline_reviews
from gym.api.server import make_app
from gym.services.collector import Collector
from gym.services.rules import RuleService
from tests.support import market_db, quote_history
from tests.test_offline_review_journal import preview


def test_journal_api_preserves_native_validation_and_cannot_backdate_acknowledgments(tmp_path, monkeypatch):
    monkeypatch.setattr(offline_reviews, "now_utc", lambda: datetime(2026, 11, 1, 8, 0, 10, tzinfo=timezone.utc))
    db = market_db(tmp_path, quote_history(n=10))
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])

    async def check():
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok", tmp_path / "runs"))) as client:
            route, headers = "/api/offline-ticket-reviews", {"X-Gym-Token": "tok"}
            body = {"action": "record", "value": preview()}
            assert (await client.post(route, json=body)).status == 403
            assert not (tmp_path / "offline_reviews.db").exists()
            assert (await client.post(route, json={**body, "value": {**preview(), "worst_total_quote": "0"}}, headers=headers)).status == 400
            assert (await client.post(route, json=body, headers=headers)).status == 200
            value = {"preview_sha256": preview()["preview_sha256"], "decision": "ACKNOWLEDGE"}
            for bad in ({**value, "at": "2026-11-01T08:00:10Z"}, {**value, "decision": []}, {**value, "decision": "APPROVE_LIVE"}):
                assert (await client.post(route, json={"action": "review", "value": bad}, headers=headers)).status == 400
            assert (await client.post(route, data='{"action":"record","action":"review","value":{}}', headers=headers)).status == 400
            assert (await client.post(route, json={"action": "review", "value": value}, headers=headers)).status == 200
            assert (await client.post(route, json={"action": "review", "value": value}, headers=headers)).status == 400
            state = await (await client.get(route, headers=headers)).json()
            assert state["tickets"][0]["state"] == "ACKNOWLEDGED_OFFLINE"
            assert state["tickets"][0]["tier1_approval"] is False
            assert state["reviews"][0]["reviewed_at"] == "2026-11-01T08:00:10+00:00"
    try:
        asyncio.run(check())
    finally:
        db.c.close()
