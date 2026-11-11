"""Executor update manifests: signed with gymctl, verified natively by the elevated PowerShell session."""
import os
import subprocess
from pathlib import Path

import pytest

from gym.services.release_signing import keygen, sign, verify

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/windows/ManifestSignature.ps1"
PHRASE = "a long signing passphrase"


def powershell_verifies(manifest, signature, public):
    command = f". '{SCRIPT}'; if (Test-ManifestSignature '{manifest}' '{signature}' '{public}') {{ 'VALID' }} else {{ 'INVALID' }}"
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip() == "VALID"


def test_sign_and_verify_in_python_and_native_powershell(tmp_path):
    private, public = tmp_path / "update.key", tmp_path / "update.pub"
    keygen(private, public, PHRASE)
    assert b"ENCRYPTED" in private.read_bytes()  # the private key is never stored in the clear
    manifest = tmp_path / "bundle.sha256"
    manifest.write_bytes(("a" * 64 + "  gym-executor.exe\n").encode())
    signature = sign(manifest, private, PHRASE)
    assert verify(manifest, signature, public)
    tampered = tmp_path / "tampered.sha256"
    tampered.write_bytes(("b" * 64 + "  gym-executor.exe\n").encode())
    assert not verify(tampered, signature, public)
    other_private, other_public = tmp_path / "other.key", tmp_path / "other.pub"
    keygen(other_private, other_public, PHRASE)
    assert not verify(manifest, signature, other_public)
    with pytest.raises(ValueError, match="already exists"):
        keygen(private, tmp_path / "x.pub", PHRASE)
    if os.name == "nt":
        assert powershell_verifies(manifest, signature, public)
        assert not powershell_verifies(tampered, signature, public)
        assert not powershell_verifies(manifest, signature, other_public)


def test_helpers_are_refused_when_they_differ_from_the_kept_bundle_manifest(tmp_path):
    import hashlib

    from gym.adapters.service_account_read import ReadUncertain, _check_bundle
    helper = tmp_path / "gym-review.exe"
    helper.write_bytes(b"MZ genuine helper")
    _check_bundle(helper)  # no kept manifest: older installs rely on the folder ACL
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    (tmp_path / "bundle.sha256").write_text(f"{digest}  gym-review.exe\n{'0' * 64}  gym-executor.exe\n", "ascii")
    _check_bundle(helper)
    helper.write_bytes(b"MZ decoy")
    with pytest.raises(ReadUncertain, match="does not match"):
        _check_bundle(helper)
    other = tmp_path / "gym-account-read.exe"
    other.write_bytes(b"MZ unlisted")
    with pytest.raises(ReadUncertain, match="does not match"):
        _check_bundle(other)
