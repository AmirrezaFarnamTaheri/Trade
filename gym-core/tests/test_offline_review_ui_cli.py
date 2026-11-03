"""C2 offline review queue is usable through CLI, Journal and guarded local API."""
import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer
from gym.adapters.store import MarketDB, SegmentWriter
from gym.api.server import make_app
from gym.cli import main
from gym.domain.assisted_ticket import prepare_preview
from gym.services.collector import Collector
from gym.services.offline_review_journal import OfflineReviewJournal
from gym.services.rules import RuleService


def data():
    return prepare_preview(
        symbol="BTCUSDT", side="BUY", intent="ENTRY", quantity="0.01",
        bid="100", ask="101", worst_price="103", fee_rate="0.002",
        operator_quote_cap="2", available_quote="2", available_base="0",
        minimum_quote="1", observed_at="2026-11-01T08:00:00Z",
        expires_at="2026-11-01T08:00:30Z", snapshot_seq=5, quote_age_ms=10,
    )


def test_cli_queue_is_durable_offline_only_and_does_not_elevate_tier(tmp_path, capsys):
    ticket = tmp_path/"preview.json"
    ticket.write_text(json.dumps(data()), encoding="utf-8")
    assert main(["--data",str(tmp_path),"ticket-queue-add",str(ticket)]) == 0
    added = json.loads(capsys.readouterr().out)
    assert added["tier1_approval"] is False
    assert added["funded_authority"] is False
    assert added["order_submitted"] is False
    assert main(["--data",str(tmp_path),"ticket-queue-review",
                 added["preview_sha256"],"ACKNOWLEDGE",
                 "--at","2026-11-01T08:00:10Z"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "ACKNOWLEDGED_OFFLINE"
    assert result["tier1_approval"] is False
    assert main(["--data",str(tmp_path),"ticket-queue-review",
                 added["preview_sha256"],"APPROVE_LIVE",
                 "--at","2026-11-01T08:00:11Z"]) == 2


def test_read_only_review_api_requires_token_and_shows_no_order_permission(tmp_path):
    async def check():
        db = MarketDB(tmp_path/"market.db")
        col = Collector(db, SegmentWriter(tmp_path/"raw", db), ["BTCUSDT"])
        with OfflineReviewJournal(tmp_path/"offline_reviews.db") as queue:
            key = queue.record(data())
            queue.review(key,"REJECT",at="2026-11-01T08:00:10Z")
            async with TestClient(TestServer(make_app(col,RuleService(db),"token",
                    offline_review_journal=queue),host="127.0.0.1")) as c:
                assert (await c.get("/api/offline-ticket-reviews")).status == 403
                response = await c.get("/api/offline-ticket-reviews",
                                       headers={"X-Gym-Token":"token"})
                assert response.status == 200
                text = await response.text()
                result = await response.json()
                assert result["authority"] == "OFFLINE_ONLY"
                assert result["funded_authority"] is False
                assert result["tickets"][0]["state"] == "REJECTED_OFFLINE"
                assert result["reviews"][0]["tier1_approval"] is False
                assert "api_key" not in text
        db.c.close()
    asyncio.run(check())


def test_review_journal_is_visible_in_bilingual_ui():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]/"src"/"gym"/"ui"
    html = (root/"index.html").read_text("utf-8")
    js = (root/"app.js").read_text("utf-8")
    assert 'id="offline-review-events"' in html
    assert 'data-t="offlineReviewTitle"' in html
    assert "/api/offline-ticket-reviews" in js
    assert "تأیید" in js
