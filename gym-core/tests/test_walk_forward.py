"""Expanding selection freezes chronology, retains failures and never reads final data."""
import json
from copy import deepcopy
from datetime import timedelta

import pytest

from gym.adapters.run_store import load_verified_run
from gym.domain.model import iso
from gym.services.experiment_registry import ExperimentRegistry
from gym.services.research_actions import research_action
from gym.services.walk_forward import walk_forward
from tests.support import START, market_db, quote_history


def request():
    minute = lambda n: iso(START + timedelta(minutes=n))
    return {"hypothesis": "Frozen expanding EMA comparison", "symbol": "BTCUSDT",
            "candidates": [{"strategy": "ema-trend", "params": {"fast": 2, "slow": n}} for n in (3, 5)],
            "windows": [{"train_from": minute(0), "train_to": minute(n),
                         "test_from": minute(n + 1), "test_to": minute(n + 21)} for n in (40, 80)],
            "final_from": minute(110), "resolution": "1min", "cash": "1000",
            "fee_rate": "0.002", "latency_ms": 500, "purge_bars": 1}


def test_native_walk_forward_records_all_trials_and_final_cutoff(tmp_path):
    db = market_db(tmp_path, quote_history(n=750))
    try:
        with ExperimentRegistry(tmp_path, store="live") as registry:
            result = walk_forward(registry, db, request())
            saved = registry.read(result["experiment_id"])
        assert saved["definition"] == request()
        attempts = [e for e in saved["events"] if e["kind"] == "ATTEMPT"]
        results = [e for e in saved["events"] if e["kind"] == "RESULT"]
        assert len(attempts) == len(results) == 6
        assert result["selection_count"] == 4 and result["test_slots"] == 2
        assert result["final_data_read"] is False and result["independent_final_evidence"] is False
        assert all(e["state"] in ("COMPLETED", "NOT_ACTIVE", "ABSTAIN", "INCOMPLETE", "FAILED") for e in results)
        for row in results:
            if row.get("run_id"):
                run = load_verified_run(tmp_path / "runs", row["run_id"], store="live")
                assert run["inputs"]["to"] <= request()["final_from"]
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_short_test_cannot_count_unfinished_warmup_as_evaluated(tmp_path):
    db = market_db(tmp_path, quote_history(n=750))
    value = request()
    value["candidates"] = [{"strategy": "ema-trend", "params": {"fast": 2, "slow": n}} for n in (50, 60)]
    value["windows"] = [{"train_from": iso(START), "train_to": iso(START + timedelta(minutes=100)),
                         "test_from": iso(START + timedelta(minutes=101)), "test_to": iso(START + timedelta(minutes=104))}]
    try:
        with ExperimentRegistry(tmp_path, store="live") as registry:
            out = walk_forward(registry, db, value)
            assert out["folds"][0]["selected"] is not None
            test = out["folds"][0]["test"]
            assert out["status"] == "INCOMPLETE"
            assert test["state"] == "NOT_ACTIVE" and test["reason"] == "WARMUP_NOT_COMPLETED"
            assert test["fills"] == 0 and not test["ready"]
            saved = registry.read(out["experiment_id"])
            assert any(e["kind"] == "RESULT" and e["state"] == "NOT_ACTIVE" for e in saved["events"])
    finally:
        db.c.close()


def test_test_and_final_changes_cannot_change_earlier_training(tmp_path):
    db = market_db(tmp_path, quote_history(n=750))
    value = request()
    value["windows"] = value["windows"][:1]
    try:
        with ExperimentRegistry(tmp_path, store="live") as registry:
            first = walk_forward(registry, db, value)
            db.c.execute("UPDATE book_top SET bid='80000',ask='80001' WHERE ts_avail>=?",
                         (value["windows"][0]["test_from"],))
            db.c.commit()
            second = walk_forward(registry, db, value)
        assert first["folds"][0]["training"] == second["folds"][0]["training"]
        assert first["folds"][0]["selected"] == second["folds"][0]["selected"]
        assert first["folds"][0]["test"]["run_id"] != second["folds"][0]["test"]["run_id"]
    finally:
        db.c.close()


