"""An update artifact is never trusted merely because a caller says it is."""
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from gym.services.signed_release import ReleaseUnsafe, verify_offline_release


def _fixture(tmp_path: Path):
    artifact = tmp_path / "update.zip"
    artifact.write_bytes(b"INERT SYNTHETIC RELEASE - NOT EXECUTABLE")
    manifest = {
        "format": "tradinggym-offline-release-v1",
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "artifact_size": artifact.stat().st_size,
        "target_schema": 2,
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    signature = key.sign(raw)
    return artifact, raw, signature, public, key


def test_authenticated_staged_artifact_is_still_not_install_authority(tmp_path):
    artifact, raw, signature, public, _ = _fixture(tmp_path)
    report = verify_offline_release(
        artifact, manifest_bytes=raw, signature=signature,
        trusted_public_key=public, current_schema=1,
    )
    assert report["signature_verified"] is True
    assert report["artifact_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert report["target_schema"] == 2
    assert report["install_authorized"] is False
    assert report["funded_arming"] is False


def test_modifying_binary_after_manifest_is_rejected(tmp_path):
    artifact, raw, signature, public, _ = _fixture(tmp_path)
    artifact.write_bytes(b"TAMPERED")
    with pytest.raises(ReleaseUnsafe, match="digest|size"):
        verify_offline_release(artifact, manifest_bytes=raw,
            signature=signature, trusted_public_key=public, current_schema=1)


def test_other_signing_key_or_modified_manifest_is_rejected(tmp_path):
    artifact, raw, signature, public, _ = _fixture(tmp_path)
    stranger = Ed25519PrivateKey.generate()
    with pytest.raises(ReleaseUnsafe, match="signature"):
        verify_offline_release(artifact, manifest_bytes=raw,
            signature=stranger.sign(raw), trusted_public_key=public, current_schema=1)
    with pytest.raises(ReleaseUnsafe, match="signature|canonical"):
        verify_offline_release(artifact, manifest_bytes=raw + b" ",
            signature=signature, trusted_public_key=public, current_schema=1)


def test_signature_cannot_promote_downgrade_or_skip_migration(tmp_path):
    artifact, raw, _, public, key = _fixture(tmp_path)
    for target in [0, 1, 3, True]:
        manifest = json.loads(raw)
        manifest["target_schema"] = target
        modified = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        with pytest.raises(ReleaseUnsafe, match="forward"):
            verify_offline_release(artifact, manifest_bytes=modified,
                signature=key.sign(modified), trusted_public_key=public, current_schema=1)


def test_rejects_manifest_extra_fields_even_when_signed(tmp_path):
    artifact, raw, _, public, key = _fixture(tmp_path)
    manifest = json.loads(raw)
    manifest["remote_download_url"] = "https://untrusted.invalid/"
    modified = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ReleaseUnsafe, match="manifest"):
        verify_offline_release(artifact, manifest_bytes=modified,
            signature=key.sign(modified), trusted_public_key=public, current_schema=1)


def test_symlink_release_refused_even_with_valid_signature(tmp_path):
    artifact, raw, signature, public, _ = _fixture(tmp_path)
    link = tmp_path / "alias.zip"
    try:
        link.symlink_to(artifact)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ReleaseUnsafe, match="regular"):
        verify_offline_release(link, manifest_bytes=raw,
            signature=signature, trusted_public_key=public, current_schema=1)


def test_duplicate_manifest_keys_fail_closed(tmp_path):
    artifact, raw, _, public, key = _fixture(tmp_path)
    duplicate = raw[:-1] + b',"target_schema":2}'
    with pytest.raises(ReleaseUnsafe, match="duplicate"):
        verify_offline_release(artifact, manifest_bytes=duplicate,
            signature=key.sign(duplicate), trusted_public_key=public, current_schema=1)
