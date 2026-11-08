"""Every API route: private unless listed public, JSON, no-store, and the shapes the UI reads."""
import asyncio

from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.run_store import save_run
from gym.adapters.store import SegmentWriter
from gym.api import PUBLIC_READS
from gym.api.server import make_app
from gym.services.collector import Collector
from gym.services.rules import RuleService
from tests.support import market_db, quote_history


def test_every_route_is_private_unless_declared_public(tmp_path):
    db = market_db(tmp_path, quote_history(n=10))
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
    runs = tmp_path / "runs"
    save_run({"run_id": "0123456789abcdef", "inputs": {"symbol": "BTCUSDT"}, "result": {"end": {"net": "1"}}}, runs)
    app = make_app(col, RuleService(db), "tok", runs)
    routes = {(r.method, r.resource.canonical) for r in app.router.routes() if r.resource and r.resource.canonical.startswith("/api/")}
    assert len(routes) > 20

    async def check():
        async with TestClient(TestServer(app)) as client:
            for method, path in sorted(routes):
                concrete = path.replace("{id}", "0123456789abcdef")
                reply = await client.request(method, concrete)
                public = method == "GET" and (path in PUBLIC_READS or path == "/api/runs/{id}")
                if not public:
                    assert reply.status == 403, f"{method} {path} must need the session key"
                    continue
                assert reply.status != 500, f"{method} {path}: {reply.status}"  # 400 without parameters; 503 from /api/ready
                assert reply.headers["Cache-Control"] == "no-store" and reply.content_type == "application/json", path
            rows = await (await client.get("/api/runs?limit=1")).json()
            assert set(rows[0]) == {"run_id", "inputs", "end"}
            assert (await client.get("/api/runs?limit=0")).status == 400
            assert (await client.get("/api/runs?sort=x")).status == 400
    asyncio.run(check())
