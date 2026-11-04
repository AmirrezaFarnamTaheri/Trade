"""Research workbench routes share the CLI's service dispatch and authority limits."""
import asyncio
import hmac
import json
import sqlite3
from contextlib import nullcontext

from aiohttp import web

from ..domain.market_models import fields
from ..services.research_actions import research_action

MAX_RESULT_BYTES = 2 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate research JSON field")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("research numbers must be finite")


def install(app, token, root, *, store):
    lock = asyncio.Lock()

    async def action(request):
        if not hmac.compare_digest(request.headers.get("X-Gym-Token", ""), token):
            return web.json_response({"error": "missing or bad X-Gym-Token"}, status=403)
        raw = await request.read()
        if len(raw) > 65536:
            raise ValueError("research input exceeds 64 KiB")
        try:
            body = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ValueError("invalid research JSON") from None
        fields(body, "action value")
        if not isinstance(body["action"], str):
            raise ValueError("invalid research action")
        # Scheduled work uses the existing tick route and its separate batching lock.
        if body["action"] in ("tick", "start", "mcp"):
            raise ValueError("use the dedicated research runner")
        inspection = body["action"] in ("list", "job-interrupt")
        if not inspection and lock.locked():
            return web.json_response({"error": "research action is already running"}, status=409)
        if root is None:
            raise ValueError("research store is not configured")
        try:
            async with nullcontext() if inspection else lock:
                task = asyncio.create_task(asyncio.to_thread(research_action, root, body["action"], body["value"], store=store))
                try:
                    result = await asyncio.shield(task)
                except asyncio.CancelledError:
                    # A disconnected client cannot release the lock while its durable mutation is running.
                    try:
                        await task
                    finally:
                        raise
        except (OSError, sqlite3.Error):
            return web.json_response({"error": "research store unavailable"}, status=503)
        chunks, size = [], 0
        for chunk in json.JSONEncoder(default=str, allow_nan=False).iterencode(result):
            size += len(chunk.encode("utf-8"))
            if size > MAX_RESULT_BYTES:
                return web.json_response({"error": "research result exceeds 2 MiB; inspect saved state or narrow the requested page/window",
                                          "result_delivered": False, "operation_may_have_committed": True,
                                          "automatic_retry_allowed": False}, status=413, headers={"Cache-Control": "no-store"})
            chunks.append(chunk)
        return web.Response(text="".join(chunks), content_type="application/json",
                            headers={"Cache-Control": "no-store"})

    app.router.add_post("/api/research/action", action)