def test_missing_data_keeps_every_attempt_instead_of_hiding_failures(tmp_path):
    db = market_db(tmp_path, [])
    try:
        with ExperimentRegistry(tmp_path, store="demo") as registry:
            result = walk_forward(registry, db, request())
            events = registry.read(result["experiment_id"])["events"]
        assert result["status"] == "INCOMPLETE"
        assert sum(e["kind"] == "RESULT" and e["state"] == "INCOMPLETE" for e in events) == 4
        assert sum(e["kind"] == "RESULT" and e["state"] == "ABSTAIN" for e in events) == 2
        assert all(fold["selected"] is None for fold in result["folds"])
    finally:
        db.c.close()


@pytest.mark.parametrize("change", ["overlap", "purge", "final", "future", "expanding", "duplicate", "cash", "budget"])
def test_invalid_plans_fail_before_registry_writes(tmp_path, change):
    value = deepcopy(request())
    if change == "overlap":
        value["windows"][1]["test_from"] = value["windows"][0]["test_from"]
    elif change == "purge":
        value["windows"][0]["test_from"] = value["windows"][0]["train_to"]
    elif change == "final":
        value["final_from"] = value["windows"][0]["test_to"]
    elif change == "future":
        value["windows"][1]["test_to"] = "2100-01-01T00:00:00Z"
    elif change == "expanding":
        value["windows"][1]["train_from"] = value["windows"][0]["test_from"]
    elif change == "duplicate":
        value["candidates"][1] = value["candidates"][0]
    elif change == "cash":
        value["cash"] = 1000.0
    else:
        value["windows"] *= 20
    db = market_db(tmp_path, [])
    try:
        with ExperimentRegistry(tmp_path, store="live") as registry:
            with pytest.raises(ValueError):
                walk_forward(registry, db, value)
            assert registry.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    finally:
        db.c.close()


def test_action_uses_existing_registry_and_native_saved_runs(tmp_path):
    db = market_db(tmp_path, quote_history(n=750))
    db.c.close()
    out = research_action(tmp_path, "walk-forward", request(), store="live")
    assert research_action(tmp_path, "experiment-status", out["experiment_id"])["workflow"] == "walk-forward/1"


def test_cli_uses_real_bounded_worker(tmp_path, capsys):
    from gym.cli import main
    root = tmp_path / "live"
    root.mkdir()
    db = market_db(root, quote_history(n=750))
    db.c.close()
    source = tmp_path / "search.json"
    source.write_text(json.dumps(request()), encoding="utf-8")
    assert main(["--data", str(tmp_path), "research", "walk-forward", str(source)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["selection_count"] == 4 and out["final_data_read"] is False
    assert (root / "experiments.sqlite3").is_file()


def test_authenticated_api_dispatches_native_worker(tmp_path):
    import asyncio

    from aiohttp.test_utils import TestClient, TestServer

    from gym.adapters.store import SegmentWriter
    from gym.api.server import make_app
    from gym.services.collector import Collector
    from gym.services.rules import RuleService

    async def check():
        db = market_db(tmp_path, quote_history(n=750))
        collector = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT"])
        try:
            app = make_app(collector, RuleService(db), "private", runs=tmp_path / "runs")
            async with TestClient(TestServer(app, host="127.0.0.1")) as client:
                payload = {"action": "walk-forward", "value": request()}
                denied = await client.post("/api/research/action", json=payload)
                assert denied.status == 403
                response = await client.post("/api/research/action", headers={"X-Gym-Token": "private"}, json=payload)
                assert response.status == 200
                assert (await response.json())["selection_count"] == 4
        finally:
            db.c.close()

    asyncio.run(check())
