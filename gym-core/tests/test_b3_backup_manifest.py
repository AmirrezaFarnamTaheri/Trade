"""B3 independently pinned backup manifest: cryptographic identity != remote proof."""
import hashlib
import json
import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from gym.services.backup_manifest import (
    BackupManifestUnsafe, prepare_backup_manifest, verify_signed_backup,
)
from gym.services.encrypted_backup import create_backup, restore_backup


@pytest.fixture(scope="module")
def example(tmp_path_factory):
    root = tmp_path_factory.mktemp("b3-signed-backup")
    ledger = root / "ledger.db"
    schema = (root.parents[2] / "executor/exec-store/schema.sql")
    # The file may be generated outside repo in CI; use current checkout root.
    from pathlib import Path
    schema = Path(__file__).resolve().parents[2] / "executor" / "exec-store" / "schema.sql"
    with sqlite3.connect(ledger) as conn:
        conn.executescript(schema.read_text())
        raw = b"offline-b3-evidence-only"
        first = hashlib.sha256(bytes(32) + len(raw).to_bytes(8, "big") + raw).digest()
        conn.execute(
            "INSERT INTO ledger_events(sequence,event_bytes,previous_hash,event_hash) VALUES(?,?,?,?)",
            (1, raw, bytes(32), first),
        )
        conn.commit()
    bundle = root / "tradinggym-exec-20261101T120000Z-0123456789abcdef.tgbak"
    create_backup(ledger, bundle, passphrase="synthetic public test passphrase 1234")
    verified = restore_backup(
        bundle, root / "restored.db", passphrase="synthetic public test passphrase 1234"
    )
    receipt = {
        **verified, "bundle": str(bundle), "verified_restore": True,
    }
    manifest = prepare_backup_manifest(bundle, receipt)
    signer = Ed25519PrivateKey.generate()
    signature = signer.sign(manifest)
    public = signer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return bundle, manifest, signature, public, signer, receipt, root


def verify(bundle, manifest, signature, public):
    return verify_signed_backup(
        bundle, manifest_bytes=manifest, signature=signature,
        trusted_public_key=public,
    )


def test_signed_ciphertext_can_be_verified_without_decryption_or_authority(example):
    bundle, manifest, signature, public, _, _, _ = example
    assert json.loads(manifest)["bundle_sha256"] == hashlib.sha256(bundle.read_bytes()).hexdigest()
    result = verify(bundle, manifest, signature, public)
    assert result["signature_verified"] is True
    assert result["encrypted_bundle_verified"] is True
    assert result["off_machine_verified"] is False
    assert result["money_authority"] is False
    assert result["install_authorized"] is False
    assert "passphrase" not in json.dumps(result).lower()


def test_signed_manifest_requires_a_verified_ledger_restore(example):
    bundle, _, _, _, _, receipt, _ = example
    for modified in [
        {**receipt, "verified_restore": False},
        {**receipt, "head_hash": "0" * 64},
        {**receipt, "sequence": receipt["sequence"] + 1},
        {**receipt, "bundle": "../../other.tgbak"},
    ]:
        with pytest.raises(BackupManifestUnsafe):
            prepare_backup_manifest(bundle, modified)


def test_different_signer_or_modified_manifest_rejected(example):
    bundle, manifest, signature, public, _, _, _ = example
    foreign = Ed25519PrivateKey.generate()
    with pytest.raises(BackupManifestUnsafe, match="signature"):
        verify(bundle, manifest, foreign.sign(manifest), public)
    with pytest.raises(BackupManifestUnsafe, match="signature|manifest"):
        verify(bundle, manifest + b" ", signature, public)


def test_ciphertext_replacement_and_symlink_refused(example):
    bundle, manifest, signature, public, _, _, root = example
    replaced = root / "replaced.tgbak"
    replaced.write_bytes(bundle.read_bytes() + b"tampering")
    with pytest.raises(BackupManifestUnsafe, match="bundle|digest|size"):
        verify(replaced, manifest, signature, public)
    alias = root / "alias.tgbak"
    try:
        alias.symlink_to(bundle)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(BackupManifestUnsafe, match="regular|link"):
        verify(alias, manifest, signature, public)


def test_canonical_manifest_and_duplicate_keys_required(example):
    bundle, manifest, _, public, signer, _, _ = example
    modified = manifest[:-1] + b',"bundle_sha256":"0"}'
    with pytest.raises(BackupManifestUnsafe, match="duplicate"):
        verify(bundle, modified, signer.sign(modified), public)
    modified = manifest.replace(b',"schema_version":1', b',"schema_version":true')
    if modified != manifest:
        with pytest.raises(BackupManifestUnsafe, match="manifest|schema"):
            verify(bundle, modified, signer.sign(modified), public)


def test_no_synthetic_receipt_can_claim_off_machine_delivery(example):
    bundle, _, _, _, _, receipt, _ = example
    forged = {**receipt, "off_machine_verified": True, "trusted_origin": True}
    with pytest.raises(BackupManifestUnsafe, match="off.machine|provenance"):
        prepare_backup_manifest(bundle, forged)
