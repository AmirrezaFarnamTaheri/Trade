"""Manual B3 single-pass command keeps backup phrases out of arguments/logs."""
from argparse import Namespace
import gym.cli as cli
import pytest


def test_backup_cli_refuses_unattended_stdin(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "stdin", type("Stdin", (), {"isatty": lambda _: False})())
    args = Namespace(ledger=str(tmp_path / "db"), destination=str(tmp_path / "offsite"), keep=3)
    with pytest.raises(ValueError, match="interactive"):
        cli.backup_once_cmd(args)


def test_backup_cli_prompts_only_interactively_without_echoing_phrase(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli.sys, "stdin", type("Stdin", (), {"isatty": lambda _: True})())
    import getpass
    monkeypatch.setattr(getpass, "getpass", lambda _: "synthetic-secret-passphrase")
    import gym.services.backup_rotation as rotation
    calls = []
    def record(*args, **kwargs):
        calls.append((args, kwargs))
        return {"verified_restore": True, "off_machine_verified": False, "deleted_old_bundles": 0}
    monkeypatch.setattr(rotation, "backup_once", record)
    args = Namespace(ledger=str(tmp_path / "db"), destination=str(tmp_path / "offsite"), keep=3)
    assert cli.backup_once_cmd(args) == 0
    assert calls[0][1]["passphrase"] == "synthetic-secret-passphrase"
    assert calls[0][1]["keep"] == 3
    assert "synthetic-secret-passphrase" not in capsys.readouterr().out


def test_backup_cli_parser_rejects_noninteractive_use(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "stdin", type("Stdin", (), {"isatty": lambda _: False})())
    code = cli.main(["backup-once", str(tmp_path / "source.db"), str(tmp_path / "other")])
    assert code == 2
