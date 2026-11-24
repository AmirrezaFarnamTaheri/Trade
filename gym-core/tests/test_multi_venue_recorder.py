"""Tests for Phase B read-only quote recorder and candidate evaluation helpers."""
from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from gym.domain.venue_contracts import QuoteSnapshot

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from record_multi_venue_quotes import (  # noqa: E402
    compare_live_wallex_vs_nobitex,
    init_quote_db,
    persist_quote_snapshot,
)

T0 = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def test_multi_venue_db_persistence_and_wallex_nobitex_arb_comparison(tmp_path):
    db_path = tmp_path / "multi_venue.sqlite3"
    con = init_quote_db(db_path)
    qs = QuoteSnapshot(
        venue="nobitex",
        symbol="BTCUSDT",
        ts_event=None,
        ts_avail=T0,
        bid=Decimal("99900"),
        ask=Decimal("100000"),
        bid_qty=Decimal("1.5"),
        ask_qty=Decimal("2.0"),
        bid_levels=((Decimal("99900"), Decimal("1.5")),),
        ask_levels=((Decimal("100000"), Decimal("2.0")),),
        flags=frozenset(),
    )
    persist_quote_snapshot(con, qs)
    count = con.execute("SELECT COUNT(*) FROM venue_quotes WHERE venue='nobitex' AND symbol='BTCUSDT'").fetchone()[0]
    con.close()
    assert count == 1

    # Mock Wallex market.db with BTCUSDT bid at 100500 (50 bps above Nobitex ask)
    wlx_db = tmp_path / "market.db"
    wcon = sqlite3.connect(wlx_db)
    wcon.execute("CREATE TABLE instruments (instrument_id INTEGER PRIMARY KEY, symbol TEXT)")
    wcon.execute("CREATE TABLE book_top (instrument_id INTEGER, ts_avail TEXT, bid TEXT, ask TEXT)")
    wcon.execute("INSERT INTO instruments VALUES (1, 'BTCUSDT')")
    wcon.execute("INSERT INTO book_top VALUES (1, '2026-11-24T12:00:00Z', '100500', '100600')")
    wcon.commit()
    wcon.close()

    arbs = compare_live_wallex_vs_nobitex(wlx_db, [qs])
    assert len(arbs) == 1
    assert arbs[0]["best_direction"] == "BUY_NBX_SELL_WLX"
    assert arbs[0]["raw_cross_gap_bps"] == 50.0
    assert arbs[0]["net_after_fees_per_unit"] > 0
