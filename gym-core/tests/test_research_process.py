"""Real disposable workers return verified data, die on deadlines and retain claims."""
import asyncio
import sqlite3
import time
from datetime import timedelta
from pathlib import Path

import pytest

from gym.domain.model import iso
from gym.services.research_ledger import ResearchLedger
from gym.services.research_process import ResearchProcessFailure, calculate
from tests.support import START, market_db, quote_history


def prepare(root):
    db = market_db(root, quote_history(n=180))
    db.c.close()
    with ResearchLedger(root / "research.sqlite3") as ledger:
        hypothesis = ledger.register({"symbol": "BTCUSDT", "strategy": "ema-trend", "params": {"fast": 2, "slow": 3}})
        return ledger.schedule({"hypothesis_id": hypothesis["hypothesis_id"], "every_seconds": 3600,
            "lookback_seconds": 1800, "first_at": iso(START + timedelta(minutes=30)),
            "resolution": "1min", "cash": "1000", "fee_rate": "0.001"})["job_id"]


def test_real_process_completes_native_run_and_validation_is_not_hidden(tmp_path):
    job = prepare(tmp_path)
    result = asyncio.run(calculate(tmp_path, "tick", at=iso(START + timedelta(minutes=30))))
    assert len(result["completed"]) == 1
    with ResearchLedger(tmp_path / "research.sqlite3", readonly=True) as ledger:
        row = ledger.overview()["jobs"][0]
        assert row["id"] == job and row["last_report"]["status"] == "COMPLETED"
    with pytest.raises(ResearchProcessFailure, match="fields") as error:
        asyncio.run(calculate(tmp_path, "replay-resume", {}))
    assert error.value.status == 400 and error.value.report["operation_may_have_committed"]
    with pytest.raises(ValueError, match="unsupported"):
        asyncio.run(calculate(tmp_path, "arbitrary-command"))


def test_worker_gets_disposable_sql_temp_space_without_inheriting_private_environment(tmp_path, monkeypatch):
    prepare(tmp_path)
    original, captured = asyncio.create_subprocess_exec, {}
    async def launch(*args, **kwargs):
        captured.update(kwargs["env"])
        assert Path(kwargs["env"]["TEMP"]).is_dir()
        return await original(*args, **kwargs)
    monkeypatch.setenv("GYM_PRIVATE_TEST_SENTINEL", "do-not-inherit")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    result = asyncio.run(calculate(tmp_path, "tick", at=iso(START + timedelta(minutes=30))))
    assert result["completed"]
    assert "GYM_PRIVATE_TEST_SENTINEL" not in captured
    assert captured["TEMP"] == captured["TMP"]
    assert not Path(captured["TEMP"]).exists()


def test_locked_database_deadline_kills_worker_and_never_retries_or_advances(tmp_path):
    prepare(tmp_path)
    blocker = sqlite3.connect(tmp_path / "research.sqlite3", isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    try:
        with pytest.raises(ResearchProcessFailure) as error:
            asyncio.run(calculate(tmp_path, "tick", at=iso(START + timedelta(minutes=30)), timeout_seconds=1))
        assert error.value.status == 504 and error.value.report["process_terminated"]
        assert error.value.report["operation_may_have_committed"] and not error.value.report["automatic_retry_allowed"]
        assert time.monotonic() - started < 6
    finally:
        blocker.rollback()
        blocker.close()
    # A late worker cannot write after the held lock is released.
    with ResearchLedger(tmp_path / "research.sqlite3", readonly=True) as ledger:
        assert ledger.overview()["jobs"][0]["next_at"] == iso(START + timedelta(minutes=30))
        assert ledger.conn.execute("SELECT count(*) FROM reports").fetchone()[0] == 0


def test_cancelled_supervisor_reaps_child_before_database_is_unlocked(tmp_path):
    prepare(tmp_path)
    blocker = sqlite3.connect(tmp_path / "research.sqlite3", isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    async def check():
        task = asyncio.create_task(calculate(tmp_path, "tick", at=iso(START + timedelta(minutes=30))))
        await asyncio.sleep(.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    try:
        asyncio.run(check())
    finally:
        blocker.rollback()
        blocker.close()
    with ResearchLedger(tmp_path / "research.sqlite3", readonly=True) as ledger:
        assert ledger.conn.execute("SELECT count(*) FROM reports").fetchone()[0] == 0
