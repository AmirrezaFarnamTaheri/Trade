"""Offline B3 encrypted backup rotation, requiring an independently mounted volume.

This is a single bounded maintenance *invocation*, intended for a future
service-owned scheduler. A distinct filesystem device is necessary but NOT
proof of an off-machine copy, credential isolation or trusted origin.
No scheduler, funded credentials, or remote network access exists here.
"""
from __future__ import annotations

import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .encrypted_backup import BackupUnsafe, create_backup, restore_backup

_BUNDLE_NAME = re.compile(r"^tradinggym-exec-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}\.tgbak$")


def _independent_volume(source: Path, folder: Path) -> bool:
    """Separate volumes are necessary, but do not establish remote provenance."""
    src_dev, dst_dev = source.stat().st_dev, folder.stat().st_dev
    return bool(src_dev and dst_dev and src_dev != dst_dev)


def backup_once(
    ledger_path: Path | str,
    backup_folder: Path | str,
    *,
    passphrase: str,
    keep: int = 7,
) -> dict:
    """Back up, authenticate/decrypt a scratch restore, THEN rotate.

    Never creates a destination directory or overwrites an existing archive.
    Deletes only regular, explicitly named archives in the chosen directory,
    after the new archive was independently restored and verified. Secrets and
    backup passphrases are never logged or stored.
    """
    source, folder = Path(ledger_path), Path(backup_folder)
    if type(keep) is not int or not 2 <= keep <= 365:
        raise BackupUnsafe("retention must retain between 2 and 365 bundles")
    if source.is_symlink() or not source.is_file():
        raise BackupUnsafe("source must be a regular unsymlinked ledger")
    if folder.is_symlink() or not folder.is_dir():
        raise BackupUnsafe("backup folder must be a pre-existing unsymlinked directory")
    if not _independent_volume(source, folder):
        raise BackupUnsafe("backup folder must reside on an independent volume")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle = folder / f"tradinggym-exec-{stamp}-{secrets.token_hex(8)}.tgbak"
    receipt = create_backup(source, bundle, passphrase=passphrase)

    # Cross-platform, encrypted-backup round trip. No active Ledger is ever
    # overwritten, and the archive is retained for investigation on failure.
    with tempfile.TemporaryDirectory(prefix=".tg-backup-check-", dir=folder) as scratch:
        restored = restore_backup(
            bundle, Path(scratch) / "restored.db", passphrase=passphrase,
        )
        for name in ("sequence", "head_hash", "file_sha256", "schema_version"):
            if receipt[name] != restored[name]:
                raise BackupUnsafe("roundtrip restore does not match encrypted backup receipt")

    candidates = []
    for candidate in folder.iterdir():
        if not _BUNDLE_NAME.fullmatch(candidate.name):
            continue
        if candidate.is_symlink() or not candidate.is_file():
            raise BackupUnsafe("unsafe matching backup file detected; refuse retention cleanup")
        candidates.append(candidate)
    # Keep newest N, using a stable name tiebreaker for same-second runs.
    candidates.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    removed = 0
    for old in candidates[keep:]:
        if old == bundle:
            raise BackupUnsafe("refusing to delete the newly verified bundle")
        old.unlink()  # No directory traversal; a symlink has already failed the check.
        removed += 1
    return {
        **receipt,
        "bundle": str(bundle),
        "verified_restore": True,
        "independent_volume": True,
        "off_machine_verified": False,
        "trusted_origin": False,
        "retention_keep": keep,
        "deleted_old_bundles": removed,
    }
