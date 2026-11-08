"""Sanitized account observations survive restart without becoming authority."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

import gym.services.external_journal as journal_mod
from gym.domain.account_observations import project_account
from gym.services.external_journal import ExternalJournal


def snapshot(at="2026-11-03T12:00:00Z", *, orders=None):
    return project_account("main", at, balances={"USDT": {"value": "10.20", "locked": "1"}},
                           orders=orders)


def test_balance_and_fee_snapshot_survives_restart_with_unverified_provenance(tmp_path):
    path = tmp_path / "journal.db"
    data = snapshot()
    data["api_key"] = "DO-NOT-COPY"
    data["balances"][0]["private"] = "DO-NOT-COPY"
    fees = {"BTCUSDT": {"maker": "0.001", "taker": "0.002", "token": "DO-NOT-COPY"}}
    with ExternalJournal(path) as journal:
        assert journal.record(data, fee_rates=fees, transport="EXECUTOR_SERVICE_WINHTTP") == 0
        assert journal.events() == []
    with ExternalJournal(path) as journal:
        saved = journal.latest_snapshot()
        assert saved["balances"][0]["venue_value"] == "10.20"
        assert saved["balances"][0]["spendable"] is None
        assert saved["fee_rates"] == {"BTCUSDT": {"maker": "0.001", "taker": "0.002"}}
        assert saved["transport"] == "EXECUTOR_SERVICE_WINHTTP"
        assert saved["permission_status"] == "UNVERIFIED"
        assert saved["funded_authority"] is False
        stored = journal.conn.execute("SELECT snapshot_json FROM external_account_snapshots").fetchone()[0]
        assert "DO-NOT-COPY" not in stored and "api_key" not in stored


def test_snapshot_staleness_is_checked_even_without_orders(tmp_path):
    with ExternalJournal(tmp_path / "journal.db") as journal:
        journal.record(snapshot("2026-11-03T12:02:00Z"))
        with pytest.raises(ValueError, match="stale"):
            journal.record(snapshot("2026-11-03T12:01:00Z"))
        assert journal.latest_snapshot()["observed_at"] == "2026-11-03T12:02:00Z"
        assert journal.latest_snapshot("subaccount:other") is None


def test_snapshot_and_order_append_are_one_transaction(tmp_path):
    with ExternalJournal(tmp_path / "journal.db") as journal:
        journal.record(snapshot())
        journal.conn.executescript("""
            CREATE TRIGGER force_snapshot_failure BEFORE INSERT ON external_account_snapshots
            BEGIN SELECT RAISE(ABORT, 'snapshot test failure'); END;
        """)
        with pytest.raises(sqlite3.DatabaseError, match="snapshot test failure"):
            journal.record(snapshot("2026-11-03T12:01:00Z", orders=[{
                "client_id": "manual-1", "status": "NEW", "filled": "0",
            }]))
        assert journal.events() == []
        assert journal.latest_snapshot()["observed_at"] == "2026-11-03T12:00:00Z"


def test_legacy_order_history_migrates_atomically_and_remains_immutable(tmp_path):
    path = tmp_path / "journal.db"
    with sqlite3.connect(path) as db:
        db.executescript(journal_mod.SCHEMA)
        db.execute("INSERT INTO external_order_events(account_id,client_id,observed_at,raw_status,"
                   "filled_observed,settlement,economic_effect,authority) VALUES(?,?,?,?,?,?,?,?)",
                   ("main", "manual-1", "2026-11-03T12:01:00.000000+00:00", "NEW", "0", "UNKNOWN", "UNVERIFIED", "READ_ONLY"))
    with ExternalJournal(path) as journal:
        assert journal.conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert journal.events()[0]["client_id"] == "manual-1"
        assert journal.latest_snapshot() is None
        with pytest.raises(ValueError, match="stale"):
            journal.record(snapshot())
        journal.record(snapshot("2026-11-03T12:02:00Z"))
        for table in ("external_order_events", "external_account_snapshots"):
            for action in (f"DELETE FROM {table}", f"UPDATE {table} SET account_id='fake'"):
                with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                    journal.conn.execute(action)
                journal.conn.rollback()


def test_failed_v1_migration_keeps_old_database_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "journal.db"
    with sqlite3.connect(path) as db:
        db.executescript(journal_mod.SCHEMA)
    monkeypatch.setattr(journal_mod, "SNAPSHOT_SCHEMA", journal_mod.SNAPSHOT_SCHEMA.replace(
        "CREATE INDEX", "INVALID SQL; CREATE INDEX",
    ))
    with pytest.raises(sqlite3.DatabaseError):
        ExternalJournal(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='external_account_snapshots'").fetchone() is None


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(funded_authority=True),
    lambda data: data.update(permission_status="VERIFIED"),
    lambda data: data["balances"][0].update(spendable="9"),
    lambda data: data["balances"].append(dict(data["balances"][0])),
    lambda data: data.update(balances={}),
])
def test_forged_snapshot_authority_or_duplicate_assets_is_rejected(tmp_path, mutate):
    with ExternalJournal(tmp_path / "journal.db") as journal:
        data = snapshot()
        mutate(data)
        with pytest.raises(ValueError):
            journal.record(data)
        assert journal.latest_snapshot() is None


def test_invalid_fee_or_transport_is_not_persisted(tmp_path):
    with ExternalJournal(tmp_path / "journal.db") as journal:
        with pytest.raises(ValueError):
            journal.record(snapshot(), fee_rates={"BTCUSDT": {"maker": "NaN", "taker": "0.002"}})
        with pytest.raises(ValueError):
            journal.record(snapshot(), transport="DO-NOT-COPY")
        assert journal.latest_snapshot() is None


def test_snapshot_exposure_is_sanitized_and_never_protectable(tmp_path):
    data = project_account("main", "2026-11-03T12:00:00Z", exposure=[{
        "account_id": "subaccount:credit-1", "product": "TRADE_CREDIT",
        "obligation_asset": "USDT", "obligation": "2.5", "token": "DO-NOT-COPY",
    }])
    data["exposure"][0]["token"] = "DO-NOT-COPY"
    with ExternalJournal(tmp_path / "journal.db") as journal:
        journal.record(data)
        saved = journal.latest_snapshot()
        assert saved["exposure"][0]["obligation"] == "2.5"
        assert saved["exposure"][0]["managed"] is False
        assert saved["exposure"][0]["protectable"] is None
        assert "DO-NOT-COPY" not in json.dumps(saved)


def test_snapshot_load_refuses_corrupt_indexed_identity_or_timestamp(tmp_path):
    data = snapshot()
    with ExternalJournal(tmp_path / "journal.db") as journal:
        journal.conn.execute(
            "INSERT INTO external_account_snapshots(account_id,observed_at,snapshot_json) VALUES(?,?,?)",
            ("main", "2026-11-03T12:01:00.000000+00:00", json.dumps(data)),
        )
        journal.conn.commit()
        with pytest.raises(ValueError, match="invalid persisted"):
            journal.latest_snapshot()


@pytest.mark.parametrize("version", [0, 1])
def test_concurrent_open_serializes_schema_creation_and_v1_migration(tmp_path, monkeypatch, version):
    path = tmp_path / "journal.db"
    connect = sqlite3.connect
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        if version == 1:
            db.executescript(journal_mod.SCHEMA)
    starting, unlocked_reads = Barrier(2), Barrier(2)

    class SynchronizedConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            cursor = super().execute(sql, *args, **kwargs)
            if sql == "PRAGMA user_version" and not self.in_transaction:
                # Force both old constructors to observe the old version before either migrates.
                observed = cursor.fetchone()
                unlocked_reads.wait(timeout=5)
                return SimpleNamespace(fetchone=lambda: observed)
            return cursor

    monkeypatch.setattr(journal_mod.sqlite3, "connect", lambda *args, **kwargs:
                        connect(*args, **kwargs, factory=SynchronizedConnection))

    def open_journal():
        starting.wait(timeout=5)
        with ExternalJournal(path) as journal:
            assert not journal.conn.in_transaction
            return journal.latest_snapshot()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(open_journal) for _ in range(2)]
        assert [future.result(timeout=12) for future in futures] == [None, None]
    with connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_unknown_future_schema_is_refused_without_modification(tmp_path):
    path = tmp_path / "journal.db"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="unsupported"):
        ExternalJournal(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 999
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


@pytest.mark.parametrize("version", [0, 1])
def test_migration_guard_failure_rolls_back_schema_and_version(tmp_path, monkeypatch, version):
    path = tmp_path / "journal.db"
    if version == 1:
        with sqlite3.connect(path) as db:
            db.executescript(journal_mod.SCHEMA)
    monkeypatch.setattr(journal_mod, "SNAPSHOT_SCHEMA", journal_mod.SNAPSHOT_SCHEMA.replace(
        "external_accounts_no_delete", "wrong_account_guard",
    ))
    with pytest.raises(ValueError, match="immutability"):
        ExternalJournal(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == version
        assert db.execute("SELECT name FROM sqlite_master WHERE name='external_account_snapshots'").fetchone() is None


@pytest.mark.parametrize("attempt", range(4))
def test_concurrent_first_open_on_new_database(tmp_path, attempt):
    starting = Barrier(2)
    path = tmp_path / "new.db"

    def open_journal():
        starting.wait(timeout=5)
        with ExternalJournal(path) as journal:
            return journal.conn.execute("PRAGMA user_version").fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(open_journal) for _ in range(2)]
        assert [future.result(timeout=12) for future in futures] == [2, 2]


def test_wal_setup_stops_retrying_at_deadline(tmp_path, monkeypatch):
    connect = sqlite3.connect
    attempts = []

    class BusyConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "PRAGMA journal_mode=WAL":
                attempts.append(sql)
                error = sqlite3.OperationalError("database is locked")
                error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                raise error
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(journal_mod.sqlite3, "connect", lambda *args, **kwargs:
                        connect(*args, **kwargs, factory=BusyConnection))
    times = iter((0, 6))
    monkeypatch.setattr(journal_mod, "monotonic", lambda: next(times))
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        ExternalJournal(tmp_path / "journal.db")
    assert len(attempts) == 1
