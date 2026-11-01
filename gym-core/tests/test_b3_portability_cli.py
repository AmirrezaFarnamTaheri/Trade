"""Synthetic encrypted B3 backup works from a CLI, including no-overwrite."""
from pathlib import Path
import subprocess
import sys
from gym.services.restore_gate import inspect_ledger

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "gym-core" / "scripts" / "b3_portability_probe.py"


def test_cli_can_produce_and_restore_an_authenticated_synthetic_ledger(tmp_path):
    bundle = tmp_path / "portable-demo.tgbak"
    restored = tmp_path / "machine2" / "exec_ledger.db"
    first = subprocess.run(
        [sys.executable, str(PROBE), "produce", str(bundle)],
        capture_output=True, text=True
    )
    assert first.returncode == 0, first.stderr
    assert bundle.read_bytes().startswith(b"TGBKUP01")
    assert not bundle.read_bytes().startswith(b"SQLite format 3")
    second = subprocess.run(
        [sys.executable, str(PROBE), "restore", str(bundle), str(restored)],
        capture_output=True, text=True
    )
    assert second.returncode == 0, second.stderr
    assert inspect_ledger(restored)["sequence"] == 2
    assert "PASS: B3 synthetic restored" in second.stdout


def test_cli_fails_closed_if_restore_target_preexists(tmp_path):
    bundle = tmp_path / "portable-demo.tgbak"
    restored = tmp_path / "active.db"
    first = subprocess.run(
        [sys.executable, str(PROBE), "produce", str(bundle)],
        capture_output=True, text=True
    )
    assert first.returncode == 0, first.stderr
    restored.write_bytes(b"KEEP ORIGINAL")
    second = subprocess.run(
        [sys.executable, str(PROBE), "restore", str(bundle), str(restored)],
        capture_output=True, text=True
    )
    assert second.returncode != 0
    assert restored.read_bytes() == b"KEEP ORIGINAL"
