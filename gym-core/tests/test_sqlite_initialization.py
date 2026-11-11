"""Concurrent openers must inspect schema versions under the migration lock."""
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from gym.adapters.store import MarketDB
from gym.services.offline_review_journal import OfflineReviewJournal, ReviewUnsafe
from gym.services.research_ledger import ResearchLedger
from gym.services.research_protocol import ResearchProtocol
from tests.test_offline_review_journal import preview


@pytest.mark.parametrize("kind", ["market", "research", "protocol", "offline"])
def test_concurrent_first_open_serializes_schema_inspection(tmp_path, monkeypatch, kind):
    path = tmp_path / ("research_protocol.sqlite3" if kind == "protocol" else "store.db")
    connect = sqlite3.connect
    seed = connect(path)
    seed.execute("PRAGMA journal_mode=WAL")
    seed.close()
    barrier = threading.Barrier(2)
    local = threading.local()

    class ConcurrentConnection(sqlite3.Connection):
        waited = False

        def _wait(self, sql):
            if not self.waited and sql.strip().upper().startswith("BEGIN"):
                self.waited = True
                barrier.wait(timeout=5)

        def execute(self, sql, *args):
            self._wait(sql)
            return super().execute(sql, *args)

        def executescript(self, sql):
            self._wait(sql)
            return super().executescript(sql)

    def tracked_connect(*args, **kwargs):
        conn = connect(*args, **kwargs, factory=ConcurrentConnection)
        local.connections.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)

    def open_store():
        local.connections = []
        try:
            if kind == "market":
                MarketDB(path)
            elif kind == "research":
                ResearchLedger(path)
            elif kind == "protocol":
                ResearchProtocol(tmp_path)
            else:
                OfflineReviewJournal(path)
        finally:
            for conn in local.connections:
                conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(open_store) for _ in range(2)]
        for result in results:
            result.result()


@pytest.mark.parametrize("kind", ["market", "research", "protocol", "offline"])
def test_first_open_retries_transient_wal_lock(tmp_path, monkeypatch, kind):
    connect = sqlite3.connect
    failures = []

    class BusyConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.strip().upper() == "PRAGMA JOURNAL_MODE=WAL" and not failures:
                failures.append(True)
                error = sqlite3.OperationalError("database is locked")
                error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                raise error
            return super().execute(sql, *args)

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: connect(*a, **kw, factory=BusyConnection))
    path = tmp_path / "store.db"
    if kind == "market":
        store = MarketDB(path)
        store.c.close()
    else:
        if kind == "research":
            store = ResearchLedger(path)
        elif kind == "protocol":
            store = ResearchProtocol(tmp_path)
        else:
            store = OfflineReviewJournal(path)
        store.conn.close()
    assert failures == [True]


def test_offline_verification_uses_one_read_snapshot(tmp_path):
    path = tmp_path / "reviews.db"
    with OfflineReviewJournal(path) as writer, OfflineReviewJournal(path) as reader:
        conn = reader.conn

        class ConcurrentReview:
            fired = False

            def execute(self, sql, *args):
                if "FROM ticket_review_events ORDER BY sequence" in sql and not self.fired:
                    self.fired = True
                    key = writer.record(preview())
                    writer.review(key, "REJECT", at="2026-11-01T08:00:11Z")
                return conn.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(conn, name)

        reader.conn = ConcurrentReview()
        try:
            reader._verify()
        except ReviewUnsafe as error:
            pytest.fail(f"valid concurrent review was reported as corruption: {error}")
        finally:
            reader.conn = conn
        assert reader.tickets()[0]["state"] == "REJECTED_OFFLINE"
