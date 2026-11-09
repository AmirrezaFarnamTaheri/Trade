"""Encrypted backup of the research store: SQLite databases, other files and the raw archive.

The executor ledger has its own backup (`encrypted_backup`). This one covers what the research evidence rests
on: market.db and the other stores in the data root, saved runs and studies, and every closed raw segment.

Layout under the destination folder:

    snapshots/<UTC stamp>/<name>.tgfile   one consistent SQLite snapshot per database, zstd then AES-256-GCM
    snapshots/<UTC stamp>/files.tar.tgfile  every other file in the data root (runs, studies, journals)
    snapshots/<UTC stamp>/MANIFEST.json   names, plaintext SHA-256 and sizes; no secrets
    segments/<YYYYMMDD>/<file>.tgfile     each closed raw segment, encrypted once and never rewritten

Each container authenticates its own header (name, kind, plaintext hash), so a renamed or swapped file fails.
Nothing here deletes source data; retention prunes only old snapshot folders this module created.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import struct
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import zstandard as zstd
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .encrypted_backup import (
    BackupAuthenticationError,
    BackupUnsafe,
    _derive_key,
    _passphrase_bytes,
)

MAGIC = b"TGBKFIL1"
_LEN = struct.Struct(">I")
_TAG = 16
_STAMP = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}\Z")
SQLITE_SUFFIXES = (".db", ".sqlite3")
# Never copied: SQLite side files (the snapshot already includes them), process locks and key material.
SKIP_NAMES = re.compile(r".*(-wal|-shm|-journal)\Z|.*\.(dpapi|tmp)\Z|\Aprocesses\Z|\Araw\Z")
STATUS_FILE = "research_backup_status.json"


def _encrypt(source: Path, output: Path, passphrase: str, header: dict, compress: bool) -> dict:
    """Stream one file into an authenticated container; returns the header written."""
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    digest, size = hashlib.sha256(), 0
    # The plaintext hash goes in the authenticated header, so hash first (one extra read, no extra memory).
    with open(source, "rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    header = {**header, "format_version": 1, "cipher": "AES-256-GCM", "kdf": "scrypt", "salt": salt.hex(),
              "nonce": nonce.hex(), "compression": "zstd" if compress else "none",
              "plaintext_sha256": digest.hexdigest(), "plaintext_size": size}
    raw = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii")
    prefix = MAGIC + _LEN.pack(len(raw)) + raw
    encryptor = Cipher(algorithms.AES(_derive_key(passphrase, salt)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(prefix)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + ".partial")
    try:
        with open(partial, "xb") as out:
            out.write(prefix)

            class Sink(io.RawIOBase):
                def writable(self):
                    return True

                def write(self, b):
                    out.write(encryptor.update(bytes(b)))
                    return len(b)
            sink = Sink()
            writer = zstd.ZstdCompressor(level=3).stream_writer(sink, closefd=False) if compress else sink
            with open(source, "rb") as stream:
                while chunk := stream.read(1 << 20):
                    writer.write(chunk)
            if compress:
                writer.flush(zstd.FLUSH_FRAME)
            out.write(encryptor.finalize())
            out.write(encryptor.tag)
            out.flush()
            os.fsync(out.fileno())
        os.replace(partial, output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return header


def read_header(container: Path) -> tuple[dict, bytes]:
    with open(container, "rb") as stream:
        if stream.read(len(MAGIC)) != MAGIC:
            raise BackupAuthenticationError(f"{container.name}: not a research backup container")
        raw_len = stream.read(4)
        if len(raw_len) != 4 or not 1 <= _LEN.unpack(raw_len)[0] <= 16384:
            raise BackupAuthenticationError(f"{container.name}: bad header length")
        raw = stream.read(_LEN.unpack(raw_len)[0])
    try:
        header = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise BackupAuthenticationError(f"{container.name}: malformed header") from None
    if not isinstance(header, dict) or header.get("format_version") != 1 or header.get("compression") not in ("zstd", "none"):
        raise BackupAuthenticationError(f"{container.name}: unsupported header")
    return header, MAGIC + raw_len + raw


def decrypt(container: Path, output: Path, passphrase: str) -> dict:
    """Authenticate and decrypt one container to `output` (must not exist); verifies the plaintext hash."""
    header, aad = read_header(container)
    if output.exists():
        raise BackupUnsafe(f"{output} already exists")
    key = _derive_key(passphrase, bytes.fromhex(header["salt"]))
    total = container.stat().st_size
    with open(container, "rb") as stream:
        stream.seek(total - _TAG)
        tag = stream.read(_TAG)
        stream.seek(len(aad))
        decryptor = Cipher(algorithms.AES(key), modes.GCM(bytes.fromhex(header["nonce"]), tag)).decryptor()
        decryptor.authenticate_additional_data(aad)
        staged = output.with_name(output.name + ".partial")
        digest = hashlib.sha256()
        try:
            with open(staged, "xb") as out:
                inflate = zstd.ZstdDecompressor().decompressobj() if header["compression"] == "zstd" else None
                remaining = total - len(aad) - _TAG
                while remaining:
                    chunk = stream.read(min(1 << 20, remaining))
                    if not chunk:
                        raise BackupAuthenticationError(f"{container.name}: truncated")
                    remaining -= len(chunk)
                    plain = decryptor.update(chunk)
                    try:
                        plain = inflate.decompress(plain) if inflate else plain
                    except zstd.ZstdError:
                        # GCM checks its tag only at the end; garbage from a wrong key fails decompression first.
                        raise BackupAuthenticationError(f"{container.name}: wrong passphrase or modified backup") from None
                    digest.update(plain)
                    out.write(plain)
                try:
                    decryptor.finalize()
                except InvalidTag:
                    raise BackupAuthenticationError(f"{container.name}: wrong passphrase or modified backup") from None
            if digest.hexdigest() != header["plaintext_sha256"]:
                raise BackupAuthenticationError(f"{container.name}: plaintext hash mismatch")
            os.replace(staged, output)
        except BaseException:
            staged.unlink(missing_ok=True)
            raise
    return header


def _snapshot_sqlite(source: Path, target: Path) -> None:
    src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(target)
    try:
        # One step: a single read transaction, consistent under WAL and not restarted by concurrent writers.
        src.backup(dst, pages=-1)
    finally:
        dst.close()
        src.close()


def _independent(source: Path, folder: Path) -> bool:
    return source.stat().st_dev != folder.stat().st_dev


def backup_research(root: Path, destination: Path, *, passphrase: str, keep: int = 7,
                    allow_same_device: bool = False, now: datetime | None = None) -> dict:
    """One snapshot of the data root plus any closed raw segments not yet copied; then prune old snapshots."""
    _passphrase_bytes(passphrase)
    if type(keep) is not int or not 2 <= keep <= 365:
        raise BackupUnsafe("retention must keep between 2 and 365 snapshots")
    if not root.is_dir() or not (root / "market.db").is_file():
        raise BackupUnsafe(f"{root} is not a data root with market.db")
    if destination.is_symlink() or not destination.is_dir():
        raise BackupUnsafe("destination must be an existing, unlinked folder")
    if not allow_same_device and not _independent(root, destination):
        raise BackupUnsafe("destination is on the same volume as the data; use another drive, or pass "
                           "--allow-same-device for a cloud-synced folder that leaves the machine by sync")
    now = now or datetime.now(UTC)
    stamp = f"{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    snapshot = destination / "snapshots" / stamp
    snapshot.mkdir(parents=True)
    entries = []
    with tempfile.TemporaryDirectory(prefix=".tg-research-", dir=destination) as scratch:
        for db in sorted(p for p in root.iterdir() if p.suffix in SQLITE_SUFFIXES and p.is_file() and not p.is_symlink()):
            copy = Path(scratch) / db.name
            _snapshot_sqlite(db, copy)
            header = _encrypt(copy, snapshot / f"{db.name}.tgfile", passphrase, {"kind": "sqlite", "name": db.name}, True)
            copy.unlink()
            entries.append({k: header[k] for k in ("kind", "name", "plaintext_sha256", "plaintext_size")})
        archive = Path(scratch) / "files.tar"
        with tarfile.open(archive, "w") as tar:
            for item in sorted(root.iterdir()):
                if item.is_symlink() or SKIP_NAMES.fullmatch(item.name) or item.suffix in SQLITE_SUFFIXES \
                        or item.name == STATUS_FILE:
                    continue
                tar.add(item, arcname=item.name, filter=lambda info: None if info.issym() or info.islnk() else info)
        header = _encrypt(archive, snapshot / "files.tar.tgfile", passphrase, {"kind": "files", "name": "files.tar"}, True)
        entries.append({k: header[k] for k in ("kind", "name", "plaintext_sha256", "plaintext_size")})
    segments = _backup_segments(root, destination, passphrase)
    manifest = {"created_at": now.isoformat(timespec="seconds"), "root": str(root), "entries": entries,
                "segments_total": segments["total"], "contains_secrets": False}
    (snapshot / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    pruned = _prune(destination / "snapshots", keep)
    report = {"snapshot": str(snapshot), "databases": [e["name"] for e in entries if e["kind"] == "sqlite"],
              "files_bytes": entries[-1]["plaintext_size"], "segments_added": segments["added"],
              "segments_total": segments["total"], "segments_refused": segments["refused"], "pruned": pruned,
              "same_device": not _independent(root, destination), "off_machine_verified": False}
    (root / STATUS_FILE).write_text(json.dumps({"at": now.isoformat(timespec="seconds"), "destination": str(destination),
                                                "snapshot": stamp, **{k: report[k] for k in ("segments_total", "same_device")}}),
                                    "utf-8")
    return report


def _backup_segments(root: Path, destination: Path, passphrase: str) -> dict:
    """Copy each closed segment once, after re-checking it against its manifest hash."""
    db = sqlite3.connect((root / "market.db").resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    try:
        rows = db.execute("SELECT seg_id, sha256 FROM segments WHERE sha256 IS NOT NULL ORDER BY seg_id").fetchall()
    finally:
        db.close()
    added, refused, total = 0, [], 0
    for seg_id, sha in rows:
        target = destination / "segments" / f"{seg_id}.tgfile"
        source = root / "raw" / seg_id
        if target.exists():
            total += 1
            continue
        if not source.is_file():
            continue  # moved to an archive drive by raw-move; back that drive up separately
        with open(source, "rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != sha:
                refused.append(seg_id)  # corrupted on disk: never back up a bad copy as if it were good
                continue
        _encrypt(source, target, passphrase, {"kind": "segment", "name": seg_id}, False)
        added += 1
        total += 1
    return {"added": added, "total": total, "refused": refused}


def _prune(folder: Path, keep: int) -> list[str]:
    stamps = sorted(p for p in folder.iterdir() if p.is_dir() and _STAMP.fullmatch(p.name) and (p / "MANIFEST.json").is_file())
    gone = stamps[:-keep]
    for old in gone:
        shutil.rmtree(old)
    return [p.name for p in gone]


def latest_snapshot(destination: Path) -> Path:
    folder = destination / "snapshots"
    stamps = sorted(p for p in folder.iterdir() if p.is_dir() and _STAMP.fullmatch(p.name) and (p / "MANIFEST.json").is_file()) \
        if folder.is_dir() else []
    if not stamps:
        raise BackupUnsafe(f"no research snapshots in {destination}")
    return stamps[-1]


def restore_research(destination: Path, target: Path, *, passphrase: str, segments: bool = True) -> dict:
    """Rebuild a data root from the newest snapshot (and the segment archive) into an empty or new folder."""
    if target.exists() and any(target.iterdir()):
        raise BackupUnsafe(f"{target} is not empty; restore never overwrites")
    snapshot = latest_snapshot(destination)
    manifest = json.loads((snapshot / "MANIFEST.json").read_text("utf-8"))
    target.mkdir(parents=True, exist_ok=True)
    restored = []
    for entry in manifest["entries"]:
        container = snapshot / f"{entry['name']}.tgfile"
        header, _ = read_header(container)
        if header.get("name") != entry["name"] or header.get("plaintext_sha256") != entry["plaintext_sha256"]:
            raise BackupAuthenticationError(f"{container.name}: does not match the snapshot manifest")
        if entry["kind"] == "sqlite":
            out = target / entry["name"]
            decrypt(container, out, passphrase)
            conn = sqlite3.connect(out.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                conn.close()
            if check != "ok":
                raise BackupAuthenticationError(f"{entry['name']}: restored database failed integrity_check")
        else:
            tar_path = target / ".files.tar"
            decrypt(container, tar_path, passphrase)
            with tarfile.open(tar_path) as tar:
                tar.extractall(target, filter="data")
            tar_path.unlink()
        restored.append(entry["name"])
    count = 0
    if segments and (destination / "segments").is_dir():
        for container in sorted((destination / "segments").rglob("*.tgfile")):
            header, _ = read_header(container)
            seg_id = container.relative_to(destination / "segments").as_posix()[: -len(".tgfile")]
            if header.get("kind") != "segment" or header.get("name") != seg_id:
                raise BackupAuthenticationError(f"{container.name}: segment name does not match its header")
            out = target / "raw" / seg_id
            out.parent.mkdir(parents=True, exist_ok=True)
            decrypt(container, out, passphrase)
            count += 1
    return {"snapshot": snapshot.name, "restored": restored, "segments": count, "target": str(target)}


def status(root: Path) -> dict | None:
    path = root / STATUS_FILE
    try:
        return json.loads(path.read_text("utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def drill(destination: Path, *, passphrase: str, segment_sample: int = 24) -> dict:
    """Prove the newest snapshot restores (every database and the files archive) plus the newest segments."""
    with tempfile.TemporaryDirectory(prefix=".tg-research-drill-", dir=destination) as scratch:
        report = restore_research(destination, Path(scratch) / "root", passphrase=passphrase, segments=False)
        containers = sorted((destination / "segments").rglob("*.tgfile")) if (destination / "segments").is_dir() else []
        for container in containers[-segment_sample:] if segment_sample else []:
            decrypt(container, Path(scratch) / f"seg-{secrets.token_hex(4)}", passphrase)
        return {**report, "target": "deleted after verification", "segments": None,
                "segments_verified": min(len(containers), segment_sample), "segments_stored": len(containers)}
