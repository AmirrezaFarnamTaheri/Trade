"""Read-only SQLite candle reader adapter keyed by instrument_id."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.model import BookTop, TradeTick, dec, parse_ts
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


def _parse_depth_json(depth_raw: str | None, symbol: str, ts_a: str):
    if not depth_raw:
        return None
    try:
        return json.loads(depth_raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed depth JSON for {symbol} at {ts_a}: {exc}") from exc


def load_book_and_trades(
    con: sqlite3.Connection,
    symbol: str,
    since_iso: str,
    *,
    until_iso: str | None = None,
    max_books: int = 8000,
    max_trades: int = 12000,
) -> tuple[list[BookTop], list[TradeTick]]:
    """Load bounded chronological book_top snapshots and trades for one symbol."""
    row = con.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (symbol,)).fetchone()
    if row is None:
        return [], []
    inst_id = row[0]
    if until_iso is not None:
        b_rows = con.execute(
            "SELECT ts_avail, bid, ask, bid_qty, ask_qty, flags, depth "
            "FROM book_top WHERE instrument_id = ? AND ts_avail >= ? AND ts_avail <= ? "
            "ORDER BY ts_avail DESC LIMIT ?",
            (inst_id, since_iso, until_iso, max_books),
        ).fetchall()
        t_rows = con.execute(
            "SELECT ts_event, ts_avail, price, qty, aggressor "
            "FROM trades WHERE instrument_id = ? AND ts_avail >= ? AND ts_avail <= ? "
            "ORDER BY ts_avail DESC LIMIT ?",
            (inst_id, since_iso, until_iso, max_trades),
        ).fetchall()
    else:
        b_rows = con.execute(
            "SELECT ts_avail, bid, ask, bid_qty, ask_qty, flags, depth "
            "FROM book_top WHERE instrument_id = ? AND ts_avail >= ? ORDER BY ts_avail DESC LIMIT ?",
            (inst_id, since_iso, max_books),
        ).fetchall()
        t_rows = con.execute(
            "SELECT ts_event, ts_avail, price, qty, aggressor "
            "FROM trades WHERE instrument_id = ? AND ts_avail >= ? ORDER BY ts_avail DESC LIMIT ?",
            (inst_id, since_iso, max_trades),
        ).fetchall()
    b_rows.reverse()
    books = [
        BookTop(
            symbol=symbol,
            ts_avail=parse_ts(ts_a),
            bid=dec(bid) if bid is not None else None,
            ask=dec(ask) if ask is not None else None,
            bid_qty=dec(bq) if bq is not None else None,
            ask_qty=dec(aq) if aq is not None else None,
            flags=frozenset(f.strip() for f in str(flags_raw).split(",") if f.strip()) if flags_raw else frozenset(),
            depth=_parse_depth_json(depth_raw, symbol, ts_a),
        )
        for ts_a, bid, ask, bq, aq, flags_raw, depth_raw in b_rows
    ]
    t_rows.reverse()
    trades = [
        TradeTick(
            symbol=symbol,
            ts_event=parse_ts(ts_e),
            ts_avail=parse_ts(ts_a),
            price=dec(px),
            qty=dec(qty),
            aggressor=str(agg),
        )
        for ts_e, ts_a, px, qty, agg in t_rows
        if px is not None and qty is not None
    ]
    return books, trades
