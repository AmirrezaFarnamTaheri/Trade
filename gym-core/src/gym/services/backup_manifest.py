"""Offline, operator-pinned signed encrypted-backup manifest (not remote proof).

An independent signing device may sign prepare_backup_manifest() output.
The PRIVATE SIGNING KEY must never be held by this module, a gym-core daemon
or the Executor. verify_signed_backup() only checks a pinned public key and
exact ciphertext bytes. It never decrypts, installs, transfers, or authorizes
an order; off_machine_verified is *always false* until independent evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .encrypted_backup import BackupAuthenticationError, _read_manifest

_FIELDS = frozenset({
    "format", "bundle_name", "bundle_sha256", "bundle_size", "schema_version",
    "sequence", "head_hash", "file_sha256", "created_at",
})
_NAME = re.compile(r"tradinggym-exec-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}\.tgbak\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SIGNED_MANIFEST = 4096
_MAX_CIPHERTEXT = 4 * 1024 * 1024 * 1024 + 65536
_FORMAT = "tradinggym-signed-encrypted-backup-v1"


class BackupManifestUnsafe(ValueError):
    """A signed backup manifest could not establish trustworthy local bytes."""


def _regular_bundle(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or not _NAME.fullmatch(path.name):
        raise BackupManifestUnsafe("bundle must be an unlinked regular named archive")


def _hash_bundle(path: Path) -> tuple[str, int]:
    _regular_bundle(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise BackupManifestUnsafe("cannot securely open encrypted bundle") from None
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= _MAX_CIPHERTEXT:
            raise BackupManifestUnsafe("bundle size or type is unsafe")
        digest = hashlib.sha256()
        with os.fdopen(os.dup(fd), "rb") as stream:
            while part := stream.read(1024 * 1024):
                digest.update(part)
        after = os.fstat(fd)
        if (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
        ) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
        ):
            raise BackupManifestUnsafe("encrypted bundle changed during inspection")
        return digest.hexdigest(), before.st_size
    finally:
        os.close(fd)


def _header(path: Path) -> dict:
    try:
        header, _, _, _ = _read_manifest(path)
    except (BackupAuthenticationError, OSError, ValueError):
        raise BackupManifestUnsafe("invalid encrypted bundle header") from None
    return header


def _validate(obj: dict) -> dict:
    if not isinstance(obj, dict) or set(obj) != _FIELDS or obj.get("format") != _FORMAT:
        raise BackupManifestUnsafe("unsupported signed manifest")
    if not isinstance(obj.get("bundle_name"), str) or not _NAME.fullmatch(obj["bundle_name"]):
        raise BackupManifestUnsafe("unsafe bundle name in manifest")
    for key in ("bundle_sha256", "head_hash", "file_sha256"):
        if not isinstance(obj.get(key), str) or not _SHA.fullmatch(obj[key]):
            raise BackupManifestUnsafe("invalid signed manifest digest")
    if type(obj.get("schema_version")) is not int or obj["schema_version"] != 1:
        raise BackupManifestUnsafe("invalid signed manifest schema")
    if type(obj.get("sequence")) is not int or obj["sequence"] < 0:
        raise BackupManifestUnsafe("invalid signed manifest sequence")
    if type(obj.get("bundle_size")) is not int or not 1 <= obj["bundle_size"] <= _MAX_CIPHERTEXT:
        raise BackupManifestUnsafe("invalid signed manifest size")
    stamp = obj.get("created_at")
    if not isinstance(stamp, str) or len(stamp) > 40 or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00", stamp
    ):
        raise BackupManifestUnsafe("invalid signed manifest timestamp")
    return obj


def _canonical(obj: dict) -> bytes:
    data = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")
    if not 1 <= len(data) <= _MAX_SIGNED_MANIFEST:
        raise BackupManifestUnsafe("signed manifest exceeds size bound")
    return data


def _decoded(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= _MAX_SIGNED_MANIFEST:
        raise BackupManifestUnsafe("signed manifest must be bounded bytes")

    def no_duplicate(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BackupManifestUnsafe("duplicate manifest key")
            result[key] = value
        return result

    try:
        obj = json.loads(raw.decode("ascii"), object_pairs_hook=no_duplicate)
    except BackupManifestUnsafe:
        raise
    except (ValueError, UnicodeDecodeError, TypeError):
        raise BackupManifestUnsafe("invalid signed manifest") from None
    _validate(obj)
    if _canonical(obj) != raw:
        raise BackupManifestUnsafe("noncanonical signed manifest")
    return obj


def _compare_header(obj: dict, header: dict) -> None:
    for key in ("schema_version", "sequence", "head_hash", "file_sha256", "created_at"):
        if obj[key] != header[key]:
            raise BackupManifestUnsafe("bundle header differs from signed manifest")


def prepare_backup_manifest(bundle_path: Path | str, receipt: dict) -> bytes:
    """Prepare canonical bytes only after local authenticated restore.

    A separate, trusted operator signing key (NOT stored here) signs these
    exact bytes after independent review. The receipt flag is not a remote
    attestation; it cannot by itself establish genuine off-machine custody.
    """
    bundle = Path(bundle_path)
    if not isinstance(receipt, dict) or (
        receipt.get("encrypted") is not True or
        receipt.get("authenticated") is not True or
        receipt.get("verified_restore") is not True
    ):
        raise BackupManifestUnsafe("verified local restore required before manifest creation")
    if receipt.get("off_machine_verified") is True or receipt.get("trusted_origin") is True:
        raise BackupManifestUnsafe("off-machine provenance cannot be asserted by local tool")
    if receipt.get("bundle") != str(bundle):
        raise BackupManifestUnsafe("receipt bundle identity mismatch")
    digest, size = _hash_bundle(bundle)
    header = _header(bundle)
    for key in ("schema_version", "sequence", "head_hash", "file_sha256"):
        if receipt.get(key) != header.get(key):
            raise BackupManifestUnsafe("verified local receipt differs from bundle header")
    record = {
        "format": _FORMAT, "bundle_name": bundle.name,
        "bundle_sha256": digest, "bundle_size": size,
        **{k: header[k] for k in (
            "schema_version", "sequence", "head_hash", "file_sha256", "created_at"
        )},
    }
    return _canonical(_validate(record))


def verify_signed_backup(
    bundle_path: Path | str, *, manifest_bytes: bytes, signature: bytes,
    trusted_public_key: bytes,
) -> dict:
    """Read-only signature + ciphertext integrity; not restoration or remote proof."""
    record = _decoded(manifest_bytes)
    if not isinstance(signature, bytes) or len(signature) != 64 or (
        not isinstance(trusted_public_key, bytes) or len(trusted_public_key) != 32
    ):
        raise BackupManifestUnsafe("missing pinned backup signature/public key")
    try:
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(
            signature, manifest_bytes
        )
    except (InvalidSignature, ValueError):
        raise BackupManifestUnsafe("signed backup signature could not be verified") from None
    bundle = Path(bundle_path)
    if bundle.name != record["bundle_name"]:
        raise BackupManifestUnsafe("signed bundle name mismatch")
    digest, size = _hash_bundle(bundle)
    if digest != record["bundle_sha256"] or size != record["bundle_size"]:
        raise BackupManifestUnsafe("signed encrypted bundle digest or size mismatch")
    _compare_header(record, _header(bundle))
    return {
        "signature_verified": True,
        "encrypted_bundle_verified": True,
        "head_hash": record["head_hash"],
        "sequence": record["sequence"],
        "schema_version": record["schema_version"],
        "off_machine_verified": False,
        "trusted_origin": False,
        "money_authority": False,
        "install_authorized": False,
    }
