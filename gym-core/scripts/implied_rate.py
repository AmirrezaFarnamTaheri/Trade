"""T10 of docs/trial-log.md: does USDTTMN fall back after standing above the rate implied by BTC?

The implied rate is BTCTMN divided by BTCUSDT. When USDTTMN is dearer than that by more than its usual gap, the
rule sells USDT for Toman and buys it back when the gap closes or a day has passed. Returns are in USDT, net of
cost on both sides. Floating point is used; a pass must be replayed in the exact paper engine before it counts.

Run from gym-core: `uv run --no-sync python scripts/implied_rate.py --db ../data/live/market.db`
(needs `gymctl history BTCTMN BTCUSDT USDTTMN --resolution 1h --from 2023-01-01T00:00:00Z` first).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from math import log
from pathlib import Path
from statistics import fmean, median, pvariance

from gym.domain.performance import _moments, deflated_sharpe, probabilistic_sharpe

HOURS, THRESHOLDS = (24, 72), (0.005, 0.01, 0.02)
COST = 0.0015  # per side: 0.10% fee plus 0.05% for half the spread
SPLIT = "2026-01-01"
MAX_HOLD = 24 * 3600
RANK_MARK, RANK_TRADES, HELD_MARK, HELD_TRADES = 0.95, 30, 0.90, 15


def gaps(usdt_tmn: dict[str, float], btc_tmn: dict[str, float], btc_usdt: dict[str, float]) -> list[tuple[str, int, float, float]]:
    """(time, epoch seconds, USDTTMN close, log gap to the implied rate) for every hour all three markets closed."""
    rows = []
    for at in sorted(usdt_tmn.keys() & btc_tmn.keys() & btc_usdt.keys()):
        epoch = int(datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp())
        rows.append((at, epoch, usdt_tmn[at], log(usdt_tmn[at]) - log(btc_tmn[at] / btc_usdt[at])))
    return rows


def trades(rows: list[tuple[str, int, float, float]], hours: int, threshold: float, cost: float) -> list[tuple[str, float, float]]:
    """(entry time, gross return, net return) per round trip. A signal seen at one close is acted on at the next."""
    out, entry, pending, start = [], None, None, 0
    for i, (at, epoch, price, gap) in enumerate(rows):
        if pending == "sell":
            entry = (at, epoch, price)
        elif pending == "buy":
            gross = entry[2] / price - 1
            out.append((entry[0], gross, (1 + gross) * (1 - cost) ** 2 - 1))
            entry = None
        pending = None
        while rows[start][1] <= epoch - hours * 3600:
            start += 1
        if i - start + 1 < hours // 4:  # too few closes in the window to call any gap usual
            continue
        excess = gap - median(row[3] for row in rows[start:i + 1])
        if entry is None and excess > threshold:
            pending = "sell"
        elif entry is not None and (excess < 0 or epoch - entry[1] >= MAX_HOLD):
            pending = "buy"
    return out


def summary(found: list[tuple[str, float, float]]) -> dict:
    net = [row[2] for row in found]
    if len(net) < 3:
        return {"trades": len(net), "sharpe": 0.0, "moments": (0.0, 3.0), "net": sum(net), "gross": sum(row[1] for row in found)}
    mean, deviation, skew, kurtosis = _moments(net)
    return {"trades": len(net), "sharpe": mean / deviation if deviation else 0.0, "moments": (skew, kurtosis),
            "net": sum(net), "gross": sum(row[1] for row in found), "mean_gross": fmean(row[1] for row in found)}


def verdict(rows: list[tuple[str, int, float, float]]) -> bool:
    cells = []
    for hours in HOURS:
        for threshold in THRESHOLDS:
            found = trades(rows, hours, threshold, COST)
            cells.append({"hours": hours, "threshold": threshold, "all": found,
                          **summary([row for row in found if row[0] < SPLIT])})
    variance = pvariance([cell["sharpe"] for cell in cells])
    print(f"T10 implied rate, cost {100 * COST:.2f}% per side; {len(rows)} shared hours from {rows[0][0][:10]}; ranked before {SPLIT}")
    for cell in cells:
        cell["deflated"] = deflated_sharpe(cell["sharpe"], cell["trades"], *cell["moments"], len(cells), variance) or 0.0
        print(f"  {cell['hours']:2}h median, {10000 * cell['threshold']:3.0f} bps: {cell['trades']:4} trades, gross "
              f"{100 * cell['gross']:7.2f}%, net {100 * cell['net']:7.2f}%, gross a trade "
              f"{10000 * cell.get('mean_gross', 0.0):6.1f} bps, deflated {cell['deflated']:.3f}")
    best = max(cells, key=lambda cell: cell["deflated"])
    if best["deflated"] < RANK_MARK or best["trades"] < RANK_TRADES:
        print(f"T10 VERDICT: FAIL on ranking (best {best['hours']}h {10000 * best['threshold']:.0f} bps, deflated "
              f"{best['deflated']:.3f} on {best['trades']} trades); {SPLIT[:4]} not scored")
        return False
    held = summary([row for row in best["all"] if row[0] >= SPLIT])
    alone = probabilistic_sharpe(held["sharpe"], held["trades"], *held["moments"]) or 0.0
    passed = alone >= HELD_MARK and held["trades"] >= HELD_TRADES
    print(f"  {best['hours']}h {10000 * best['threshold']:.0f} bps passed ranking; {SPLIT[:4]} scored once: {held['trades']} trades, "
          f"gross {100 * held['gross']:.2f}%, net {100 * held['net']:.2f}%, probability Sharpe > 0: {alone:.3f}")
    print(f"T10 VERDICT: {'PASS' if passed else 'FAIL'}")
    return passed


def closes(connection, symbol: str) -> dict[str, float]:
    return {at: float(close) for at, close in connection.execute(
        "SELECT t, c FROM venue_candles WHERE instrument_id = ? AND resolution = '1h'", (f"wallex:{symbol}",))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True)
    connection = sqlite3.connect(f"file:{parser.parse_args().db.as_posix()}?mode=ro", uri=True)
    rows = gaps(*(closes(connection, symbol) for symbol in ("USDTTMN", "BTCTMN", "BTCUSDT")))
    if len(rows) < 1000:
        print(f"only {len(rows)} shared hourly closes; backfill the three markets first", file=sys.stderr)
        return 2
    verdict(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
