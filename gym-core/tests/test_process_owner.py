"""Actual OS ownership cannot be inferred from PID text or old RUNNING records."""
import json
import os
import subprocess
import sys

import pytest

from gym.services.process_owner import ProcessOwner, process_status


def test_lock_is_exclusive_and_stopped_receipt_cannot_claim_liveness(tmp_path):
    assert process_status(tmp_path, store="live")["owners"] == []
    with ProcessOwner(tmp_path, "scheduler", store="live"):
        row = process_status(tmp_path, store="live")["owners"][0]
        assert row["state"] == "ALIVE" and row["pid"] == os.getpid()
        with pytest.raises(ValueError, match="another"):
            with ProcessOwner(tmp_path, "scheduler", store="live"):
                pytest.fail("duplicate owner admitted")
        assert process_status(tmp_path, store="demo")["owners"] == []
    assert process_status(tmp_path, store="live")["owners"][0]["state"] == "STOPPED"


def test_abrupt_process_death_releases_os_lock_without_rewriting_receipt(tmp_path):
    code = ("import sys,json; sys.path=json.loads(sys.argv[2]); from gym.services.process_owner import ProcessOwner; import time; "
            "owner=ProcessOwner(sys.argv[1],'campaign',store='live'); owner.__enter__(); "
            "print('ready',flush=True); time.sleep(60)")
    child = subprocess.Popen([getattr(sys, "_base_executable", sys.executable), "-I", "-c", code, str(tmp_path), json.dumps(sys.path)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        assert process_status(tmp_path, store="live")["owners"][0]["state"] == "ALIVE"
        assert process_status(tmp_path, store="live")["owners"][0]["pid"] == child.pid
    finally:
        child.kill()
        child.wait(timeout=5)
        child.stdout.close()
    assert process_status(tmp_path, store="live")["owners"][0]["state"] == "STOPPED"


def test_invalid_receipt_is_unknown_instead_of_alive(tmp_path):
    with ProcessOwner(tmp_path, "scheduler", store="live") as owner:
        owner.stream.seek(1)
        owner.stream.truncate(1)
        owner.stream.write(b"not JSON")
        assert process_status(tmp_path, store="live")["owners"][0]["state"] == "UNKNOWN"
