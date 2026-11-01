"""B1 offline manual order provenance is visible but never money-authoritative."""
import asyncio
import json
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import MarketDB, SegmentWriter
from gym.api.server import make_app
from gym.cli import main
from gym.services.collector import Collector
from gym.services.external_journal import ExternalJournal
from gym.services.rules import RuleService


def test_manual_json_observation_cli_is_durable_and_api_is_token_protected(tmp_path):
    external = {
        "account_id": "main", "observed_at": "2026-10-31T15:01:00Z",
        "orders": [{"client_id": "external-1", "status": "new-unverified", "filled": "0.25",
                    "symbol": "BTCUSDT", "api_key": "DO-NOT-STORE"}],
    }
    source = tmp_path / "manual.json"
    source.write_text(json.dumps(external), "utf-8")
    assert main(["--data", str(tmp_path), "external-observe", str(source)]) == 0

    path = tmp_path / "live" / "external_journal.db"
    with ExternalJournal(path) as journal:
        rows = journal.events()
        assert len(rows) == 1 and rows[0]["raw_status"] == "new-unverified"
        assert "DO-NOT-STORE" not in str(rows)

        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        async def check():
            app = make_app(col, RuleService(db), "tok", external_journal=journal)
            async with TestClient(TestServer(app, host="127.0.0.1")) as c:
                assert (await c.get("/api/external-order-events")).status == 403
                r = await c.get("/api/external-order-events", headers={"X-Gym-Token": "tok"})
                assert r.status == 200
                data = await r.json()
                assert data["authority"] == "READ_ONLY"
                assert data["events"][0]["settlement"] == "UNKNOWN"
                assert "DO-NOT-STORE" not in await r.text()
        asyncio.run(check())
        db.c.close()


def test_external_order_ui_has_bilingual_journal_and_no_settlement_claims():
    ui = Path(__file__).resolve().parents[1] / "src" / "gym" / "ui"
    html = (ui / "index.html").read_text("utf-8")
    js = (ui / "app.js").read_text("utf-8")
    assert 'id="external-order-events"' in html
    assert 'data-t="externalHistory"' in html
    assert "/api/external-order-events" in js
    assert "async function externalJournal()" in js
    assert "مشاهدات" in js and "unverified" in js.lower()
