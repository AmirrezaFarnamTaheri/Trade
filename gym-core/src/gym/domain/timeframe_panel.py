"""Multi-timeframe causal candle panel, bar-source parity audit & eligibility contract (v2 spec §2)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from .model import parse_ts


@dataclass(frozen=True)
class BarPoint:
    symbol: str
    ts_start: datetime
    ts_avail: datetime                # bar closing time when bar becomes causally observable
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_source: str                   # "NATIVE_1D" | "NATIVE_1H" | "RESAMPLED_1H" | "RESAMPLED_1M"
    clock_complete: bool
    nonzero_volume_fraction: float
    last_trade_age_bars: int
    entry_eligible: bool
    mark_status: str                  # "FRESH" | "STALE_MARK"


def _resolution_timedelta(resolution: str) -> timedelta:
    mapping = {"1min": timedelta(minutes=1), "1h": timedelta(hours=1), "1d": timedelta(days=1)}
    if resolution not in mapping:
        raise ValueError(f"unsupported native resolution: {resolution!r}")
    return mapping[resolution]


def load_keyed_candles(
    con: sqlite3.Connection,
    symbol: str,
    resolution: str,
    *,
    limit: int = 25000,
) -> list[BarPoint]:
    """Keyed instrument_id candle query preserving zero-volume stale-mark diagnostics."""
    inst = con.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (symbol,)).fetchone()
    if inst is None:
        return []
    rows = con.execute(
        "SELECT t, o, h, l, c, v FROM venue_candles "
        "WHERE instrument_id = ? AND resolution = ? ORDER BY t DESC LIMIT ?",
        (inst[0], resolution, limit),
    ).fetchall()
    rows.reverse()

    delta = _resolution_timedelta(resolution)
    source = f"NATIVE_{resolution.upper()}"
    out: list[BarPoint] = []
    stale_age = 0
    for ts_s, o, h, lo, c, v in rows:
        if None in (o, h, lo, c):
            continue
        fo, fh, fl, fc = float(o), float(h), float(lo), float(c)
        fv = float(v) if v is not None else 0.0
        if fo <= 0 or fh <= 0 or fl <= 0 or fc <= 0:
            continue
        t_start = parse_ts(ts_s)
        has_trade = fv > 0.0
        if has_trade:
            stale_age = 0
        else:
            stale_age += 1
        out.append(
            BarPoint(
                symbol=symbol,
                ts_start=t_start,
                ts_avail=t_start + delta,
                open=fo,
                high=fh,
                low=fl,
                close=fc,
                volume=fv,
                bar_source=source,
                clock_complete=True,
                nonzero_volume_fraction=1.0 if has_trade else 0.0,
                last_trade_age_bars=stale_age,
                entry_eligible=has_trade,
                mark_status="FRESH" if has_trade else "STALE_MARK",
            )
        )
    return out


def resample_hourly_to_bucket(
    hourly_bars: list[BarPoint],
    hours: int,
    *,
    offset_hours: int = 0,
) -> list[BarPoint]:
    """Lossless UTC-aligned resampling of hourly bars into 2h/6h/12h/24h buckets with strict completeness."""
    if hours not in (2, 6, 12, 24):
        raise ValueError("hours must be one of (2, 6, 12, 24)")
    if not (0 <= offset_hours < hours):
        raise ValueError("offset_hours must satisfy 0 <= offset_hours < hours")
    if not hourly_bars:
        return []

    buckets: dict[datetime, list[BarPoint]] = {}
    for bar in sorted(hourly_bars, key=lambda b: b.ts_start):
        epoch_h = int(bar.ts_start.timestamp() // 3600)
        shifted = ((epoch_h - offset_hours) // hours) * hours + offset_hours
        b_start = datetime.fromtimestamp(shifted * 3600, tz=bar.ts_start.tzinfo)
        buckets.setdefault(b_start, []).append(bar)

    out: list[BarPoint] = []
    stale_age = 0
    for b_start in sorted(buckets):
        sub = buckets[b_start]
        complete = len(sub) == hours
        nz = sum(1 for x in sub if x.volume > 0)
        nz_frac = nz / len(sub)
        vol = sum(x.volume for x in sub)
        has_trade = vol > 0.0
        stale_age = 0 if has_trade else stale_age + 1
        out.append(
            BarPoint(
                symbol=sub[0].symbol,
                ts_start=b_start,
                ts_avail=b_start + timedelta(hours=hours),
                open=sub[0].open,
                high=max(x.high for x in sub),
                low=min(x.low for x in sub),
                close=sub[-1].close,
                volume=vol,
                bar_source="RESAMPLED_1H",
                clock_complete=complete,
                nonzero_volume_fraction=nz_frac,
                last_trade_age_bars=stale_age,
                entry_eligible=(complete and has_trade and nz_frac >= 0.5),
                mark_status="FRESH" if has_trade else "STALE_MARK",
            )
        )
    return out


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
