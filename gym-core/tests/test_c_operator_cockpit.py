"""C1-C3 operator cockpit must never imply funded or certified permissions."""
import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer
from gym.adapters.store import MarketDB, SegmentWriter
from gym.api.server import make_app
from gym.services.collector import Collector
from gym.services.rules import RuleService


def ticket(**overrides):
    source = {
        "symbol": "BTCUSDT", "side": "BUY", "intent": "ENTRY",
        "quantity": "0.01", "bid": "100", "ask": "101",
        "worst_price": "103", "fee_rate": "0.002",
        "operator_quote_cap": "2", "available_quote": "2",
        "available_base": "0", "minimum_quote": "1",
        "observed_at": "2026-11-01T08:00:00Z",
        "expires_at": "2026-11-01T08:00:30Z",
        "snapshot_seq": 5, "quote_age_ms": 10,
    }
    source.update(overrides)
    return source


def test_offline_ticket_preview_requires_local_token_and_cannot_activate_trading(tmp_path):
    async def run():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        async with TestClient(TestServer(make_app(col, RuleService(db), "local-token"), host="127.0.0.1")) as c:
            assert (await c.post("/api/dry-run/ticket", json=ticket())).status == 403
            response = await c.post("/api/dry-run/ticket",
                headers={"X-Gym-Token":"local-token"}, json=ticket())
            assert response.status == 200
            body = await response.json()
            assert body["mode"] == "DRY_RUN"
            assert body["funded_authority"] is False
            assert body["order_submitted"] is False
            assert body["client_id"] is None
            assert "venue_order_id" not in body
            bad = await c.post("/api/dry-run/ticket",
                headers={"X-Gym-Token":"local-token"},
                json=ticket(api_key="SECRET-MUST-NOT-APPEAR"))
            assert bad.status == 400
            assert "SECRET-MUST-NOT-APPEAR" not in await bad.text()
            over = await c.post("/api/dry-run/ticket",
                headers={"X-Gym-Token":"local-token"},
                json=ticket(operator_quote_cap="0.1"))
            assert over.status == 400
        db.c.close()
    asyncio.run(run())


def test_autopilot_health_is_disarmed_and_unavailable_even_on_demo_runner(tmp_path):
    async def run():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"], demo=True)
        async with TestClient(TestServer(make_app(col, RuleService(db), "local-token"), host="127.0.0.1")) as c:
            assert (await c.get("/api/automation-safety")).status == 403
            response = await c.get("/api/automation-safety",
                headers={"X-Gym-Token":"local-token"})
            assert response.status == 200
            body = await response.json()
            assert body["mode"] == "DISARMED"
            assert body["protection"] == "UNAVAILABLE"
            assert body["venue_stops"] == "NOT_CERTIFIED"
            assert body["funded_authority"] is False
            assert body["autopilot_enabled"] is False
            assert body["entries_enabled"] is False
        db.c.close()
    asyncio.run(run())


def test_operate_cockpit_has_english_persian_and_no_fake_live_values():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src" / "gym" / "ui"
    html = (root / "index.html").read_text("utf-8")
    js = (root / "app.js").read_text("utf-8")
    assert 'data-view="operate"' in html
    assert 'id="v-operate"' in html
    assert 'id="offline-ticket"' in html
    assert 'id="preview-ticket"' in html
    assert 'id="protection-state"' in html
    assert "حفاظت" in js and "OFFLINE" in js
    assert "/api/dry-run/ticket" in js
    assert "/api/automation-safety" in js
    assert "order_submitted" in js
