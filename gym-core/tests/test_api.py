"""Loopback protection and run/journal/evidence command integration."""
import asyncio
from datetime import datetime, timedelta

from gym.adapters.store import MarketDB, SegmentWriter
from gym.adapters.run_store import save_run
from gym.api.server import make_app
from gym.domain.model import UTC
from gym.services.collector import Collector
from gym.services.paper import paper
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history




def test_api_loopback_and_token(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    from gym.api.server import make_app

    async def go():
        db = MarketDB(tmp_path / "m.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["USDTTMN"])
        svc = RuleService(db)
        svc.preset("usdt-irt-october-2026", datetime(2026, 10, 1, tzinfo=UTC))
        async with TestClient(TestServer(make_app(col, svc, "tok"), host="127.0.0.1")) as c:
            assert (await c.post("/api/presets/usdt-irt-october-2026")).status == 403
            assert (await c.get("/api/markets", headers={"Host": "evil.example"})).status == 403
            m = await (await c.get("/api/markets")).json()
            assert set(m["markets"][0]["act"]) == {"entry", "exit"}
            r = await c.post("/api/rules/import", data="[1]", headers={"X-Gym-Token": "tok"})
            assert r.status == 400
            assert "__GYM_TOKEN__" not in await (await c.get("/")).text()
    asyncio.run(go())


def test_journal_api_and_cli(tmp_path, capsys):
    from aiohttp.test_utils import TestClient, TestServer
    from gym.cli import main
    root = tmp_path / "live"
    root.mkdir()
    db = market_db(root, quote_history(n=500))
    out = paper(db, "BTCUSDT", START, START + timedelta(hours=1), resolution="1min", fast=2, slow=3)
    runs = root / "runs"
    save_run(out, runs)
    col = Collector(db, SegmentWriter(root / "raw", db), ["BTCUSDT"])
    async def check():
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok", runs), host="127.0.0.1")) as c:
            rows = await (await c.get("/api/runs")).json()
            assert rows[0]["run_id"] == out["run_id"]
            d = await (await c.get("/api/runs/" + out["run_id"])).json()
            assert d["result"]["decisions"][0]["marks"]
            assert d["evidence"]["claim_ceiling"] == "EXPERIMENTAL"
            assert (await c.get("/api/runs/not-a-run")).status == 400
            assert (await c.get("/api/runs/" + "0"*16)).status == 404
            assert 'data-view="journal"' in await (await c.get("/")).text()
            assert (await c.get("/app.js")).status == 200
            assert (await c.get("/styles.css")).status == 200
    asyncio.run(check())
    db.c.close()
    assert main(["--data", str(tmp_path), "evidence", out["run_id"], "--diagnostics", "--decide", "NONE", "--note", "not funded"]) == 0
    assert (runs / (out["run_id"] + ".evidence.md")).exists()
    assert len(list(runs.glob("*.decision.json"))) == 1
