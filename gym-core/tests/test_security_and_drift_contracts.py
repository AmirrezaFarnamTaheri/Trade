"""Loopback security matrix, EN/FA translation parity, and docs/action drift gates (O015-O018, I019, U033)."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import SegmentWriter
from gym.api.server import UI, make_app
from gym.services.collector import Collector
from gym.services.evidence import evidence
from gym.services.rules import RuleService
from tests.support import market_db, quote_history

REPO_ROOT = Path(__file__).resolve().parents[2]
GYM_DOCS = REPO_ROOT / "gym-core" / "docs"


def test_en_fa_vocabulary_has_complete_key_and_placeholder_parity():
    """U033: every UI translation key has non-empty EN and FA strings with identical {placeholders}."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node not installed")
    src = UI.with_name("workspace-config.js").read_text("utf-8")
    # Evaluate vocabulary table in a minimal sandbox without DOM dependencies.
    script = (
        "const document = { getElementById: () => ({ textContent: '{\"demo\":true,\"resolutions\":[]}' }) };\n"
        "const location = { hash: '', pathname: '/', search: '' };\n"
        "const history = { replaceState() {} };\n"
        "const sessionStorage = { getItem() { return ''; }, setItem() {} };\n"
        "const addEventListener = () => {};\n"
        + src
        + "\nconsole.log(JSON.stringify(vocabulary));\n"
    )
    res = subprocess.run([node, "-"], input=script, capture_output=True, encoding="utf-8", timeout=15)
    assert res.returncode == 0, res.stderr
    vocab = json.loads(res.stdout)
    assert len(vocab) >= 100
    placeholder = re.compile(r"\{[a-zA-Z0-9_]+\}")
    for key, pair in vocab.items():
        assert isinstance(pair, list) and len(pair) == 2, key
        en, fa = pair
        assert isinstance(en, str) and en.strip(), f"empty EN for {key}"
        assert isinstance(fa, str) and fa.strip(), f"empty FA for {key}"
        assert set(placeholder.findall(en)) == set(placeholder.findall(fa)), f"placeholder drift for {key}: {en!r} vs {fa!r}"


def test_loopback_api_security_bounds_and_no_secret_echo(tmp_path):
    """O015, O016, O017, O018: private routes require token, cross-origin writes refused, malformed inputs bounded."""
    db = market_db(tmp_path, quote_history(n=3))
    seg = SegmentWriter(tmp_path / "raw", db)
    secret_token = "tok-super-secret-0123456789"

    async def check():
        col = Collector(db, seg, ["BTCUSDT"], demo=True)
        app = make_app(col, RuleService(db), secret_token, tmp_path / "runs")
        # Confirm no live order submission endpoint exists on the loopback server (O017).
        paths = {r.resource.canonical for r in app.router.routes() if r.resource}
        assert not any("submit-order" in p or "arm-executor" in p for p in paths)

        async with TestClient(TestServer(app)) as client:
            # Private endpoints reject missing/wrong tokens (O015).
            for private_path in ("/api/evidence", "/api/account", "/api/offline-reviews"):
                resp = await client.get(private_path)
                assert resp.status == 403, private_path
                body = await resp.text()
                assert secret_token not in body

            # Public index never embeds session token (O016).
            idx = await client.get("/")
            assert idx.status == 200 and secret_token not in await idx.text()

            # DNS-rebinding defence: non-loopback Host header is rejected with 403 (O015).
            rebind = await client.get("/api/health", headers={"Host": "evil.example"})
            assert rebind.status == 403

            # CSRF defence: write without per-run token is rejected with 403 and emits no CORS allow-origin (O015).
            cross = await client.post(
                "/api/compare",
                headers={"Origin": "https://evil.example"},
                json={},
            )
            assert cross.status == 403
            assert "Access-Control-Allow-Origin" not in cross.headers
            assert cross.headers.get("X-Content-Type-Options") == "nosniff"
            assert cross.headers.get("Cache-Control") == "no-store"

            # Malformed decimal/timestamp on authorized request returns 400 without echoing secrets (O018).
            bad = await client.post(
                "/api/compare",
                headers={"X-Gym-Token": secret_token},
                json={"symbol": "BTCUSDT", "cash": "NaN", "from": "not-a-date", "to": "also-bad"},
            )
            assert bad.status in (400, 422)
            assert secret_token not in await bad.text()

            # Enriched /api/evidence exposes truthful checkpoint, trial budget, and disarmed authority.
            ev_resp = await client.get("/api/evidence", headers={"X-Gym-Token": secret_token})
            assert ev_resp.status == 200
            ev = await ev_resp.json()
            assert ev["funded_authority"] is False
            assert ev["checkpoint"]["date"] == "2027-02-08"
            assert ev["checkpoint"]["host_status"] == "DISARMED_NOT_CERTIFIED"
            assert ev["trial_budget"]["limit"] == 2

    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()


def test_docs_and_runtime_agree_on_deadlines_disarmed_status_and_policy_exceptions():
    """I019: key documents and runtime evidence agree on 2027-02-08, 2027-05-19, DISARMED, and 2026-11-16 backup exception."""
    readme = (REPO_ROOT / "README.md").read_text("utf-8")
    product = (REPO_ROOT / "PRODUCT.md").read_text("utf-8")
    roadmap = (GYM_DOCS / "roadmap.md").read_text("utf-8")
    dr = (GYM_DOCS / "disaster-recovery.md").read_text("utf-8")
    checkpoint_doc = (REPO_ROOT / "docs" / "2027-02-08-checkpoint-protocol.md").read_text("utf-8")
    custody_doc = (GYM_DOCS / "independent-custody-protocol.md").read_text("utf-8")
    sampling_doc = (GYM_DOCS / "evidence-and-sampling-contract.md").read_text("utf-8")

    for doc in (readme, product, roadmap, checkpoint_doc):
        assert "DISARMED" in doc.upper()
    for doc in (product, roadmap, checkpoint_doc):
        assert "2027-02-08" in doc
    for doc in (roadmap, checkpoint_doc, custody_doc):
        assert "2027-05-19" in doc
    for doc in (roadmap, dr):
        assert "2026-11-16" in doc
    assert "UNKNOWN / REFUSED" in sampling_doc

    ev = evidence(None)
    assert ev["funded_authority"] is False
    assert ev["checkpoint"]["date"] == "2027-02-08"
    assert ev["checkpoint"]["breadth_score_after"] == "2027-05-19"
    assert ev["trial_budget"]["active"] <= ev["trial_budget"]["limit"] == 2
