"""Maintenance command implementations; invocation stays in gym.cli."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC
from pathlib import Path

from ..domain.model import iso, parse_ts
from ..services.collector import now_utc
from .common import (
    open_db,
    store_root,
)


def raw_move_cmd(args) -> int:
    """Move whole, finished raw/YYYYMMDD day folders to another volume; never today's or a partial move."""
    from ..adapters.store import move_raw_days

    days = move_raw_days(store_root(args) / "raw", Path(args.to), args.before)
    print(f"moved {len(days)} day folder(s) to {args.to}")
    return 0


def verify_segments_cmd(args) -> int:
    from ..adapters.store import verify_segments

    db = open_db(args)
    try:
        report = verify_segments(db, [store_root(args) / "raw", *(Path(p) for p in args.archive)])
    finally:
        db.c.close()
    print(json.dumps(report, indent=2))
    return 1 if report["mismatched"] else 0


def doctor_cmd(args) -> int:
    """Run every local verifier read-only; exit 1 when any check fails."""
    from ..services.doctor import diagnose

    report = diagnose(store_root(args), now_utc(), full=args.full, archives=[Path(p) for p in args.archive])
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for c in report["checks"]:
            print(f"{c['status']:<4}  {c['check']:<18} {c['detail']}")
        print()
        print(f"{report['status']}: {report['root']}")
    return 1 if report["status"] == "FAIL" else 0


def compact_cmd(args) -> int:
    from ..adapters.store import compact_quotes

    db = open_db(args)
    try:
        before = parse_ts(args.before)
        removed = compact_quotes(db, before, args.bucket, now_utc())
        if args.vacuum:
            db.c.execute("VACUUM")
    finally:
        db.c.close()
    print(f"removed {removed} quote rows before {args.before} (kept the last per market and {args.bucket})")
    return 0


def backup_once_cmd(args) -> int:
    """Manual offline encrypted backup to a pre-existing independent volume.

    No passphrase in arguments, environment variables or command history.
    This is NOT scheduled remote backup, does not provision venue credentials,
    and cannot establish that another machine holds an archive.
    """
    import getpass

    from ..services.backup_rotation import backup_once

    if getattr(args, "stored_passphrase", False):
        from ..adapters.secret_store import load_backup_passphrase
        phrase = load_backup_passphrase()
    elif not sys.stdin.isatty():
        raise ValueError("backup-once requires an interactive protected console or --stored-passphrase")
    else:
        phrase = getpass.getpass("Offline ledger recovery passphrase (not a venue API key): ")
    try:
        report = backup_once(args.ledger, args.destination,
                             passphrase=phrase, keep=args.keep)
    finally:
        del phrase
    _backup_receipt(args, "BACKUP", report)
    # Never output a recovery passphrase, access token, or private API key.
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def restore_backup_cmd(args) -> int:
    """Restore an encrypted offline backup into a new ledger file (B3 second-machine restore).

    Passphrase only from an interactive console. Never overwrites; restored ledger
    is DISARMED evidence until the Executor reconciles it.
    """
    import getpass

    from ..services.encrypted_backup import restore_backup

    if not sys.stdin.isatty():
        raise ValueError("restore-backup requires an interactive protected console")
    phrase = getpass.getpass("Offline ledger recovery passphrase: ")
    try:
        report = restore_backup(args.bundle, args.destination, passphrase=phrase)
    finally:
        del phrase
    import platform
    from datetime import datetime
    report |= {"restored_at": iso(datetime.now(UTC)), "host": platform.node(), "mode_after": "DISARMED"}
    _backup_receipt(args, "RESTORE", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def restore_drill_cmd(args) -> int:
    """Prove the newest bundle restores: decrypt and verify into a temporary ledger, then remove it."""
    import getpass
    import tempfile

    from ..services.encrypted_backup import restore_backup

    bundles = sorted(Path(args.folder).glob("*.tgbak"), key=lambda p: p.stat().st_mtime)
    if not bundles:
        raise ValueError(f"no .tgbak bundles in {args.folder}")
    if args.stored_passphrase:
        from ..adapters.secret_store import load_backup_passphrase
        phrase = load_backup_passphrase()
    elif not sys.stdin.isatty():
        raise ValueError("restore-drill requires an interactive console or --stored-passphrase")
    else:
        phrase = getpass.getpass("Offline ledger recovery passphrase: ")
    with tempfile.TemporaryDirectory(prefix="gym-restore-drill-") as scratch:
        try:
            report = restore_backup(bundles[-1], Path(scratch) / "ledger.db", passphrase=phrase)
        finally:
            del phrase
    report |= {"bundle": str(bundles[-1]), "drill": True, "restored_copy": "deleted"}
    _backup_receipt(args, "RESTORE", report)  # a drill is a verified restore; the copy is gone
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


def _backup_receipt(args, kind, report):
    from ..services.backup_status import record
    try:
        record(store_root(args), kind, report)
        report["status_recorded"] = True
    except (ValueError, OSError, sqlite3.Error, KeyError, AttributeError):
        # A display receipt failure cannot undo the completed encrypted backup/restore.
        report["status_recorded"] = False
        report["status_error"] = "Operation completed; local display receipt unavailable. Do not repeat the operation automatically."


def update_check_cmd(args) -> int:
    """Admission check before an Executor update; exit 2 with the reason when unsafe."""
    from ..services.restore_gate import RestoreUnsafe, inspect_ledger
    from ..services.update_gate import assess_update

    try:
        ledger = inspect_ledger(args.ledger)
    except RestoreUnsafe as e:
        ledger = {"error": str(e)}
    report = assess_update(open_positions=args.open_positions, unknown_orders=args.unknown_orders,
                           alternative_protection=args.alternative_protection,
                           accepted_outage=args.accepted_outage,
                           ledger_integrity_ok="error" not in ledger)
    print(json.dumps(report | {"ledger": ledger}, ensure_ascii=False, indent=2))
    return 0


def verify_backup_manifest_cmd(args) -> int:
    """Verify ciphertext against an *independently pinned* public key.

    The public key is NOT fetched from the backup, manifest or network.
    This operation does not restore a ledger or establish off-machine custody.
    """
    from ..services import backup_manifest

    def read_regular(path_str: str, limit: int, label: str, exact: int | None = None) -> bytes:
        source = Path(path_str)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"{label} must be a regular unsymlinked file")
        if not 1 <= source.stat().st_size <= limit:
            raise ValueError(f"{label} exceeds size limit")
        # These bounded inputs are signatures and public metadata, never
        # private signing keys or recovery passphrases.
        raw = source.read_bytes()
        if len(raw) > limit or (exact is not None and len(raw) != exact):
            raise ValueError(f"{label} has an invalid length")
        return raw

    manifest = read_regular(args.manifest, 4096, "manifest")
    signature = read_regular(args.signature, 64, "signature", 64)
    public_key = read_regular(args.pinned_public_key, 32, "pinned public key", 32)
    report = backup_manifest.verify_signed_backup(
        Path(args.bundle), manifest_bytes=manifest, signature=signature,
        trusted_public_key=public_key,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0
