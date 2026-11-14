"""The Version 1 runner counts every grid cell as a trial and refuses a verdict on too few sessions."""
import importlib.util
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from gym.domain.model import TEHRAN, BookTop

spec = importlib.util.spec_from_file_location("usdttmn_v1", Path(__file__).resolve().parents[1] / "scripts/usdttmn_v1.py")
v1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v1)


def session(day, mids):
    start = datetime(2026, 11, day, 11, 32, 30, tzinfo=TEHRAN)
    return [BookTop("USDTTMN", start + timedelta(minutes=5 * i), Decimal(mid) - 1, Decimal(mid) + 1,
                    Decimal(5000), Decimal(5000), frozenset()) for i, mid in enumerate(mids)]


def test_every_cell_is_a_trial_and_a_quiet_market_nets_zero_everywhere():
    days = {f"2026-11-{day:02}": session(day, [100000] * 60) for day in (4, 5, 6)}
    rows = v1.evaluate(days)
    v1.verdicts(rows)
    assert len(rows) == len(v1.FEES) * len(v1.DIRECTIONS) * len(v1.GRID) == 24
    assert all(row["net"] == [0.0, 0.0, 0.0] and row["trips"] == 0 and row["sharpe"] == 0.0 for row in rows)


def test_a_rich_then_back_session_pays_sell_rich_and_costs_more_at_the_higher_fee():
    mids = [100000] * 13 + [101000] * 2 + [100000] * 20
    rows = v1.evaluate({"2026-11-04": session(4, mids)})
    cell = {(row["fee"], row["direction"], row["lookback"], row["entry_bps"]): row["net"][0] for row in rows}
    low, high = cell[v1.FEES[0], "SELL_RICH", 12, 50], cell[v1.FEES[1], "SELL_RICH", 12, 50]
    assert low > high and low > 5
    assert cell[v1.FEES[0], "SELL_RICH", 12, 200] == 0.0


def test_too_few_sessions_is_reported_as_insufficient_not_as_a_verdict(tmp_path, capsys):
    import sqlite3
    db = tmp_path / "market.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE book_top (instrument_id, ts_avail, bid, ask, bid_qty, ask_qty, flags)")
    connection.executemany("INSERT INTO book_top VALUES ('wallex:USDTTMN',?,?,?,?,?,'')",
                           [(q.ts_avail.isoformat(), str(q.bid), str(q.ask), "5000", "5000") for q in session(4, [100000] * 20)])
    connection.commit()
    connection.close()
    assert v1.main(["--db", str(db), "--all-sessions"]) == 0
    assert "VERDICT: INSUFFICIENT_SESSIONS (1 of 30)" in capsys.readouterr().out
    assert v1.main(["--db", str(db)]) == 1  # the only session is incomplete
