"""Step 0 of the USDTTMN intraday test: is the daily swing larger than what a round trip costs?

For each Tehran day, over collected top-of-book quotes inside the trading session, this prints the mid-price
range, the median spread, the median size at the touch, and the best round trip a trader with perfect foresight
could have made: sell USDT at the bid, buy it back later at the ask, pay the fee on both sides. That last number
is an upper bound on any rule. If it is not well above zero on most days, no rule can work and the test stops.

Run from gym-core: `uv run --no-sync python scripts/usdttmn_range.py [--db ../data/live/market.db] [--json]`.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
# Venue rule wallex-usdttmn-closure-2330-1130 (status REPORTED): the market is closed 23:30 to 11:30 Tehran.
SESSION_OPEN, SESSION_CLOSE = time(11, 30), time(23, 30)
FEE = Decimal("0.001")  # per side
EDGE_GAP = 30  # minutes a day's first and last quote may sit inside the session and still count as complete


def percent(value: Decimal) -> Decimal:
    return (value * 100).quantize(Decimal("0.001"))


def day_stats(quotes: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal]], fee: Decimal = FEE) -> dict:
    """Statistics for one session from (time, bid, ask, bid size, ask size) rows in time order."""
    mids = [(bid + ask) / 2 for _, bid, ask, _, _ in quotes]
    best_bid, capture = quotes[0][1], None
    for _, bid, ask, _, _ in quotes[1:]:
        # Sold one USDT at the best earlier bid, bought back now at the ask, fee charged on each side.
        trip = best_bid * (1 - fee) / (ask * (1 + fee)) - 1
        capture = trip if capture is None else max(capture, trip)
        best_bid = max(best_bid, bid)
    minutes = lambda at: at.hour * 60 + at.minute
    first, last = quotes[0][0], quotes[-1][0]
    return {
        "quotes": len(quotes), "first": first.strftime("%H:%M"), "last": last.strftime("%H:%M"),
        "complete": (minutes(first) - minutes(SESSION_OPEN) <= EDGE_GAP
                     and minutes(SESSION_CLOSE) - minutes(last) <= EDGE_GAP),
        "range_percent": percent((max(mids) - min(mids)) / min(mids)),
        "median_spread_percent": percent(median((ask - bid) / ((bid + ask) / 2) for _, bid, ask, _, _ in quotes)),
        "median_bid_size_usdt": median(size for _, _, _, size, _ in quotes),
        "median_ask_size_usdt": median(size for _, _, _, _, size in quotes),
        "foresight_round_trip_percent": None if capture is None else percent(capture),
    }


def load(db: Path) -> dict[str, list]:
    """Unflagged in-session USDTTMN quotes by Tehran date."""
    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT ts_avail, bid, ask, bid_qty, ask_qty FROM book_top "
            "WHERE instrument_id='wallex:USDTTMN' AND flags='' ORDER BY ts_avail").fetchall()
    finally:
        connection.close()
    days: dict[str, list] = {}
    for stamp, bid, ask, bid_size, ask_size in rows:
        at = datetime.fromisoformat(stamp).astimezone(TEHRAN)
        if SESSION_OPEN <= at.time() < SESSION_CLOSE:
            days.setdefault(at.date().isoformat(), []).append(
                (at, Decimal(bid), Decimal(ask), Decimal(bid_size), Decimal(ask_size)))
    return days


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parents[2] / "data/live/market.db")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = {day: day_stats(quotes) for day, quotes in load(args.db).items() if len(quotes) > 1}
    complete = [row["foresight_round_trip_percent"] for row in report.values() if row["complete"]]
    summary = {"days": len(report), "complete_days": len(complete),
               "median_foresight_round_trip_percent": median(complete) if complete else None,
               "complete_days_with_positive_foresight": sum(1 for value in complete if value > 0)}
    if args.json:
        print(json.dumps({"fee_per_side": str(FEE), "days": report, "summary": summary}, default=str, indent=2))
        return 0
    print("day         quotes first last  full  range%  spread%  bid-size  ask-size  foresight-trip%")
    for day, row in report.items():
        print(f"{day}  {row['quotes']:6} {row['first']} {row['last']} {'yes' if row['complete'] else 'no ':4} "
              f"{row['range_percent']:7} {row['median_spread_percent']:8} {row['median_bid_size_usdt']:9.0f} "
              f"{row['median_ask_size_usdt']:9.0f} {row['foresight_round_trip_percent']:16}")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
