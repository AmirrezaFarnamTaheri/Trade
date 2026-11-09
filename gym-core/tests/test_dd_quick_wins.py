"""Regressions for the due-diligence quick wins: token guard, exact candle parsing, atomic spec versioning."""
import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.wallex import parse_udf
from gym.api import guard, token_matches
from gym.domain.model import InstrumentId
from tests.support import START, market_db


def test_non_ascii_token_is_a_bad_token_not_a_server_error():
    assert token_matches("tok", "tok") and not token_matches("tok", "other")
    assert not token_matches("\u00e9", "tok") and not token_matches("t\u00f6k", "tok")

    async def ping(_):
        return web.json_response({"ok": True})

    app = web.Application(middlewares=[guard("tok")])
    app.router.add_post("/api/ping", ping)

    async def check():
        async with TestClient(TestServer(app)) as client:
            reply = await client.post("/api/ping", headers={"X-Gym-Token": "\u00e9"})
            assert reply.status == 403
            assert (await client.post("/api/ping", headers={"X-Gym-Token": "tok"})).status == 200
    asyncio.run(check())


def test_udf_numbers_are_exact_decimals_from_the_json_text():
    # 0.1 + 0.2 style values, and more digits than a binary double keeps: a float round trip changes them.
    text = ('{"s":"ok","t":[%d],"o":[0.30000000000000004441],"h":[12345678901234567.89],'  # noqa: UP031
            '"l":[0.1],"c":["0.2"],"v":[1e-8]}' % START.timestamp())
    [k] = parse_udf(text)
    assert str(k["o"]) == "0.30000000000000004441"
    assert str(k["h"]) == "12345678901234567.89"
    assert k["l"] == Decimal("0.1") and k["c"] == Decimal("0.2") and k["v"] == Decimal("1e-8")
    with pytest.raises(ValueError, match="finite"):
        parse_udf('{"s":"ok","t":[1],"o":[NaN],"h":[1],"l":[1],"c":[1],"v":[1]}')


class FailingInsert:
    """Connection proxy that fails the successor insert, as a crash between the two statements would."""

    def __init__(self, c):
        self.c = c

    def execute(self, sql, *args):
        if sql.startswith("insert into instrument_specs"):
            raise RuntimeError("crash between close and insert")
        return self.c.execute(sql, *args)


def test_spec_version_close_and_insert_are_atomic(tmp_path):
    db = market_db(tmp_path, [])
    inst = InstrumentId.wallex("BTCUSDT", "BTC", "USDT")
    db.upsert_instrument(inst, {}, {"step": "0.01"}, "rest:test", START)
    real = db.c
    db.c = FailingInsert(real)
    with pytest.raises(RuntimeError):
        db.upsert_instrument(inst, {}, {"step": "0.001"}, "rest:test", START + timedelta(hours=1))
    db.c = real
    rows = real.execute("select spec, valid_to from instrument_specs where instrument_id='wallex:BTCUSDT'").fetchall()
    assert rows == [('{"step": "0.01"}', None)]
    db.upsert_instrument(inst, {}, {"step": "0.001"}, "rest:test", START + timedelta(hours=1))
    assert real.execute("select count(*) from instrument_specs where valid_to is null").fetchone()[0] == 1


def test_gateway_child_sees_only_allowlisted_and_configured_key_variables(tmp_path):
    import json as _json

    from gym.services.model_gateway import gateway_env
    (tmp_path / "config.json").write_text(_json.dumps({"connections": [
        {"id": "a", "provider": "openai", "auth": {"type": "api_key", "env": ["RESEARCH_KEY_1"]}},
        {"id": "b", "provider": "anthropic", "auth": {"type": "oauth"}}]}), encoding="utf-8")
    parent = {"GYM_MODEL_HOME": str(tmp_path), "PATH": "p", "SystemRoot": "C:/Windows", "https_proxy": "http://proxy",
              "RESEARCH_KEY_1": "k1", "AWS_SECRET_ACCESS_KEY": "canary", "GITHUB_TOKEN": "canary",
              "GYM_MODEL_ALLOW_LOOPBACK_HTTP": "1"}
    env = gateway_env(parent)
    assert "canary" not in env.values()
    assert env["RESEARCH_KEY_1"] == "k1" and env["PATH"] == "p" and env["SystemRoot"] == "C:/Windows"
    assert env["https_proxy"] == "http://proxy" and env["GYM_MODEL_ALLOW_LOOPBACK_HTTP"] == "1"
    assert "GYM_MODEL_PYTHON" in env
    (tmp_path / "config.json").write_text("not json", encoding="utf-8")
    assert "RESEARCH_KEY_1" not in gateway_env(parent)


