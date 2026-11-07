"""Observed liquidity, sampled risk and private paper-summary contracts."""
import asyncio
import json
import shutil
import subprocess
from datetime import timedelta
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.run_store import save_run
from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.domain.model import BookSide, QualityLimits, iso
from gym.domain.strategy import digest
from gym.services.collector import Collector
from gym.services.liquidity import liquidity_snapshot
from gym.services.paper import paper
from gym.services.reports import paper_summary, sampled_drawdown
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history


def sides():
    return {"bid": BookSide([(Decimal("99.9"), Decimal("2.123456789")),
                             (Decimal("99.75"), Decimal(3)), (Decimal("99.5"), Decimal(4))], START),
            "ask": BookSide([(Decimal("100.1"), Decimal(1)), (Decimal("100.25"), Decimal(2)),
                             (Decimal("100.5"), Decimal(3))], START)}


def test_observed_depth_is_exact_and_includes_boundary_levels():
    report = liquidity_snapshot(sides(), START, QualityLimits())
    assert report["status"] == "AVAILABLE"
    assert report["level_counts"] == {"bid": 3, "ask": 3}
    assert [r["bid_base"] for r in report["bands"]] == ["2.123456789", "5.123456789", "9.123456789"]
    assert report["bands"][0]["bid_quote"] == "212.1333332211"
    assert report["bands"][0]["ask_base"] == "1"
    assert report["scope"] == "OBSERVED_LEVELS_ONLY"


@pytest.mark.parametrize("fault", ["missing", "stale", "future", "crossed", "nonfinite", "duplicate", "nonpositive"])
def test_bad_depth_never_publishes_numeric_aggregates(fault):
    book = sides()
    if fault == "missing":
        book["ask"] = None
    elif fault in ("stale", "future"):
        book["ask"] = BookSide(book["ask"].levels, START + timedelta(seconds=1 if fault == "future" else -121))
    else:
        price = {"crossed": "101", "nonfinite": "NaN", "duplicate": "99.9", "nonpositive": "0"}[fault]
        book["bid"] = BookSide(book["bid"].levels + [(Decimal(price), Decimal(1))], START)
    report = liquidity_snapshot(book, START, QualityLimits())
    assert report["status"] == "UNAVAILABLE" and report["bands"] == []


def curve_record(values):
    return {"inputs": {"from": iso(START), "to": iso(START + timedelta(minutes=10))},
            "result": {"start_cash": "1000", "curve": [(iso(START + timedelta(minutes=i+1)), v)
                                                       for i, v in enumerate(values)]}}


def test_drawdown_includes_first_loss_initial_cash_and_final_estimate():
    out = curve_record(["900", "1100", "990"])
    out["result"]["end"] = {"equity": "880"}
    report = sampled_drawdown(out)
    assert report["maximum_percent"] == "20.00000000"
    assert report["peak_at"] == iso(START + timedelta(minutes=2))
    assert report["peak_to_trough_seconds"] == 480
    assert report["continuous_path_verified"] is False
    assert sampled_drawdown(curve_record(["900"]))["maximum_percent"] == "10.00000000"
    assert sampled_drawdown(curve_record([]))["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1"])
def test_invalid_equity_cannot_become_a_plausible_risk_metric(bad):
    with pytest.raises(ValueError):
        sampled_drawdown(curve_record([bad]))


def test_summary_is_allowlisted_authenticated_and_references_the_original_run(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=29), resolution="1min", fast=2, slow=3)
        out["private_account"] = {"api_key": "private-canary"}
        out["inputs"]["private_path"] = "private-canary"
        out["warnings"].append("private-canary")
        out["evidence"] = {"note": "private-canary"}
        out["capital_decisions"] = [{"note": "private-canary"}]
        card = paper_summary(out)
        assert "private-canary" not in json.dumps(card)
        assert card["outputs_digest"] == out["outputs_digest"]
        assert card["end"]["net"] == out["result"]["end"]["net"]
        checksum = card.pop("summary_digest")
        assert digest(card) == checksum
        runs = tmp_path / "runs"
        save_run(out, runs)
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])

        async def check():
            async with TestClient(TestServer(make_app(col, RuleService(db), "tok", runs))) as client:
                url = "/api/runs/" + out["run_id"] + "/summary"
                assert (await client.get(url)).status == 403
                response = await client.get(url, headers={"X-Gym-Token": "tok"})
                assert response.status == 200, await response.text()
                assert response.headers["Cache-Control"] == "no-store"
                assert "attachment" in response.headers["Content-Disposition"]
                saved = await response.json()
                assert saved["schema"] == "paper-summary/2" and "funded_authority" not in saved and saved["summary_digest"] == checksum
                assert "private-canary" not in json.dumps(saved)
                assert (await client.get("/api/runs/not-a-run/summary", headers={"X-Gym-Token": "tok"})).status == 400
                assert (await client.get("/api/runs/" + "0"*16 + "/summary", headers={"X-Gym-Token": "tok"})).status == 404
        asyncio.run(check())
    finally:
        db.c.close()


def test_summary_checksum_survives_browser_json_round_trip(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js required for actual JavaScript JSON round trip")
    db = market_db(tmp_path, quote_history(n=180))
    try:
        out = paper(db, "BTCUSDT", START, START + timedelta(minutes=29), resolution="1min", fast=2, slow=3)
        card = paper_summary(out)
        assert card["cost_assumptions"]["max_wait_s"] == "60.0"
        result = subprocess.run([node, "-e", "let s='';process.stdin.on('data',b=>s+=b);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s))));"],
                                input=json.dumps(card), capture_output=True, text=True, check=True, timeout=10)
        downloaded = json.loads(result.stdout)
        checksum = downloaded.pop("summary_digest")
        assert digest(downloaded) == checksum
    finally:
        db.c.close()
