"""GYM_WALLEX_PROXY routes public venue traffic through the named proxy."""
import asyncio

from aiohttp import web
from aiohttp.test_utils import TestServer

from gym.adapters import wallex


def test_public_session_sends_requests_through_the_configured_proxy(monkeypatch):
    seen = []

    async def proxy(request):
        seen.append(str(request.url))
        return web.Response(text="via proxy")

    async def scenario():
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", proxy)
        async with TestServer(app) as server:
            monkeypatch.setenv("GYM_WALLEX_PROXY", str(server.make_url("/")))
            async with wallex.public_session() as session, session.get("http://venue.invalid/v1/markets") as reply:
                return await reply.text()

    assert asyncio.run(scenario()) == "via proxy"
    assert seen == ["http://venue.invalid/v1/markets"]


def test_public_session_is_direct_without_the_setting(monkeypatch):
    monkeypatch.delenv("GYM_WALLEX_PROXY", raising=False)

    async def scenario():
        async with wallex.public_session() as session:
            return session._default_proxy

    assert asyncio.run(scenario()) is None
