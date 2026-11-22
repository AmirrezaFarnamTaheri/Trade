"""Market schema upgrades preserve replay rows and enable bounded range searches."""
import json
import sqlite3
from contextlib import closing
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.store import MIGRATIONS, MarketDB, SegmentWriter
from gym.domain.model import TradeTick, iso
from gym.services.data_portal import DataPortal
from gym.services.replay_input_audit import audit_replay_inputs
from gym.services.research_actions import research_action
from tests.support import START, quote


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


@pytest.mark.parametrize("source,raw_ask,side_refs,matched,legacy", [
    ("REST", "101", False, 2, 2),
    ("REST", "102", False, 1, 1),
    ("REST_UNBOUND", "101", False, 0, 0),
    ("WS", "101", False, 2, 2),
    ("WS_BID_ONLY", "101", False, 1, 1),
    ("REST", "101", True, 1, 0),
])
def test_legacy_reference_only_proves_labelled_book_sides(tmp_path, source, raw_ask, side_refs, matched, legacy):
    db = MarketDB(tmp_path / "market.db")
    root = tmp_path / "raw"
    writer = SegmentWriter(root, db)
    bids = [{"price": "99", "quantity": "1"}]
    asks = [{"price": raw_ask, "quantity": "1"}]
    with closing(db.c), closing(writer):
        if source.startswith("REST"):
            endpoint = "rest:/v1/depth?symbol=BTCUSDT" if source == "REST" else "rest:/v1/depth"
            ref = writer.write(endpoint, json.dumps({"result": {"bid": bids, "ask": asks}}), START)
        else:
            messages = [json.dumps({"push": {"channel": f"orderbook:BTCUSDT@{side}Depth", "pub": {"data": rows}}})
                        for side, rows in (("buy", bids), ("sell", asks))]
            if source == "WS_BID_ONLY":
                messages.pop()
            ref = writer.write("ws", "\n".join(messages), START)
        writer.close()
        db.add_book_top(quote(START, "99", "101"), ref, side_refs=(ref, None) if side_refs else (None, None))
        result = audit_replay_inputs(db, [root], "BTCUSDT", START, START + timedelta(seconds=1))
        assert result["book_sides_matched"] == matched
        assert result["legacy_book_sides_matched"] == legacy
        assert result["verified"] is (matched == 2)
        if source == "REST_UNBOUND":
            assert result["broken"] == [{"reason": "UNBOUND_REST_SYMBOL", "ref": ref}]


def test_raw_replay_audit_can_read_relocated_archive(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    archive = tmp_path / "archive"
    db = MarketDB(root / "market.db")
    writer = SegmentWriter(archive, db)
    with closing(db.c), closing(writer):
        raw = {"result": {"bid": [{"price": "99", "quantity": "1"}], "ask": [{"price": "101", "quantity": "1"}]}}
        ref = writer.write("rest:/v1/depth?symbol=BTCUSDT", json.dumps(raw), START)
        db.add_book_top(quote(START, "99", "101"), ref)
    value = {"symbol": "BTCUSDT", "from": iso(START), "to": iso(START + timedelta(seconds=1))}
    absent = research_action(root, "raw-replay-audit", value)
    assert [item["reason"] for item in absent["broken"]] == ["MISSING_FILE"]
    located = research_action(root, "raw-replay-audit", {**value, "archives": [str(archive)]})
    assert located["verified"] and located["legacy_book_sides_matched"] == 2
    with pytest.raises(ValueError, match="archive directory paths"):
        research_action(root, "raw-replay-audit", {**value, "archives": str(archive)})
