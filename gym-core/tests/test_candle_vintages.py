"""Actual stored revisions remain point-in-time and latest projection never regresses."""
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.store import MIGRATIONS, MarketDB
from gym.domain.model import iso
from gym.services.data_portal import DataPortal
from tests.support import START


def candle(value="100"):
    return {"t": START, **{k: Decimal(value) for k in "ohlc"}, "v": Decimal(1)}


def test_corrections_are_retained_and_exclusive_cutoffs_select_old_knowledge(tmp_path):
    db = MarketDB(tmp_path / "market.db")
    try:
        first, revised = START + timedelta(minutes=2), START + timedelta(minutes=3)
        db.upsert_candles("BTCUSDT", "1min", [candle()], first)
        db.upsert_candles("BTCUSDT", "1min", [candle("101")], revised)
        portal = DataPortal(db)
        def read(at):
            return portal.venue_candles("BTCUSDT", "1min", START, revised, as_of=at)
        assert read(first) == []
        assert read(revised)[0]["c"] == 100
        assert read(revised + timedelta(seconds=1))[0]["c"] == 101
        db.upsert_candles("BTCUSDT", "1min", [candle("99")], first - timedelta(seconds=1))
        assert read(None)[0]["c"] == 101
        assert db.c.execute("SELECT c FROM venue_candles").fetchone()[0] == "101"
        db.upsert_candles("BTCUSDT", "1min", [candle("101")], revised)
        assert db.c.execute("SELECT count(*) FROM candle_vintages").fetchone()[0] == 3
        with pytest.raises(ValueError, match="conflicting"):
            db.upsert_candles("BTCUSDT", "1min", [candle("999")], revised)
        with pytest.raises(sqlite3.IntegrityError):
            db.c.execute("DELETE FROM candle_vintages")
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_old_database_migration_preserves_only_genuinely_retained_fetch(tmp_path):
    path = tmp_path / "market.db"
    connection = sqlite3.connect(path)
    connection.executescript(MIGRATIONS[0] + MIGRATIONS[1] + "PRAGMA user_version=2;")
    row = ("wallex:BTCUSDT", "1min", iso(START), "1", "1", "1", "1", "1", iso(START + timedelta(minutes=2)))
    connection.execute("INSERT INTO venue_candles VALUES(?,?,?,?,?,?,?,?,?)", row)
    connection.commit()
    connection.close()
    db = MarketDB(path)
    try:
        assert db.c.execute("SELECT * FROM candle_vintages").fetchall() == [row]
        assert db.c.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    finally:
        db.c.close()


@pytest.mark.parametrize("version", [2, 4, 999])
def test_readonly_market_requires_current_schema_without_mutating_old_store(tmp_path, version):
    path = tmp_path / "market.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("".join(MIGRATIONS[:version]))
        connection.execute(f"PRAGMA user_version={version}")
    with pytest.raises(ValueError, match="market schema"):
        MarketDB(path, readonly=True)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == version
    if version < len(MIGRATIONS):
        migrated = MarketDB(path)
        migrated.c.close()
        reader = MarketDB(path, readonly=True)
        assert DataPortal(reader).publication() is None
        reader.c.close()


def test_writable_market_refuses_future_schema_without_rewriting_version(tmp_path):
    path = tmp_path / "market.db"
    db = MarketDB(path)
    db.c.execute("PRAGMA user_version=999")
    db.c.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    with pytest.raises(ValueError, match="market schema"):
        MarketDB(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 999
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
