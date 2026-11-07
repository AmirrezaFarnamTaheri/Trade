"""Legacy EMA options remain compatible while maintained commands use registry parameters."""
import json
from datetime import timedelta

from gym.cli import main
from gym.domain.model import iso
from tests.support import START, market_db, quote_history


def test_legacy_ema_flags_and_registry_params_save_the_same_native_record(tmp_path, capsys):
    root = tmp_path / "live"
    root.mkdir()
    market_db(root, quote_history(n=180)).c.close()
    command = ["--data", str(tmp_path), "paper", "BTCUSDT", "--from", iso(START),
               "--to", iso(START + timedelta(minutes=30)), "--res", "1min"]
    assert main([*command, "--fast", "2", "--slow", "3"]) == 0
    files = list((root / "runs").glob("*.json"))
    assert len(files) == 1
    original = files[0].read_bytes()
    assert main([*command, "--params", json.dumps({"fast": 2, "slow": 3})]) == 0
    assert list((root / "runs").glob("*.json")) == files
    assert files[0].read_bytes() == original
    capsys.readouterr()
