"""Supervised paper jobs pause, resume and restart at their committed clock."""
import asyncio
from datetime import timedelta
import sqlite3

import pytest

from gym.domain.model import iso
from gym.services import research_runner
from gym.services.research_ledger import ResearchLedger
from tests.support import START, market_db, quote_history


def prepared_job(root):
    db = market_db(root, quote_history())
    db.c.close()
    with ResearchLedger(root / "research.sqlite3") as ledger:
        hypothesis = ledger.register({"symbol": "BTCUSDT", "strategy": "ema-trend",
                                      "params": {"fast": 2, "slow": 3}})
        return ledger.schedule({"hypothesis_id": hypothesis["hypothesis_id"], "every_seconds": 3600,
                                "lookback_seconds": 3600, "first_at": iso(START + timedelta(hours=1)),
                                "resolution": "1min", "cash": "1000", "fee_rate": "0.001"})["job_id"]


def test_runner_pause_resume_and_restart_preserve_committed_clock(tmp_path, monkeypatch):
    job = prepared_job(tmp_path)
    original = ResearchLedger.run_due
    stop = asyncio.Event()

    def one_tick(ledger, db, at, **kwargs):
        assert db.c.execute("PRAGMA query_only").fetchone()[0] == 1
        result = original(ledger, db, at, **kwargs)
        stop.set()
        return result

    monkeypatch.setattr(ResearchLedger, "run_due", one_tick)

    def run_at(at):
        stop.clear()
        monkeypatch.setattr(research_runner, "now_utc", lambda: at)
        return asyncio.run(research_runner.watch(tmp_path, stop=stop))

    first = run_at(START + timedelta(hours=1))
    assert first["state"] == "STOPPED" and first["ticks"] == first["completed"] == 1
    assert not first["funded_authority"] and not first["order_submitted"]
    with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        assert ledger.pause(job)["enabled"] is False
    assert run_at(START + timedelta(hours=2))["completed"] == 0
    with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        assert ledger.resume(job)["enabled"] is True
        assert ledger.overview()["jobs"][0]["next_at"] == iso(START + timedelta(hours=2))
    assert run_at(START + timedelta(hours=2))["completed"] == 1
    assert run_at(START + timedelta(hours=2))["completed"] == 0
    with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        assert ledger.conn.execute("SELECT count(*) FROM reports").fetchone()[0] == 2
        assert ledger.overview()["jobs"][0]["next_at"] == iso(START + timedelta(hours=3))


def test_stop_wakes_idle_poll_and_can_be_repeated(tmp_path, monkeypatch):
    prepared_job(tmp_path)
    monkeypatch.setattr(research_runner, "now_utc", lambda: START)

    async def scenario():
        stop = asyncio.Event()
        task = asyncio.create_task(research_runner.watch(tmp_path, poll_seconds=60, stop=stop))
        await asyncio.sleep(0)
        stop.set()
        stop.set()
        result = await asyncio.wait_for(task, 1)
        assert result["ticks"] == 1 and result["completed"] == result["failed"] == 0
        assert (await research_runner.watch(tmp_path, stop=stop))["ticks"] == 0

    asyncio.run(scenario())


def test_cancellation_stops_foreground_loop_cleanly(tmp_path, monkeypatch):
    prepared_job(tmp_path)
    monkeypatch.setattr(research_runner, "now_utc", lambda: START)

    async def scenario():
        task = asyncio.create_task(research_runner.watch(tmp_path, poll_seconds=60))
        await asyncio.sleep(0)
        task.cancel()
        result = await task
        assert result["state"] == "STOPPED" and result["reason"] == "Operator interrupted"

    asyncio.run(scenario())


def test_runner_never_creates_missing_market_data(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        asyncio.run(research_runner.watch(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_unexpected_failure_surfaces_without_advancing_job(tmp_path, monkeypatch):
    prepared_job(tmp_path)
    monkeypatch.setattr(research_runner, "now_utc", lambda: START + timedelta(hours=1))

    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("test failure")

    monkeypatch.setattr("gym.services.research_ledger.paper", broken)
    with pytest.raises(sqlite3.OperationalError, match="test failure"):
        asyncio.run(research_runner.watch(tmp_path))
    with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        assert ledger.overview()["jobs"][0]["next_at"] == iso(START + timedelta(hours=1))
        assert ledger.overview()["jobs"][0]["last_report"]["status"] == "RUNNING"


@pytest.mark.parametrize("poll", [0, -1, True, float("nan"), float("inf"), 61, "5"])
def test_poll_interval_is_bounded(tmp_path, poll):
    with pytest.raises(ValueError, match="poll"):
        asyncio.run(research_runner.watch(tmp_path, poll_seconds=poll))


def test_resume_rejects_unknown_job(tmp_path):
    with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        with pytest.raises(ValueError, match="unknown"):
            ledger.resume("missing")
