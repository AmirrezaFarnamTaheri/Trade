"""Portable paper reports are escaped, script-free and allowlisted."""
import asyncio
import json
from datetime import timedelta
from decimal import Decimal
from html import unescape

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.run_store import save_run
from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.cli import main
from gym.domain.sim import CostModel
from gym.services.collector import Collector
from gym.services.paper import paper
from gym.services.portable_report import render_html
from gym.services.reports import paper_summary
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history


def test_portable_exports_keep_optional_execution_assumptions(tmp_path):
    db = market_db(tmp_path, quote_history(n=100))
    try:
        cost = CostModel(order_type="limit", maker_fee_rate=Decimal("0.0002"),
                         max_participation=Decimal("0.25"), max_fraction=Decimal("0.3"))
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=17), resolution="1min",
                    fast=2, slow=3, cost=cost)
        out["inputs"]["cost"]["private_notes"] = "private-canary"
        expected = {**cost.describe(), "max_wait_s": "60.0"}
        card = paper_summary(out)
        assert card["cost_assumptions"] == expected
        html = render_html(out)
        assert "private-canary" not in html
        exported = json.loads(unescape(html.split("<pre>", 1)[1].split("</pre>", 1)[0]))
        assert exported["cost_assumptions"] == expected
    finally:
        db.c.close()


def test_html_download_requires_token_and_uses_the_existing_allowlisted_report(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    out = paper(db, "BTCUSDT", START, START + timedelta(minutes=29), resolution="1min", fast=2, slow=3)
    out["private_notes"] = "private-canary"
    save_run(out, tmp_path / "runs")
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])

    async def check():
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok", tmp_path / "runs"))) as client:
            route = "/api/runs/" + out["run_id"] + "/summary.html"
            assert (await client.get(route)).status == 403
            result = await client.get(route, headers={"X-Gym-Token": "tok"})
            assert result.status == 200 and result.content_type == "text/html"
            assert await result.text() == render_html(out)
            assert result.headers["Cache-Control"] == "no-store"
            assert result.headers["Content-Disposition"].endswith('.html"')
            assert (await client.get(route, headers={"X-Gym-Token": "tok", "Host": "evil.example"})).status == 403
            (tmp_path / "runs" / (out["run_id"] + ".json")).write_text(json.dumps({**out, "run_id": "forged"}), encoding="utf-8")
            assert (await client.get(route, headers={"X-Gym-Token": "tok"})).status == 400
    try:
        asyncio.run(check())
    finally:
        db.c.close()


def test_portable_report_escapes_fields_and_omits_private_records(tmp_path, capsys):
    db = market_db(tmp_path, quote_history(n=180))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=29), resolution="1min", fast=2, slow=3)
    finally:
        db.c.close()
    out["private_notes"] = "private-canary"
    out["warnings"].append("private-canary")
    html = render_html(out)
    assert "private-canary" not in html
    assert "<script" not in html and "http://" not in html and "https://" not in html
    assert paper_summary(out)["summary_digest"] in html
    assert "PAPER ONLY" in html and "default-src 'none'" in unescape(html)
    assert 'name="viewport"' in html
    out["inputs"]["symbol"] = '<img src=x onerror="alert(1)">'
    assert "<img" not in render_html(out) and "&lt;img" in render_html(out)
    out["inputs"]["symbol"] = "BTCUSDT"
    live = tmp_path / "data" / "live"
    save_run(out, live / "runs")
    target = tmp_path / "paper.html"
    args = ["--data", str(live.parent), "summary", out["run_id"], "--format", "html", "--output", str(target)]
    assert main(args) == 0
    assert target.read_text(encoding="utf-8") == render_html(out)
    assert main(args) == 2
    assert not (live / "research.sqlite3").exists()
    assert main(["--data", str(live.parent), "summary", out["run_id"]]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[-1])["summary_digest"] == paper_summary(out)["summary_digest"]


@pytest.mark.parametrize("format", ["json", "html"])
@pytest.mark.parametrize("content", ["{}", "null", "[]", "[" * 1100 + "]" * 1100])
def test_malformed_summary_is_rejected_without_partial_output(tmp_path, capsys, format, content):
    root = tmp_path / "live" / "runs"
    root.mkdir(parents=True)
    (root / ("0" * 16 + ".json")).write_text(content)
    output = tmp_path / "report.html"
    assert main(["--data", str(tmp_path), "summary", "0" * 16,
                 "--format", format, "--output", str(output)]) == 2
    assert "error:" in capsys.readouterr().err and not output.exists()
