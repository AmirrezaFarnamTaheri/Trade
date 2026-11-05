"""Explicit same-origin operator relay; never exposed through paper/MCP dispatch."""

import asyncio
import hmac

from aiohttp import web

from ..adapters.service_review import review
from ..adapters.wallex_account_read import ReadUncertain, parse_account_json
from ..contracts.review_wire import encode_request


def install(app, token, *, enabled):
    lock = asyncio.Lock()

    async def handle(request):
        if not hmac.compare_digest(request.headers.get("X-Gym-Token", ""), token):
            return web.json_response(
                {"error": "local operator token required"}, status=403
            )
        if not enabled:
            return web.json_response(
                {
                    "error": "native operator reviews disabled in DEMO",
                    "funded_authority": False,
                },
                status=403,
            )
        if request.method == "POST":
            if request.headers.get("Origin") != f"{request.scheme}://{request.host}":
                return web.json_response(
                    {"error": "same-origin operator request required"}, status=403
                )
            raw = await request.read()
            if len(raw) > 16384:
                return web.json_response(
                    {"error": "native review input exceeds bound"}, status=413
                )
            try:
                value = parse_account_json(raw)
            except ReadUncertain:
                return web.json_response(
                    {"error": "invalid native review JSON"}, status=400
                )
        else:
            value = {"action": "status"}
        try:
            encode_request(value, bytes([1]) * 16)
        except ValueError:
            return web.json_response(
                {"error": "invalid native review fields or envelope"}, status=400
            )
        if lock.locked():
            return web.json_response(
                {"error": "a native review request is running; no retry performed"},
                status=409,
            )
        try:
            async with lock:
                task = asyncio.create_task(review(value))
                try:
                    result = await asyncio.shield(task)
                except asyncio.CancelledError:
                    try:
                        await task
                    finally:
                        raise
        except (ReadUncertain, ValueError, OSError):
            return web.json_response(
                {
                    "error": "native review unacknowledged; inspect the same identity before retry",
                    "operation_may_have_committed": True,
                    "automatic_retry_allowed": False,
                    "funded_authority": False,
                    "order_submitted": False,
                },
                status=503,
                headers={"Cache-Control": "no-store"},
            )
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    app.router.add_get("/api/operator-reviews", handle)
    app.router.add_post("/api/operator-reviews", handle)
