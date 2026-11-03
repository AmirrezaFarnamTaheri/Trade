"""C1 safe local Health and operator-import workflow; nothing can place an order."""
import asyncio
import hashlib
import json
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import MarketDB, SegmentWriter
from gym.api.server import make_app
from gym.cli import main
from gym.services.collector import Collector
from gym.services.rules import RuleService
from gym.services.venue_facts import VenueFactsJournal


def evidence():
    return {
        "evidence_id": "manual-20261101-1",
        "observed_at": "2026-11-01T08:00:00Z",
        "source": "SANITIZED_EXPORT",
        "kind": "FEES",
        "endpoint": "ACCOUNT_FEE",
        "state": "OBSERVED",
        "account_scope": "main",
        "response_version": "v1",
        "evidence_sha256": hashlib.sha256(b"sanitized fee evidence").hexdigest(),
    }


def test_cli_refuses_raw_credentials_and_imports_only_sanitized_metadata(tmp_path, capsys):
    source = tmp_path / "read-only-evidence.json"
    source.write_text(json.dumps({**evidence(), "api_key": "DO-NOT-STORE"}), encoding="utf-8")
    assert main(["--data", str(tmp_path), "venue-fact-import", str(source)]) == 2
    db_path = tmp_path / "live" / "venue_facts.db"
    assert not db_path.exists() or VenueFactsJournal(db_path).facts() == []
    source.write_text(json.dumps(evidence()), encoding="utf-8")
    assert main(["--data", str(tmp_path), "venue-fact-import", str(source)]) == 0
    assert "DO-NOT-STORE" not in capsys.readouterr().out
    with VenueFactsJournal(db_path) as journal:
        assert journal.facts()[0]["kind"] == "FEES"
        assert journal.capabilities()["assisted_order"]["state"] == "BLOCKED"


def test_token_guarded_c1_api_and_health_never_claim_certification(tmp_path):
    async def check():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        with VenueFactsJournal(tmp_path / "facts.db") as facts:
            facts.record(evidence())
            app = make_app(col, RuleService(db), "operator-run-token", venue_facts=facts)
            async with TestClient(TestServer(app, host="127.0.0.1")) as c:
                assert (await c.get("/api/venue-facts")).status == 403
                response = await c.get("/api/venue-facts", headers={"X-Gym-Token": "operator-run-token"})
                assert response.status == 200
                safe = await response.json()
                assert safe["authority"] == "READ_ONLY"
                assert safe["facts"][0]["evidence_id"] == "manual-20261101-1"
                assert safe["capabilities"]["venue_probe"]["state"] == "NOT_CERTIFIED"
                assert safe["capabilities"]["autopilot"]["funded_authority"] is False
                assert "DO-NOT-STORE" not in await response.text()
                health = await (await c.get("/api/health")).json()
                assert health["venue_validation"]["funded_authority"] is False
        db.c.close()
    asyncio.run(check())


def test_missing_venue_facts_is_unconfigured_not_a_live_account(tmp_path):
    async def check():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok"), host="127.0.0.1")) as c:
            response = await c.get("/api/venue-facts", headers={"X-Gym-Token": "tok"})
            assert response.status == 200
            data = await response.json()
            assert data["state"] == "NOT_CONFIGURED"
            assert data["facts"] == []
            assert data["funded_authority"] is False
        db.c.close()
    asyncio.run(check())


def test_bilingual_health_panel_renders_evidence_and_blocked_capabilities():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src" / "gym" / "ui"
    html = (root / "index.html").read_text("utf-8")
    js = (root / "app.js").read_text("utf-8")
    assert 'id="venue-facts"' in html
    assert 'data-t="venueFactsTitle"' in html
    assert "/api/venue-facts" in js
    assert "تأییدنشده" in js
    assert "NOT_CERTIFIED" in js
