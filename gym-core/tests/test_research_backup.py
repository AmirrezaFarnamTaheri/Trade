"""Research-store backup: consistent snapshots, segments copied once, authenticated restore, never overwriting."""
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from gym.adapters.store import MarketDB, SegmentWriter
from gym.services.doctor import diagnose
from gym.services.encrypted_backup import BackupAuthenticationError, BackupUnsafe
from gym.services.research_backup import backup_research, drill, restore_research
from tests.support import START, quote_history

PHRASE = "correct horse battery staple"


def data_root(tmp_path):
    root = tmp_path / "live"
    db = MarketDB(root / "market.db")
    for row in quote_history(n=50):
        db.add_book_top(row, None)
    writer = SegmentWriter(root / "raw", db)
    writer.write("ws", "first hour", START)
    writer.write("ws", "second hour", START + timedelta(hours=1))  # rotates: the first segment closes
    writer.close()
    db.c.close()
    (root / "runs").mkdir()
    (root / "runs" / "abc.json").write_text('{"run_id": "abc"}', "utf-8")
    (root / "wallex-read.dpapi").write_bytes(b"never copied")
    sqlite3.connect(root / "research.sqlite3").execute("create table t(x)").connection.commit()
    return root


def test_backup_restores_byte_identical_data_and_copies_segments_once(tmp_path):
    root, dest = data_root(tmp_path), tmp_path / "backup"
    dest.mkdir()
    first = backup_research(root, dest, passphrase=PHRASE, allow_same_device=True)
    assert first["databases"] == ["market.db", "research.sqlite3"] and first["segments_added"] == 2
    second = backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, keep=2)
    assert second["segments_added"] == 0 and second["segments_total"] == 2
    assert b"first hour" not in b"".join(p.read_bytes() for p in dest.rglob("*.tgfile"))  # encrypted at rest

    restored = tmp_path / "restored"
    report = restore_research(dest, restored, passphrase=PHRASE)
    assert report["segments"] == 2 and (restored / "runs" / "abc.json").read_text("utf-8") == '{"run_id": "abc"}'
    assert report["manifest_status"] == "AUTHENTICATED"
    assert not (restored / "wallex-read.dpapi").exists()
    for seg in (root / "raw").rglob("*.jsonl.zst"):
        assert (restored / "raw" / seg.relative_to(root / "raw")).read_bytes() == seg.read_bytes()
    original = sqlite3.connect(root / "market.db").execute("select count(*), max(bid) from book_top").fetchone()
    assert sqlite3.connect(restored / "market.db").execute("select count(*), max(bid) from book_top").fetchone() == original
    status = {c["check"]: c["status"] for c in diagnose(restored, START)["checks"]}
    assert status["raw_segments"] == "PASS"  # the rebuilt root passes the integrity check on its own
    with pytest.raises(BackupUnsafe, match="not empty"):
        restore_research(dest, restored, passphrase=PHRASE)
    assert drill(dest, passphrase=PHRASE)["segments_verified"] == 2


def test_nested_database_backup_restores_committed_wal_without_sidecars(tmp_path):
    root = data_root(tmp_path)
    nested = root / "sweeps" / "window.sqlite3"
    nested.parent.mkdir()
    dest = tmp_path / "backup"
    dest.mkdir()
    conn = sqlite3.connect(nested)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE results(value)")
        conn.execute("INSERT INTO results VALUES (42)")
        conn.commit()
        assert nested.with_suffix(".sqlite3-wal").exists()
        backup_research(root, dest, passphrase=PHRASE, allow_same_device=True)
        restored = tmp_path / "restored"
        restore_research(dest, restored, passphrase=PHRASE)
        path = restored / "sweeps" / nested.name
        assert sorted(p.name for p in path.parent.iterdir()) == [nested.name]
        with sqlite3.connect(path) as copy:
            assert copy.execute("SELECT value FROM results").fetchall() == [(42,)]
    finally:
        conn.close()


def test_restore_reports_missing_segments_without_claiming_complete_archive(tmp_path):
    root, dest = data_root(tmp_path), tmp_path / "backup"
    dest.mkdir()
    backup_research(root, dest, passphrase=PHRASE, allow_same_device=True)
    container = next((dest / "segments").rglob("*.tgfile"))
    missing = container.relative_to(dest / "segments").as_posix().removesuffix(".tgfile")
    container.unlink()
    report = restore_research(dest, tmp_path / "restored", passphrase=PHRASE)
    assert report["segments"] == 1
    assert report["segment_coverage"] == {"status": "INCOMPLETE", "missing": [missing]}
    rehearsal = drill(dest, passphrase=PHRASE)
    assert rehearsal["segment_coverage"] == report["segment_coverage"]
    assert rehearsal["segments_verified"] == 1


