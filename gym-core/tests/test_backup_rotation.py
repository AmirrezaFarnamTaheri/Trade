"""B3 offline encrypted backup rotation: negative cases are the safety contract."""
import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from gym.services import backup_rotation
from gym.services.encrypted_backup import BackupAuthenticationError, BackupUnsafe


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


def test_restore_drill_verifies_the_newest_bundle_and_leaves_no_copy(tmp_path, monkeypatch, capsys):
    import json

    from gym.adapters import secret_store
    from gym.cli import main
    source, destination = tmp_path / "source.db", tmp_path / "external"
    ledger(source)
    destination.mkdir()
    monkeypatch.setattr(backup_rotation, "_independent_volume", lambda source, folder: True)
    backup_rotation.backup_once(source, destination, passphrase="correct horse battery staple")
    monkeypatch.setattr(secret_store, "load_backup_passphrase", lambda root=None: "correct horse battery staple")
    assert main(["--data", str(tmp_path / "data"), "restore-drill", str(destination), "--stored-passphrase"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["drill"] is True and report["restored_copy"] == "deleted" and report["bundle"].endswith(".tgbak")
    monkeypatch.setattr(secret_store, "load_backup_passphrase", lambda root=None: "wrong passphrase entirely")
    assert main(["--data", str(tmp_path / "data"), "restore-drill", str(destination), "--stored-passphrase"]) != 0


def chain(path: Path, records):
    """A valid hash-chained ledger holding exactly `records`."""
    path.unlink(missing_ok=True)
    schema = (Path(__file__).resolve().parents[2] / "executor/exec-store/schema.sql").read_text()
    from contextlib import closing
    with closing(sqlite3.connect(path)) as db:
        db.executescript(schema)
        previous = bytes(32)
        for sequence, raw in enumerate(records, 1):
            digest = hashlib.sha256(previous + len(raw).to_bytes(8, "big") + raw).digest()
            db.execute("INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) VALUES(?,?,?,?)",
                       (sequence, raw, previous, digest))
            previous = digest
        db.commit()


def test_anchors_refuse_a_truncated_or_rebuilt_ledger_before_rotation(tmp_path, monkeypatch):
    from gym.services.ledger_anchors import ANCHORS, AnchorViolation
    source, destination = tmp_path / "source.db", tmp_path / "external"
    destination.mkdir()
    monkeypatch.setattr(backup_rotation, "_independent_volume", lambda source, folder: True)
    phrase = "correct horse battery staple"
    chain(source, [b"one", b"two"])
    backup_rotation.backup_once(source, destination, passphrase=phrase, keep=2)
    chain(source, [b"one", b"two", b"three"])  # an honest ledger only grows
    assert backup_rotation.backup_once(source, destination, passphrase=phrase, keep=2)["anchors_checked"] == 1
    before = sorted(destination.glob("*.tgbak"))
    for name, records in (("truncated", [b"one", b"two"]), ("rebuilt", [b"one", b"TWO", b"three", b"four"])):
        chain(source, records)
        with pytest.raises(AnchorViolation, match=name if name == "truncated" else "replaced"):
            backup_rotation.backup_once(source, destination, passphrase=phrase, keep=2)
        assert all(p.exists() for p in before)  # nothing older was rotated away
    assert len((destination / ANCHORS).read_text("ascii").splitlines()) == 2
