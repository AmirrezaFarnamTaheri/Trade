"""Tests for S1+S5 prospective forward journal and live Wallex vs Nobitex execution-cost audit."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from gym.services.experiments.leader_forward_journal import record_s1_s5_leader_journal
from gym.services.experiments.venue_execution_audit import (
    run_venue_execution_cost_audit,
)


def test_venue_execution_cost_audit_computes_spread_depth_and_savings(tmp_path: Path) -> None:
    wdb = tmp_path / "wallex.sqlite3"
    mdb = tmp_path / "multi.sqlite3"
    report = tmp_path / "report.md"
    receipt = tmp_path / "receipt.json"

    wcon = sqlite3.connect(wdb)
    wcon.execute("CREATE TABLE instruments (instrument_id INTEGER PRIMARY KEY, symbol TEXT)")
    wcon.execute(
        "CREATE TABLE book_top (instrument_id INTEGER, ts_avail TEXT, bid TEXT, ask TEXT, "
        "bid_qty TEXT, ask_qty TEXT, depth TEXT)"
    )
    wcon.execute("INSERT INTO instruments VALUES (1, 'BTCUSDT')")
    wcon.execute(
        "INSERT INTO book_top VALUES (1, '2026-11-24T10:00:00Z', '100000', '100300', '0.01', '0.01', "
        "'[[[\"100000\",\"0.05\"]],[[\"100300\",\"0.05\"]]]')"
    )
    wcon.commit()
    wcon.close()

    mcon = sqlite3.connect(mdb)
    mcon.execute(
        "CREATE TABLE venue_quotes (venue TEXT, symbol TEXT, ts_avail TEXT, bid TEXT, ask TEXT, "
        "bid_qty TEXT, ask_qty TEXT, depth_json TEXT)"
    )
    mcon.execute(
        "INSERT INTO venue_quotes VALUES ('nobitex', 'BTCUSDT', '2026-11-24T10:00:05Z', '100140', '100180', "
        "'0.2', '0.2', '[[[\"100140\",\"0.5\"]],[[\"100180\",\"0.5\"]]]')"
    )
    mcon.commit()
    mcon.close()

    res = run_venue_execution_cost_audit(wdb, mdb, report, receipt)
    assert len(res["symbols"]) == 1
    row = res["symbols"][0]
    assert row["symbol"] == "BTCUSDT"
    assert row["matched_pairs"] == 1
    assert row["wallex_median_spread_bps"] > row["nobitex_median_spread_bps"]
    assert row["oneway_taker_saving_bps"] > 10.0
    assert report.is_file() and receipt.is_file()


def test_leader_forward_journal_refuses_v1_control_path(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="v1 control"):
        record_s1_s5_leader_journal(tmp_path / "market.db", tmp_path / "mix-journal.jsonl")


def test_leader_forward_journal_writes_registration_and_handles_missing_candles(tmp_path: Path) -> None:
    db = tmp_path / "market.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE instruments (instrument_id INTEGER PRIMARY KEY, symbol TEXT)")
    con.execute("CREATE TABLE venue_candles (instrument_id INTEGER, resolution TEXT, t TEXT, o TEXT, h TEXT, l TEXT, c TEXT, v TEXT)")
    con.commit()
    con.close()

    reg = tmp_path / "reg.json"
    res = record_s1_s5_leader_journal(
        db, tmp_path / "s1-s5-leader-journal.jsonl", registration_path=reg, as_of=datetime(2026, 11, 24, tzinfo=UTC)
    )
    assert res["status"] == "INSUFFICIENT_CANDLES"
    reg_data = json.loads(reg.read_text(encoding="utf-8"))
    assert reg_data["strategy_id"] == "S1_S5_DROP_S2_ADMM_LEADER"
    assert reg_data["funded_authority"] is False
    assert reg_data["executor_state"] == "DISARMED"
