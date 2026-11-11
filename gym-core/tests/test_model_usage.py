"""Model usage ledger: per provider and model, unknown cost kept apart from zero."""
import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gym.api import guard, models
from gym.services.model_usage import ModelUsage


def completion(provider, model, tokens_in, tokens_out, cost):
    return {"model": {"provider": provider, "id": model, "preset": "p"},
            "usage": {"input": tokens_in, "output": tokens_out, "cost": None if cost is None else {"total": cost}, "costSource": "SDK_CATALOG_ESTIMATE"}}


def test_usage_sums_tokens_and_cost_per_model(tmp_path):
    ledger = ModelUsage(tmp_path / "usage.db")
    ledger.record(completion("openai", "gpt", 100, 20, 0.0012))
    ledger.record(completion("openai", "gpt", 50, 10, None))
    ledger.record({"model": {}})  # malformed: ignored
    row = ledger.summary()["by_model"][0]
    assert row["calls"] == 2 and row["input_tokens"] == 150 and row["output_tokens"] == 30
    assert row["cost"] == "0.0012" and row["calls_without_cost"] == 1
    ledger.close()


def test_completions_through_the_api_are_recorded(tmp_path, monkeypatch):
    async def fake(self, action, value=None):
        return completion("anthropic", "claude", 7, 3, 0.5)
    monkeypatch.setattr(models.ModelGateway, "request", fake)
    app = web.Application(middlewares=[guard("tok")])
    models.install(app, tmp_path / "usage.db")

    async def check():
        async with TestClient(TestServer(app)) as client:
            headers = {"X-Gym-Token": "tok"}
            await client.post("/api/models", json={"action": "complete", "value": {"preset": "p", "prompt": "x"}}, headers=headers)
            summary = await (await client.post("/api/models", json={"action": "usage"}, headers=headers)).json()
            assert summary["by_model"][0]["provider"] == "anthropic" and summary["by_model"][0]["cost"] == "0.5"
    asyncio.run(check())


def test_caps_refuse_the_next_call_before_it_reaches_the_gateway(tmp_path, monkeypatch):
    sent = []

    async def fake(self, action, value=None):
        sent.append(action)
        return completion("openai", "gpt", 1, 1, 0.4)
    monkeypatch.setattr(models.ModelGateway, "request", fake)
    app = web.Application(middlewares=[guard("tok")])
    models.install(app, tmp_path / "usage.db")
    call = {"action": "complete", "value": {"preset": "p", "prompt": "x"}}

    async def check():
        async with TestClient(TestServer(app)) as client:
            headers = {"X-Gym-Token": "tok"}
            limits = await client.post("/api/models", json={"action": "usage_limits", "value": {"daily_calls": 2}}, headers=headers)
            assert (await limits.json())["limits"]["daily_calls"] == "2"
            assert (await client.post("/api/models", json=call, headers=headers)).status == 200
            assert (await client.post("/api/models", json=call, headers=headers)).status == 200
            refused = await client.post("/api/models", json=call, headers=headers)
            assert refused.status == 400 and "daily model call cap" in (await refused.json())["error"]
            assert len(sent) == 2
            await client.post("/api/models", json={"action": "usage_limits", "value": {"daily_calls": None, "daily_cost": "0.8"}}, headers=headers)
            refused = await client.post("/api/models", json=call, headers=headers)
            assert refused.status == 400 and "cost cap" in (await refused.json())["error"] and len(sent) == 2
            bad = await client.post("/api/models", json={"action": "usage_limits", "value": {"daily_calls": -1}}, headers=headers)
            assert bad.status == 400
    asyncio.run(check())
