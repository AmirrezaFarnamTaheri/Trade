"""Event-loop lag sampler for the collector (measure before moving writes off the loop).

Every `interval` seconds the sampler asks to wake up; how late it actually wakes is the time the loop spent on
other work, including the synchronous SQLite writes. A rolling window gives p50, p99 and max, shown in
/api/health, so the 373-market host's real numbers decide whether a writer thread is needed.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque

WARN_P99_MS = 250.0  # above this, websocket frames queue long enough to matter for reconnect and clock guards


class LoopLag:
    def __init__(self, interval: float = 0.5, window: int = 1200, clock=time.monotonic):
        self.interval, self.clock = interval, clock
        self.samples: deque[float] = deque(maxlen=window)

    def record(self, lag_ms: float) -> None:
        self.samples.append(max(0.0, lag_ms))

    def report(self) -> dict:
        if not self.samples:
            return {"samples": 0, "p50_ms": None, "p99_ms": None, "max_ms": None, "status": "NO_DATA"}
        ordered = sorted(self.samples)

        def pick(q):
            return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)

        p99 = pick(0.99)
        return {"samples": len(ordered), "p50_ms": pick(0.50), "p99_ms": p99, "max_ms": round(ordered[-1], 1),
                "window_s": round(len(ordered) * self.interval), "warn_p99_ms": WARN_P99_MS,
                "status": "WARN" if p99 > WARN_P99_MS else "OK"}

    async def run(self) -> None:
        while True:
            expected = self.clock() + self.interval
            await asyncio.sleep(self.interval)
            self.record((self.clock() - expected) * 1000)
