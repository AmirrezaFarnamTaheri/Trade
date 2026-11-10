"""P-2: refuse to start a prospective window that the archive volume cannot last through.

A preregistered evaluation needs collection to run until its test window closes. If the last day's archive growth
says the volume reaches the 5 GiB floor (where collection stops) before then, the window would be voided, so the
registration is refused up front with the numbers, instead of failing silently mid-window.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def ensure_runway(root: Path, until: datetime, now: datetime) -> dict:
    from ..adapters.store import MarketDB, storage_forecast
    path = Path(root) / "market.db"
    if not path.is_file():
        return {"status": "UNKNOWN", "reason": "no market store"}
    db = MarketDB(path, readonly=True)
    try:
        forecast = storage_forecast(db, Path(root) / "raw", now)
    finally:
        db.c.close()
    needed = max(0.0, (until - now).total_seconds() / 3600)
    runway = forecast["hours_to_floor"]
    if runway is None:
        return {"status": "UNKNOWN", "reason": "no archive growth measured in the last day", **forecast}
    if runway < needed:
        raise ValueError(f"archive volume reaches the 5 GiB collection floor in {runway:.0f} h, before this window "
                         f"ends in {needed:.0f} h; free space or move raw day folders (--archive-to) first")
    return {"status": "OK", "hours_needed": round(needed, 1), **forecast}
