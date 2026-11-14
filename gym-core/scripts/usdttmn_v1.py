"""Version 1 of the USDTTMN intraday test: does a hand-set rule beat holding USDT after costs?

Runs the fixed parameter grid of `gym.domain.intraday` over every recorded session, for both directions and at two
fee rates. Every grid cell is a counted trial. Prints the net USDT per session and, for each cell, the probability
that its per-session Sharpe beats the best of that many unskilled trials (the deflated Sharpe). The pass mark is 0.95.

Run from gym-core: `uv run --no-sync python scripts/usdttmn_v1.py [--db ../data/live/market.db] [--all-sessions]`.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from statistics import fmean, pvariance

from gym.domain.intraday import DIRECTIONS, Params, run_session
from gym.domain.model import TEHRAN, BookTop
from gym.domain.performance import _moments, deflated_sharpe

SESSION_OPEN, SESSION_CLOSE = time(11, 30), time(23, 30)
EDGE_GAP = 30  # minutes a session's first and last quote may sit inside it and still count as complete
# The account rate read from /v1/account/fee, and the public level-1 taker rate for Toman markets (/v2/structured-fee).
FEES = (Decimal("0.001"), Decimal("0.003"))
GRID = [(lookback, entry) for lookback in (12, 36) for entry in (50, 100, 200)]
# ASSUMED margin cost per BUY_CHEAP trade as a share of the loan; replace with a venue margin preview before relying on it.
FINANCING_BPS = Decimal(10)
MIN_SESSIONS = 30  # below this the deflated Sharpe is printed but is not a verdict
PASS = 0.95


def sessions(db: Path, complete_only: bool) -> dict[str, list[BookTop]]:
    """In-session USDTTMN quotes by Tehran date, keeping the collector's flags so unusable quotes are skipped."""
    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT ts_avail, bid, ask, bid_qty, ask_qty, flags FROM book_top "
                                  "WHERE instrument_id='wallex:USDTTMN' ORDER BY ts_avail, rowid").fetchall()
    finally:
        connection.close()
    days: dict[str, list[BookTop]] = {}
    for stamp, bid, ask, bid_size, ask_size, flags in rows:
        at = datetime.fromisoformat(stamp)
        local = at.astimezone(TEHRAN)
        if SESSION_OPEN <= local.time() < SESSION_CLOSE and None not in (bid, ask, bid_size, ask_size):
            days.setdefault(local.date().isoformat(), []).append(
                BookTop("USDTTMN", at, Decimal(bid), Decimal(ask), Decimal(bid_size), Decimal(ask_size),
                        frozenset(filter(None, flags.split(",")))))

    def minutes(moment: datetime) -> int:
        local = moment.astimezone(TEHRAN)
        return local.hour * 60 + local.minute

    def complete(quotes: list[BookTop]) -> bool:
        return (minutes(quotes[0].ts_avail) - (11 * 60 + 30) <= EDGE_GAP
                and (23 * 60 + 30) - minutes(quotes[-1].ts_avail) <= EDGE_GAP)

    return {day: quotes for day, quotes in days.items() if not complete_only or complete(quotes)}


def evaluate(days: dict[str, list[BookTop]]) -> list[dict]:
    rows = []
    for fee in FEES:
        for direction in DIRECTIONS:
            for lookback, entry in GRID:
                params = Params(direction=direction, lookback=lookback, entry_bps=entry,
                                financing_bps=FINANCING_BPS if direction == "BUY_CHEAP" else Decimal(0))
                results = [run_session(quotes, params, fee_rate=fee) for quotes in days.values()]
                rows.append({"fee": fee, "direction": direction, "lookback": lookback, "entry_bps": entry,
                             "net": [float(result["net_usdt"]) for result in results],
                             "trips": sum(result["round_trips"] for result in results),
                             "stranded": sum(result["state"] == "STRANDED" for result in results),
                             "halted": sum(result["halted"] for result in results)})
    return rows


def verdicts(rows: list[dict]) -> None:
    """Deflated Sharpe per cell, against every cell tried at the same fee (both directions are counted)."""
    for fee in FEES:
        family = [row for row in rows if row["fee"] == fee]
        sharpes = []
        for row in family:
            mean, deviation, skew, kurtosis = _moments(row["net"]) if len(row["net"]) > 1 else (fmean(row["net"]), 0.0, 0.0, 3.0)
            row["sharpe"], row["moments"] = (mean / deviation if deviation else 0.0), (skew, kurtosis)
            sharpes.append(row["sharpe"])
        variance = pvariance(sharpes) if len(sharpes) > 1 else 0.0
        for row in family:
            row["deflated"] = deflated_sharpe(row["sharpe"], len(row["net"]), *row["moments"], len(family), variance)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parents[2] / "data/live/market.db")
    parser.add_argument("--all-sessions", action="store_true", help="include sessions with missing edges")
    args = parser.parse_args(argv)
    days = sessions(args.db, not args.all_sessions)
    if not days:
        print("no sessions")
        return 1
    rows = evaluate(days)
    verdicts(rows)
    print(f"sessions: {', '.join(days)}")
    print(f"trials per fee rate: {len(GRID) * len(DIRECTIONS)}; size 1000 USDT; benchmark: holding USDT nets 0")
    print("fee    direction  look entry  trips strand halt  total-USDT  deflated  net USDT per session")
    for row in rows:
        deflated = "   n/a" if row["deflated"] is None else f"{row['deflated']:6.3f}"
        print(f"{row['fee']:<6} {row['direction']:<10} {row['lookback']:4} {row['entry_bps']:5}  {row['trips']:5} "
              f"{row['stranded']:6} {row['halted']:4}  {sum(row['net']):10.2f}  {deflated}  "
              + " ".join(f"{value:7.2f}" for value in row["net"]))
    best = max((row["deflated"] or 0.0) for row in rows)
    if len(days) < MIN_SESSIONS:
        print(f"VERDICT: INSUFFICIENT_SESSIONS ({len(days)} of {MIN_SESSIONS}); best deflated Sharpe probability {best:.3f}")
    else:
        print(f"VERDICT: {'PASS' if best >= PASS else 'FAIL'}; best deflated Sharpe probability {best:.3f} against {PASS}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
