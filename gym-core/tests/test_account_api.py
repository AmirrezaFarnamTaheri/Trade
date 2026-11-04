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


def test_account_api_reads_persisted_snapshot_without_network_or_credentials(tmp_path):
    from gym.domain.account_observations import project_account
    from gym.services.external_journal import ExternalJournal

    async def run():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        with ExternalJournal(tmp_path / "external.db") as journal:
            journal.record(project_account("main", "2026-11-03T12:00:00Z",
                           balances={"USDT": {"value": "10.2", "locked": "1"}}),
                           fee_rates={"BTCUSDT": {"maker": "0.001", "taker": "0.002"}},
                           transport="EXECUTOR_SERVICE_WINHTTP")
            app = make_app(col, RuleService(db), "secret", external_journal=journal)
            async with TestClient(TestServer(app, host="127.0.0.1")) as c:
                assert (await c.get("/api/account-observations")).status == 403
                response = await c.get("/api/account-observations", headers={"X-Gym-Token": "secret"})
                assert response.status == 200 and response.headers["Cache-Control"] == "no-store"
                saved = await response.json()
                assert saved["state"] == "OBSERVED"
                assert saved["balances"][0]["venue_value"] == "10.2"
                assert saved["fee_rates"]["BTCUSDT"]["maker"] == "0.001"
                assert saved["permission_status"] == "UNVERIFIED" and saved["funded_authority"] is False
        db.c.close()
    asyncio.run(run())


def test_account_api_does_not_expose_corrupt_snapshot_data(tmp_path):
    from gym.services.external_journal import ExternalJournal

    async def run():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        with ExternalJournal(tmp_path / "external.db") as journal:
            journal.conn.execute(
                "INSERT INTO external_account_snapshots(account_id,observed_at,snapshot_json) VALUES(?,?,?)",
                ("main", "2026-11-03T12:00:00.000000+00:00", '{"api_key":"DO-NOT-COPY"}'),
            )
            journal.conn.commit()
            app = make_app(col, RuleService(db), "secret", external_journal=journal)
            async with TestClient(TestServer(app, host="127.0.0.1")) as c:
                response = await c.get("/api/account-observations", headers={"X-Gym-Token": "secret"})
                assert response.status == 503
                assert "DO-NOT-COPY" not in await response.text()
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
