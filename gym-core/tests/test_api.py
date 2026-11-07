"""Loopback protection and run/journal/evidence command integration."""
import asyncio
import re
from datetime import datetime, timedelta
from decimal import Decimal

from gym.adapters.run_store import save_run
from gym.adapters.store import MarketDB, SegmentWriter
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
            assert m["universe"]["mode"] == "explicit" and m["universe"]["observed_markets"] == 1
            r = await c.post("/api/rules/import", data="[1]", headers={"X-Gym-Token": "tok"})
            assert r.status == 400
            assert "__GYM_TOKEN__" not in await (await c.get("/")).text()
    asyncio.run(go())


def test_market_api_uses_domain_qualification_without_rounding_quotes(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    async def check():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT", "ETHUSDT", "LTCUSDT"])
        now = datetime.now(UTC)
        for symbol, bid, ask in (("BTCUSDT", "1E-8", "2E-8"), ("ETHUSDT", "2E-8", "1E-8")):
            col.on_depth(symbol, "bid", [(Decimal(bid), Decimal(1))], now, "fixture")
            col.on_depth(symbol, "ask", [(Decimal(ask), Decimal(2))], now, "fixture")
        col.tick(now)
        try:
            async with TestClient(TestServer(make_app(col, RuleService(db), "tok"), host="127.0.0.1")) as client:
                response = await client.get("/api/markets")
                assert response.status == 200
                rows = {row["symbol"]: row for row in (await response.json())["markets"]}
                assert rows["BTCUSDT"]["qualified"] is True
                assert rows["BTCUSDT"]["bid"] == "1E-8"
                assert rows["BTCUSDT"]["ask"] == "2E-8"
                assert rows["ETHUSDT"]["qualified"] is False
                assert "CROSSED" in rows["ETHUSDT"]["flags"]
                assert rows["LTCUSDT"]["qualified"] is False
                assert rows["LTCUSDT"]["bid"] is None
        finally:
            db.c.close()

    asyncio.run(check())


def test_ui_asset_urls_follow_contents_without_restarting(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    from gym.api import server

    ui = tmp_path / "index.html"
    ui.write_text('<script src="/app.js"></script><script src="/models.js"></script><script src="/research.js"></script><script src="/replay-chart.js"></script><script src="/native-review.js"></script><link href="/styles.css"><script src="/margin.js"></script>', encoding="utf-8")
    script, style = tmp_path / "app.js", tmp_path / "styles.css"
    script.write_text("// old", encoding="utf-8")
    style.write_text("body {}", encoding="utf-8")
    (tmp_path / "models.js").write_text("// model controls", encoding="utf-8")
    (tmp_path / "research.js").write_text("// research controls", encoding="utf-8")
    (tmp_path / "margin.js").write_text("// margin controls", encoding="utf-8")
    (tmp_path / "replay-chart.js").write_text("// decision chart", encoding="utf-8")
    (tmp_path / "native-review.js").write_text("// protected review controls", encoding="utf-8")
    for extra in ("charts.js", "runs.js"):
        (tmp_path / extra).write_text("// " + extra, encoding="utf-8")
    monkeypatch.setattr(server, "UI", ui)

    async def check():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        try:
            async with TestClient(TestServer(make_app(col, RuleService(db), "tok"), host="127.0.0.1")) as client:
                first = await (await client.get("/")).text()
                assert first == await (await client.get("/")).text()
                script.write_text("// new", encoding="utf-8")
                updated = await (await client.get("/")).text()
                assert first != updated
                urls = re.findall(r'(?:src|href)="([^"]+)"', updated)
                assert len(urls) == 7 and all("?v=" in url for url in urls)
                assert (await (await client.get(urls[0])).text()) == "// new"
                assert (await (await client.get(urls[1])).text()) == "// model controls"
                assert (await (await client.get(urls[2])).text()) == "// research controls"
                assert (await (await client.get(urls[3])).text()) == "// decision chart"
                assert (await (await client.get(urls[4])).text()) == "// protected review controls"
                assert (await (await client.get(urls[5])).text()) == "body {}"
                assert (await (await client.get(urls[6])).text()) == "// margin controls"
                (tmp_path / "margin.js").write_text("// updated margin controls", encoding="utf-8")
                refreshed = await (await client.get("/")).text()
                assert urls[0] in refreshed and urls[6] not in refreshed
        finally:
            db.c.close()

    asyncio.run(check())


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
            assert 'data-view="research"' in await (await c.get("/")).text()
            assert (await c.get("/app.js")).status == 200
            assert (await c.get("/styles.css")).status == 200
    asyncio.run(check())
    db.c.close()
    assert main(["--data", str(tmp_path), "evidence", out["run_id"], "--diagnostics", "--decide", "NONE", "--note", "not funded"]) == 0
    assert (runs / (out["run_id"] + ".evidence.md")).exists()
    assert len(list(runs.glob("*.decision.json"))) == 1
