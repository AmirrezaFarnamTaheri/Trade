"""Replay the fixed btc-daily-trend rule in PaperSession; candle-derived quotes are assumptions, not historical books.

Run from gym-core: python scripts/daily_trend_replay.py --db ../data/live/market.db --out ../data/research/daily-trend-replay
This checks exact accounting, not a new holdout score. The scoring window is frozen to the original btc-daily-trend run.
"""
import argparse
import json
import sqlite3
from collections import deque
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from gym.adapters.run_store import save_run
from gym.domain.model import BookTop, iso, parse_ts
from gym.domain.periods import Fixed
from gym.domain.sim import CostModel
from gym.domain.strategy import digest, long_flat
from gym.services.data_portal import DataPortal
from gym.services.paper import session_result
from gym.services.session import ENGINE_VERSION, PaperSession

DAY = timedelta(days=1)
SPLIT, END = parse_ts("2024-01-01T00:00:00Z"), parse_ts("2026-11-15T00:00:00Z")


class FixedDailyTrend:
    name, params = "btc-daily-trend-fixed", {"lookback": 50}

    def __init__(self):
        self.closes, self.feature_values = deque(maxlen=50), {}

    def decide(self, snap, holding):
        self.closes.append(snap.bar.close)
        mean = sum(self.closes) / len(self.closes)
        self.feature_values = {"mean": str(mean), "closes": len(self.closes)}
        return long_flat(snap, holding, snap.bar.close > mean if len(self.closes) == 50 else None, self.feature_values)


def replay(portal, candles):
    if len(candles) < 51 or any(not c.is_finite() or c <= 0 for _, c in candles):
        raise ValueError("need at least 51 positive daily closes, including warmup")
    if any(a >= b for (a, _), (b, _) in zip(candles, candles[1:])):
        raise ValueError("daily closes must be strictly ordered")
    cash = Decimal(1000)
    cost = CostModel(fee_rate=Decimal("0.001"), latency=timedelta(0))
    session = PaperSession(portal, lambda _: [], FixedDailyTrend(), "BTCUSDT", candles[0][0], "1day", cash, cost)
    session.consolidator.period = Fixed(DAY)  # Wallex's downloaded daily candles use UTC boundaries.
    session.warmup_until = SPLIT - timedelta(microseconds=1)
    tops = []
    for i, (day, close) in enumerate(candles):
        end = day + DAY
        # shortcut: daily closes supply assumed touch quotes; use recorded books for fill qualification.
        for at in ([end - timedelta(microseconds=1), end] if i < len(candles) - 1 else [end - timedelta(microseconds=1)]):
            top = BookTop("BTCUSDT", at, close * Decimal("0.999"), close * Decimal("1.001"), None, None, frozenset())
            session.feed(top)
            tops.append(top)
    session.finish(tops[-1].ts_avail)  # mark the terminal close without opening a new position beyond the window
    result = session_result(session, tops, cash)
    inputs = {"engine": ENGINE_VERSION, "kind": "btc-daily-trend-accounting-replay", "symbol": "BTCUSDT",
              "from": iso(SPLIT), "to_exclusive": iso(END), "cost": cost.describe(), "cash": str(cash),
              "data": digest(candles), "strategy": FixedDailyTrend.name, "params": FixedDailyTrend.params,
              "quotes": "daily close +/- 0.10%; immediate fill; unknown historical liquidity and constraints"}
    return {"run_id": digest(inputs)[:16], "mode": "PAPER", "inputs": inputs, "result": result,
            "outputs_digest": digest(result)[:16],
            "limitations": ["Reuses already scored btc-daily-trend data; no new selection or probability calculation.",
                            "Candle-derived spread and liquidity assumptions cannot qualify historical fills.",
                            "Starts in 1000 USDT at the scoring boundary; no inherited pre-2024 position.",
                            "Historical rules unavailable; known dated lot constraints apply. No terminal forced sale."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    with sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True) as connection:
        rows = [(parse_ts(t), Decimal(c)) for t, c in connection.execute(
            "SELECT t,c FROM venue_candles WHERE instrument_id='wallex:BTCUSDT' AND resolution='1d' "
            "AND t<? AND CAST(v AS REAL)>0 ORDER BY t", (iso(END),))]
        warm = [row for row in rows if row[0] < SPLIT][-50:]
        scored = [row for row in rows if row[0] >= SPLIT]
        if len(warm) != 50 or not scored or scored[0][0] != SPLIT or scored[-1][0] + DAY != END:
            raise ValueError("btc-daily-trend's frozen window or its warmup is incomplete")
        out = replay(DataPortal(SimpleNamespace(c=connection)), [*warm, *scored])
    path = save_run(out, args.out)
    print(json.dumps({"path": str(path), "run_id": out["run_id"], "engine": ENGINE_VERSION,
                      "scored_days": len(scored), "fills": out["result"]["fills"],
                      "end": out["result"]["end"], "limitations": out["limitations"]}, indent=2))


if __name__ == "__main__":
    main()
