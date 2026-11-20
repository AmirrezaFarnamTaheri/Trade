"""Encrypted backup of the research store: SQLite databases, other files and the raw archive.

The executor ledger has its own backup (`encrypted_backup`). This one covers what the research evidence rests
on: market.db and the other stores in the data root, saved runs and studies, and every closed raw segment.

Layout under the destination folder:

    snapshots/<UTC stamp>/<name>.tgfile   one consistent SQLite snapshot per database, zstd then AES-256-GCM
    snapshots/<UTC stamp>/files.tar.tgfile  every other file in the data root (runs, studies, journals)
    snapshots/<UTC stamp>/MANIFEST.tgfile authenticated snapshot inventory, bound to the snapshot stamp
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

from ..adapters.atomic_text import write_text
from .encrypted_backup import (
    _SCRYPT_N,
    _SCRYPT_P,
    _SCRYPT_R,
    BackupAuthenticationError,
    BackupUnsafe,
    _derive_key,
    _passphrase_bytes,
)

MAGIC = b"TGBKFIL1"
_LEN = struct.Struct(">I")
_TAG = 16
_STAMP = re.compile(r"[0-9]{8}T[0-9]{6}Z-(?:z[0-9]{6}-)?[0-9a-f]{6}\Z")
SQLITE_SUFFIXES = (".db", ".sqlite3")
# Never copied: SQLite side files (the snapshot already includes them), process locks and key material.
SKIP_NAMES = re.compile(r".*(-wal|-shm|-journal)\Z|.*\.(dpapi|tmp)\Z|\Aprocesses\Z|\Araw\Z")
STATUS_FILE = "research_backup_status.json"
MANIFEST = "MANIFEST.tgfile"
LEGACY_MANIFEST = "MANIFEST.json"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_KDF_PARAMETERS = {"n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P}


def _encrypt(source: Path, output: Path, passphrase: str, header: dict, compress: bool) -> dict:
    """Stream one file into an authenticated container; returns the header written."""
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    digest, size = hashlib.sha256(), 0
    # The plaintext hash goes in the authenticated header, so hash first (one extra read, no extra memory).
    with open(source, "rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    header = {**header, "format_version": 2, "cipher": "AES-256-GCM", "kdf": "scrypt", "salt": salt.hex(),
              "kdf_parameters": _KDF_PARAMETERS,
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
    if (not isinstance(header, dict) or header.get("format_version") not in (1, 2)
            or header.get("compression") not in ("zstd", "none")
            or header.get("cipher") != "AES-256-GCM" or header.get("kdf") != "scrypt"
            or (header.get("format_version") == 2 and header.get("kdf_parameters") != _KDF_PARAMETERS)):
        raise BackupAuthenticationError(f"{container.name}: unsupported header")
    for field, length in (("salt", 32), ("nonce", 24), ("plaintext_sha256", 64)):
        value = header.get(field)
        if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-f]{{{length}}}", value):
            raise BackupAuthenticationError(f"{container.name}: invalid {field}")
    if type(header.get("plaintext_size")) is not int or header["plaintext_size"] < 0:
        raise BackupAuthenticationError(f"{container.name}: invalid plaintext size")
    return header, MAGIC + raw_len + raw


def decrypt(container: Path, output: Path, passphrase: str, *, expected_header: dict | None = None) -> dict:
    """Authenticate and decrypt one container to `output` (must not exist); verifies the plaintext hash."""
    header, aad = read_header(container)
    if expected_header and any(header.get(field) != value for field, value in expected_header.items()):
        raise BackupAuthenticationError(f"{container.name}: does not match the snapshot manifest")
    if output.exists():
        raise BackupUnsafe(f"{output} already exists")
    key = _derive_key(passphrase, bytes.fromhex(header["salt"]))
    total = container.stat().st_size
    if total < len(aad) + _TAG:
        raise BackupAuthenticationError(f"{container.name}: truncated")
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
            if staged.stat().st_size != header["plaintext_size"] or digest.hexdigest() != header["plaintext_sha256"]:
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
    if not root.is_dir() or not (root / "market.db").is_file() or (root / "market.db").is_symlink():
        raise BackupUnsafe(f"{root} is not a data root with market.db")
    if destination.is_symlink() or not destination.is_dir():
        raise BackupUnsafe("destination must be an existing, unlinked folder")
    if destination.resolve().is_relative_to(root.resolve()):
        raise BackupUnsafe("destination must be outside the data root")
    if not allow_same_device and not _independent(root, destination):
        raise BackupUnsafe("destination is on the same volume as the data; use another drive, or pass "
                           "--allow-same-device for a cloud-synced folder that leaves the machine by sync")
    now = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    # The z prefix sorts these after legacy snapshots made in the same second.
    stamp = f"{now:%Y%m%dT%H%M%SZ}-z{now:%f}-{secrets.token_hex(3)}"
    snapshot = destination / "snapshots" / stamp
    snapshot.mkdir(parents=True)
    entries = []
    closed_segments, open_segments = {}, []
    with tempfile.TemporaryDirectory(prefix=".tg-research-", dir=destination) as scratch:
        for db in sorted(p for p in root.iterdir() if p.suffix in SQLITE_SUFFIXES and p.is_file() and not p.is_symlink()):
            copy = Path(scratch) / db.name
            _snapshot_sqlite(db, copy)
            if db.name == "market.db":
                closed_segments, open_segments = _segment_inventory(copy)
            header = _encrypt(copy, snapshot / f"{db.name}.tgfile", passphrase, {"kind": "sqlite", "name": db.name}, True)
            copy.unlink()
            entries.append({k: header[k] for k in ("kind", "name", "plaintext_sha256", "plaintext_size")})
        archive = Path(scratch) / "files.tar"
        nested_databases = []

        def archive_member(info):
            name = Path(info.name)
            if (not (info.isfile() or info.isdir()) or SKIP_NAMES.fullmatch(name.name)
                    or name.name == STATUS_FILE):
                return None
            if info.isfile() and name.suffix in SQLITE_SUFFIXES:
                nested_databases.append(name)
                return None
            return info

        with tarfile.open(archive, "w") as tar:
            for item in sorted(root.iterdir()):
                if item.suffix not in SQLITE_SUFFIXES or item.is_dir():
                    tar.add(item, arcname=item.name, filter=archive_member)
            copy = Path(scratch) / "nested.sqlite3"
            for name in nested_databases:
                _snapshot_sqlite(root / name, copy)
                tar.add(copy, arcname=name.as_posix())
                copy.unlink()
        header = _encrypt(archive, snapshot / "files.tar.tgfile", passphrase, {"kind": "files", "name": "files.tar"}, True)
        entries.append({k: header[k] for k in ("kind", "name", "plaintext_sha256", "plaintext_size")})
    segments = _backup_segments(root, destination, passphrase, closed_segments)
    manifest = {"version": 1, "snapshot": stamp, "created_at": now.isoformat(timespec="seconds"),
                "root": str(root), "entries": entries,
                "segments_total": segments["total"], "open_segments_excluded": open_segments, "contains_secrets": False}
    with tempfile.TemporaryDirectory(prefix=".tg-manifest-", dir=destination) as scratch:
        source = Path(scratch) / LEGACY_MANIFEST
        source.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        manifest_header = _encrypt(source, snapshot / MANIFEST, passphrase,
                                   {"kind": "manifest", "name": stamp}, False)
    pruned = _prune(destination / "snapshots", keep)
    report = {"snapshot": str(snapshot), "databases": [e["name"] for e in entries if e["kind"] == "sqlite"],
              "manifest_sha256": manifest_header["plaintext_sha256"],
              "files_bytes": entries[-1]["plaintext_size"], "segments_added": segments["added"],
              "segments_total": segments["total"], "segments_refused": segments["refused"], "pruned": pruned,
              "open_segments_excluded": open_segments,
              "same_device": not _independent(root, destination), "off_machine_verified": False}
    write_text(root / STATUS_FILE, json.dumps({"at": now.isoformat(timespec="seconds"), "destination": str(destination),
                                              "snapshot": stamp, **{k: report[k] for k in ("segments_total", "same_device", "manifest_sha256")}}))
    return report


def _segment_inventory(market_db: Path) -> tuple[dict[str, str], list[str]]:
    db = sqlite3.connect(market_db.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    try:
        rows = db.execute("SELECT seg_id, sha256 FROM segments ORDER BY seg_id").fetchall()
    finally:
        db.close()
    return ({seg_id: sha for seg_id, sha in rows if sha is not None},
            [seg_id for seg_id, sha in rows if sha is None])


def _backup_segments(root: Path, destination: Path, passphrase: str, closed: dict[str, str]) -> dict:
    """Copy only segments already closed in the saved SQLite snapshot."""
    added, refused, total = 0, [], 0
    for seg_id, sha in closed.items():
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


def _complete_snapshots(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.is_symlink() and _STAMP.fullmatch(p.name)
                  and ((p / MANIFEST).is_file() or (p / LEGACY_MANIFEST).is_file()))


def _prune(folder: Path, keep: int) -> list[str]:
    stamps = _complete_snapshots(folder)
    gone = stamps[:-keep]
    for old in gone:
        shutil.rmtree(old)
    return [p.name for p in gone]


def latest_snapshot(destination: Path, snapshot_id: str | None = None) -> Path:
    stamps = _complete_snapshots(destination / "snapshots")
    if snapshot_id is not None:
        for stamp in stamps:
            if stamp.name == snapshot_id:
                return stamp
        raise BackupUnsafe("requested snapshot is not retained")
    if not stamps:
        raise BackupUnsafe(f"no research snapshots in {destination}")
    return stamps[-1]


def _snapshot_segments(archive: Path, expected: dict[str, str]) -> dict[str, Path]:
    """Verify archive headers only for segments that belong to the selected cut."""
    containers = {}
    for container in sorted(archive.rglob("*.tgfile")):
        seg_id = container.relative_to(archive).as_posix().removesuffix(".tgfile")
        if seg_id not in expected:
            continue
        header, _ = read_header(container)
        if header.get("kind") != "segment" or header.get("name") != seg_id:
            raise BackupAuthenticationError(f"{container.name}: segment name does not match its header")
        if header["plaintext_sha256"] != expected[seg_id]:
            raise BackupAuthenticationError(f"{container.name}: does not match market.db segment digest")
        containers[seg_id] = container
    return containers


def _coverage(expected, containers):
    missing = sorted(expected.keys() - containers.keys())
    return {"status": "INCOMPLETE" if missing else "COMPLETE", "missing": missing}


def _restore_manifest(snapshot: Path, passphrase: str, expected_digest: str | None) -> tuple[list[dict], str, str | None]:
    container = snapshot / MANIFEST
    manifest_digest = None
    if container.exists() or container.is_symlink():
        with tempfile.TemporaryDirectory(prefix=".tg-manifest-") as scratch:
            source = Path(scratch) / LEGACY_MANIFEST
            header = decrypt(container, source, passphrase)
            if header.get("kind") != "manifest" or header.get("name") != snapshot.name:
                raise BackupAuthenticationError("research backup manifest does not belong to this snapshot")
            manifest_digest = header["plaintext_sha256"]
            raw = source.read_bytes()
    else:
        raw = (snapshot / LEGACY_MANIFEST).read_bytes()
    if expected_digest is not None and manifest_digest != expected_digest:
        raise BackupAuthenticationError("research backup does not match the trusted manifest digest")
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise BackupAuthenticationError("invalid research backup manifest") from None
    if not isinstance(manifest, dict) or (manifest_digest is not None and
            (manifest.get("version") != 1 or manifest.get("snapshot") != snapshot.name)):
        raise BackupAuthenticationError("invalid research backup manifest identity")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise BackupAuthenticationError("invalid research backup manifest entries")
    names = set()
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        if (not isinstance(name, str) or name in names or re.search(r'[/\\:\x00]', name)
                or not isinstance(entry.get("plaintext_sha256"), str)
                or not _SHA256.fullmatch(entry["plaintext_sha256"])
                or type(entry.get("plaintext_size")) is not int or entry["plaintext_size"] < 0
                or not ((entry.get("kind") == "sqlite" and Path(name).suffix in SQLITE_SUFFIXES)
                        or (entry.get("kind") == "files" and name == "files.tar"))):
            raise BackupAuthenticationError("invalid research backup manifest entry")
        names.add(name)
    if not {"market.db", "files.tar"} <= names:
        raise BackupAuthenticationError("research backup manifest is missing required entries")
    status = "PINNED" if expected_digest is not None else "AUTHENTICATED" if manifest_digest else "LEGACY_UNVERIFIED"
    return entries, status, manifest_digest


def restore_research(destination: Path, target: Path, *, passphrase: str, segments: bool = True,
                     expected_manifest_sha256: str | None = None, snapshot_id: str | None = None) -> dict:
    """Rebuild a data root from the newest snapshot (and the segment archive) into an empty or new folder."""
    if target.exists() and any(target.iterdir()):
        raise BackupUnsafe(f"{target} is not empty; restore never overwrites")
    snapshot = latest_snapshot(destination, snapshot_id)
    entries, manifest_status, manifest_digest = _restore_manifest(snapshot, passphrase, expected_manifest_sha256)
    target.mkdir(parents=True, exist_ok=True)
    restored = []
    for entry in entries:
        container = snapshot / f"{entry['name']}.tgfile"
        expected = {field: entry[field] for field in ("kind", "name", "plaintext_sha256", "plaintext_size")}
        if manifest_status == "LEGACY_UNVERIFIED":
            expected["format_version"] = 1
        if entry["kind"] == "sqlite":
            out = target / entry["name"]
            decrypt(container, out, passphrase, expected_header=expected)
            conn = sqlite3.connect(out.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                conn.close()
            if check != "ok":
                raise BackupAuthenticationError(f"{entry['name']}: restored database failed integrity_check")
        else:
            tar_path = target / ".files.tar"
            decrypt(container, tar_path, passphrase, expected_header=expected)
            with tarfile.open(tar_path) as tar:
                tar.extractall(target, filter="data")
            tar_path.unlink()
        restored.append(entry["name"])
    closed, opened = _segment_inventory(target / "market.db")
    containers = {}
    coverage = {"status": "NOT_CHECKED", "missing": []}
    if segments:
        containers = _snapshot_segments(destination / "segments", closed)
        for seg_id, container in containers.items():
            out = target / "raw" / seg_id
            out.parent.mkdir(parents=True, exist_ok=True)
            decrypt(container, out, passphrase,
                    expected_header={"kind": "segment", "name": seg_id, "plaintext_sha256": closed[seg_id]})
        coverage = _coverage(closed, containers)
    return {"snapshot": snapshot.name, "restored": restored, "segments": len(containers),
            "segment_coverage": coverage, "open_segments_excluded": opened, "target": str(target), "manifest_status": manifest_status,
            "manifest_sha256": manifest_digest,
            "segment_integrity": {"scope": "FULL_RESTORE" if segments else "NOT_CHECKED", "verified": len(containers),
                                  "expected": len(closed)}, "cross_host_verified": False}


def status(root: Path) -> dict | None:
    path = root / STATUS_FILE
    try:
        return json.loads(path.read_text("utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def drill(destination: Path, *, passphrase: str, segment_sample: int = 24,
          expected_manifest_sha256: str | None = None, snapshot_id: str | None = None) -> dict:
    """Prove the newest snapshot restores (every database and the files archive) plus the newest segments."""
    if type(segment_sample) is not int or segment_sample < 0:
        raise BackupUnsafe("segment sample must be a nonnegative integer")
    with tempfile.TemporaryDirectory(prefix=".tg-research-drill-", dir=destination) as scratch:
        report = restore_research(destination, Path(scratch) / "root", passphrase=passphrase, segments=False,
                                  expected_manifest_sha256=expected_manifest_sha256, snapshot_id=snapshot_id)
        closed, _ = _segment_inventory(Path(scratch) / "root" / "market.db")
        containers = _snapshot_segments(destination / "segments", closed)
        report["segment_coverage"] = _coverage(closed, containers)
        sample = list(containers.items())[-segment_sample:] if segment_sample else []
        for seg_id, container in sample:
            decrypt(container, Path(scratch) / f"seg-{secrets.token_hex(4)}", passphrase,
                    expected_header={"kind": "segment", "name": seg_id, "plaintext_sha256": closed[seg_id]})
        return {**report, "target": "deleted after verification", "segments": None,
                "segment_integrity": {"scope": "SAMPLED_DRILL", "verified": len(sample), "expected": len(closed)},
                "segments_verified": min(len(containers), segment_sample), "segments_stored": len(containers)}
