"""B3 offline public-recovery-key backup: no API keys or live Executor authority."""
from pathlib import Path
import hashlib
import os
import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives import serialization

from gym.services.recovery_key_backup import (
    RecoveryUnsafe, RecoveryAuthenticationError,
    create_recovery_key_backup, restore_recovery_key_backup,
)


def synthetic_ledger(path: Path):
    schema = (Path(__file__).resolve().parents[2] / "executor/exec-store/schema.sql").read_text()
    with sqlite3.connect(path) as db:
        db.executescript(schema)
        event = b"b3-recovery-key-example"
        digest = hashlib.sha256(bytes(32) + len(event).to_bytes(8, "big") + event).digest()
        db.execute("INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) VALUES(?,?,?,?)",
                   (1, event, bytes(32), digest))
        db.commit()


def keypair():
    private = X25519PrivateKey.generate()
    raw_private = private.private_bytes(serialization.Encoding.Raw,
                                        serialization.PrivateFormat.Raw,
                                        serialization.NoEncryption())
    raw_public = private.public_key().public_bytes(serialization.Encoding.Raw,
                                                   serialization.PublicFormat.Raw)
    return raw_private, raw_public


def test_public_key_archive_is_authenticated_and_portable_without_passphrase(tmp_path):
    private, public = keypair()
    ledger, bundle, restored = (tmp_path / "exec_ledger.db",
                                tmp_path / "offsite.tgbak", tmp_path / "restored.db")
    synthetic_ledger(ledger)
    (tmp_path / "secrets.dat").write_bytes(b"PRIVATE VENUE SECRET MUST NOT APPEAR")
    created = create_recovery_key_backup(ledger, bundle, recovery_public_key=public)
    assert created["encrypted"] is True and created["verified_roundtrip"] is True
    assert created["trusted_origin"] is False and created["install_authorized"] is False
    assert b"PRIVATE VENUE SECRET" not in bundle.read_bytes()
    result = restore_recovery_key_backup(bundle, restored, recovery_private_key=private)
    assert result["sequence"] == created["sequence"] == 1
    assert result["head_hash"] == created["head_hash"]
    assert result["file_sha256"] == created["file_sha256"]
    assert result["trusted_origin"] is False
    assert result["install_authorized"] is False
    with pytest.raises(RecoveryUnsafe, match="already exists"):
        restore_recovery_key_backup(bundle, restored, recovery_private_key=private)


def test_wrong_recipient_and_modified_ciphertext_fail_without_publishing(tmp_path):
    private, public = keypair()
    wrong, _ = keypair()
    ledger, archive = tmp_path / "ledger.db", tmp_path / "encrypted.tgbak"
    synthetic_ledger(ledger)
    create_recovery_key_backup(ledger, archive, recovery_public_key=public)
    with pytest.raises(RecoveryAuthenticationError):
        restore_recovery_key_backup(archive, tmp_path / "wrong.db", recovery_private_key=wrong)
    assert not (tmp_path / "wrong.db").exists()
    content = bytearray(archive.read_bytes())
    content[-20] ^= 0x01
    archive.write_bytes(content)
    with pytest.raises(RecoveryAuthenticationError):
        restore_recovery_key_backup(archive, tmp_path / "tampered.db", recovery_private_key=private)
    assert not (tmp_path / "tampered.db").exists()


def test_recovery_key_backups_never_overwrite_an_existing_destination(tmp_path):
    private, public = keypair()
    ledger, archive = tmp_path / "ledger.db", tmp_path / "encrypted.tgbak"
    synthetic_ledger(ledger)
    archive.write_bytes(b"EXISTING BUNDLE")
    with pytest.raises(RecoveryUnsafe, match="already exists"):
        create_recovery_key_backup(ledger, archive, recovery_public_key=public)
    assert archive.read_bytes() == b"EXISTING BUNDLE"
    archive.unlink()
    create_recovery_key_backup(ledger, archive, recovery_public_key=public)
    target = tmp_path / "target.db"
    target.write_bytes(b"NEVER OVERWRITE")
    with pytest.raises(RecoveryUnsafe, match="already exists"):
        restore_recovery_key_backup(archive, target, recovery_private_key=private)
    assert target.read_bytes() == b"NEVER OVERWRITE"


def test_invalid_recovery_key_and_symlinked_source_fail_closed(tmp_path):
    _, public = keypair()
    ledger, bundle = tmp_path / "ledger.db", tmp_path / "backup.tgbak"
    synthetic_ledger(ledger)
    with pytest.raises(RecoveryUnsafe):
        create_recovery_key_backup(ledger, bundle, recovery_public_key=b"bad")
    assert not bundle.exists()
    symlink = tmp_path / "alias.db"
    try:
        symlink.symlink_to(ledger)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(RecoveryUnsafe):
        create_recovery_key_backup(symlink, bundle, recovery_public_key=public)
    assert not bundle.exists()
