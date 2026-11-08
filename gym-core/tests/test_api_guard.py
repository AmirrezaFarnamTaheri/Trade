"""Shared API middleware: error mapping and browser security headers."""
import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gym.api import guard
from gym.services.model_gateway import GatewayUnavailable


def test_gateway_outage_is_503_and_every_response_carries_security_headers():
    async def down(_):
        raise GatewayUnavailable("model gateway unavailable")

    async def bad(_):
        raise ValueError("bad input")

    app = web.Application(middlewares=[guard("tok")])
    app.router.add_post("/api/down", down)
    app.router.add_post("/api/bad", bad)

    async def check():
        async with TestClient(TestServer(app)) as client:
            headers = {"X-Gym-Token": "tok"}
            down_reply = await client.post("/api/down", headers=headers)
            assert down_reply.status == 503 and (await down_reply.json())["error"] == "model gateway unavailable"
            bad_reply = await client.post("/api/bad", headers=headers)
            assert bad_reply.status == 400
            for reply in (down_reply, bad_reply):
                assert "script-src 'self'" in reply.headers["Content-Security-Policy"]
                assert reply.headers["X-Content-Type-Options"] == "nosniff"
    asyncio.run(check())


def test_session_key_rotation_retires_the_old_key():
    async def ping(_):
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[guard("old-key")])
    app.router.add_post("/api/ping", ping)

    async def check():
        async with TestClient(TestServer(app)) as client:
            assert (await client.post("/api/session/rotate")).status == 403
            reply = await client.post("/api/session/rotate", headers={"X-Gym-Token": "old-key"})
            new = (await reply.json())["token"]
            assert len(new) >= 32 and reply.headers["Cache-Control"] == "no-store"
            assert (await client.post("/api/ping", headers={"X-Gym-Token": "old-key"})).status == 403
            assert (await client.post("/api/ping", headers={"X-Gym-Token": new})).status == 200
    asyncio.run(check())
