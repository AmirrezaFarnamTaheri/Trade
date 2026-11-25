"""Shared causal simulation helpers for v3 unified multi-horizon book experiments.

Eliminates duplicated bar-price resolution, daily-signal alignment, window/annual return
aggregation, and purged walk-forward fold schedules across adaptive, exit, and bear-regime studies.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ...domain.timeframe_panel import BarPoint

WALKFORWARD_FOLDS: tuple[tuple[datetime, datetime], ...] = (
    (datetime(2024, 9, 1, tzinfo=UTC), datetime(2025, 4, 1, tzinfo=UTC)),
    (datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 11, 24, tzinfo=UTC)),
    (datetime(2025, 11, 24, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
)


def resolve_bar_prices(
    symbols: tuple[str, ...],
    by_start: dict[str, dict[datetime, BarPoint]],
    by_avail: dict[str, dict[datetime, BarPoint]],
    ts: datetime,
    last_px: dict[str, float],
) -> tuple[dict[str, float], set[str]]:
    """Resolve strictly causal next-bar execution prices and tradable symbol set at timestamp ts."""
    exec_px: dict[str, float] = {}
    tradable: set[str] = set()
    for sym in symbols:
        nxt, cur = by_start[sym].get(ts), by_avail[sym].get(ts)
        if nxt is not None and nxt.open > 0:
            exec_px[sym], last_px[sym] = nxt.open, nxt.open
            if cur is not None and cur.entry_eligible:
                tradable.add(sym)
        elif cur is not None and cur.close > 0:
            exec_px[sym], last_px[sym] = cur.close, cur.close
        elif sym in last_px:
            exec_px[sym] = last_px[sym]
    return exec_px, tradable


def latest_signal_date(sig_dates: list[datetime], ts: datetime) -> datetime | None:
    """Return latest daily signal timestamp <= ts via causal binary search (works for both 0h & 1h phases)."""
    lo, hi, ans = 0, len(sig_dates) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if sig_dates[mid] <= ts:
            ans, lo = mid, mid + 1
        else:
            hi = mid - 1
    return sig_dates[ans] if ans >= 0 else None


def nav_ts_to_daily(nav_by_ts: dict[datetime, float]) -> dict[str, float]:
    """Collapse an intraday timestamped NAV series to end-of-UTC-day ISO-date NAVs."""
    out: dict[str, float] = {}
    for ts in sorted(nav_by_ts):
        out[ts.date().isoformat()] = nav_by_ts[ts]
    return out


def window_return_pct(nav_by_ts: dict[datetime, float], hours: float) -> float:
    """Compute exact trailing percentage return over the last `hours` of a timestamped NAV series."""
    if len(nav_by_ts) < 2:
        return 0.0
    ts_list = sorted(nav_by_ts)
    end_ts = ts_list[-1]
    target_start = end_ts - timedelta(hours=hours)
    ref_ts = min(ts_list, key=lambda t: abs((t - target_start).total_seconds()))
    v0, v1 = nav_by_ts[ref_ts], nav_by_ts[end_ts]
    return round(((v1 / v0) - 1.0) * 100.0, 2) if v0 > 0 else 0.0


def year_returns_pct(daily: dict[str, float], years: tuple[str, ...] = ("2024", "2025", "2026")) -> dict[str, float]:
    """Compute calendar-year percentage returns from an ISO-date NAV dictionary."""
    out: dict[str, float] = {}
    dates = sorted(daily)
    for yr in years:
        yd = [d for d in dates if d.startswith(yr)]
        if len(yd) >= 2 and daily[yd[0]] > 0:
            out[yr] = round((daily[yd[-1]] / daily[yd[0]] - 1.0) * 100.0, 2)
    return out
