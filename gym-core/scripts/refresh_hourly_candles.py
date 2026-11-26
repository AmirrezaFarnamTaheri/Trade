"""Refresh hourly (1h) Wallex venue candles for the active TradingGYM champion universe.

Uses the exact MarketDB + SegmentWriter + Collector.fetch_candles pipeline so raw venue
responses and candle vintages remain intact while keeping 1h / 2h forward panels fresh.
Strictly public market-data reads only; DISARMED / zero order authority.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gym.adapters import wallex
from gym.adapters.store import MarketDB, SegmentWriter
from gym.domain.model import iso, now_utc, parse_ts
from gym.domain.multi_asset_research import BASE_13_SYMBOLS
from gym.services.collector import Collector
from gym.services.experiments.ignition_expansion_study import IGNITION_18_CRYPTO

DEFAULT_HOURLY_SYMBOLS: tuple[str, ...] = tuple(
    dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO + ("PAXGUSDT", "SLVONUSDT"))
)
HISTORY_PAGE_HOURS = 480


def compute_catchup_window(
    last_ts: datetime | None,
    now: datetime,
    *,
    lookback_hours: int = 48,
    max_catchup_days: int = 14,
) -> tuple[datetime, datetime]:
    """Compute a bounded UTC [start, end] fetch window that catches up stale 1h candles safely."""
    floor_start = now - timedelta(days=max_catchup_days)
    min_window_start = now - timedelta(hours=lookback_hours)
    if last_ts is None:
        return floor_start, now
    candidate = min(last_ts - timedelta(hours=2), min_window_start)
    return max(floor_start, candidate), now


def _latest_1h_by_symbol(db: MarketDB, symbols: tuple[str, ...]) -> dict[str, datetime | None]:
    out: dict[str, datetime | None] = {s: None for s in symbols}
    placeholders = ",".join("?" * len(symbols))
    rows = db.c.execute(
        f"SELECT i.symbol, MAX(c.t) FROM venue_candles c "
        f"JOIN instruments i ON i.instrument_id = c.instrument_id "
        f"WHERE c.resolution = '1h' AND i.symbol IN ({placeholders}) "
        f"GROUP BY i.symbol",
        symbols,
    ).fetchall()
    for sym, tmax in rows:
        if isinstance(tmax, (int, float)):
            out[sym] = datetime.fromtimestamp(tmax, UTC)
        elif tmax:
            out[sym] = parse_ts(str(tmax))
    return out


async def refresh_hourly_candles(
    data_dir: Path,
    symbols: tuple[str, ...] = DEFAULT_HOURLY_SYMBOLS,
    *,
    lookback_hours: int = 48,
    max_catchup_days: int = 14,
) -> dict:
    """Fetch missing 1h candles for every target symbol into data/live/market.db (best-effort)."""
    started = time.monotonic()
    live_root = data_dir / "live"
    db = MarketDB(live_root / "market.db")
    seg = SegmentWriter(live_root / "raw", db)
    now = now_utc()
    totals: dict[str, int] = {}
    failed: dict[str, str] = {}
    try:
        latest_map = _latest_1h_by_symbol(db, symbols)
        page = timedelta(hours=HISTORY_PAGE_HOURS)
        async with wallex.public_session() as session:
            collector = Collector(db, seg, list(symbols))
            for sym in symbols:
                start, end = compute_catchup_window(
                    latest_map.get(sym),
                    now,
                    lookback_hours=lookback_hours,
                    max_catchup_days=max_catchup_days,
                )
                got_total, hi, empty = 0, end, 0
                while hi > start and empty < 2:
                    lo = max(start, hi - page)
                    for attempt in range(3):
                        err_before = collector.candle_errors
                        got = await collector.fetch_candles(session, sym, "1h", lo, hi)
                        if collector.candle_errors == err_before:
                            break
                        await asyncio.sleep(1.5 * (attempt + 1))
                    else:
                        failed[sym] = iso(lo)
                        break
                    got_total += got
                    empty = 0 if got else empty + 1
                    hi = lo
                totals[sym] = got_total
    finally:
        seg.close()
        db.c.close()

    return {
        "as_of": iso(now),
        "symbols_requested": len(symbols),
        "refreshed_symbols": sum(1 for v in totals.values() if v > 0),
        "total_candles": sum(totals.values()),
        "failed_symbols": failed,
        "elapsed_s": round(time.monotonic() - started, 2),
        "per_symbol": totals,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh 1h Wallex candles for TradingGYM champion universe")
    parser.add_argument("--data-dir", type=Path, default=Path("../data"))
    parser.add_argument("--lookback-hours", type=int, default=48)
    parser.add_argument("--max-catchup-days", type=int, default=14)
    parser.add_argument("--symbols", nargs="*", help="Optional symbol override list")
    args = parser.parse_args()

    symbols = tuple(s.upper() for s in args.symbols) if args.symbols else DEFAULT_HOURLY_SYMBOLS
    summary = asyncio.run(
        refresh_hourly_candles(
            args.data_dir,
            symbols=symbols,
            lookback_hours=args.lookback_hours,
            max_catchup_days=args.max_catchup_days,
        )
    )
    print(json.dumps(summary, indent=2))
    return 0 if not summary["failed_symbols"] else 1


if __name__ == "__main__":
    sys.exit(main())
