"""Loopback paired-research behavior, persistence, and worker isolation."""
import asyncio
import sqlite3
from copy import deepcopy
from datetime import timedelta
from threading import Event

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import SegmentWriter
from gym.api import server
from gym.domain.model import iso
from gym.services.collector import Collector
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history


@pytest.fixture
def research_app(tmp_path, monkeypatch):
    monkeypatch.delenv("GYM_FEE_RATE", raising=False)
    db = market_db(tmp_path, quote_history(n=180))
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
    runs = tmp_path / "runs"
    yield db, col, runs
    db.c.close()


def request_body():
    return {"symbol": "BTCUSDT", "from": iso(START), "to": iso(START + timedelta(minutes=29)),
            "resolution": "1min", "cash": "1000.123456789012345678",
            "candidates": [{"strategy": "ema-trend", "params": {"fast": 2, "slow": 3}},
                           {"strategy": "sma-reversion", "params": {"lookback": 4}}]}


def test_setup_compare_and_saved_runs(research_app):
    db, col, runs = research_app

    async def check():
        async with TestClient(TestServer(server.make_app(col, RuleService(db), "tok", runs))) as client:
            setup_response = await client.get("/api/research")
            setup = await setup_response.json()
            assert setup_response.headers["Cache-Control"] == "no-store"
            assert setup["authority"] == "PAPER_ONLY" and setup["funded_authority"] is False
            assert setup["symbols"] == ["BTCUSDT"]
            assert len(setup["strategies"]) == 10
            assert setup["coverage"]["observations"] == 180
            assert setup["defaults"]["fee_rate"] == "0.001"
            unknown = await (await client.get("/api/research?symbol=UNKNOWN")).json()
            assert unknown["coverage"]["observations"] == 0
            for token in (None, "wrong"):
                headers = {} if token is None else {"X-Gym-Token": token}
                assert (await client.post("/api/compare", json=request_body(), headers=headers)).status == 403
            for fee in (None, "0.001234567890123456789"):
                body = request_body()
                if fee is not None:
                    body["fee_rate"] = fee
                response = await client.post("/api/compare", json=body, headers={"X-Gym-Token": "tok"})
                assert response.status == 200, await response.text()
                result = await response.json()
                assert response.headers["Cache-Control"] == "no-store"
                assert result["mode"] == "COMPARE" and result["authority"] == "PAPER_ONLY"
                assert result["funded_authority"] is False and result["order_submitted"] is False
                assert len(result["runs"]) == 2
                for record in result["runs"]:
                    assert record["inputs"]["cash"] == body["cash"]
                    assert record["inputs"]["cost"]["fee_rate"] == (fee or "0.001")
                    saved = await (await client.get("/api/runs/" + record["run_id"])).json()
                    assert saved["inputs"] == record["inputs"]
                    assert saved["result"]["start_cash"] == body["cash"]
                    assert saved["result"]["decisions"]
                first, second = result["runs"]
                assert first["inputs"]["data"] == second["inputs"]["data"]
                assert first["inputs"]["snapshots"] == second["inputs"]["snapshots"]
            assert len(await (await client.get("/api/runs")).json()) == 4
            safety = await (await client.get("/api/automation-safety", headers={"X-Gym-Token": "tok"})).json()
            assert safety["funded_authority"] is False and safety["entries_enabled"] is False
    asyncio.run(check())


def test_chronological_validation_api_saves_referenced_runs_before_manifest(research_app):
    import json
    db, col, runs = research_app

    async def check():
        async with TestClient(TestServer(server.make_app(col, RuleService(db), "tok", runs))) as client:
            assert (await client.post("/api/validate", json=request_body())).status == 403
            response = await client.post("/api/validate", json=request_body(), headers={"X-Gym-Token": "tok"})
            assert response.status == 200, await response.text()
            report = await response.json()
            assert report["mode"] == "TEMPORAL_VALIDATION" and report["independent_final_evidence"] is False
            manifest = runs / "validations" / (report["validation_id"] + ".json")
            saved = json.loads(manifest.read_text("utf-8"))
            assert saved["funded_authority"] is False
            assert saved["selection"] == report["selection"]
            for run in report["runs"]:
                assert (await client.get("/api/runs/" + run["run_id"])).status == 200
            assert "runs" not in saved
    asyncio.run(check())


def test_multi_window_api_retains_references_and_rejects_missing_authority(research_app):
    import json
    db, col, runs = research_app

    async def check():
        async with TestClient(TestServer(server.make_app(col, RuleService(db), "tok", runs))) as client:
            body = {**request_body(), "folds": 2}
            assert (await client.post("/api/validate", json=body)).status == 403
            response = await client.post("/api/validate", json=body, headers={"X-Gym-Token": "tok"})
            assert response.status == 200, await response.text()
            report = await response.json()
            assert report["mode"] == "MULTI_WINDOW_VALIDATION" and report["fold_count"] == 2
            assert report["funded_authority"] is False and report["order_submitted"] is False
            assert response.headers["Cache-Control"] == "no-store"
            saved = json.loads((runs / "validations" / (report["validation_id"] + ".json")).read_text("utf-8"))
            assert saved["folds"] == report["folds"] and "runs" not in saved
            ids = {row["run_id"] for row in report["runs"]}
            for fold in report["folds"]:
                assert set(fold["selection"]["run_ids"]) <= ids
                assert fold["holdout_run_id"] is None or fold["holdout_run_id"] in ids
            for run_id in ids:
                assert (await client.get("/api/runs/" + run_id)).status == 200
    asyncio.run(check())