def test_docs_state_the_registry_strategy_count():
    import re
    from pathlib import Path

    from gym.domain.registry import STRATEGIES
    words = {12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen",
             18: "eighteen", 19: "nineteen", 20: "twenty"}
    expected = words[len(STRATEGIES)]
    docs = Path(__file__).resolve().parents[1] / "docs"
    # Current-state claims only; dated study write-ups keep the count they had at the time.
    claims = [(p.name, m.group(1).lower()) for p in docs.glob("*.md")
              for m in re.finditer(r"\b(" + "|".join(words.values()) + r") (?:registry strategies|native long/flat rules)", p.read_text(encoding="utf-8"), re.IGNORECASE)]
    assert claims and all(word == expected for _, word in claims), claims


def test_open_segment_is_in_the_manifest_and_crash_tails_are_reported(tmp_path):
    from gym.adapters.store import MarketDB, SegmentWriter, verify_segments
    db = MarketDB(tmp_path / "market.db")
    writer = SegmentWriter(tmp_path / "raw", db)
    writer.write("ws", "a", START)
    [(seg_id, sha)] = db.c.execute("select seg_id, sha256 from segments").fetchall()
    assert sha is None  # registered at open, before any close
    report = verify_segments(db, [tmp_path / "raw"])
    assert report["unclosed"] == [seg_id] and report["checked"] == 0
    writer.close()
    assert db.c.execute("select sha256 is not null, seq_to from segments").fetchone() == (1, 1)
    assert verify_segments(db, [tmp_path / "raw"])["unclosed"] == []
    # A file written by an older build, or copied in, with no row at all.
    stray = tmp_path / "raw" / seg_id.split("/")[0] / "99-0.jsonl.zst"
    stray.write_bytes(b"")
    assert verify_segments(db, [tmp_path / "raw"])["unregistered"] == [f"{seg_id.split('/')[0]}/99-0.jsonl.zst"]


def test_daily_sweep_flags_crash_tails_but_not_the_live_segment(tmp_path):
    from gym.adapters.store import MarketDB, SegmentWriter
    from gym.services.collector import Collector
    db = MarketDB(tmp_path / "market.db")
    crashed = SegmentWriter(tmp_path / "raw", db)
    crashed.write("ws", "a", START)
    crashed.w = None  # a hard kill: the row stays open and the file is never finalized
    live = SegmentWriter(tmp_path / "raw", db)
    live.write("ws", "b", START + timedelta(minutes=5))
    col = Collector(db, live, ["BTCUSDT"])
    col.db_path = tmp_path / "market.db"
    flags = [flag for flag, _ in col.verify_raw(START + timedelta(minutes=10))]
    assert flags == ["SEGMENT_UNCLOSED"]
    live.close()


def test_doctor_reports_each_check_and_fails_on_a_tampered_segment(tmp_path, capsys):
    from gym.adapters.store import MarketDB, SegmentWriter
    from gym.cli import main
    from gym.services.doctor import diagnose
    root = tmp_path / "live"
    db = MarketDB(root / "market.db")
    writer = SegmentWriter(root / "raw", db)
    writer.write("ws", "a", START)
    writer.close()
    db.c.close()
    report = diagnose(root, START + timedelta(minutes=5))
    status = {c["check"]: c["status"] for c in report["checks"]}
    assert status["market_db"] == status["raw_segments"] == status["segment_manifest"] == "PASS"
    assert status["venue_facts"] == "SKIP" and status["backup_receipts"] == "WARN" and report["read_only"]
    assert not (root / "venue_facts.db").exists()  # a missing journal is reported, never created
    [seg] = list((root / "raw").rglob("*.jsonl.zst"))
    seg.write_bytes(b"tampered")
    assert main(["--data", str(tmp_path), "doctor", "--full"]) == 1
    assert "FAIL  raw_segments" in capsys.readouterr().out


def test_fill_timestamps_follow_the_shared_contract_fixture():
    import json as _json
    from pathlib import Path

    from gym.adapters.wallex_order_evidence import InvalidOrderEvidence, _timestamp
    fixture = _json.loads((Path(__file__).resolve().parents[2] / "contracts/v1/fixtures/fill-timestamps.json").read_text("utf-8"))
    for value in fixture["accept"]:
        assert _timestamp(value) == value, value
    for value in fixture["reject"]:
        with pytest.raises(InvalidOrderEvidence):
            _timestamp(value)


def test_every_cited_evidence_path_has_a_digest_in_the_tracked_index():
    """Receipts stay out of git, but each .pi/ citation in the docs must resolve to a digest in evidence/INDEX.json."""
    import json as _json
    import re
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    index = _json.loads((repo / "evidence" / "INDEX.json").read_text("utf-8"))["entries"]
    cited = {raw.rstrip("./") for doc in (repo / "gym-core" / "docs").glob("*.md")
             for raw in re.findall(r"\.pi/([A-Za-z0-9_./-]+)", doc.read_text("utf-8"))}
    missing = sorted(c for c in cited if index.get(c, {}).get("kind") in (None, "missing"))
    assert not missing, f"cite evidence only after running scripts/evidence_index.py: {missing}"
