"""Research workbench routes share the CLI's service dispatch and authority limits."""
import asyncio
import json
import sqlite3
from contextlib import nullcontext

from aiohttp import web

from ..domain.market_models import fields
from ..domain.model import strict_loads
from ..services.research_actions import research_action
from ..services.research_process import HEAVY_ACTIONS, ResearchProcessFailure, calculate
from . import finish

MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_PORTFOLIO_RESULT_BYTES = 20 * 1024 * 1024


def _encode_portfolio(result):
    return json.dumps(result, default=str, ensure_ascii=False, allow_nan=False).encode("utf-8")


def install(app, root, *, store):
    lock = asyncio.Lock()

    async def action(request):
        raw = await request.read()
        if len(raw) > 65536:
            raise ValueError("research input exceeds 64 KiB")
        body = strict_loads(raw, "research JSON")
        fields(body, "action value")
        if not isinstance(body["action"], str):
            raise ValueError("invalid research action")
        # Scheduled work uses the existing tick route and its separate batching lock.
        if body["action"] in ("tick", "start"):
            raise ValueError("use the dedicated research runner")
        if body["action"] == "raw-replay-audit" and isinstance(body["value"], dict) and "archives" in body["value"]:
            raise ValueError("raw archive directory selection requires the research CLI")
        inspection = body["action"] in ("list", "job-interrupt")
        if not inspection and lock.locked():
            return web.json_response({"error": "research action is already running"}, status=409)
        if root is None:
            raise ValueError("research store is not configured")
        try:
            async with nullcontext() if inspection else lock:
                calculation = (calculate(root, body["action"], body["value"], store=store)
                               if body["action"] in HEAVY_ACTIONS else
                               asyncio.to_thread(research_action, root, body["action"], body["value"], store=store))
                result = await finish(calculation)
        except ResearchProcessFailure as error:
            return web.json_response(error.report, status=error.status)
        except (OSError, sqlite3.Error):
            return web.json_response({"error": "research store unavailable"}, status=503)
        if body["action"] == "portfolio-read":
            # A verified native artifact can be 16 MiB before its derived report fields are added.
            payload = await asyncio.to_thread(_encode_portfolio, result)
            if len(payload) <= MAX_PORTFOLIO_RESULT_BYTES:
                return web.Response(body=payload, content_type="application/json", charset="utf-8")
            return web.json_response({"error": "portfolio result exceeds the delivery limit",
                                      "result_delivered": False}, status=413)
        chunks, size = [], 0
        for chunk in json.JSONEncoder(default=str, allow_nan=False).iterencode(result):
            size += len(chunk.encode("utf-8"))
            if size > MAX_RESULT_BYTES:
                return web.json_response({"error": "research result exceeds 2 MiB; inspect saved state or narrow the requested page/window",
                                          "result_delivered": False, "operation_may_have_committed": True,
                                          "automatic_retry_allowed": False}, status=413)
            chunks.append(chunk)
        return web.Response(text="".join(chunks), content_type="application/json")

    app.router.add_post("/api/research/action", action)
