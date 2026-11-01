"""B2 cockpit view of the Fake Venue chaos-suite report: evidence only, never authority."""
import asyncio
import json

from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import MarketDB, SegmentWriter
from gym.api.server import make_app
from gym.services.collector import Collector
from gym.services.rules import RuleService


def test_chaos_report_states(tmp_path):
    report = tmp_path / "chaos" / "report.json"

    async def check():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        app = make_app(col, RuleService(db), "tok", chaos_report=report)
        async with TestClient(TestServer(app, host="127.0.0.1")) as c:
            assert (await (await c.get("/api/chaos-report")).json()) == {"state": "NOT_RUN"}
            report.parent.mkdir()
            report.write_text("{not json", encoding="utf-8")
            assert (await c.get("/api/chaos-report")).status == 503
            report.write_text(json.dumps({"report": "b2-chaos-suite", "passed": True, "total_violations": 0,
                                          "funded_authority": False, "fixtures": []}), encoding="utf-8")
            r = await c.get("/api/chaos-report")
            data = await r.json()
            assert r.headers["Cache-Control"] == "no-store"
            assert data["state"] == "REPORTED" and data["passed"] is True and data["funded_authority"] is False
        db.c.close()
    asyncio.run(check())
