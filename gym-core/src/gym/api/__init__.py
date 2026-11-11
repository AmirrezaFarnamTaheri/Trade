"""Shared loopback API helpers."""
import asyncio
import hmac
import secrets

from aiohttp import web

LOOPBACK = {"127.0.0.1", "localhost"}
# Same-origin scripts and styles only; chart geometry is set through the DOM style API, never inline (S-13).
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                               "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
# Public market/paper reads; every other /api/ route, and every write, needs the per-run token.
PUBLIC_READS = frozenset({"/api/markets", "/api/health", "/api/ready", "/api/capabilities", "/api/research",
                          "/api/runs", "/api/check", "/api/rules", "/api/rules/export", "/api/chaos-report"})


def token_matches(supplied: str, expected: str) -> bool:
    """Constant-time comparison that treats a non-ASCII header as a bad token instead of a server error."""
    try:
        return hmac.compare_digest(supplied.encode("ascii"), expected.encode("ascii"))
    except UnicodeEncodeError:
        return False


def guard(token: str):
    key = [token]  # replaced by POST /api/session/rotate; every other tab and printed link stops working

    @web.middleware
    async def middleware(req: web.Request, handler):
        # DNS-rebinding and CSRF defence: loopback Host only; the per-run token on every write and private read.
        if (req.host or "").rsplit(":", 1)[0] not in LOOPBACK:
            return web.json_response({"error": "loopback only"}, status=403)
        public = req.method == "GET" and (req.path in PUBLIC_READS or req.path.startswith("/api/runs/") and req.path.count("/") == 3)
        if req.path.startswith("/api/") and not public and not token_matches(req.headers.get("X-Gym-Token", ""), key[0]):
            return web.json_response({"error": "missing or bad X-Gym-Token"}, status=403)
        if req.method == "POST" and req.path == "/api/session/rotate":
            key[0] = secrets.token_urlsafe(24)
            return web.json_response({"token": key[0]}, headers={"Cache-Control": "no-store"})
        try:
            response = await handler(req)
        except (ValueError, KeyError) as e:
            response = web.json_response({"error": str(e)}, status=400)
        except ConnectionError as e:  # a local dependency (the model gateway) is down; retrying later can work
            response = web.json_response({"error": str(e)}, status=503)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if req.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
    return middleware


async def finish(coro):
    """Await a durable operation to completion even if the client disconnects, so its lock is never released early."""
    task = asyncio.ensure_future(coro)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise
