"""Real persistent paper jobs, exact shadow accounting and a read-only MCP boundary."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
import json
import sqlite3

import pytest

from gym.cli import main
from gym.domain.model import iso
from gym.services.research_ledger import ResearchLedger
from gym.services.research_mcp import handle, serve_stdio
from tests.support import START, market_db, quote_history


def test_mcp_discovery_declares_only_the_enforced_local_read_capabilities(tmp_path):
    tools = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, tmp_path)["result"]["tools"]
    for tool in tools:
        assert tool["annotations"] == {"readOnlyHint": True, "destructiveHint": False,
                                       "idempotentHint": True, "openWorldHint": False}
    reply = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "strategy_catalog", "arguments": {}}}, tmp_path)
    capabilities = json.loads(reply["result"]["content"][0]["text"])["capabilities"]
    assert set(capabilities["tools"]) == {tool["name"] for tool in tools}
    assert capabilities["read_only"] is True and capabilities["runtime_isolation_verified"] is False
    assert capabilities["external_requests"] is False and capabilities["order_submission"] is False
    denied = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "place_order", "arguments": {}}}, tmp_path)
    assert denied["result"]["isError"] is True


def hypothesis(ledger):
    return ledger.register({"symbol": "BTCUSDT", "strategy": "ema-trend", "params": {"fast": 2, "slow": 3}})["hypothesis_id"]


def observation(at=START, *, status="OPEN", bid="99", ask="100"):
    return {"at": iso(at), "bid": bid, "ask": ask, "status": status, "qualified": True}


def schedule(ledger):
    return ledger.schedule({"hypothesis_id": hypothesis(ledger), "every_seconds": 3600,
                            "lookback_seconds": 3600, "first_at": iso(START + timedelta(hours=1)),
                            "resolution": "1min", "cash": "1000", "fee_rate": "0.001"})


def test_shadow_survives_restart_and_closure_with_received_asset_fees(tmp_path):
    path = tmp_path / "research.sqlite3"
    with ResearchLedger(path) as ledger:
        hid = hypothesis(ledger)
        opening = {"position_id": "shadow-1", "hypothesis_id": hid, "quote": observation(),
                   "gross_quantity": "2", "fee_rate": "0.1"}
        assert ledger.open_shadow(opening)["state"] == "SHADOW_OPEN"
        assert ledger.open_shadow(opening)["opened"]["net_quantity"] == "1.8"
        with pytest.raises(ValueError, match="conflicting"):
            ledger.open_shadow({**opening, "gross_quantity": "3"})
    with ResearchLedger(path) as ledger:
        closed_quote = observation(START + timedelta(hours=1), status="CLOSED")
        assert ledger.settle_shadow({"position_id": "shadow-1", "quote": closed_quote})["state"] == "PENDING_REOPEN"
        assert ledger.shadow("shadow-1")["state"] == "SHADOW_OPEN"
    with ResearchLedger(path) as ledger:
        closing = {"position_id": "shadow-1", "quote": observation(START + timedelta(hours=2), bid="110", ask="111")}
        result = ledger.settle_shadow(closing)
        assert result == ledger.settle_shadow(closing)
        assert result["state"] == "SHADOW_CLOSED"
        assert Decimal(result["closed"]["proceeds_quote"]) == Decimal("178.2")
        assert Decimal(result["closed"]["net_quote"]) == Decimal("-21.8")
        assert not result["funded_authority"] and not result["venue_settled"]
        with pytest.raises(ValueError, match="conflicting"):
            ledger.settle_shadow({**closing, "quote": observation(START + timedelta(hours=3))})


def test_shadow_large_exact_products_and_tiny_fee_roundtrip(tmp_path):
    with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        opening = {"position_id": "large", "hypothesis_id": hypothesis(ledger),
                   "quote": observation(bid="9" * 60, ask="9" * 60),
                   "gross_quantity": "9" * 60, "fee_rate": "0.0000001"}
        ledger.open_shadow(opening)
        result = ledger.settle_shadow({"position_id": "large", "quote": observation(START + timedelta(seconds=1), bid="9" * 60, ask="9" * 60)})
        assert result["state"] == "SHADOW_CLOSED" and Decimal(result["closed"]["net_quote"]) < 0


def test_registry_and_schedule_reject_unregistered_unbounded_and_floating_inputs(tmp_path):
    with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        for request in ({"symbol": "../secret", "strategy": "ema-trend", "params": {}},
                        {"symbol": "BTCUSDT", "strategy": "custom-code", "params": {}},
                        {"symbol": "BTCUSDT", "strategy": "ema-trend", "params": {"fast": True}}):
            with pytest.raises(ValueError):
                ledger.register(request)
        hid = hypothesis(ledger)
        base = {"hypothesis_id": hid, "every_seconds": 3600, "lookback_seconds": 3600,
                "first_at": iso(START), "resolution": "1min", "cash": "1000", "fee_rate": "0.001"}
        for patch in ({"cash": 1000.0}, {"every_seconds": True}, {"lookback_seconds": 2678401},
                      {"fee_rate": "NaN"}, {"resolution": []}, {"first_at": None}, {"first_at": "2026-01-01T00:00:00"},
                      {"hypothesis_id": "unknown"}, {"authority": "FUNDED"}):
            with pytest.raises(ValueError):
                ledger.schedule({**base, **patch})


def test_real_scheduled_replay_is_durable_bounded_and_idempotent(tmp_path):
    db = market_db(tmp_path, quote_history())
    try:
        path = tmp_path / "research.sqlite3"
        with ResearchLedger(path) as ledger:
            job = schedule(ledger)
            due = START + timedelta(hours=1)
            out = ledger.run_due(db, iso(due))
            assert len(out["completed"]) == 1 and not out["order_submitted"]
            assert ledger.run_due(db, iso(due))["completed"] == []
            saved = json.loads(ledger.conn.execute("SELECT body FROM reports").fetchone()[0])
            assert saved["inputs"]["cost"]["fee_rate"] == "0.001"
            assert "hold USDT" in saved["baselines"]
            assert not db.c.in_transaction
        with ResearchLedger(path) as ledger:
            assert len(ledger.overview()["alerts"]) == 2
            ledger.pause(job["job_id"])
            assert ledger.run_due(db, iso(due + timedelta(days=1)))["completed"] == []
    finally:
        db.c.close()


def test_explicit_recovery_preserves_failure_and_checks_the_due_window(tmp_path):
    db = market_db(tmp_path, [])
    due = START + timedelta(hours=1)
    try:
        with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
            job = schedule(ledger)
            assert len(ledger.run_due(db, iso(due))["failed"]) == 1
            request = {"job_id": job["job_id"], "expected_due": iso(due), "action": "RETRY", "reason": "collector restored"}
            result = ledger.recover(request, at=due + timedelta(minutes=1))
            assert result["next_at"] == iso(due)
            assert ledger.overview()["jobs"][0]["last_report"]["attempts"] == 1
            skipped = ledger.recover({**request, "action": "SKIP", "reason": "confirmed historical coverage gap"}, at=due + timedelta(minutes=2))
            assert skipped["next_at"] == iso(due + timedelta(hours=1))
            report = json.loads(ledger.conn.execute("SELECT body FROM reports").fetchone()[0])
            assert report["status"] == "SKIPPED" and report["previous_failure"]["status"] == "FAILED"
            assert len(ledger.overview()["alerts"]) == 4
            with pytest.raises(ValueError, match="changed"):
                ledger.recover(request, at=due + timedelta(minutes=3))
            with pytest.raises(ValueError):
                ledger.recover({**request, "expected_due": skipped["next_at"]}, at=due + timedelta(minutes=3))
    finally:
        db.c.close()


def test_result_publication_failure_does_not_advance_or_report_completion(tmp_path, monkeypatch):
    from gym.services import research_ledger
    db = market_db(tmp_path, quote_history(n=500))
    try:
        with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
            job = schedule(ledger)
            before = ledger.overview()["jobs"][0]["next_at"]
            def unavailable(*_):
                raise OSError("publication unavailable")
            monkeypatch.setattr(research_ledger, "save_run", unavailable)
            with pytest.raises(OSError):
                ledger.run_due(db, iso(START + timedelta(hours=1)))
            after = ledger.overview()
            assert after["jobs"][0]["next_at"] == before
            assert after["jobs"][0]["last_report"]["status"] == "RUNNING"
            assert after["jobs"][0]["last_report"]["liveness"] == "UNKNOWN"
            assert [a["kind"] for a in after["alerts"]] == ["RESEARCH_STARTED"]
            assert after["jobs"][0]["id"] == job["job_id"]
    finally:
        db.c.close()


def test_failed_tick_persists_retry_without_advancing_clock_or_starving_healthy_job(tmp_path):
    db = market_db(tmp_path, quote_history())
    path = tmp_path / "research.sqlite3"
    try:
        with ResearchLedger(path) as ledger:
            good = schedule(ledger)
            bad = ledger.schedule({"hypothesis_id": hypothesis(ledger), "every_seconds": 3600,
                                   "lookback_seconds": 3600, "first_at": iso(START - timedelta(hours=1)),
                                   "resolution": "1min", "cash": "1000", "fee_rate": "0.001"})
            now = START + timedelta(hours=1)
            out = ledger.run_due(db, iso(now), limit=2)
            assert [a["job_id"] for a in out["failed"]] == [bad["job_id"]]
            assert [a["job_id"] for a in out["completed"]] == [good["job_id"]]
            assert out["failed"][0]["attempts"] == 1
            assert out["failed"][0]["retry_at"] == iso(now + timedelta(hours=1))
            assert ledger.conn.execute("SELECT next_at FROM jobs WHERE id=?", (bad["job_id"],)).fetchone()[0] == bad["next_at"]
            failed = json.loads(ledger.conn.execute("SELECT body FROM reports WHERE job_id=?", (bad["job_id"],)).fetchone()[0])
            assert failed["status"] == "FAILED" and "result" not in failed
            assert not db.c.in_transaction
        with ResearchLedger(path) as ledger:
            assert ledger.run_due(db, iso(now))["failed"] == []
            retried = ledger.run_due(db, iso(now + timedelta(hours=1)))
            assert retried["failed"][0]["job_id"] == bad["job_id"]
            assert retried["failed"][0]["attempts"] == 2
            assert not retried["failed"][0]["order_submitted"]
    finally:
        db.c.close()


def test_mcp_is_readonly_even_at_database_boundary_and_has_no_secret_tools(tmp_path):
    path = tmp_path / "research.sqlite3"
    with ResearchLedger(path) as ledger:
        hypothesis(ledger)
    with ResearchLedger(path, readonly=True) as ledger:
        with pytest.raises(sqlite3.OperationalError):
            hypothesis(ledger)
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    names = {tool["name"] for tool in handle(request, tmp_path)["result"]["tools"]}
    assert names == {"strategy_catalog", "research_state", "market_coverage"}
    for name, arguments in (("read_file", {"path": "../secrets"}), ("research_state", {"path": "../secrets"}),
                            ("provision_key", {}), ("execute_order", {})):
        call = {**request, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        assert handle(call, tmp_path)["result"]["isError"] is True
    call = {**request, "method": "tools/call", "params": {"name": "research_state", "arguments": {}}}
    assert handle(call, tmp_path)["result"]["isError"] is False
    sink = StringIO()
    assert serve_stdio(tmp_path, StringIO(json.dumps(request) + "\n{\n"), sink) == 0
    lines = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert lines[0]["id"] == 1 and lines[1]["error"]["code"] == -32700
    assert serve_stdio(tmp_path, StringIO("x" * 65537), StringIO()) == 2


def test_cli_register_list_and_reject_bad_json(tmp_path, capsys):
    source = tmp_path / "hypothesis.json"
    source.write_text(json.dumps({"symbol": "BTCUSDT", "strategy": "ema-trend", "params": {}}), "utf-8")
    prefix = ["--data", str(tmp_path)]
    assert main(prefix + ["research", "register", str(source), "--demo"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert not first["funded_authority"]
    assert main(prefix + ["research", "list", "--demo"]) == 0
    assert len(json.loads(capsys.readouterr().out)["hypotheses"]) == 1
    source.write_text("not valid JSON", "utf-8")
    assert main(prefix + ["research", "register", str(source), "--demo"]) == 2
    assert "not valid JSON" not in capsys.readouterr().err


def test_unknown_database_is_not_modified(tmp_path):
    path = tmp_path / "other.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE keep(value)")
        conn.execute("INSERT INTO keep VALUES(42)")
    with pytest.raises(ValueError, match="unversioned"):
        ResearchLedger(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert conn.execute("SELECT value FROM keep").fetchone()[0] == 42
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 1


def test_research_tool_provenance_binds_arguments_and_actual_payload(tmp_path):
    from hashlib import sha256
    from gym.domain.strategy import digest

    db = market_db(tmp_path, quote_history(n=10))
    db.c.close()
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "market_coverage", "arguments": {"symbol": "BTCUSDT"}}}
    result = handle(request, tmp_path)["result"]
    assert result["isError"] is False
    payload = result["content"][0]["text"]
    provenance = result["_meta"]["tradinggym/provenance"]
    assert provenance["tool"] == "market_coverage"
    assert provenance["arguments_digest"] == digest({"symbol": "BTCUSDT"})
    assert provenance["payload_sha256"] == sha256(payload.encode("utf-8")).hexdigest()
    assert provenance["source_authenticity_verified"] is False
    value = json.loads(payload)
    value["observations"] += 1
    assert provenance["payload_sha256"] != sha256(json.dumps(value).encode("utf-8")).hexdigest()
