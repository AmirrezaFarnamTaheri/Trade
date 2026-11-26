"""Tests for daily idempotent mix-journal-v2 recorder and cross-venue arb audit."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from record_mix_journal_v2 import MIX_V2_SYMBOLS, record_daily_mix_v2  # noqa: E402

T0 = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def _seed_market_db(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE instruments (instrument_id INTEGER PRIMARY KEY, symbol TEXT)")
    con.execute("CREATE TABLE venue_candles (instrument_id INTEGER, resolution TEXT, t TEXT, o TEXT, h TEXT, l TEXT, c TEXT)")
    con.execute("CREATE TABLE book_top (instrument_id INTEGER, ts_avail TEXT, bid TEXT, ask TEXT, bid_qty TEXT, ask_qty TEXT, depth TEXT)")
    for idx, sym in enumerate(MIX_V2_SYMBOLS, start=1):
        con.execute("INSERT INTO instruments VALUES (?, ?)", (idx, sym))
        for d in range(85):
            ts = (T0 + timedelta(days=d)).isoformat().replace("+00:00", "Z")
            px = 100.0 + d * 0.5
            con.execute(
                "INSERT INTO venue_candles VALUES (?, '1d', ?, ?, ?, ?, ?)",
                (idx, ts, str(px), str(px * 1.01), str(px * 0.99), str(px * 1.005)),
            )
        depth = json.dumps([[["140", "20"], ["139", "30"]], [["141", "20"], ["142", "30"]]])
        con.execute(
            "INSERT INTO book_top VALUES (?, ?, '140', '141', '20', '20', ?)",
            (idx, (T0 + timedelta(days=84)).isoformat().replace("+00:00", "Z"), depth),
        )
    con.commit()
    con.close()


def test_mix_journal_v2_recorder_is_idempotent_and_refuses_v1(tmp_path):
    db_path = tmp_path / "market.db"
    _seed_market_db(db_path)

    with pytest.raises(ValueError, match="v1 control"):
        record_daily_mix_v2(db_path, tmp_path / "mix-journal.jsonl", as_of=T0 + timedelta(days=85))

    v2 = tmp_path / "mix-journal-v2.jsonl"
    r1 = record_daily_mix_v2(db_path, v2, as_of=T0 + timedelta(days=85))
    assert r1["status"] == "RECORDED" and r1["entries_written"] == len(MIX_V2_SYMBOLS)

    # Same UTC day must be idempotent (0 new rows written)
    r2 = record_daily_mix_v2(db_path, v2, as_of=T0 + timedelta(days=85, hours=3))
    assert r2["status"] == "ALREADY_RECORDED" and r2["entries_written"] == 0

    # Next UTC day writes 5 new rows preserving original start_date
    r3 = record_daily_mix_v2(db_path, v2, as_of=T0 + timedelta(days=86))
    assert r3["status"] == "RECORDED" and r3["entries_written"] == len(MIX_V2_SYMBOLS)
    rows = [json.loads(line) for line in v2.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 * len(MIX_V2_SYMBOLS)
    assert len({r["start_date"] for r in rows}) == 1
