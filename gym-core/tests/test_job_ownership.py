"""Real SQLite connections fence publication without keeping a write lock during replay."""
from datetime import timedelta
import json
import asyncio
from threading import Event

import pytest

from gym.adapters.store import MarketDB
from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.services.collector import Collector
from gym.services.rules import RuleService
from aiohttp.test_utils import TestClient, TestServer
from gym.domain.model import iso
from gym.services import research_ledger
from gym.services.research_ledger import ResearchLedger
from tests.support import START, market_db, quote_history
from tests.test_research_ledger import schedule


def test_replaced_attempt_cannot_publish_over_new_owner(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history())
    path, due = tmp_path / "research.sqlite3", START + timedelta(hours=1)
    original = research_ledger.paper
    try:
        with ResearchLedger(path) as worker:
            job = schedule(worker)

            def takeover(*args, **kwargs):
                with ResearchLedger(path) as operator:
                    running = operator.overview()["jobs"][0]["last_report"]
                    assert running["status"] == "RUNNING" and running["liveness"] == "UNKNOWN"
                    request = {"job_id": job["job_id"], "expected_due": iso(due),
                               "expected_claim": running["claim_id"], "reason": "replace interrupted worker"}
                    with pytest.raises(ValueError, match="timestamp"):
                        operator.interrupt({**request, "expected_due": None}, at=due)
                    with pytest.raises(ValueError, match="changed"):
                        operator.interrupt({**request, "expected_claim": "stale"}, at=due)
                    operator.interrupt(request, at=due)
                    # A replacement claims before the old calculation returns.
                    monkeypatch.setattr(research_ledger, "paper", original)
                    other_db = MarketDB(tmp_path / "market.db", readonly=True)
                    try:
                        assert len(operator.run_due(other_db, iso(due), limit=1)["completed"]) == 1
                    finally:
                        other_db.c.close()
                return original(*args, **kwargs)

            monkeypatch.setattr(research_ledger, "paper", takeover)
            result = worker.run_due(db, iso(due), limit=1)
            assert result["completed"] == [] and len(result["superseded"]) == 1
            assert worker.overview()["jobs"][0]["next_at"] == iso(due + timedelta(hours=1))
            kinds = [a["kind"] for a in worker.overview()["alerts"]]
            assert kinds.count("RESEARCH_STARTED") == 2 and kinds.count("RESEARCH_COMPLETED") == 1
            assert kinds.count("RESEARCH_INTERRUPTED") == 1
            assert len(list((tmp_path / "runs").glob("*.json"))) == 1
    finally:
        db.c.close()


def test_crash_claim_survives_restart_and_requires_explicit_interruption(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history())
    path, due = tmp_path / "research.sqlite3", START + timedelta(hours=1)
    try:
        with ResearchLedger(path) as worker:
            job = schedule(worker)
            def crash(*_, **__):
                raise OSError("worker lost")
            monkeypatch.setattr(research_ledger, "paper", crash)
            with pytest.raises(OSError):
                worker.run_due(db, iso(due), limit=1)
        with ResearchLedger(path) as operator:
            running = operator.overview()["jobs"][0]["last_report"]
            assert running["status"] == "RUNNING"
            assert operator.run_due(db, iso(due + timedelta(days=1)), limit=1)["failed"] == []
            request = {"job_id": job["job_id"], "expected_due": iso(due),
                       "expected_claim": running["claim_id"], "reason": "worker exited"}
            assert not operator.interrupt(request, at=due)["process_terminated"]
            assert json.loads(operator.conn.execute("SELECT body FROM reports").fetchone()[0])["status"] == "FAILED"
            with pytest.raises(ValueError, match="changed"):
                operator.interrupt(request, at=due)
    finally:
        db.c.close()


def test_api_can_inspect_and_fence_while_catchup_is_running(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history())
    path, due = tmp_path / "research.sqlite3", START + timedelta(hours=1)
    entered, release = Event(), Event()
    original = research_ledger.paper
    with ResearchLedger(path) as ledger:
        job = schedule(ledger)
    def parked(*args, **kwargs):
        entered.set()
        assert release.wait(10), "test did not release the paper worker"
        return original(*args, **kwargs)
    monkeypatch.setattr(research_ledger, "paper", parked)
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
    async def check():
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok", tmp_path / "runs"))) as client:
            route, headers = "/api/research/action", {"X-Gym-Token": "tok"}
            pending = asyncio.create_task(client.post(route, json={"action": "job-catch-up", "value": {"job_id": job["job_id"], "limit": 1}}, headers=headers))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                response = await client.post(route, json={"action": "list", "value": None}, headers=headers)
                assert response.status == 200
                running = (await response.json())["jobs"][0]["last_report"]
                value = {"job_id": job["job_id"], "expected_due": iso(due), "expected_claim": running["claim_id"], "reason": "release parked attempt"}
                assert (await client.post(route, json={"action": "job-interrupt", "value": value})).status == 403
                response = await client.post(route, json={"action": "job-interrupt", "value": value}, headers=headers)
                assert response.status == 200, await response.text()
                assert not (await response.json())["process_terminated"]
            finally:
                release.set()
                response = await pending
            report = await response.json()
            assert response.status == 200 and not report["completed"] and len(report["superseded"]) == 1
    try:
        asyncio.run(check())
    finally:
        db.c.close()
