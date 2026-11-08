"""Private model controls; credential and OAuth ownership remains in the Node gateway."""
from aiohttp import web

from ..services.model_gateway import ModelGateway
from ..services.model_usage import ModelUsage


def install(app: web.Application, usage_path=None):
    gateway = ModelGateway()
    usage = ModelUsage(usage_path) if usage_path else None

    async def control(request):
        try:
            body = await request.json()
        except (ValueError, RecursionError):
            raise ValueError("invalid model control JSON") from None
        if not isinstance(body, dict) or set(body) - {"action", "value"} or not isinstance(body.get("action"), str):
            raise ValueError("invalid model control request")
        if body["action"] == "usage":
            return web.json_response(usage.summary() if usage else {"by_model": [], "note": "usage ledger not configured"})
        result = await gateway.request(body["action"], body.get("value"))
        if usage and body["action"] == "complete" and isinstance(result, dict):
            usage.record(result)
        return web.json_response(result)

    async def close(_):
        await gateway.close()
        if usage:
            usage.close()

    app.router.add_post("/api/models", control)
    app.on_cleanup.append(close)
