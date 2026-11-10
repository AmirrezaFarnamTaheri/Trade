"""E-4: replayed full-universe load on the collector's real write path; the event loop must stay responsive.

Every one of 373 markets changes both book sides on every tick (the worst case: every market is written each tick)
and prints a trade, all through `on_depth`, `on_trade` and `tick` on the event loop, with the lag sampler running.
Measured on the development laptop (2026-11-10): tick p99 about 30-60 ms, loop-lag p99 well under the bound.
The decision rule from the finding: a writer thread is added only if this bound is breached on the target host.
"""
import asyncio
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from gym.adapters.store import MarketDB, SegmentWriter
from gym.services.collector import Collector
from gym.services.loop_lag import WARN_P99_MS, LoopLag

MARKETS = 373
TICKS = 40


def test_full_universe_ticks_keep_event_loop_lag_under_the_bound(tmp_path):
    db = MarketDB(tmp_path / "market.db")
    symbols = [f"C{i:03d}USDT" for i in range(MARKETS)]
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), symbols)
    start = datetime(2026, 11, 10, 9, tzinfo=UTC)

    async def scenario():
        lag = LoopLag(interval=0.01, window=10_000)
        sampler = asyncio.create_task(lag.run())
        durations = []
        for n in range(TICKS):
            now = start + timedelta(seconds=n)
            for i, sym in enumerate(symbols):
                px = Decimal(1000 + i) + Decimal(n) / 100
                col.on_depth(sym, "bid", [(px, Decimal(1))], now, "load")
                col.on_depth(sym, "ask", [(px + Decimal("0.5"), Decimal(2))], now, "load")
                col.on_trade(sym, {"timestamp": now.isoformat(), "price": str(px), "quantity": "0.01",
                                   "isBuyOrder": bool(n % 2)}, now, "load")
                await asyncio.sleep(0)  # each market's frames arrive as their own websocket events
            began = time.perf_counter()
            col.tick(now)
            durations.append((time.perf_counter() - began) * 1000)
            await asyncio.sleep(0.02)
        sampler.cancel()
        return sorted(durations), lag.report()

    durations, report = asyncio.run(scenario())
    rows = db.c.execute("SELECT count(*) FROM book_top").fetchone()[0]
    db.c.close()
    assert rows == MARKETS * TICKS  # every market written every tick: the worst case was exercised
    tick_p99 = durations[int(0.99 * (len(durations) - 1))]
    print(f"tick p50 {durations[len(durations) // 2]:.1f} ms, p99 {tick_p99:.1f} ms; loop lag {report}")
    assert report["p99_ms"] < WARN_P99_MS, report
    assert tick_p99 < 1000, durations  # one tick writes every market at once; a second would stall the feed
