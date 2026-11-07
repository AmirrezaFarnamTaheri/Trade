"""Actual authenticated backup/restore receipts are bounded, private and observational."""
import asyncio
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
