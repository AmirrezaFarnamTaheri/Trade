"""Foreground paper scheduler; stop after the current tick, restart at committed clocks."""
import asyncio
import math
import sqlite3
from pathlib import Path

from .collector import now_utc
from .research_process import ResearchProcessFailure, calculate


async def watch(root: Path | str, *, store: str = "live", poll_seconds: float = 5,
                stop: asyncio.Event | None = None) -> dict[str, object]:
    """Poll local data only; Ctrl+C or an event stops without disabling scheduled jobs."""
    if store not in ("live", "demo"):
        raise ValueError("research store must be live or demo")
    if (type(poll_seconds) not in (int, float) or not math.isfinite(poll_seconds)
            or not 1 <= poll_seconds <= 60):
        raise ValueError("research poll interval must be 1..60 seconds")
    root, stop = Path(root), stop if stop is not None else asyncio.Event()
    if not (root / "market.db").is_file():
        raise sqlite3.OperationalError("paper market store missing")
    ticks = completed = failed = 0
    reason = "Stop requested"
    try:
        while not stop.is_set():
            result = await calculate(root, "tick", store=store, at=now_utc().isoformat())
            ticks += 1
            completed += len(result["completed"])
            failed += len(result["failed"])
            if not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
                except TimeoutError:
                    pass
    except asyncio.CancelledError:
        reason = "Operator interrupted"
    except ResearchProcessFailure as error:
        return {"state": "STOPPED", **error.report, "ticks": ticks, "completed": completed, "failed": failed}
    return {"state": "STOPPED", "reason": reason, "ticks": ticks, "completed": completed, "failed": failed}
