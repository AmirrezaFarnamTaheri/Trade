"""B1 read-only manual account observation UI/API contract.

Live credential provisioning is deliberately NOT part of this view. The API
does not accept secrets or give funded order authority to the browser.
"""
import asyncio
from aiohttp.test_utils import TestClient, TestServer
from gym.adapters.store import MarketDB, SegmentWriter
from gym.api.server import make_app
from gym.services.collector import Collector
from gym.services.rules import RuleService


def test_account_api_is_token_guarded_and_defaults_to_not_configured(tmp_path):
    async def run():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        async with TestClient(TestServer(make_app(col, RuleService(db), "secret"), host="127.0.0.1")) as c:
            assert (await c.get("/api/account-observations")).status == 403
            result = await (await c.get("/api/account-observations", headers={"X-Gym-Token": "secret"})).json()
            assert result["state"] == "NOT_CONFIGURED"
            assert result["authority"] == "READ_ONLY"
            assert result["balances"] == [] and result["orders"] == []
        db.c.close()
    asyncio.run(run())


def test_account_api_sanitizes_raw_observations_and_does_not_derive_cash(tmp_path):
    async def run():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        raw = {
            "account_id": "main", "observed_at": "2026-10-31T15:00:00Z",
            "balances": {"USDT": {"value": "10.01", "locked": "4", "api_key": "NO-LEAK"}},
            "orders": [{"client_id": "external-1", "status": "UNLISTED", "filled": "1", "api_key": "NO-LEAK"}],
        }
        app = make_app(col, RuleService(db), "secret", account_observation=raw)
        async with TestClient(TestServer(app, host="127.0.0.1")) as c:
            resp = await c.get("/api/account-observations", headers={"X-Gym-Token": "secret"})
            assert resp.status == 200
            text = await resp.text()
            assert "NO-LEAK" not in text
            data = await resp.json()
            assert data["balances"][0]["spendable"] is None
            assert data["orders"][0]["settlement"] == "UNKNOWN"
            assert data["orders"][0]["funded_trade"] is False
        db.c.close()
    asyncio.run(run())


def test_journal_renders_readonly_account_state_bilingually():
    from pathlib import Path
    ui = Path(__file__).resolve().parents[1] / "src" / "gym" / "ui"
    html = (ui / "index.html").read_text("utf-8")
    js = (ui / "app.js").read_text("utf-8")
    assert 'data-t="accountRead"' in html
    assert 'id="account-state"' in html and 'id="account-observations"' in html
    assert "async function accountJournal()" in js
    assert "/api/account-observations" in js
    assert "حساب" in js and "NOT_CONFIGURED" in js
