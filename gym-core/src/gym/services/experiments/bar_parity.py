"""Daily vs resampled-hourly bar-parity and zero-volume coverage audit service."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from ...adapters.candle_reader import load_keyed_candles
from ...domain.timeframe_panel import resample_hourly_to_bucket


def audit_bar_parity_and_coverage(
    con: sqlite3.Connection,
    symbols: tuple[str, ...],
    *,
    start_at: datetime,
    end_at: datetime,
) -> dict[str, dict]:
    """Compare native 1d candles vs 24h resampled 1h candles on complete days and disclose zero-volume fractions."""
    report: dict[str, dict] = {}
    for sym in symbols:
        daily = [b for b in load_keyed_candles(con, sym, "1d", limit=3500) if start_at <= b.ts_start <= end_at]
        hourly = [b for b in load_keyed_candles(con, sym, "1h", limit=35000) if start_at <= b.ts_start <= end_at]
        resamp_24h = {b.ts_start: b for b in resample_hourly_to_bucket(hourly, 24) if b.clock_complete}
        d_map = {b.ts_start: b for b in daily}

        common = sorted(set(d_map) & set(resamp_24h))
        unequal_open = 0
        unequal_close = 0
        max_open_gap_bps = 0.0
        for dt in common:
            db, rb = d_map[dt], resamp_24h[dt]
            if abs(db.open - rb.open) > 1e-12:
                unequal_open += 1
                gap = abs(db.open - rb.open) / db.open * 10000.0
                max_open_gap_bps = max(max_open_gap_bps, gap)
            if abs(db.close - rb.close) > 1e-12:
                unequal_close += 1

        zero_vol_hours = sum(1 for b in hourly if b.volume <= 0)
        zero_vol_days = sum(1 for b in daily if b.volume <= 0)
        report[sym] = {
            "daily_bars": len(daily),
            "zero_vol_days": zero_vol_days,
            "hourly_bars": len(hourly),
            "zero_vol_hours": zero_vol_hours,
            "complete_days_compared": len(common),
            "unequal_open_days": unequal_open,
            "unequal_close_days": unequal_close,
            "max_open_gap_bps": round(max_open_gap_bps, 2),
        }
    return report
