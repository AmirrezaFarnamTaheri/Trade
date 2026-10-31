"""Portable authenticated B3 backups; never includes secrets.dat.

Backups use a passphrase-derived key (scrypt) and AES-256-GCM. The encrypted
payload is a consistent SQLite backup created through SQLite's backup API.
Restore decrypts into a private staging file, verifies the AEAD tag, SQLite
integrity and the exact event hash chain, then publishes by a no-overwrite
same-volume hard link. This module does not install a ledger or provision keys.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import struct
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .restore_gate import RestoreUnsafe, inspect_ledger, inspect_pinned_ledger

_MAGIC = b"TGBKUP01"
_HEADER_LENGTH = struct.Struct(">I")
_TAG_BYTES = 16
_SALT_BYTES = 16
_NONCE_BYTES = 12
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_MAX_HEADER = 16 * 1024
_MAX_BUNDLE = 4 * 1024 * 1024 * 1024


class BackupUnsafe(ValueError):
    """A backup or restore operation is unsafe to start."""


class BackupAuthenticationError(ValueError):
    """Backup authentication, format or verified ledger integrity failed."""


def _passphrase_bytes(passphrase: str) -> bytes:
    if not isinstance(passphrase, str) or len(passphrase) < 12:
        raise BackupUnsafe("recovery passphrase must contain at least 12 characters")
    raw = passphrase.encode("utf-8")
    if len(raw) > 4096:
        raise BackupUnsafe("recovery passphrase is too long")
    return raw


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        _passphrase_bytes(passphrase), salt=salt, n=_SCRYPT_N,
        r=_SCRYPT_R, p=_SCRYPT_P, dklen=32, maxmem=128 * 1024 * 1024,
    )


def _regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise BackupUnsafe(f"{label} must be an independent regular file")


def _snapshot_database(source: Path, destination: Path) -> None:
    source_uri = "file:" + quote(str(source.resolve()), safe="/:") + "?mode=ro"
    src = sqlite3.connect(source_uri, uri=True, timeout=5)
    dst = sqlite3.connect(destination, timeout=5)
    try:
        src.backup(dst, pages=256, sleep=0.05)
        dst.commit()
    except sqlite3.Error:
        raise BackupUnsafe("SQLite could not produce a consistent backup snapshot") from None
    finally:
        dst.close()
        src.close()


def _header_bytes(manifest: dict) -> bytes:
    try:
        raw = json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("ascii")
    except (TypeError, ValueError):
        raise BackupUnsafe("invalid backup manifest") from None
    if not 1 <= len(raw) <= _MAX_HEADER:
        raise BackupUnsafe("backup manifest exceeds size limit")
    return raw


def create_backup(
    source: Path | str,
    destination: Path | str,
    *,
    passphrase: str,
) -> dict:
    """Create an exclusive, passphrase-encrypted backup of one SQLite ledger.

    Only the ledger database is snapshotted; adjacent secrets.dat and other
    files are never enumerated or copied. Existing bundles are never replaced.
    """
    source_path, output_path = Path(source), Path(destination)
    _regular_file(source_path, "ledger source")
    _passphrase_bytes(passphrase)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() or output_path.is_symlink():
        raise BackupUnsafe("backup destination already exists")
    salt, nonce = secrets.token_bytes(_SALT_BYTES), secrets.token_bytes(_NONCE_BYTES)
    fd = -1
    try:
        with tempfile.TemporaryDirectory(prefix="tg-backup-", dir=output_path.parent) as temp_dir:
            snapshot = Path(temp_dir) / "snapshot.db"
            _snapshot_database(source_path, snapshot)
            evidence = inspect_ledger(snapshot)
            size = snapshot.stat().st_size
            if size < 1 or size > _MAX_BUNDLE:
                raise BackupUnsafe("ledger snapshot exceeds backup size limit")
            manifest = {
                "format_version": 1,
                "cipher": "AES-256-GCM",
                "kdf": "scrypt",
                "scrypt_n": _SCRYPT_N,
                "scrypt_r": _SCRYPT_R,
                "scrypt_p": _SCRYPT_P,
                "salt": salt.hex(),
                "nonce": nonce.hex(),
                "schema_version": evidence["schema_version"],
                "sequence": evidence["sequence"],
                "head_hash": evidence["head_hash"],
                "file_sha256": evidence["file_sha256"],
                "file_size": size,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "contains_secrets_dat": False,
            }
            header = _header_bytes(manifest)
            prefix = _MAGIC + _HEADER_LENGTH.pack(len(header)) + header
            key = _derive_key(passphrase, salt)
            encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
            encryptor.authenticate_additional_data(prefix)
            fd = os.open(
                output_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            with os.fdopen(fd, "wb") as output:
                fd = -1
                output.write(prefix)
                with snapshot.open("rb") as plaintext:
                    while chunk := plaintext.read(1024 * 1024):
                        output.write(encryptor.update(chunk))
                output.write(encryptor.finalize())
                output.write(encryptor.tag)
                output.flush()
                os.fsync(output.fileno())
            return {
                "encrypted": True,
                "authenticated": True,
                "trusted_origin": "passphrase_authenticated",
                "schema_version": evidence["schema_version"],
                "sequence": evidence["sequence"],
                "head_hash": evidence["head_hash"],
                "file_sha256": evidence["file_sha256"],
                "file_size": size,
            }
    except FileExistsError:
        raise BackupUnsafe("backup destination already exists") from None
    except Exception:
        if fd >= 0:
            os.close(fd)
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _read_manifest(bundle: Path) -> tuple[dict, bytes, int, int]:
    _regular_file(bundle, "backup bundle")
    size = bundle.stat().st_size
    if size < len(_MAGIC) + 4 + _TAG_BYTES or size > _MAX_BUNDLE + _MAX_HEADER + 64:
        raise BackupAuthenticationError("backup size is invalid")
    with bundle.open("rb") as stream:
        if stream.read(len(_MAGIC)) != _MAGIC:
            raise BackupAuthenticationError("unknown backup format")
        raw_length = stream.read(4)
        if len(raw_length) != 4:
            raise BackupAuthenticationError("truncated backup header")
        header_length = _HEADER_LENGTH.unpack(raw_length)[0]
        if not 1 <= header_length <= _MAX_HEADER:
            raise BackupAuthenticationError("backup header length is invalid")
        header = stream.read(header_length)
        if len(header) != header_length:
            raise BackupAuthenticationError("truncated backup manifest")
    try:
        manifest = json.loads(header.decode("ascii"))
        if not isinstance(manifest, dict):
            raise ValueError
        expected_keys = {
            "format_version", "cipher", "kdf", "scrypt_n", "scrypt_r", "scrypt_p",
            "salt", "nonce", "schema_version", "sequence", "head_hash",
            "file_sha256", "file_size", "created_at", "contains_secrets_dat",
        }
        if set(manifest) != expected_keys:
            raise ValueError
        if (manifest["format_version"] != 1 or manifest["cipher"] != "AES-256-GCM"
            or manifest["kdf"] != "scrypt" or manifest["scrypt_n"] != _SCRYPT_N
            or manifest["scrypt_r"] != _SCRYPT_R or manifest["scrypt_p"] != _SCRYPT_P
            or manifest["contains_secrets_dat"] is not False):
            raise ValueError
        salt, nonce = bytes.fromhex(manifest["salt"]), bytes.fromhex(manifest["nonce"])
        if len(salt) != _SALT_BYTES or len(nonce) != _NONCE_BYTES:
            raise ValueError
        for name in ("head_hash", "file_sha256"):
            value = manifest[name]
            if not isinstance(value, str) or len(value) != 64 or any(
                c not in "0123456789abcdef" for c in value
            ):
                raise ValueError
        if type(manifest["sequence"]) is not int or manifest["sequence"] < 0:
            raise ValueError
        if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
            raise ValueError
        if type(manifest["file_size"]) is not int or not 1 <= manifest["file_size"] <= _MAX_BUNDLE:
            raise ValueError
        header_end = len(_MAGIC) + 4 + header_length
        ciphertext_length = size - header_end - _TAG_BYTES
        if ciphertext_length != manifest["file_size"]:
            raise ValueError
        return manifest, _MAGIC + raw_length + header, header_end, ciphertext_length
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise BackupAuthenticationError("backup manifest is malformed or unsupported") from None


def restore_backup(
    bundle_path: Path | str,
    destination: Path | str,
    *,
    passphrase: str,
) -> dict:
    """Authenticate/decrypt to a private stage, verify chain, then publish no-overwrite."""
    bundle, target = Path(bundle_path), Path(destination)
    _passphrase_bytes(passphrase)
    _regular_file(bundle, "backup bundle")
    if target.exists() or target.is_symlink():
        raise BackupUnsafe("restore destination already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise BackupUnsafe("restore destination already exists")
    manifest, aad, offset, ciphertext_length = _read_manifest(bundle)
    salt, nonce = bytes.fromhex(manifest["salt"]), bytes.fromhex(manifest["nonce"])
    key = _derive_key(passphrase, salt)
    with bundle.open("rb") as stream:
        stream.seek(-_TAG_BYTES, os.SEEK_END)
        tag = stream.read(_TAG_BYTES)
        stream.seek(offset)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(aad)
        fd, temp_name = tempfile.mkstemp(prefix=".tg-restore-", suffix=".db", dir=target.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as output:
                remaining = ciphertext_length
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise BackupAuthenticationError("backup ciphertext is truncated")
                    remaining -= len(chunk)
                    output.write(decryptor.update(chunk))
                try:
                    output.write(decryptor.finalize())
                except InvalidTag:
                    raise BackupAuthenticationError("wrong passphrase or modified backup") from None
                output.flush()
                os.fsync(output.fileno())
            try:
                evidence = inspect_pinned_ledger(
                    temp,
                    expected_head_hash=manifest["head_hash"],
                    expected_file_sha256=manifest["file_sha256"],
                )
            except RestoreUnsafe:
                raise BackupAuthenticationError("decrypted ledger failed integrity verification") from None
            if evidence["sequence"] != manifest["sequence"]:
                raise BackupAuthenticationError("backup event sequence does not match manifest")
            # Same-directory hard link is atomic and fails if target exists.
            try:
                os.link(temp, target)
            except FileExistsError:
                raise BackupUnsafe("restore destination already exists") from None
            except OSError:
                raise BackupUnsafe("filesystem cannot publish a no-overwrite restore") from None
            return {
                "encrypted": True,
                "authenticated": True,
                "trusted_origin": "passphrase_authenticated",
                "schema_version": evidence["schema_version"],
                "sequence": evidence["sequence"],
                "head_hash": evidence["head_hash"],
                "file_sha256": evidence["file_sha256"],
                "destination": str(target),
            }
        except InvalidTag:
            raise BackupAuthenticationError("wrong passphrase or modified backup") from None
        finally:
            temp.unlink(missing_ok=True)
