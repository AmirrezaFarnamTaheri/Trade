"""Foreground paper scheduler; stop after the current tick, restart at committed clocks."""
import asyncio
import math
from pathlib import Path

from ..adapters.store import MarketDB
from .collector import now_utc
from .research_ledger import ResearchLedger


async def watch(root: Path | str, *, store: str = "live", poll_seconds: float = 5,
                stop: asyncio.Event | None = None) -> dict[str, object]:
    """Poll local data only; Ctrl+C or an event stops without disabling scheduled jobs."""
    if store not in ("live", "demo"):
        raise ValueError("research store must be live or demo")
    if (type(poll_seconds) not in (int, float) or not math.isfinite(poll_seconds)
            or not 1 <= poll_seconds <= 60):
        raise ValueError("research poll interval must be 1..60 seconds")
    root, stop = Path(root), stop if stop is not None else asyncio.Event()
    ticks = completed = failed = 0
    reason = "Stop requested"
    try:
        while not stop.is_set():
            db = MarketDB(root / "market.db", readonly=True)
            try:
                db.c.execute("PRAGMA query_only=ON")
                with ResearchLedger(root / "research.sqlite3") as ledger:
                    result = ledger.run_due(db, now_utc().isoformat(), store=store, limit=10)
            finally:
                db.c.close()
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
    return {"state": "STOPPED", "reason": reason, "ticks": ticks, "completed": completed, "failed": failed,
            "authority": "PAPER_ONLY", "funded_authority": False, "order_submitted": False}
