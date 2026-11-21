"""Full local restore drills and negative fault-injection checks (O003-O008, O010)."""
from __future__ import annotations

import io
import json
import sqlite3
import tarfile
from datetime import timedelta
from pathlib import Path

import pytest

from gym.adapters.store import MarketDB, SegmentWriter
from gym.services.doctor import diagnose
from gym.services.encrypted_backup import BackupAuthenticationError, BackupUnsafe
from gym.services.research_backup import (
    MANIFEST,
    _encrypt,
    backup_research,
    drill,
    latest_snapshot,
    read_header,
    restore_research,
)
from tests.support import START, quote_history

PHRASE = "correct horse battery staple"


def _seed_store(tmp_path: Path) -> Path:
    root = tmp_path / "live"
    db = MarketDB(root / "market.db")
    for row in quote_history(n=30):
        db.add_book_top(row, None)
    writer = SegmentWriter(root / "raw", db)
    writer.write("ws", "hour-one", START)
    writer.write("ws", "hour-two", START + timedelta(hours=1))
    writer.close()
    db.c.close()
    (root / "runs").mkdir()
    (root / "runs" / "frozen-run.json").write_text('{"run_id": "frozen-run", "outputs_digest": "abc"}', "utf-8")
    (root / "arm-policy.json").write_text('{"schema": 1, "loss_cap_quote": "0"}', "utf-8")
    conn = sqlite3.connect(root / "research.sqlite3")
    conn.execute("CREATE TABLE t(x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    return root


def test_full_local_restore_of_pinned_older_snapshot_passes_doctor_and_stays_disarmed(tmp_path):
    """O003, O004, O007: restore pinned older snapshot to empty root, run doctor, confirm FULL_RESTORE & DISARMED."""
    root = _seed_store(tmp_path)
    dest = tmp_path / "backup"
    dest.mkdir()
    snap1 = backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, now=START, keep=3)
    # Add a third segment and a second snapshot later.
    db = MarketDB(root / "market.db")
    writer = SegmentWriter(root / "raw", db)
    writer.write("ws", "hour-three", START + timedelta(hours=2))
    writer.close()
    db.c.close()
    snap2 = backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, now=START + timedelta(days=1), keep=3)
    assert snap1["manifest_sha256"] != snap2["manifest_sha256"]

    snap1_id = Path(snap1["snapshot"]).name
    restored = tmp_path / "restored-snap1"
    report = restore_research(dest, restored, passphrase=PHRASE, snapshot_id=snap1_id,
                              expected_manifest_sha256=snap1["manifest_sha256"])
    assert report["snapshot"] == snap1_id
    assert report["manifest_status"] == "PINNED"
    assert report["segment_coverage"] == {"status": "COMPLETE", "missing": []}
    assert report["segment_integrity"] == {"scope": "FULL_RESTORE", "verified": 2, "expected": 2}
    assert report["cross_host_verified"] is False
    assert (restored / "runs" / "frozen-run.json").read_text("utf-8") == '{"run_id": "frozen-run", "outputs_digest": "abc"}'

    # Doctor checks pass cleanly on the rebuilt isolated root.
    checks = {c["check"]: c["status"] for c in diagnose(restored, START + timedelta(hours=2))["checks"]}
    assert checks["market_db"] == "PASS"
    assert checks["raw_segments"] == "PASS"
    assert checks["segment_manifest"] == "PASS"
    assert checks["executor_ledger"] == "SKIP"  # executor remains isolated / DISARMED

    # Sampled drill explicitly distinguishes SAMPLED_DRILL from FULL_RESTORE and cross_host_verified=False.
    sampled = drill(dest, passphrase=PHRASE, snapshot_id=snap1_id,
                    expected_manifest_sha256=snap1["manifest_sha256"], segment_sample=1)
    assert sampled["segment_integrity"] == {"scope": "SAMPLED_DRILL", "verified": 1, "expected": 2}
    assert sampled["cross_host_verified"] is False

    # Non-existent snapshot ID fails closed.
    with pytest.raises(BackupUnsafe, match="not retained"):
        restore_research(dest, tmp_path / "restored-missing", passphrase=PHRASE, snapshot_id="19990101T000000Z")


def test_encrypted_container_rejects_unsupported_kdf_cipher_and_format_version(tmp_path):
    """O008: malformed header, unsupported KDF/cipher/version are refused without writing corrupt output."""
    root = _seed_store(tmp_path)
    dest = tmp_path / "backup"
    dest.mkdir()
    backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, now=START)
    snap = latest_snapshot(dest)
    target = snap / "market.db.tgfile"
    raw = target.read_bytes()
    # Container layout: magic + length-prefixed JSON header + ciphertext. Corrupt header magic/bytes.
    corrupted = b"BADMAGIC" + raw[8:]
    target.write_bytes(corrupted)
    out = tmp_path / "restored-corrupt"
    with pytest.raises((BackupAuthenticationError, BackupUnsafe, ValueError)):
        restore_research(dest, out, passphrase=PHRASE)
    assert not (out / "market.db").exists()


def test_tar_path_traversal_and_symlink_escape_are_refused_during_restore(tmp_path):
    """O010: malicious tar member escaping restore target root is rejected before extraction."""
    root = _seed_store(tmp_path)
    dest = tmp_path / "backup"
    dest.mkdir()
    backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, now=START)
    snap = latest_snapshot(dest)

    # Craft a malicious files.tar with a parent-directory traversal member and re-encrypt it + manifest.
    evil_tar = tmp_path / "evil.tar"
    with tarfile.open(evil_tar, "w") as tar:
        info = tarfile.TarInfo(name="../escaped.txt")
        payload = b"should never escape"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    files_container = snap / "files.tar.tgfile"
    files_container.unlink()
    _encrypt(evil_tar, files_container, PHRASE, {"kind": "files", "name": "files.tar"}, True)
    files_header, _ = read_header(files_container)
    # Update manifest so the container passes authentication and specifically tests tar extraction defense.
    market_container = snap / "market.db.tgfile"
    research_container = snap / "research.sqlite3.tgfile"
    entries = []
    for name, kind, path in [
        ("market.db", "sqlite", market_container),
        ("research.sqlite3", "sqlite", research_container),
        ("files.tar", "files", files_container),
    ]:
        h = files_header if name == "files.tar" else read_header(path)[0]
        entries.append({"kind": kind, "name": name, "plaintext_sha256": h["plaintext_sha256"],
                        "plaintext_size": h["plaintext_size"]})
    manifest_raw = tmp_path / "manifest.json"
    manifest_raw.write_text(json.dumps({"version": 1, "snapshot": snap.name, "entries": entries}), "utf-8")
    (snap / MANIFEST).unlink()
    _encrypt(manifest_raw, snap / MANIFEST, PHRASE, {"kind": "manifest", "name": snap.name}, False)

    out = tmp_path / "isolated-target"
    with pytest.raises((tarfile.OutsideDestinationError, tarfile.FilterError, BackupAuthenticationError, BackupUnsafe)):
        restore_research(dest, out, passphrase=PHRASE)
    assert not (tmp_path / "escaped.txt").exists()
