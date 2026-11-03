"""B3 offline encrypted backup rotation: negative cases are the safety contract."""
from pathlib import Path
import hashlib
import sqlite3
import os

import pytest

from gym.services.encrypted_backup import BackupUnsafe, BackupAuthenticationError
from gym.services import backup_rotation


def ledger(path: Path):
    schema = (Path(__file__).resolve().parents[2] / "executor/exec-store/schema.sql").read_text()
    with sqlite3.connect(path) as db:
        db.executescript(schema)
        raw = b"synthetic-ledger-record"
        digest = hashlib.sha256(bytes(32) + len(raw).to_bytes(8, "big") + raw).digest()
        db.execute(
            "INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) VALUES(?,?,?,?)",
            (1, raw, bytes(32), digest),
        )
        db.commit()


def test_backup_rotation_refuses_same_device_without_writing(tmp_path):
    source, destination = tmp_path / "source.db", tmp_path / "external"
    ledger(source)
    destination.mkdir()
    with pytest.raises(BackupUnsafe, match="independent volume"):
        backup_rotation.backup_once(source, destination, passphrase="correct horse battery staple")
    assert list(destination.iterdir()) == []


def test_backup_rotation_roundtrips_before_pruning_old_bundles(tmp_path, monkeypatch):
    source, destination = tmp_path / "source.db", tmp_path / "external"
    ledger(source)
    destination.mkdir()
    monkeypatch.setattr(backup_rotation, "_independent_volume", lambda source, folder: True)
    paths = []
    for index in range(3):
        result = backup_rotation.backup_once(source, destination,
            passphrase="correct horse battery staple", keep=2)
        assert result["verified_restore"] is True
        assert result["off_machine_verified"] is False
        assert result["trusted_origin"] is False
        paths.append(Path(result["bundle"]))
        if index < 2:
            os.utime(paths[-1], (1000 + index, 1000 + index))
    assert not paths[0].exists()
    assert paths[1].exists() and paths[2].exists()
    assert len(list(destination.glob("tradinggym-exec-*.tgbak"))) == 2


def test_backup_failure_must_not_delete_older_backups(tmp_path, monkeypatch):
    source, destination = tmp_path / "source.db", tmp_path / "external"
    ledger(source)
    destination.mkdir()
    monkeypatch.setattr(backup_rotation, "_independent_volume", lambda source, folder: True)
    existing = backup_rotation.backup_once(source, destination,
        passphrase="correct horse battery staple", keep=2)
    old = Path(existing["bundle"])
    original = old.read_bytes()
    def reject_restore(*args, **kwargs):
        raise BackupAuthenticationError("verification failed")
    monkeypatch.setattr(backup_rotation, "restore_backup", reject_restore)
    with pytest.raises(BackupAuthenticationError):
        backup_rotation.backup_once(source, destination,
            passphrase="correct horse battery staple", keep=2)
    assert old.read_bytes() == original


def test_symlinked_backup_root_is_rejected(tmp_path, monkeypatch):
    source, real = tmp_path / "source.db", tmp_path / "real"
    ledger(source)
    real.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("OS cannot create a symlink")
    monkeypatch.setattr(backup_rotation, "_independent_volume", lambda source, folder: True)
    with pytest.raises(BackupUnsafe, match="symlink"):
        backup_rotation.backup_once(source, alias,
            passphrase="correct horse battery staple")
    assert list(real.iterdir()) == []
