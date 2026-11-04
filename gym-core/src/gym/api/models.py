"""Private model controls; credential and OAuth ownership remains in the Node gateway."""
import hmac

from aiohttp import web

from ..services.model_gateway import ModelGateway


def install(app: web.Application, token: str):
    gateway = ModelGateway()

    async def control(request):
        if not hmac.compare_digest(request.headers.get("X-Gym-Token", ""), token):
            return web.json_response({"error": "missing or bad X-Gym-Token"}, status=403)
        try:
            body = await request.json()
        except (ValueError, RecursionError):
            raise ValueError("invalid model control JSON") from None
        if not isinstance(body, dict) or set(body) - {"action", "value"} or not isinstance(body.get("action"), str):
            raise ValueError("invalid model control request")
        result = await gateway.request(body["action"], body.get("value"))
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def close(_):
        await gateway.close()

    app.router.add_post("/api/models", control)
    app.on_cleanup.append(close)
