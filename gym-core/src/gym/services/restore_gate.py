"""B3 OFFLINE restore inspection only: NO write path, no backup encryption.

Use on a quiescent, independently decrypted staging copy, never on a live
Executor database. The returned hash is evidence, NOT proof of origin unless
it is checked against an authenticated off-machine manifest.
"""
from __future__ import annotations

import hashlib
import sqlite3
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
        with sqlite3.connect(uri, uri=True, timeout=1) as db:
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
    except sqlite3.Error as exc:
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
    # Encryption/authenticated manifest and off-machine restore remain gates.
    return inspect_ledger(src)


def assess_migration_staging(state: dict) -> dict:
    """Pure B3 STAGING refusal policy; never invokes an updater.

    All asserted facts must be verified by a privileged release controller
    and linked to fresh evidence. A caller-supplied dictionary is NOT proof
    of these claims and cannot authorize installation, keys or funded arming.
    """
    if not isinstance(state, dict):
        raise RestoreUnsafe("missing update preflight facts")
    for name in ("active_funded_authority", "ledger_integrity_verified",
                 "off_machine_restore_proven", "migration_rehearsed"):
        if type(state.get(name)) is not bool:
            raise RestoreUnsafe("missing or malformed update preflight evidence")
    for name in ("unresolved_orders", "current_schema", "target_schema"):
        if type(state.get(name)) is not int:
            raise RestoreUnsafe("missing or malformed schema/order fact")
    if state["unresolved_orders"] < 0 or state["current_schema"] < 1:
        raise RestoreUnsafe("invalid outstanding order/schema state")
    if state["active_funded_authority"] or state["unresolved_orders"] > 0:
        raise RestoreUnsafe("unsafe update while trading authority or orders remain")
    if not all(state[key] for key in (
        "ledger_integrity_verified", "off_machine_restore_proven", "migration_rehearsed"
    )):
        raise RestoreUnsafe("staged update lacks verified migration or recovery evidence")
    if state["target_schema"] != state["current_schema"] + 1:
        raise RestoreUnsafe("only single forward schema migration is permitted")
    return {
        "allow_staged_update": True,
        "install_authorized": False,
        "funded_arming": False,
    }
