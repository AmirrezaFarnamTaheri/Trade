"""B3 signed *offline* release evidence only; no installer, download or authority.

The trusted Ed25519 public key must come from an operator-authenticated,
privileged out-of-band source, never the artifact or manifest itself.
Verification alone MUST NOT authorize installation or funded trading.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_FORMAT = "tradinggym-offline-release-v1"
_FIELDS = {"format", "artifact_sha256", "artifact_size", "target_schema"}
_MAX_BYTES = 2 * 1024 * 1024 * 1024


class ReleaseUnsafe(ValueError):
    """A release artifact is not eligible for offline staged review."""


def _unique_object(items: list[tuple[str, Any]]) -> dict:
    out = {}
    for key, value in items:
        if key in out:
            raise ReleaseUnsafe("duplicate manifest fields are prohibited")
        out[key] = value
    return out


def _read_manifest(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not (1 <= len(raw) <= 4096):
        raise ReleaseUnsafe("manifest must be bounded UTF-8 bytes")
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except ReleaseUnsafe:
        raise
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise ReleaseUnsafe("invalid manifest") from exc
    if not isinstance(obj, dict) or set(obj) != _FIELDS:
        raise ReleaseUnsafe("unsupported manifest fields")
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    if canonical != raw:
        raise ReleaseUnsafe("noncanonical signed manifest")
    if obj.get("format") != _FORMAT:
        raise ReleaseUnsafe("unrecognized manifest format")
    if type(obj.get("artifact_size")) is not int or not 1 <= obj["artifact_size"] <= _MAX_BYTES:
        raise ReleaseUnsafe("invalid artifact size")
    if type(obj.get("target_schema")) is not int:
        raise ReleaseUnsafe("invalid forward-only schema version")
    digest = obj.get("artifact_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(
        char not in "0123456789abcdef" for char in digest
    ):
        raise ReleaseUnsafe("invalid artifact digest")
    return obj


def verify_offline_release(
    artifact: Path | str, *, manifest_bytes: bytes,
    signature: bytes, trusted_public_key: bytes, current_schema: int,
) -> dict:
    """Check signed manifest and full file digest from a pinned open handle.

    This method does not inspect system/ledger state, install software, migrate
    databases, verify operating-system principals, or grant trade authority.
    """
    manifest = _read_manifest(manifest_bytes)
    if type(current_schema) is not int or current_schema < 1 or (
        manifest["target_schema"] != current_schema + 1
    ):
        raise ReleaseUnsafe("only one forward schema step is permitted")
    if not isinstance(signature, bytes) or len(signature) != 64 or (
        not isinstance(trusted_public_key, bytes) or len(trusted_public_key) != 32
    ):
        raise ReleaseUnsafe("missing trusted signature or pinned public key")
    try:
        key = Ed25519PublicKey.from_public_bytes(trusted_public_key)
        key.verify(signature, manifest_bytes)
    except (InvalidSignature, ValueError) as exc:
        raise ReleaseUnsafe("release signature did not verify") from exc

    path = Path(artifact)
    if path.is_symlink() or not path.is_file():
        raise ReleaseUnsafe("artifact must be an unsymlinked regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        handle = os.open(path, flags)
    except OSError as exc:
        raise ReleaseUnsafe("cannot securely open release artifact") from exc
    try:
        before = os.fstat(handle)
        if not stat.S_ISREG(before.st_mode):
            raise ReleaseUnsafe("artifact is not a regular file")
        if before.st_size != manifest["artifact_size"]:
            raise ReleaseUnsafe("artifact size mismatch")
        actual = hashlib.sha256()
        with os.fdopen(os.dup(handle), "rb", closefd=True) as reader:
            while chunk := reader.read(1024 * 1024):
                actual.update(chunk)
        after = os.fstat(handle)
        if (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns) != (
            after.st_ino, after.st_dev, after.st_size, after.st_mtime_ns
        ):
            raise ReleaseUnsafe("artifact changed during inspection")
        if actual.hexdigest() != manifest["artifact_sha256"]:
            raise ReleaseUnsafe("release artifact digest mismatch")
    finally:
        os.close(handle)
    return {
        "format": _FORMAT,
        "target_schema": manifest["target_schema"],
        "artifact_sha256": actual.hexdigest(),
        "signature_verified": True,
        "install_authorized": False,
        "funded_arming": False,
    }
