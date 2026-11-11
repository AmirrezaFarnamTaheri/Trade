"""Local offline acknowledgments reuse the canonical journal; never Executor approval."""
import asyncio
import re
import sqlite3

from aiohttp import web

from ..domain.market_models import fields
from ..domain.model import now_utc, strict_loads
from ..services.offline_review_journal import OfflineReviewJournal
from . import finish


def install(app, path):
    lock = asyncio.Lock()

    async def read(request):
        result = {"state": "NOT_CONFIGURED", "authority": "OFFLINE_ONLY",
                  "tickets": [], "reviews": []}
        if path is not None and path.is_file():
            try:
                with OfflineReviewJournal(path) as journal:
                    journal.conn.execute("BEGIN")
                    result.update(state="OFFLINE_ONLY", tickets=journal.tickets(), reviews=journal.review_events())
            except (ValueError, OSError, sqlite3.Error):
                return web.json_response({"error": "offline journal unavailable"}, status=503)
        return web.json_response(result)

    async def write(request):
        raw = await request.read()
        if len(raw) > 32768:
            raise ValueError("offline review exceeds 32 KiB")
        body = strict_loads(raw, "offline review JSON")
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
                    return {"preview_sha256": key, "state": "PREVIEWED"}
                value = body["value"]
                fields(value, "preview_sha256 decision")
                if type(value["decision"]) is not str:
                    raise ValueError("invalid offline decision")
                if type(value["preview_sha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value["preview_sha256"]):
                    raise ValueError("invalid preview digest")
                return journal.review(value["preview_sha256"], value["decision"], at=now_utc().isoformat())
        try:
            async with lock:
                result = await finish(asyncio.to_thread(commit))
        except (OSError, sqlite3.Error):
            return web.json_response({"error": "offline journal unavailable"}, status=503)
        return web.json_response(result)

    app.router.add_post("/api/offline-ticket-reviews", write)
    app.router.add_get("/api/offline-ticket-reviews", read)
