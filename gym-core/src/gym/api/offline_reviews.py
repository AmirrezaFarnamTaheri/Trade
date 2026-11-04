"""Local offline acknowledgments reuse the canonical journal; never Executor approval."""
import asyncio
import hmac
import json
import re
import sqlite3

from aiohttp import web

from ..domain.market_models import fields
from ..services.collector import now_utc
from ..services.offline_review_journal import OfflineReviewJournal


def install(app, token, path):
    lock = asyncio.Lock()

    async def read(request):
        if not hmac.compare_digest(request.headers.get("X-Gym-Token", ""), token):
            return web.json_response({"error": "offline review token required"}, status=403)
        result = {"state": "NOT_CONFIGURED", "authority": "OFFLINE_ONLY", "funded_authority": False,
                  "tickets": [], "reviews": []}
        if path is not None and path.is_file():
            try:
                with OfflineReviewJournal(path) as journal:
                    journal.conn.execute("BEGIN")
                    result.update(state="OFFLINE_ONLY", tickets=journal.tickets(), reviews=journal.review_events())
            except (ValueError, OSError, sqlite3.Error):
                return web.json_response({"error": "offline journal unavailable"}, status=503)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def write(request):
        if not hmac.compare_digest(request.headers.get("X-Gym-Token", ""), token):
            return web.json_response({"error": "local operator token required"}, status=403)
        raw = await request.read()
        if len(raw) > 32768:
            raise ValueError("offline review exceeds 32 KiB")
        def unique(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("duplicate offline review field")
                result[key] = value
            return result
        try:
            body = json.loads(raw, object_pairs_hook=unique)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise ValueError("invalid offline review JSON") from None
        fields(body, "action value")
        if body["action"] not in ("record", "review"):
            raise ValueError("unknown offline review action")
        if path is None:
            raise ValueError("offline review store is not configured")
        if lock.locked():
            return web.json_response({"error": "offline journal write is running"}, status=409)

        def commit():
            with OfflineReviewJournal(path) as journal:
                if body["action"] == "record":
                    key = journal.record(body["value"])
                    return {"preview_sha256": key, "state": "PREVIEWED", "tier1_approval": False,
                            "funded_authority": False, "order_submitted": False}
                value = body["value"]
                fields(value, "preview_sha256 decision")
                if type(value["decision"]) is not str:
                    raise ValueError("invalid offline decision")
                if type(value["preview_sha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value["preview_sha256"]):
                    raise ValueError("invalid preview digest")
                return journal.review(value["preview_sha256"], value["decision"], at=now_utc().isoformat())
        try:
            async with lock:
                task = asyncio.create_task(asyncio.to_thread(commit))
                try:
                    result = await asyncio.shield(task)
                except asyncio.CancelledError:
                    try:
                        await task
                    finally:
                        raise
        except (OSError, sqlite3.Error):
            return web.json_response({"error": "offline journal unavailable"}, status=503)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    app.router.add_post("/api/offline-ticket-reviews", write)
    app.router.add_get("/api/offline-ticket-reviews", read)
