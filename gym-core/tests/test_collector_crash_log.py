import pytest

import gym.cli as cli


def test_collector_crash_leaves_a_traceback_on_disk(tmp_path, monkeypatch):
    async def broken(args):
        raise RuntimeError("venue socket exploded")

    monkeypatch.setattr(cli, "serve", broken)
    with pytest.raises(RuntimeError, match="venue socket exploded"):
        cli.main(["--data", str(tmp_path), "run", "--no-browser"])
    log = (tmp_path / "live" / "collector-crash.log").read_text("utf-8")
    assert "RuntimeError: venue socket exploded" in log
    assert log.startswith("=== ") and "Z" in log.splitlines()[0]


def test_doctor_reports_the_newest_crash_for_a_week(tmp_path):
    from datetime import UTC, datetime

    from gym.services.doctor import _crash
    now = datetime(2026, 11, 19, 12, tzinfo=UTC)
    assert _crash(tmp_path, now) == {"check": "collector_crash", "status": "PASS", "detail": "no collector crash recorded"}
    (tmp_path / "collector-crash.log").write_text(
        "=== 2026-11-10T00:00:00.000000Z\nTraceback\nOSError: old\n\n"
        "=== 2026-11-18T03:00:00.000000Z\nTraceback\nRuntimeError: venue socket exploded\n\n", "utf-8")
    check = _crash(tmp_path, now)
    assert check["status"] == "WARN"
    assert check["detail"] == "2 crash(es) logged; newest 2026-11-18T03:00:00+00:00: RuntimeError: venue socket exploded"
    assert _crash(tmp_path, datetime(2026, 11, 30, tzinfo=UTC))["status"] == "PASS"


def test_a_clean_stop_writes_no_crash_log(tmp_path, monkeypatch):
    async def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "serve", interrupted)
    assert cli.main(["--data", str(tmp_path), "run", "--no-browser"]) == 0
    assert not (tmp_path / "live" / "collector-crash.log").exists()
