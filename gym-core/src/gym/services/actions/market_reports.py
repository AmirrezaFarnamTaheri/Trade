"""Read-only market-report action handlers (technicals, spreads, trade-flow, candles)."""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from ...adapters.store import MarketDB
from ...domain.market_models import decimal, fields
from ...domain.model import now_utc, parse_ts


def _open_market_db(root: Path) -> MarketDB:
    path = root / "market.db"
    if not path.is_file():
        raise ValueError("research requires an existing market store")
    return MarketDB(path, readonly=True)


def handle_market_report(root: Path, action: str, value, store: str, at):
    """Execute bounded read-only technicals, spreads, trade-flow, and candle-crosscheck reports."""
    from ..data_portal import DataPortal
    from ..feed_crosscheck import candle_crosscheck
    from ..market_statistics import spread_report, trade_flow_report
    from ..technical_analysis import technical_reports

    fields(
        value,
        {"technicals": "symbol from to resolutions", "candles": "symbol from to as_of tolerance_bps"}.get(
            action, "symbol from to"
        ),
    )
    if not isinstance(value["from"], str) or not isinstance(value["to"], str):
        raise ValueError("report bounds must be zoned timestamps")
    start, end = parse_ts(value["from"]), parse_ts(value["to"])
    if not start < end or end - start > timedelta(days=31):
        raise ValueError("report window must be positive and at most 31 days")
    if not isinstance(value["symbol"], str) or not re.fullmatch(r"[A-Z0-9]{2,24}", value["symbol"]):
        raise ValueError("report requires one market symbol")

    db = _open_market_db(root)
    try:
        if action == "technicals":
            return technical_reports(db, value["symbol"], start, end, resolutions=value["resolutions"], store=store)
        db.c.execute("BEGIN")
        table, timestamp = ("trades", "ts_event") if action in ("trade-flow", "candles") else ("book_top", "ts_avail")
        count = db.c.execute(
            f"SELECT count(*) FROM {table} WHERE instrument_id=? "
            f"AND substr({timestamp},1,10)>=? AND substr({timestamp},1,10)<=?",
            ("wallex:" + value["symbol"], start.date().isoformat(), end.date().isoformat()),
        ).fetchone()[0]
        if count > 100000:
            raise ValueError("too many observations; narrow the report window")
        if action == "candles":
            if not isinstance(value["as_of"], str) or not isinstance(value["tolerance_bps"], str):
                raise ValueError("candle cutoff and tolerance must be strings")
            cutoff = parse_ts(value["as_of"])
            if cutoff > now_utc():
                raise ValueError("candle cutoff cannot be in the future")
            report = candle_crosscheck(
                DataPortal(db),
                value["symbol"],
                start,
                end,
                tolerance_bps=decimal(value["tolerance_bps"], "tolerance_bps"),
                as_of=cutoff,
            )
            return {**report, "store": store, "funded_authority": False, "order_submitted": False}
        return (trade_flow_report if action == "trade-flow" else spread_report)(
            db, start, end, symbol=value["symbol"], store=store
        )
    finally:
        db.c.close()
