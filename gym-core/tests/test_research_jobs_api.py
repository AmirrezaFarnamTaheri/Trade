"""Authenticated paper schedule controls use the durable research ledger."""
import asyncio
from datetime import timedelta

from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.api import server
from gym.domain.model import iso
from gym.services.collector import Collector
from gym.services.research_ledger import ResearchLedger
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history


def test_research_controls_are_authenticated_durable_and_paper_only(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "now_utc", lambda: START + timedelta(minutes=29))
    db = market_db(tmp_path, quote_history(n=180))
    seg = SegmentWriter(tmp_path / "raw", db)
    col = Collector(db, seg, ["BTCUSDT"])
    path = tmp_path / "research.sqlite3"
    with ResearchLedger(path) as ledger:
        hypothesis = ledger.register({"symbol": "BTCUSDT", "strategy": "ema-trend", "params": {"fast": 2, "slow": 3}})
        job = ledger.schedule({"hypothesis_id": hypothesis["hypothesis_id"], "every_seconds": 3600,
                               "lookback_seconds": 1800, "first_at": iso(START + timedelta(minutes=29)),
                               "resolution": "1min", "cash": "1000", "fee_rate": "0.001"})

    async def check():
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok", tmp_path / "runs"))) as client:
            for endpoint in ("/api/research-state", "/api/research/jobs/" + job["job_id"] + "/pause"):
                request = client.get if endpoint.endswith("state") else client.post
                assert (await request(endpoint)).status == 403
            headers = {"X-Gym-Token": "tok"}
            response = await client.get("/api/research-state", headers=headers)
            assert response.status == 200
            assert response.headers["Cache-Control"] == "no-store"
            state = await response.json()
            assert state["authority"] == "PAPER_ONLY" and state["funded_authority"] is False
            assert state["jobs"][0]["enabled"] is True
            assert state["jobs"][0]["last_report"] is None
            due = state["jobs"][0]["next_at"]
            for action, enabled in (("pause", False), ("resume", True)):
                result = await client.post("/api/research/jobs/" + job["job_id"] + "/" + action,
                                           json={}, headers=headers)
                assert result.status == 200
                assert (await result.json())["enabled"] is enabled
                state = await (await client.get("/api/research-state", headers=headers)).json()
                assert state["jobs"][0]["next_at"] == due
            assert (await client.post("/api/research/jobs/unknown/pause", json={}, headers=headers)).status == 400
            assert (await client.post("/api/research/jobs/" + job["job_id"] + "/pause",
                                      json={"funded_authority": True}, headers=headers)).status == 400
            tick = await client.post("/api/research/tick", json={}, headers=headers)
            assert tick.status == 200
            result = await tick.json()
            assert result["order_submitted"] is False
            assert len(result["completed"]) == 1
            state = await (await client.get("/api/research-state", headers=headers)).json()
            assert state["jobs"][0]["last_report"]["status"] == "COMPLETED"
            assert state["jobs"][0]["last_report"]["run_id"] == result["completed"][0]["run_id"]
            run_id = result["completed"][0]["run_id"]
            saved = await (await client.get("/api/runs/" + run_id)).json()
            assert saved["run_id"] == run_id and saved["inputs"]["strategy"] == "ema-trend"
            monkeypatch.setattr(server, "now_utc", lambda: START + timedelta(minutes=89))
            result = await (await client.post("/api/research/tick", json={}, headers=headers)).json()
            assert len(result["failed"]) == 1
            state = await (await client.get("/api/research-state", headers=headers)).json()
            last = state["jobs"][0]["last_report"]
            assert last["status"] == "FAILED" and last["attempts"] == 1
            assert last["retry_at"] == result["failed"][0]["retry_at"]
    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()


def test_unconfigured_research_read_does_not_create_a_ledger(tmp_path):
    db = market_db(tmp_path, quote_history(n=3))
    seg = SegmentWriter(tmp_path / "raw", db)
    col = Collector(db, seg, ["BTCUSDT"])

    async def check():
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok", tmp_path / "runs"))) as client:
            response = await client.get("/api/research-state", headers={"X-Gym-Token": "tok"})
            assert response.status == 200
            assert (await response.json())["state"] == "NOT_CONFIGURED"
            assert not (tmp_path / "research.sqlite3").exists()
    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()
