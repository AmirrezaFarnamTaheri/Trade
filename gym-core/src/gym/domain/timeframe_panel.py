"""Pure multi-timeframe bar types and UTC-aligned resampling rules (no I/O)."""
from __future__ import annotations

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


def resolution_timedelta(resolution: str) -> timedelta:
    mapping = {"1min": timedelta(minutes=1), "1h": timedelta(hours=1), "1d": timedelta(days=1)}
    if resolution not in mapping:
        raise ValueError(f"unsupported native resolution: {resolution!r}")
    return mapping[resolution]


def build_bar_points_from_rows(
    symbol: str,
    resolution: str,
    raw_rows: list[tuple],
) -> list[BarPoint]:
    """Convert chronologically ordered (t, o, h, l, c, v) tuples into BarPoint records."""
    delta = resolution_timedelta(resolution)
    source = f"NATIVE_{resolution.upper()}"
    out: list[BarPoint] = []
    stale_age = 0
    for ts_s, o, h, lo, c, v in raw_rows:
        if None in (o, h, lo, c):
            continue
        fo, fh, fl, fc = float(o), float(h), float(lo), float(c)
        fv = float(v) if v is not None else 0.0
        if fo <= 0 or fh <= 0 or fl <= 0 or fc <= 0:
            continue
        t_start = parse_ts(ts_s)
        has_trade = fv > 0.0
        stale_age = 0 if has_trade else stale_age + 1
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
    """Lossless UTC-aligned resampling of hourly bars into 2h/3h/4h/6h/12h/24h buckets with strict completeness."""
    if hours not in (2, 3, 4, 6, 12, 24):
        raise ValueError("hours must be one of (2, 3, 4, 6, 12, 24)")
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
