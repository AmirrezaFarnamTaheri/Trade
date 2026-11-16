"""Offline ledger inspection; never replaces a ledger or changes execution authority.

Use on a quiescent, independently decrypted staging copy, never on a live
Executor database. The returned hash is evidence, NOT proof of origin unless
it is checked against an independently authenticated manifest.
"""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote


class RestoreUnsafe(ValueError):
    """A candidate cannot be safely considered for a non-destructive restore."""


def inspect_ledger(source: Path | str) -> dict:
    path = Path(source)
    if path.is_symlink() or not path.is_file():
        raise RestoreUnsafe("source is not an independent regular ledger file")
    if Path(str(path) + "-wal").exists() or Path(str(path) + "-shm").exists():
        raise RestoreUnsafe("live SQLite WAL sidecar present; checkpoint a quiescent snapshot")
    previous = bytes(32)
    sequence = 0
    try:
        uri = "file:" + quote(str(path.resolve()), safe="/:") + "?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version != 1:
                raise RestoreUnsafe("unsupported or missing schema version")
            guards = dict(db.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND "
                "name IN ('ledger_events_no_update', 'ledger_events_no_delete')"))
            if len(guards) != 2 or not all(
                "RAISE(ABORT" in sql.upper() and "BEFORE " + action in sql.upper()
                for action, sql in (("UPDATE", guards.get("ledger_events_no_update", "")),
                                    ("DELETE", guards.get("ledger_events_no_delete", "")))
            ):
                raise RestoreUnsafe("immutable event guards missing or altered")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RestoreUnsafe("SQLite structural integrity check failed")
            for idx, raw, stored_prev, stored_hash in db.execute(
                "SELECT sequence,event_bytes,previous_hash,event_hash "
                "FROM ledger_events ORDER BY sequence"
            ):
                expected = sequence + 1
                if type(idx) is not int or idx != expected:
                    raise RestoreUnsafe("ledger sequence missing or out of order")
                if not isinstance(raw, bytes) or not 1 <= len(raw) <= 1_048_576:
                    raise RestoreUnsafe("invalid stored event bytes")
                if not isinstance(stored_prev, bytes) or len(stored_prev) != 32 or stored_prev != previous:
                    raise RestoreUnsafe("ledger previous hash mismatch")
                current = hashlib.sha256(
                    previous + len(raw).to_bytes(8, "big") + raw
                ).digest()
                if not isinstance(stored_hash, bytes) or stored_hash != current:
                    raise RestoreUnsafe("ledger event hash mismatch")
                previous = current
                sequence = idx
    except sqlite3.Error:
        raise RestoreUnsafe("unreadable or damaged SQLite candidate") from None
    digest = hashlib.sha256()
    with path.open("rb") as data:
        while block := data.read(1_048_576):
            digest.update(block)
    return {
        "schema_version": 1,
        "sequence": sequence,
        "head_hash": previous.hex(),
        "file_sha256": digest.hexdigest(),
        "encrypted": False,
        "trusted_origin": False,
    }


def check_restore_target(source: Path | str, destination: Path | str) -> dict:
    """Admission check ONLY. Never creates/replaces the destination."""
    src, dst = Path(source), Path(destination)
    if dst.exists() or dst.is_symlink():
        raise RestoreUnsafe("destination already exists; no overwrite is allowed")
    if src.parent.resolve() == dst.parent.resolve() and src.name == dst.name:
        raise RestoreUnsafe("source cannot be restored over itself")
    if (src.parent / "secrets.dat").exists():
        raise RestoreUnsafe("secrets.dat must never be present in a backup bundle")
    # The chosen destination and account credentials are NOT touched here.
    return inspect_ledger(src)


def _expected_digest(value: str) -> str:
    """Compare trusted out-of-band digests; do NOT authenticate them here."""
    if not isinstance(value, str) or len(value) != 64 or any(
        c not in "0123456789abcdefABCDEF" for c in value
    ):
        raise RestoreUnsafe("expected digest must be 64 hexadecimal characters")
    return value.lower()


def inspect_pinned_ledger(
    source: Path | str, *,
    expected_head_hash: str, expected_file_sha256: str,
) -> dict:
    """Reject any mismatch against independently authenticated external data.

    This does not authenticate the manifest, decrypt a backup, or install it.
    Calling code must separately establish the trusted provenance of the
    expected digests and ensure the staging copy cannot change during checks.
    """
    expected_head_hash = _expected_digest(expected_head_hash)
    expected_file_sha256 = _expected_digest(expected_file_sha256)
    report = inspect_ledger(source)
    if report["head_hash"] != expected_head_hash:
        raise RestoreUnsafe("expected ledger head hash does not match")
    if report["file_sha256"] != expected_file_sha256:
        raise RestoreUnsafe("expected backup file sha256 does not match")
    # Not an authenticated source: matching a caller-supplied digest is NOT
    # equivalent to verifying a trusted, signed or AEAD-protected manifest.
    return report


def check_pinned_restore_target(
    source: Path | str, destination: Path | str, *,
    expected_head_hash: str, expected_file_sha256: str,
) -> dict:
    """Evaluate only; never create, overwrite or rename an active ledger."""
    check_restore_target(source, destination)
    return inspect_pinned_ledger(
        source, expected_head_hash=expected_head_hash,
        expected_file_sha256=expected_file_sha256,
    )
