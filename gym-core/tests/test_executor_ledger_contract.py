"""Independent Python fixtures for the cross-language stored-byte ledger contract.

These tests verify shared bytes and SQLite DDL, not the Rust implementation;
Rust behavior must also pass cargo test on the actual target platform.
"""
import hashlib
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts/v1/fixtures/genesis-event.json"
SCHEMA = ROOT / "executor/exec-store/schema.sql"
GOLDEN_HASH = "d180d43ebb90c9d8f4d9d1ea683f9baa019a328f619b94ef0011968ea6dcd6db"


def test_stored_bytes_have_documented_hash():
    event = FIXTURE.read_bytes()
    digest = hashlib.sha256(bytes(32) + len(event).to_bytes(8, "big") + event).hexdigest()
    assert digest == GOLDEN_HASH
    assert hashlib.sha256(bytes(32) + (len(event) + 1).to_bytes(8, "big") + event).hexdigest() != digest


def test_sql_schema_is_append_only_with_forward_version():
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA.read_text(encoding="utf-8"))
    assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    payload = FIXTURE.read_bytes()
    digest = hashlib.sha256(bytes(32) + len(payload).to_bytes(8, "big") + payload).digest()
    db.execute("INSERT INTO ledger_events VALUES (?,?,?,?)", (1, payload, bytes(32), digest))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE ledger_events SET event_bytes=? WHERE sequence=1", (b"altered",))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM ledger_events WHERE sequence=1")
    assert db.execute("SELECT event_bytes FROM ledger_events").fetchone()[0] == payload
