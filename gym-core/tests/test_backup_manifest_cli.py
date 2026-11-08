"""Off-machine operator can verify signed ciphertext without a private key."""
import json
from pathlib import Path

from gym.cli import main
from gym.services import backup_manifest


def prepare(tmp_path):
    parts = [tmp_path / name for name in
             ("bundle.tgbak", "manifest.json", "manifest.sig", "pinned-public-key.bin")]
    parts[0].write_bytes(b"FAKE-BUNDLE")
    parts[1].write_bytes(b'{"version":1}')
    parts[2].write_bytes(b"x" * 64)
    parts[3].write_bytes(b"k" * 32)
    return parts


def test_verify_backup_manifest_command_is_read_only_and_reports_no_offmachine_proof(
    tmp_path, monkeypatch, capsys,
):
    bundle, manifest, signature, public = prepare(tmp_path)
    seen = []

    def checked(path, **kwargs):
        seen.append((path, kwargs))
        return {
            "signature_verified": True, "encrypted_bundle_verified": True,
            "off_machine_verified": False, "trusted_origin": False,
            "money_authority": False, "install_authorized": False,
        }

    monkeypatch.setattr(backup_manifest, "verify_signed_backup", checked)
    assert main(["verify-backup-manifest",
                 str(bundle), str(manifest), str(signature), str(public)]) == 0
    assert seen[0][0] == Path(bundle)
    assert seen[0][1]["manifest_bytes"] == b'{"version":1}'
    assert seen[0][1]["signature"] == b"x" * 64
    assert seen[0][1]["trusted_public_key"] == b"k" * 32
    output = json.loads(capsys.readouterr().out)
    assert output["off_machine_verified"] is False
    assert output["install_authorized"] is False


def test_refuses_missing_or_oversized_pinned_key_without_verifying(tmp_path, monkeypatch, capsys):
    bundle, manifest, signature, public = prepare(tmp_path)
    monkeypatch.setattr(backup_manifest, "verify_signed_backup",
                        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not reach verifier")))
    public.write_bytes(b"k" * 33)
    assert main(["verify-backup-manifest",
                 str(bundle), str(manifest), str(signature), str(public)]) == 2
    assert "public" in capsys.readouterr().err.lower()
    public.unlink()
    assert main(["verify-backup-manifest",
                 str(bundle), str(manifest), str(signature), str(public)]) == 2


def test_refuses_symlinked_signature_before_open(tmp_path, capsys):
    bundle, manifest, signature, public = prepare(tmp_path)
    alias = tmp_path / "alias.sig"
    try:
        alias.symlink_to(signature)
    except (NotImplementedError, OSError):
        return
    assert main(["verify-backup-manifest",
                 str(bundle), str(manifest), str(alias), str(public)]) == 2
    assert "regular" in capsys.readouterr().err.lower()
