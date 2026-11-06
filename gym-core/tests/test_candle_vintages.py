"""Actual stored revisions remain point-in-time and latest projection never regresses."""
from datetime import timedelta
from decimal import Decimal
import sqlite3

import pytest

from gym.adapters.store import MarketDB, MIGRATIONS
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
