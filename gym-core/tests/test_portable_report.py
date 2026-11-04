"""Portable paper reports are escaped, script-free and allowlisted."""
from datetime import timedelta
from html import unescape
import json

import pytest

from gym.adapters.run_store import save_run
from gym.cli import main
from gym.services.paper import paper
from gym.services.portable_report import render_html
from gym.services.reports import paper_summary
from tests.support import START, market_db, quote_history


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
