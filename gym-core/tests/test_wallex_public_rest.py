import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters import wallex


def test_public_observations_reject_redirects(monkeypatch):
    async def check():
        calls = []

        async def redirect(request):
            raise web.HTTPFound("/other")

        async def other(request):
            calls.append(request.path)
            return web.json_response({"result": "not the requested resource"})

        app = web.Application()
        app.add_routes([web.get("/depth", redirect), web.get("/other", other)])
        async with TestClient(TestServer(app)) as client:
            monkeypatch.setattr(wallex, "REST", str(client.make_url("/")).rstrip("/"))
            with pytest.raises(aiohttp.ClientResponseError) as refused:
                await wallex.get_text(client.session, "/depth")
            assert refused.value.status == 302
            assert not calls
            assert await wallex.get_text(client.session, "/other") == '{"result": "not the requested resource"}'

    asyncio.run(check())
