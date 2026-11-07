"""Shared-cash replay reaches the private API and immutable, verified saved records."""
import asyncio
import json
from datetime import timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.run_store import load_verified_run
from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.domain.model import iso
from gym.services.collector import Collector
from gym.services.research_actions import research_action
from gym.services.research_process import calculate
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history


def request():
    return {"symbols": ["BTCUSDT", "ETHUSDT"], "from": iso(START),
            "to": iso(START + timedelta(minutes=30)), "resolution": "1min", "cash": "1000",
            "strategy": "ema-trend", "params": {"fast": 2, "slow": 3},
            "rules_mode": "point-in-time", "cost": {"fee_rate": "0.001", "latency_ms": 500,
                "max_wait_s": 60, "fee_assumption": "fee-in-received-asset"}}


def prepare(root):
    return market_db(root, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))


def test_native_portfolio_saved_read_and_integrity(tmp_path):
    prepare(tmp_path).c.close()
    out = research_action(tmp_path, "portfolio-replay", request())
    reference = {"run_id": out["run_id"]}
    loaded = research_action(tmp_path, "portfolio-read", reference)
    assert loaded["mode"] == "PORTFOLIO" and loaded["outputs_digest"] == out["outputs_digest"]
    assert loaded["result"]["markets"]["BTCUSDT"]["fills"] > 0
    assert research_action(tmp_path, "portfolio-list")["runs"][0]["run_id"] == out["run_id"]
    assert research_action(tmp_path, "portfolio-replay", request())["run_id"] == out["run_id"]
    with pytest.raises(ValueError, match="store mismatch"):
        research_action(tmp_path, "portfolio-read", reference, store="demo")
    path = tmp_path / "runs" / "portfolios" / (out["run_id"] + ".json")
    changed = json.loads(path.read_text("utf-8"))
    changed["performance"] = {"total_return_pct": "99999999"}
    path.write_text(json.dumps(changed), "utf-8")
    assert research_action(tmp_path, "portfolio-read", reference)["performance"] == loaded["performance"]
    assert load_verified_run(path.parent, out["run_id"], store="live")["performance"] == loaded["performance"]
    changed["result"]["end"]["equity"] = "999999"
    path.write_text(json.dumps(changed), "utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_verified_run(path.parent, out["run_id"], store="live")


@pytest.mark.parametrize("change", [
    {"symbols": ["BTCUSDT"]}, {"symbols": ["BTCUSDT", "BTCUSDT"]},
    {"symbols": ["BTCUSDT", "../escape"]}, {"symbols": ["BTCUSDT", "UNKNOWN"]},
    {"to": iso(START + timedelta(days=32))}, {"from": iso(START + timedelta(days=1))},
    {"cash": "NaN"}, {"cash": "0"}, {"cost": {"fee_rate": "0.001", "ignored": True}},
    {"rules_mode": "invented"}, {"resolution": "invalid"}, {"params": {"fast": True}}, {"resolution": []},
    {"cost": {"fee_rate": "0.001", "latency_ms": 500, "max_wait_s": 10**1000, "fee_assumption": "fee-in-received-asset"}},
])
def test_invalid_portfolio_requests_leave_no_records(tmp_path, change):
    prepare(tmp_path).c.close()
    with pytest.raises(ValueError):
        research_action(tmp_path, "portfolio-replay", {**request(), **change})
    assert not list((tmp_path / "runs").rglob("*.json"))


def test_portfolio_private_api_uses_real_supervised_worker(tmp_path):
    db = prepare(tmp_path)
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT", "ETHUSDT"])
    app = make_app(col, RuleService(db), "tok", tmp_path / "runs")

    async def check():
        async with TestClient(TestServer(app)) as client:
            body = {"action": "portfolio-replay", "value": request()}
            assert (await client.post("/api/research/action", json=body)).status == 403
            response = await client.post("/api/research/action", json=body, headers={"X-Gym-Token": "tok"})
            assert response.status == 200, await response.text()
            saved = await response.json()
            assert saved["authority"] == "PAPER_ONLY"
            loaded = await calculate(tmp_path, "portfolio-replay", request())
            assert loaded["run_id"] == saved["run_id"]
            response = await client.post("/api/research/action", json={"action": "portfolio-read", "value": {"run_id": saved["run_id"]}},
                                         headers={"X-Gym-Token": "tok"})
            assert response.status == 200
            assert (await response.json())["result"]["balances"]
    try:
        asyncio.run(check())
    finally:
        db.c.close()


def test_portfolio_observation_budget_is_checked_inside_snapshot(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("gym.services.portfolio")
    prepare(tmp_path).c.close()
    monkeypatch.setattr(module, "MAX_OBSERVATIONS", 10)
    with pytest.raises(ValueError, match="observation budget"):
        research_action(tmp_path, "portfolio-replay", request())
    assert not (tmp_path / "runs").exists()
