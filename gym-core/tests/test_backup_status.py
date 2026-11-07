"""Actual authenticated backup/restore receipts are bounded, private and observational."""
import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.services.backup_status import record, status
from gym.services.collector import Collector
from gym.services.encrypted_backup import create_backup, restore_backup
from gym.services.rules import RuleService
from tests.support import market_db, quote_history
from tests.test_encrypted_backup import make_ledger


def test_receipt_merge_retains_history_is_idempotent_and_latest_is_chronological(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from gym.services import backup_status
    canonical, older = tmp_path / "canonical", tmp_path / "older"
    report = {"encrypted": True, "authenticated": True, "verified_restore": True,
              "sequence": 3, "head_hash": "a" * 64, "file_sha256": "b" * 64, "schema_version": 1}
    monkeypatch.setattr(backup_status, "now_utc", lambda: datetime(2026, 11, 7, tzinfo=UTC))
    newest = record(canonical, "BACKUP", report)
    monkeypatch.setattr(backup_status, "now_utc", lambda: datetime(2026, 11, 5, tzinfo=UTC))
    previous = record(older, "BACKUP", {**report, "sequence": 2})
    source = (older / "backup_status.sqlite3").read_bytes()
    assert backup_status.merge_receipts(canonical, older) == {"source_receipts": 1, "inserted": 1, "duplicates": 0}
    assert backup_status.merge_receipts(canonical, older) == {"source_receipts": 1, "inserted": 0, "duplicates": 1}
    assert status(canonical)["latest"]["BACKUP"] == newest
    assert (older / "backup_status.sqlite3").read_bytes() == source
    with sqlite3.connect(canonical / "backup_status.sqlite3") as conn:
        assert [json.loads(body) for body, in conn.execute("SELECT body FROM receipts ORDER BY seq")] == [newest, previous]
        with pytest.raises(sqlite3.IntegrityError, match="retain"):
            conn.execute("DELETE FROM receipts")


def test_receipt_merge_validates_whole_source_before_appending(tmp_path):
    from gym.services.backup_status import merge_receipts
    report = {"encrypted": True, "authenticated": True, "verified_restore": True,
              "sequence": 1, "head_hash": "a" * 64, "file_sha256": "b" * 64, "schema_version": 1}
    target, source = tmp_path / "target", tmp_path / "source"
    record(target, "BACKUP", report)
    record(source, "BACKUP", report)
    with sqlite3.connect(source / "backup_status.sqlite3") as conn:
        conn.execute("INSERT INTO receipts(kind,body) VALUES('RESTORE','{}')")
    with pytest.raises(ValueError, match="fields"):
        merge_receipts(target, source)
    with sqlite3.connect(target / "backup_status.sqlite3") as conn:
        assert conn.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1


def test_real_roundtrip_receipts_preserve_concurrent_history_and_omit_private_fields(tmp_path):
    root = tmp_path / "workspace"
    assert status(root)["state"] == "NO_RECEIPTS" and not root.exists()
    source, bundle = tmp_path / "ledger.db", tmp_path / "saved.tgbak"
    make_ledger(source)
    backup = create_backup(source, bundle, passphrase="fixture recovery passphrase")
    restored = restore_backup(bundle, tmp_path / "restored.db", passphrase="fixture recovery passphrase")
    assert backup["head_hash"] == restored["head_hash"]
    backup["verified_restore"] = True
    backup["private_field"] = "DO-NOT-COPY"
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(record, root, kind, value) for kind, value in (("BACKUP", backup), ("RESTORE", restored))]
        for result in results:
            assert result.result()["mode_after"] == "DISARMED"
    observed = status(root)
    assert observed["state"] == "RECORDED" and all(observed["latest"].values())
    assert not observed["archive_availability_verified"] and not observed["off_machine_verified"]
    assert "DO-NOT-COPY" not in str(observed) and "destination" not in str(observed)
    with sqlite3.connect(root / "backup_status.sqlite3") as conn:
        assert conn.execute("SELECT count(*) FROM receipts").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE receipts SET body='{}'")
        with pytest.raises(sqlite3.IntegrityError, match="retain"):
            conn.execute("DELETE FROM receipts")
    with pytest.raises(ValueError):
        record(root, "BACKUP", {**backup, "verified_restore": False})


def test_backup_status_api_requires_token_and_does_not_create_receipts(tmp_path):
    db = market_db(tmp_path, quote_history(n=3))
    seg = SegmentWriter(tmp_path / "raw", db)
    async def check():
        col = Collector(db, seg, ["BTCUSDT"])
        async with TestClient(TestServer(make_app(col, RuleService(db), "tok", tmp_path / "runs"))) as client:
            assert (await client.get("/api/backup-status")).status == 403
            response = await client.get("/api/backup-status", headers={"X-Gym-Token": "tok"})
            assert response.status == 200 and response.headers["Cache-Control"] == "no-store"
            value = await response.json()
            assert value["state"] == "NO_RECEIPTS" and not value["funded_authority"]
            assert not (tmp_path / "backup_status.sqlite3").exists()
            (tmp_path / "backup_status.sqlite3").write_bytes(b"damaged receipt journal")
            response = await client.get("/api/backup-status", headers={"X-Gym-Token": "tok"})
            assert response.status == 503 and response.headers["Cache-Control"] == "no-store"
            assert await response.json() == {"state": "UNREADABLE"}
    try:
        asyncio.run(check())
    finally:
        seg.close()
        db.c.close()
