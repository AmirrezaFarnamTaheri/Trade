"""Regressions for the due-diligence quick wins: token guard, exact candle parsing, atomic spec versioning."""
import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.wallex import parse_udf
from gym.api import guard, token_matches
from gym.domain.model import InstrumentId
from tests.support import START, market_db


def test_non_ascii_token_is_a_bad_token_not_a_server_error():
    assert token_matches("tok", "tok") and not token_matches("tok", "other")
    assert not token_matches("\u00e9", "tok") and not token_matches("t\u00f6k", "tok")

    async def ping(_):
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[guard("tok")])
    app.router.add_post("/api/ping", ping)

    async def check():
        async with TestClient(TestServer(app)) as client:
            reply = await client.post("/api/ping", headers={"X-Gym-Token": "\u00e9"})
            assert reply.status == 403
            assert (await client.post("/api/ping", headers={"X-Gym-Token": "tok"})).status == 200
    asyncio.run(check())


def test_udf_numbers_are_exact_decimals_from_the_json_text():
    # 0.1 + 0.2 style values, and more digits than a binary double keeps: a float round trip changes them.
    text = ('{"s":"ok","t":[%d],"o":[0.30000000000000004441],"h":[12345678901234567.89],'  # noqa: UP031
            '"l":[0.1],"c":["0.2"],"v":[1e-8]}' % START.timestamp())
    [k] = parse_udf(text)
    assert str(k["o"]) == "0.30000000000000004441"
    assert str(k["h"]) == "12345678901234567.89"
    assert k["l"] == Decimal("0.1") and k["c"] == Decimal("0.2") and k["v"] == Decimal("1e-8")
    with pytest.raises(ValueError, match="finite"):
        parse_udf('{"s":"ok","t":[1],"o":[NaN],"h":[1],"l":[1],"c":[1],"v":[1]}')


class FailingInsert:
    """Connection proxy that fails the successor insert, as a crash between the two statements would."""

    def __init__(self, c):
        self.c = c

    def execute(self, sql, *args):
        if sql.startswith("insert into instrument_specs"):
            raise RuntimeError("crash between close and insert")
        return self.c.execute(sql, *args)


def test_spec_version_close_and_insert_are_atomic(tmp_path):
    db = market_db(tmp_path, [])
    inst = InstrumentId.wallex("BTCUSDT", "BTC", "USDT")
    db.upsert_instrument(inst, {}, {"step": "0.01"}, "rest:test", START)
    real = db.c
    db.c = FailingInsert(real)
    with pytest.raises(RuntimeError):
        db.upsert_instrument(inst, {}, {"step": "0.001"}, "rest:test", START + timedelta(hours=1))
    db.c = real
    rows = real.execute("select spec, valid_to from instrument_specs where instrument_id='wallex:BTCUSDT'").fetchall()
    assert rows == [('{"step": "0.01"}', None)]
    db.upsert_instrument(inst, {}, {"step": "0.001"}, "rest:test", START + timedelta(hours=1))
    assert real.execute("select count(*) from instrument_specs where valid_to is null").fetchone()[0] == 1


def test_gateway_child_sees_only_allowlisted_and_configured_key_variables(tmp_path):
    import json as _json

    from gym.services.model_gateway import gateway_env
    (tmp_path / "config.json").write_text(_json.dumps({"connections": [
        {"id": "a", "provider": "openai", "auth": {"type": "api_key", "env": ["RESEARCH_KEY_1"]}},
        {"id": "b", "provider": "anthropic", "auth": {"type": "oauth"}}]}), encoding="utf-8")
    parent = {"GYM_MODEL_HOME": str(tmp_path), "PATH": "p", "SystemRoot": "C:/Windows", "https_proxy": "http://proxy",
              "RESEARCH_KEY_1": "k1", "AWS_SECRET_ACCESS_KEY": "canary", "GITHUB_TOKEN": "canary",
              "GYM_MODEL_ALLOW_LOOPBACK_HTTP": "1"}
    env = gateway_env(parent)
    assert "canary" not in env.values()
    assert env["RESEARCH_KEY_1"] == "k1" and env["PATH"] == "p" and env["SystemRoot"] == "C:/Windows"
    assert env["https_proxy"] == "http://proxy" and env["GYM_MODEL_ALLOW_LOOPBACK_HTTP"] == "1"
    assert "GYM_MODEL_PYTHON" in env
    (tmp_path / "config.json").write_text("not json", encoding="utf-8")
    assert "RESEARCH_KEY_1" not in gateway_env(parent)
