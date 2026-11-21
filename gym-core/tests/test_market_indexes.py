"""Market schema upgrades preserve replay rows and enable bounded range searches."""
import sqlite3
from contextlib import closing
from datetime import timedelta
from decimal import Decimal

from gym.adapters.store import MIGRATIONS, MarketDB
from gym.domain.model import TradeTick, iso
from gym.services.data_portal import DataPortal
from tests.support import START


def test_market_schema_upgrade_preserves_trade_order_and_indexes_ranges(tmp_path):
    path = tmp_path / "market.db"
    end = START + timedelta(minutes=1)
    ticks = [TradeTick("BTCUSDT", START, START, Decimal(price), Decimal(1), "BUY") for price in (2, 1)]
    with closing(sqlite3.connect(path)) as old:
        old.executescript("".join(MIGRATIONS[:5]) + "PRAGMA user_version=5;")
        old.executemany("INSERT INTO trades VALUES(?,?,?,?,?,?,?)", [
            ("wallex:BTCUSDT", iso(t.ts_event), iso(t.ts_avail), str(t.price), "1", "BUY", "raw") for t in ticks
        ])
        old.commit()

    with closing(MarketDB(path).c) as connection:
        queries = (
            ("SELECT * FROM trades WHERE instrument_id=? AND ts_event>=? AND ts_event<? ORDER BY ts_event,rowid",
             ("wallex:BTCUSDT", iso(START), iso(end)), "trades_event"),
            ("SELECT COUNT(*) FROM book_top WHERE ts_avail>=? AND ts_avail<?",
             (iso(START), iso(end)), "book_top_time"),
        )
        for sql, params, index in queries:
            plan = connection.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
            assert any("SEARCH" in row[3] and index in row[3] for row in plan), plan
    db = MarketDB(path, readonly=True)
    with closing(db.c):
        assert DataPortal(db).trades_by_event("BTCUSDT", START, end) == ticks


def test_pre_side_reference_schema_is_readable_without_upgrading_live_database(tmp_path):
    from gym.services.replay_input_audit import audit_replay_inputs

    path = tmp_path / "market.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("".join(MIGRATIONS[:6]) + "PRAGMA user_version=6;")
        connection.execute("INSERT INTO book_top(instrument_id,ts_avail,bid,ask) VALUES(?,?,?,?)",
                           ("wallex:BTCUSDT", iso(START), "1", "2"))
        connection.commit()
    db = MarketDB(path, readonly=True)
    with closing(db.c):
        result = audit_replay_inputs(db, [], "BTCUSDT", START, START + timedelta(seconds=1))
        assert result["book_rows"] == 1 and not result["verified"]
        assert db.c.execute("PRAGMA user_version").fetchone()[0] == 6
