"""Preregistration cannot be retuned/retried and outcome memory cannot travel backwards."""
import json
from datetime import timedelta

import pytest

from gym.adapters.run_store import save_run
from gym.cli import main
from gym.services.paper import paper
from gym.services.research_actions import review_runs
from gym.services.research_protocol import ResearchProtocol
from tests.support import START, market_db, quote_history


def request():
    return {"symbol": "BTCUSDT", "strategy": "ema-trend", "params": {"fast": 2, "slow": 3},
            "selection_end": (START - timedelta(minutes=10)).isoformat(), "test_from": START.isoformat(),
            "test_to": (START + timedelta(minutes=29)).isoformat(), "resolution": "1min", "cash": "1000", "fee_rate": "0.002"}


def test_frozen_consume_once_protocol_persists_success_and_rejects_overlap(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    clock = {"at": START - timedelta(minutes=5)}
    try:
        with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as ledger:
            registered = ledger.register(request())
            key = registered["evaluation_id"]
            assert ledger.register(request()) == registered
            with pytest.raises(ValueError, match="overlaps"):
                ledger.register({**request(), "params": {"fast": 3, "slow": 5}})
            with pytest.raises(ValueError, match="not complete"):
                ledger.consume(key, db)
            assert ledger.evaluation(key)["state"] == "REGISTERED"
            clock["at"] = START + timedelta(hours=1)
            result = ledger.consume(key, db)
            assert result["state"] == "EVALUATED" and not result["independent_final_evidence"]
            assert (tmp_path / "runs" / (result["result"]["run_id"] + ".json")).is_file()
            with pytest.raises(ValueError, match="consumed"):
                ledger.consume(key, db)
        with ResearchProtocol(tmp_path) as reopened:
            assert reopened.evaluation(key) == result
    finally:
        db.c.close()


def test_failed_and_interrupted_evaluations_remain_consumed(tmp_path, monkeypatch):
    import gym.services.research_protocol as protocol
    db = market_db(tmp_path, [])
    clock = {"at": START - timedelta(minutes=5)}
    try:
        with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as ledger:
            key = ledger.register(request())["evaluation_id"]
            clock["at"] = START + timedelta(hours=1)
            with pytest.raises(ValueError):
                ledger.consume(key, db)
            assert ledger.evaluation(key)["state"] == "FAILED"
            with pytest.raises(ValueError, match="consumed"):
                ledger.consume(key, db)
            assert not db.c.in_transaction
            clock["at"] = START - timedelta(minutes=5)
            other = {**request(), "symbol": "ETHUSDT"}
            key = ledger.register(other)["evaluation_id"]
            monkeypatch.setattr(protocol, "paper", lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
            clock["at"] = START + timedelta(hours=1)
            with pytest.raises(KeyboardInterrupt):
                ledger.consume(key, db)
            assert ledger.evaluation(key)["state"] == "CONSUMED"
            with pytest.raises(ValueError, match="consumed"):
                ledger.consume(key, db)
    finally:
        db.c.close()


@pytest.mark.parametrize("change", [{"test_from": (START - timedelta(minutes=6)).isoformat()},
    {"selection_end": START.isoformat()}, {"resolution": "session"}, {"cash": "NaN"}, {"approved": True}])
def test_bad_registration_cannot_read_or_consume_data(tmp_path, change):
    with ResearchProtocol(tmp_path, clock=lambda: START - timedelta(minutes=5)) as ledger:
        with pytest.raises(ValueError):
            ledger.register({**request(), **change})
        assert ledger.conn.execute("SELECT count(*) FROM evaluations").fetchone()[0] == 0


def test_engine_change_blocks_consumption_and_database_retuning_is_refused(tmp_path, monkeypatch):
    import sqlite3

    import gym.services.research_protocol as protocol
    clock = {"at": START - timedelta(minutes=5)}
    db = market_db(tmp_path, [])
    try:
        with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as ledger:
            key = ledger.register(request())["evaluation_id"]
            clock["at"] = START + timedelta(hours=1)
            monkeypatch.setattr(protocol, "_engine_digest", lambda: "changed")
            with pytest.raises(ValueError, match="engine changed"):
                ledger.consume(key, db)
            assert ledger.evaluation(key)["state"] == "REGISTERED"
            with pytest.raises(sqlite3.IntegrityError):
                ledger.conn.execute("UPDATE evaluations SET body='{}'")
    finally:
        db.c.close()


def test_numeric_analysts_and_resolved_outcomes_are_cutoff_bound_and_private(tmp_path):
    db = market_db(tmp_path, quote_history(n=180))
    try:
        run = paper(db, "BTCUSDT", START, START + timedelta(minutes=29), resolution="1min", fast=2, slow=3)
        run["private_notes"] = "never-publish"
        save_run(run, tmp_path / "runs")
        key = run["run_id"]
        with pytest.raises(ValueError, match="cutoff"):
            review_runs(tmp_path / "runs", [key], as_of=START)
        review = review_runs(tmp_path / "runs", [key], as_of=START + timedelta(hours=1))
        assert len(review["reports"]) == 3 and all(r["status"] == "VERIFIED_NUMERIC" for r in review["reports"])
        assert not review["semantic_grounding_verified"] and "never-publish" not in json.dumps(review)
        clock = {"at": START}
        with ResearchProtocol(tmp_path, clock=lambda: clock["at"]) as ledger:
            assert ledger.record_outcome(key)["status"] == "PENDING"
            assert ledger.outcomes(START)["outcomes"] == []
            clock["at"] = START + timedelta(hours=1)
            resolved = ledger.record_outcome(key)
            assert resolved["status"] == "RESOLVED" and resolved["net_quote"] == run["result"]["end"]["net"]
            assert ledger.outcomes(START + timedelta(minutes=59))["outcomes"] == []
            assert ledger.outcomes(clock["at"])["outcomes"][0]["run_id"] == key
            clock["at"] += timedelta(hours=1)
            assert ledger.record_outcome(key) == resolved
            assert "never-publish" not in json.dumps(ledger.outcomes(clock["at"]))
    finally:
        db.c.close()


def test_cli_protocol_uses_real_clock_and_preserves_cutoff_reads(tmp_path, capsys):
    root = tmp_path / "live"
    root.mkdir()
    db = market_db(root, quote_history(n=180))
    try:
        run = paper(db, "BTCUSDT", START, START + timedelta(minutes=29), resolution="1min", fast=2, slow=3)
        save_run(run, root / "runs")
    finally:
        db.c.close()
    source = tmp_path / "review.json"
    source.write_text(json.dumps({"run_ids": [run["run_id"]]}))
    prefix = ["--data", str(tmp_path), "research"]
    assert main([*prefix, "review", str(source)]) == 0
    assert len(json.loads(capsys.readouterr().out)["reports"]) == 3
    assert main([*prefix, "outcome-add", run["run_id"], "--at", START.isoformat()]) == 2
    capsys.readouterr()
    assert main([*prefix, "outcome-add", run["run_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "RESOLVED"
    assert main([*prefix, "outcomes", "--at", START.isoformat()]) == 0
    assert json.loads(capsys.readouterr().out)["outcomes"] == []
    assert main([*prefix, "final-status", "bad"]) == 2