@pytest.mark.parametrize("folds", [True, 0, 6, "2", 1.5, None])
def test_invalid_api_window_counts_never_publish(research_app, folds):
    db, col, runs = research_app

    async def check():
        async with TestClient(TestServer(server.make_app(col, RuleService(db), "tok", runs))) as client:
            response = await client.post("/api/validate", json={**request_body(), "folds": folds}, headers={"X-Gym-Token": "tok"})
            assert response.status == 400, await response.text()
            assert not list(runs.rglob("*.json"))
    asyncio.run(check())


BAD_FIELDS = [
    {"folds": 2},
    {"symbol": "UNKNOWN"}, {"symbol": "../BTCUSDT"}, {"symbol": None},
    {"candidates": []}, {"candidates": [{}]}, {"candidates": [None, {}]},
    {"candidates": [{"strategy": "unknown"}, {"strategy": "ema-trend"}]},
    {"candidates": [{"strategy": "ema-trend", "params": {"fast": True}}, {"strategy": "ema-trend"}]},
    {"candidates": [{"strategy": "ema-trend", "params": {"extra": 1}}, {"strategy": "ema-trend"}]},
    {"latency_ms": True}, {"latency_ms": 1.5}, {"latency_ms": -1}, {"latency_ms": 60001},
    {"from": "2026-10-29T09:00:00"}, {"from": "bad"}, {"to": "2999-01-01T00:00:00Z"},
    {"to": iso(START)}, {"to": iso(START + timedelta(days=32))},
    {"resolution": "invalid"}, {"resolution": []}, {"resolution": True},
    {"rules_mode": "live"}, {"rules_mode": {}}, {"funded_authority": True},
] + [{field: value} for field in ("cash", "fee_rate")
     for value in (True, 1, 0.001, "NaN", "Infinity", "-1", "", " 1", "1_0", "1e999999", "1" * 65)] + [
    {"cash": "0"}, {"fee_rate": "1"},
]


@pytest.mark.parametrize("fields", BAD_FIELDS)
def test_invalid_comparisons_are_not_saved(research_app, fields):
    db, col, runs = research_app

    async def check():
        async with TestClient(TestServer(server.make_app(col, RuleService(db), "tok", runs))) as client:
            body = deepcopy(request_body())
            body.update(fields)
            response = await client.post("/api/compare", json=body, headers={"X-Gym-Token": "tok"})
            assert response.status == 400, await response.text()
            assert "error" in await response.json()
            assert not list(runs.glob("*.json"))
    asyncio.run(check())


def test_no_storage_and_non_object_requests(research_app):
    db, col, runs = research_app

    async def check():
        for storage in (None, runs):
            async with TestClient(TestServer(server.make_app(col, RuleService(db), "tok", storage))) as client:
                bodies = [request_body()] if storage is None else [[], None, True, "text"]
                for body in bodies:
                    response = await client.post("/api/compare", json=body, headers={"X-Gym-Token": "tok"})
                    assert response.status == 400
                assert not list(runs.glob("*.json"))
    asyncio.run(check())


def test_pending_worker_is_readonly_nonblocking_and_busy(research_app, monkeypatch):
    db, col, runs = research_app
    entered, release = Event(), Event()
    original = server.compare

    def pending(worker_db, *args, **kwargs):
        assert worker_db is not db
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            worker_db.c.execute("delete from book_top where 0")
        entered.set()
        assert release.wait(5), "test did not release comparison worker"
        return original(worker_db, *args, **kwargs)

    monkeypatch.setattr(server, "compare", pending)

    async def check():
        reading_body, release_body = asyncio.Event(), asyncio.Event()
        original_json = server.web.Request.json

        async def paused_json(request, *args, **kwargs):
            body = await original_json(request, *args, **kwargs)
            if request.headers.get("X-Test-Pause-Body"):
                reading_body.set()
                await release_body.wait()
            return body

        monkeypatch.setattr(server.web.Request, "json", paused_json)
        async with TestClient(TestServer(server.make_app(col, RuleService(db), "tok", runs))) as client:
            slow_body = asyncio.create_task(client.post("/api/compare", json=request_body(),
                headers={"X-Gym-Token": "tok", "X-Test-Pause-Body": "1"}))
            await asyncio.wait_for(reading_body.wait(), 1)
            task = asyncio.create_task(client.post("/api/compare", json=request_body(), headers={"X-Gym-Token": "tok"}))
            try:
                assert await asyncio.to_thread(entered.wait, 3), "worker never started"
                release_body.set()
                assert (await asyncio.wait_for(slow_body, 1)).status == 409
                response = await asyncio.wait_for(client.get("/api/health"), 1)
                assert response.status == 200
                busy = await asyncio.wait_for(client.post("/api/compare", json=request_body(), headers={"X-Gym-Token": "tok"}), 1)
                assert busy.status == 409
            finally:
                release_body.set()
                release.set()
                await slow_body
                response = await task
            assert response.status == 200, await response.text()
            # A completed worker must release the lock for the next request.
            assert (await client.post("/api/compare", json=request_body(), headers={"X-Gym-Token": "tok"})).status == 200
    asyncio.run(check())
