"""Private controls and shared research dispatch, without a provider/account call."""
import asyncio
import json
from threading import Event
from types import SimpleNamespace

import pytest
from aiohttp import web

from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import SegmentWriter
from gym.api import models
from gym.api import research
from gym.api.server import make_app
from gym.services.collector import Collector
from gym.services.rules import RuleService
from tests.support import market_db, quote_history


def test_research_workbench_uses_native_ledger_and_rejects_runner_or_clock_injection(tmp_path):
    db = market_db(tmp_path, quote_history(n=10))
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])

    async def check():
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok", tmp_path / "runs"))) as client:
            route = "/api/research/action"
            body = {"action": "register", "value": {"symbol": "BTCUSDT", "strategy": "rsi-rebound", "params": {}}}
            assert (await client.post(route, json=body)).status == 403
            response = await client.post(route, json=body, headers={"X-Gym-Token": "tok"})
            assert response.status == 200
            result = await response.json()
            assert result["authority"] == "PAPER_ONLY" and result["funded_authority"] is False
            assert response.headers["Cache-Control"] == "no-store"
            assert (tmp_path / "research.sqlite3").is_file()
            diagnostic = await client.post(route, json={"action": "technicals", "value": {
                "symbol": "BTCUSDT", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:10:00Z", "resolutions": ["1min", "15min"]}},
                headers={"X-Gym-Token": "tok"})
            assert diagnostic.status == 200
            report = await diagnostic.json()
            assert set(report["timeframes"]) == {"1min", "15min"} and report["funded_authority"] is False
            candle_input = {"symbol": "BTCUSDT", "from": "2026-01-01T00:00:00Z", "to": "2026-01-01T00:10:00Z",
                            "as_of": "2026-01-01T00:11:00Z", "tolerance_bps": "10"}
            candle = await client.post(route, json={"action": "candles", "value": candle_input}, headers={"X-Gym-Token": "tok"})
            assert candle.status == 200
            assert (await candle.json())["knowledge_mode"] == "POINT_IN_TIME"
            for change in ({"tolerance_bps": "NaN"}, {"tolerance_bps": "1e99999"}, {"tolerance_bps": "-1"}, {"as_of": "2099-01-01T00:00:00Z"},
                           {"as_of": "2026-01-01T00:09:00Z"}, {"to": "2026-03-01T00:00:00Z"}):
                assert (await client.post(route, json={"action": "candles", "value": {**candle_input, **change}}, headers={"X-Gym-Token": "tok"})).status == 400
            for bad in ({**body, "at": "2020-01-01T00:00:00Z"}, {"action": "shell", "value": "anything"},
                        {"action": "tick", "value": None}, {"action": [], "value": None}):
                assert (await client.post(route, json=bad, headers={"X-Gym-Token": "tok"})).status == 400
            assert (await client.post(route, data=json.dumps({"action": "register", "value": "x" * 65536}), headers={"X-Gym-Token": "tok"})).status == 400
    try:
        asyncio.run(check())
    finally:
        db.c.close()


def test_model_api_authenticates_before_starting_bridge_and_closes_owned_process(tmp_path, monkeypatch):
    calls = []

    class Gateway:
        async def request(self, action, value):
            calls.append((action, value))
            return {"mode": "RESEARCH_ONLY", "funded_authority": False}

        async def close(self):
            calls.append("closed")

    monkeypatch.setattr(models, "ModelGateway", Gateway)
    db = market_db(tmp_path, quote_history(n=10))
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])

    async def check():
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok"))) as client:
            for headers in ({}, {"X-Gym-Token": "wrong"}, {"X-Gym-Token": "tok", "Host": "evil.example"}):
                assert (await client.post("/api/models", json={"action": "status"}, headers=headers)).status == 403
                assert calls == []
            assert (await client.post("/api/models", json={"action": "status", "path": "arbitrary"}, headers={"X-Gym-Token": "tok"})).status == 400
            assert (await client.post("/api/models", data="{", headers={"X-Gym-Token": "tok"})).status == 400
            response = await client.post("/api/models", json={"action": "status"}, headers={"X-Gym-Token": "tok"})
            assert response.status == 200 and response.headers["Cache-Control"] == "no-store"
            assert calls == [("status", None)]
        assert calls[-1] == "closed"
    try:
        asyncio.run(check())
    finally:
        db.c.close()


def test_cancelled_research_client_keeps_lock_until_durable_work_finishes(tmp_path, monkeypatch):
    started, release = Event(), Event()

    def work(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return {"saved": True}

    monkeypatch.setattr(research, "research_action", work)

    async def check():
        app = web.Application()
        research.install(app, "tok", tmp_path, store="live")
        handler = next(iter(app.router.routes())).handler

        async def read():
            return b'{"action":"register","value":{}}'

        request = SimpleNamespace(headers={"X-Gym-Token": "tok"}, read=read)
        task = asyncio.create_task(handler(request))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            assert (await handler(request)).status == 409
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(check())