def test_backup_and_restore_scope_raw_segments_to_the_market_snapshot(tmp_path, monkeypatch):
    from gym.services import research_backup

    root, dest = data_root(tmp_path), tmp_path / "backup"
    dest.mkdir()
    db = MarketDB(root / "market.db")
    writer = SegmentWriter(root / "raw", db)
    open_id = writer.write("ws", "still open at capture", START + timedelta(hours=2)).split("#")[0]
    original = research_backup._snapshot_sqlite

    def copy_with_rollover(source, target):
        original(source, target)
        if source == root / "market.db":
            writer.close()  # this segment closes while the rest of the backup is still running

    monkeypatch.setattr(research_backup, "_snapshot_sqlite", copy_with_rollover)
    try:
        first = backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, now=START)
        assert first["open_segments_excluded"] == [open_id]
        assert first["segments_total"] == 2
        container = dest / "segments" / f"{open_id}.tgfile"
        assert not container.exists()
        later = backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, now=START + timedelta(days=1))
        assert later["open_segments_excluded"] == [] and container.is_file()
        Path(later["snapshot"]).rename(tmp_path / "later-snapshot")
        target = tmp_path / "restored"
        restored = restore_research(dest, target, passphrase=PHRASE, expected_manifest_sha256=first["manifest_sha256"])
        assert restored["open_segments_excluded"] == [open_id]
        assert restored["segment_coverage"] == {"status": "COMPLETE", "missing": []}
        assert not (target / "raw" / open_id).exists()
        rehearsal = drill(dest, passphrase=PHRASE)
        assert rehearsal["open_segments_excluded"] == [open_id]
        assert rehearsal["segments_stored"] == rehearsal["segments_verified"] == 2
    finally:
        writer.close()
        db.c.close()


def test_restore_refuses_segment_that_disagrees_with_snapshotted_market_db(tmp_path):
    from gym.services.research_backup import _encrypt, read_header

    root, dest = data_root(tmp_path), tmp_path / "backup"
    dest.mkdir()
    backup_research(root, dest, passphrase=PHRASE, allow_same_device=True)
    container = next((dest / "segments").rglob("*.tgfile"))
    header, _ = read_header(container)
    wrong = tmp_path / "different-segment"
    wrong.write_bytes(b"different content")
    container.unlink()
    _encrypt(wrong, container, PHRASE, {"kind": "segment", "name": header["name"]}, False)
    with pytest.raises(BackupAuthenticationError, match="market.db segment digest"):
        restore_research(dest, tmp_path / "restored", passphrase=PHRASE)
    with pytest.raises(BackupAuthenticationError, match="market.db segment digest"):
        drill(dest, passphrase=PHRASE)


def test_restore_pins_independent_receipt_and_rejects_a_rolled_back_snapshot(tmp_path):
    import shutil
    from pathlib import Path

    root, dest = data_root(tmp_path), tmp_path / "backup"
    dest.mkdir()
    backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, now=START)
    latest = backup_research(root, dest, passphrase=PHRASE, allow_same_device=True, now=START + timedelta(days=1))
    digest = latest["manifest_sha256"]
    assert drill(dest, passphrase=PHRASE, expected_manifest_sha256=digest)["manifest_status"] == "PINNED"
    shutil.rmtree(Path(latest["snapshot"]))
    with pytest.raises(BackupAuthenticationError, match="trusted manifest digest"):
        restore_research(dest, tmp_path / "restored", passphrase=PHRASE, expected_manifest_sha256=digest)
    assert not (tmp_path / "restored").exists()


def test_manifest_tampering_has_no_plaintext_fallback(tmp_path):
    from gym.services.research_backup import LEGACY_MANIFEST, MANIFEST, latest_snapshot

    root, dest = data_root(tmp_path), tmp_path / "backup"
    dest.mkdir()
    backup_research(root, dest, passphrase=PHRASE, allow_same_device=True)
    snapshot = latest_snapshot(dest)
    manifest = snapshot / MANIFEST
    data = bytearray(manifest.read_bytes())
    data[-17] ^= 1
    manifest.write_bytes(data)
    (snapshot / LEGACY_MANIFEST).write_text('{"entries": []}', encoding="utf-8")
    with pytest.raises(BackupAuthenticationError, match="modified backup"):
        restore_research(dest, tmp_path / "restored", passphrase=PHRASE)
    assert not (tmp_path / "restored").exists()


def test_wrong_passphrase_tampering_and_swapped_files_are_refused(tmp_path):
    root, dest = data_root(tmp_path), tmp_path / "backup"
    dest.mkdir()
    backup_research(root, dest, passphrase=PHRASE, allow_same_device=True)
    with pytest.raises(BackupAuthenticationError):
        drill(dest, passphrase="a different long passphrase")
    snapshot = next((dest / "snapshots").iterdir())
    market, research = snapshot / "market.db.tgfile", snapshot / "research.sqlite3.tgfile"
    market_bytes = market.read_bytes()
    market.write_bytes(research.read_bytes())  # swapped: the authenticated header names the other database
    with pytest.raises(BackupAuthenticationError, match="manifest"):
        drill(dest, passphrase=PHRASE)
    tampered = bytearray(market_bytes)
    tampered[-40] ^= 1
    market.write_bytes(bytes(tampered))
    with pytest.raises(BackupAuthenticationError):
        drill(dest, passphrase=PHRASE)


def test_corrupted_segment_is_not_backed_up_and_same_volume_needs_consent(tmp_path):
    root, dest = data_root(tmp_path), tmp_path / "backup"
    dest.mkdir()
    with pytest.raises(BackupUnsafe, match="same volume"):
        backup_research(root, dest, passphrase=PHRASE)
    seg = min((root / "raw").rglob("*.jsonl.zst"))
    seg.write_bytes(b"bit rot")
    report = backup_research(root, dest, passphrase=PHRASE, allow_same_device=True)
    assert report["segments_refused"] == [seg.relative_to(root / "raw").as_posix()] and report["segments_added"] == 1
    assert json.loads((root / "research_backup_status.json").read_text("utf-8"))["segments_total"] == 1
