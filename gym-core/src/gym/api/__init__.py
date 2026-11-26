"""Shared loopback API helpers."""
import asyncio
import hmac
import logging
import secrets
import time
from collections import deque
from urllib.parse import urlparse

from aiohttp import web

log = logging.getLogger(__name__)
LOOPBACK = {"127.0.0.1", "localhost"}
# Same-origin scripts and styles only; chart geometry is set through the DOM style API, never inline.
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


def _deepest_package_module(error: BaseException) -> str:
    """The first two parts of the innermost gym module on the error's traceback, e.g. `gym.services`."""
    found, step = "", error.__traceback__
    while step is not None:
        name = step.tb_frame.f_globals.get("__name__", "")
        if name.startswith("gym."):
            found = ".".join(name.split(".")[:2])
        step = step.tb_next
    return found


def _origin_allowed(origin: str) -> bool:
    parsed = urlparse(origin)
    return parsed.scheme in ("http", "https") and (parsed.hostname or "") in LOOPBACK


def guard(token: str):
    key = [token]  # replaced by POST /api/session/rotate; every other tab and printed link stops working
    rotations: deque[float] = deque()

    async def dispatch(req: web.Request, handler):
        # DNS-rebinding and CSRF defence: loopback Host, Origin/Sec-Fetch-Site checks, and per-run token.
        if (req.host or "").rsplit(":", 1)[0] not in LOOPBACK:
            return web.json_response({"error": "loopback only"}, status=403)
        origin = req.headers.get("Origin")
        if origin and not _origin_allowed(origin):
            return web.json_response({"error": "cross-origin request refused"}, status=403)
        fetch_site = (req.headers.get("Sec-Fetch-Site") or "").lower()
        if fetch_site and fetch_site not in ("same-origin", "none"):
            return web.json_response({"error": "cross-site request refused"}, status=403)
        public = req.method == "GET" and (req.path in PUBLIC_READS or req.path.startswith("/api/runs/") and req.path.count("/") == 3)
        if req.path.startswith("/api/") and not public and not token_matches(req.headers.get("X-Gym-Token", ""), key[0]):
            return web.json_response({"error": "missing or bad X-Gym-Token"}, status=403)
        if req.method == "POST" and req.path == "/api/session/rotate":
            now_m = time.monotonic()
            while rotations and now_m - rotations[0] > 60.0:
                rotations.popleft()
            if len(rotations) >= 5:
                return web.json_response({"error": "session rotation rate limit exceeded"}, status=429)
            rotations.append(now_m)
            key[0] = secrets.token_urlsafe(24)
            return web.json_response({"token": key[0]}, headers={"Cache-Control": "no-store"})
        try:
            response = await handler(req)
        except ValueError as e:
            response = web.json_response({"error": str(e)}, status=400)
        except KeyError as e:
            # A handler reading an absent request field is bad input. The same error from deeper code is a bug:
            # it must surface as a 500 and keep its text out of the browser.
            if _deepest_package_module(e) in ("gym.api", "gym.contracts"):
                response = web.json_response({"error": f"missing field {e}"}, status=400)
            else:
                log.exception("unhandled KeyError in %s %s", req.method, req.path)
                response = web.json_response({"error": "internal error"}, status=500)
        return response

    @web.middleware
    async def middleware(req: web.Request, handler):
        try:
            response = await dispatch(req, handler)
        except web.HTTPException as exc:
            _response_headers(req, exc)
            raise
        _response_headers(req, response)
        return response
    return middleware


def _response_headers(req: web.Request, response: web.StreamResponse) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if req.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")


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
