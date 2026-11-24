"""Read-only SQLite candle reader adapter keyed by instrument_id."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..domain.timeframe_panel import BarPoint, build_bar_points_from_rows


def open_readonly_market_db(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=10.0)


def load_keyed_candles(
    con: sqlite3.Connection,
    symbol: str,
    resolution: str,
    *,
    limit: int = 25000,
) -> list[BarPoint]:
    """Seek directly on (instrument_id, resolution, t) and return domain BarPoint records."""
    inst = con.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (symbol,)).fetchone()
    if inst is None:
        return []
    rows = con.execute(
        "SELECT t, o, h, l, c, v FROM venue_candles "
        "WHERE instrument_id = ? AND resolution = ? ORDER BY t DESC LIMIT ?",
        (inst[0], resolution, limit),
    ).fetchall()
    rows.reverse()
    return build_bar_points_from_rows(symbol, resolution, rows)
