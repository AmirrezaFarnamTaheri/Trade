"""B3 portable passphrase-encrypted backups and non-destructive restore."""
from pathlib import Path
import hashlib
import sqlite3

import pytest

from gym.services.encrypted_backup import (
    BackupAuthenticationError,
    BackupUnsafe,
    create_backup,
    restore_backup,
)


def _symlink_or_skip(link, target):
    try:
        link.symlink_to(target)
    except OSError as exc:  # Windows without SeCreateSymbolicLinkPrivilege
        pytest.skip(f"symlinks unavailable: {exc}")


def make_ledger(path: Path, events=(b"one", b"two")):
    schema = (Path(__file__).resolve().parents[2] / "executor/exec-store/schema.sql").read_text()
    db = sqlite3.connect(path)
    db.executescript(schema)
    previous = bytes(32)
    for sequence, raw in enumerate(events, 1):
        digest = hashlib.sha256(previous + len(raw).to_bytes(8, "big") + raw).digest()
        db.execute(
            "INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) VALUES(?,?,?,?)",
            (sequence, raw, previous, digest),
        )
        previous = digest
    db.commit()
    db.close()
    return previous.hex()


def test_backup_is_portable_authenticated_and_restores_to_new_machine_path(tmp_path):
    source = tmp_path / "exec_ledger.db"
    bundle = tmp_path / "portable.tgbak"
    destination = tmp_path / "second-machine" / "exec_ledger.db"
    expected_head = make_ledger(source)
    (tmp_path / "secrets.dat").write_bytes(b"VENUE SECRET MUST NEVER BE BACKED UP")
    manifest = create_backup(source, bundle, passphrase="correct horse battery staple")
    assert manifest["encrypted"] is True
    assert manifest["schema_version"] == 1
    assert manifest["head_hash"] == expected_head
    assert manifest["trusted_origin"] is False
    assert manifest["authentication"] == "AES-256-GCM passphrase AEAD"
    assert b"VENUE SECRET MUST NEVER BE BACKED UP" not in bundle.read_bytes()
    restored = restore_backup(bundle, destination, passphrase="correct horse battery staple")
    assert restored["head_hash"] == expected_head
    assert restored["sequence"] == 2
    assert restored["authenticated"] is True
    # SQLite online backup makes a new, logically identical snapshot. The
    # on-disk WAL header/counters can differ from the original live database.
    with sqlite3.connect(source) as original_db, sqlite3.connect(destination) as recovered_db:
        sql = "SELECT sequence, event_bytes, previous_hash, event_hash FROM ledger_events ORDER BY sequence"
        assert original_db.execute(sql).fetchall() == recovered_db.execute(sql).fetchall()
    from gym.services.restore_gate import inspect_ledger
    assert inspect_ledger(destination)["head_hash"] == expected_head


def test_wrong_passphrase_and_ciphertext_tampering_never_publish_restore(tmp_path):
    source = tmp_path / "exec_ledger.db"
    bundle = tmp_path / "portable.tgbak"
    expected = make_ledger(source)
    create_backup(source, bundle, passphrase="correct horse battery staple")
    wrong_dest = tmp_path / "wrong.db"
    with pytest.raises(BackupAuthenticationError):
        restore_backup(bundle, wrong_dest, passphrase="incorrect passphrase")
    assert not wrong_dest.exists()
    raw = bytearray(bundle.read_bytes())
    raw[-20] ^= 0x40
    bundle.write_bytes(raw)
    tampered_dest = tmp_path / "tampered.db"
    with pytest.raises(BackupAuthenticationError):
        restore_backup(bundle, tampered_dest, passphrase="correct horse battery staple")
    assert not tampered_dest.exists()


def test_restore_refuses_existing_destination_without_modifying_it(tmp_path):
    source = tmp_path / "exec_ledger.db"
    bundle = tmp_path / "portable.tgbak"
    make_ledger(source)
    create_backup(source, bundle, passphrase="correct horse battery staple")
    destination = tmp_path / "active.db"
    destination.write_bytes(b"active ledger must not be overwritten")
    with pytest.raises(BackupUnsafe, match="exists"):
        restore_backup(bundle, destination, passphrase="correct horse battery staple")
    assert destination.read_bytes() == b"active ledger must not be overwritten"


def test_backup_refuses_symlink_source_existing_bundle_and_weak_passphrase(tmp_path):
    source = tmp_path / "exec_ledger.db"
    make_ledger(source)
    bundle = tmp_path / "portable.tgbak"
    with pytest.raises(BackupUnsafe, match="passphrase"):
        create_backup(source, bundle, passphrase="short")
    create_backup(source, bundle, passphrase="correct horse battery staple")
    with pytest.raises(BackupUnsafe, match="exists"):
        create_backup(source, bundle, passphrase="correct horse battery staple")
    link = tmp_path / "linked.db"
    _symlink_or_skip(link, source)
    with pytest.raises(BackupUnsafe):
        create_backup(link, tmp_path / "link.tgbak", passphrase="correct horse battery staple")


def test_backup_bundle_truncation_and_unknown_version_fail_closed(tmp_path):
    source = tmp_path / "exec_ledger.db"
    bundle = tmp_path / "portable.tgbak"
    make_ledger(source)
    create_backup(source, bundle, passphrase="correct horse battery staple")
    raw = bundle.read_bytes()
    truncated = tmp_path / "truncated.tgbak"
    truncated.write_bytes(raw[:32])
    with pytest.raises(BackupAuthenticationError):
        restore_backup(truncated, tmp_path / "truncated.db", passphrase="correct horse battery staple")
    unknown = bytearray(raw)
    unknown[0] ^= 1
    bad = tmp_path / "bad.tgbak"
    bad.write_bytes(unknown)
    with pytest.raises(BackupAuthenticationError):
        restore_backup(bad, tmp_path / "bad.db", passphrase="correct horse battery staple")


def test_backup_failure_before_open_never_unlinks_someone_elses_bundle(tmp_path, monkeypatch):
    import gym.services.encrypted_backup as backup_mod

    source = tmp_path / "exec_ledger.db"
    bundle = tmp_path / "portable.tgbak"
    make_ledger(source)
    sentinel = b"OTHER PROCESS CREATED THIS BUNDLE"

    def failure_during_snapshot(_source, _snapshot):
        # Reproduce a filesystem race after the early exists() check.
        bundle.write_bytes(sentinel)
        raise BackupUnsafe("simulated snapshot failure")

    monkeypatch.setattr(backup_mod, "_snapshot_database", failure_during_snapshot)
    with pytest.raises(BackupUnsafe, match="simulated"):
        create_backup(source, bundle, passphrase="correct horse battery staple")
    assert bundle.read_bytes() == sentinel


def test_ci_checks_lock_without_granting_token_write_permissions():
    ci = (Path(__file__).resolve().parents[2] / ".github/workflows/validate.yml").read_text()
    assert "update-python-lock:" not in ci
    assert "contents: write" not in ci
    assert "uv lock --check" in ci
    assert "uv sync --locked --group dev" in ci
