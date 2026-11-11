"""Research-store backup: consistent snapshots, segments copied once, authenticated restore, never overwriting."""
import json
import sqlite3
from datetime import timedelta

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
