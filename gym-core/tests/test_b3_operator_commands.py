"""B3 exit evidence via operator commands: restore to a new path; an unsafe update is refused."""
import json
import sys

from gym.cli import main
from gym.services.encrypted_backup import create_backup
from tests.test_encrypted_backup import make_ledger

PHRASE = "correct horse battery staple"


def test_restore_backup_cli_publishes_verified_new_ledger(tmp_path, monkeypatch, capsys):
    source, bundle = tmp_path / "exec_ledger.db", tmp_path / "b.tgbak"
    head = make_ledger(source)
    create_backup(source, bundle, passphrase=PHRASE)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": PHRASE)
    dest = tmp_path / "second-machine" / "exec_ledger.db"
    assert main(["restore-backup", str(bundle), str(dest)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["head_hash"] == head and out["mode_after"] == "DISARMED" and dest.is_file()
    assert PHRASE not in json.dumps(out)
    assert main(["restore-backup", str(bundle), str(dest)]) == 2  # never overwrites
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "wrong passphrase entirely")
    assert main(["restore-backup", str(bundle), str(tmp_path / "other.db")]) == 2
    assert not (tmp_path / "other.db").exists()


def test_update_check_refuses_unsafe_updates(tmp_path, capsys):
    ledger = tmp_path / "exec_ledger.db"
    make_ledger(ledger)
    base = ["update-check", str(ledger), "--open-positions"]
    assert main(base + ["0", "--unknown-orders", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["mode_after"] == "DISARMED"
    assert main(base + ["0", "--unknown-orders", "1"]) == 2
    assert main(base + ["2", "--unknown-orders", "0"]) == 2
    assert "alternative protection" in capsys.readouterr().err
    assert main(base + ["2", "--unknown-orders", "0", "--alternative-protection"]) == 0
    capsys.readouterr()
    ledger.write_bytes(ledger.read_bytes()[:-512])  # damaged ledger
    assert main(base + ["0", "--unknown-orders", "0"]) == 2
    assert "ledger integrity" in capsys.readouterr().err
