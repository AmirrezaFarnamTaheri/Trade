"""Version 1 of the USDTTMN intraday test: does a hand-set rule beat holding USDT after costs?

Runs the fixed parameter grid of `gym.domain.intraday` over every recorded session, for both directions and at two
fee rates. Every grid cell is a counted trial. Prints the net USDT per session and, for each cell, the probability
that its per-session Sharpe beats the best of that many unskilled trials (the deflated Sharpe). The pass mark is 0.95.

Quote mode (default) fills on recorded top-of-book quotes; only days the collector ran exist. Bar mode (`--bars`)
runs the same rule on the venue's 1-minute candles, which reach back years (`gymctl history USDTTMN --resolution
1min`). A candle has no bid or ask, so bar mode ASSUMES them: each traded minute becomes one quote at the minute's
end, `--spread-bps` wide around the close, with unlimited size. Sessions before 2026-09-30 come from a market that
traded around the clock; the same 11:30-23:30 Tehran window is cut from them. In bar mode the settings are ranked on
sessions before the held-out date only, and the held-out sessions are scored once, for the best-ranked setting.
`--compare` runs both modes on the days that have recorded quotes, to show what the assumptions change.

Run from gym-core: `uv run --no-sync python scripts/usdttmn_v1.py [--db PATH] [--all-sessions | --bars | --compare]`.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, time, timedelta
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
HOLDOUT_FROM = "2026-01-01"  # bar mode: sessions from this Tehran date on are never used to rank settings
MIN_TRADED_MINUTES = 360  # bar mode: a session with fewer traded minutes (of 720) is left out
UNLIMITED = Decimal(10) ** 9  # bar mode has no touch size


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


def bar_sessions(db: Path, spread_bps: Decimal) -> dict[str, list[BookTop]]:
    """One assumed quote per traded 1-minute candle, at the minute's end, inside the session window."""
    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT t, c FROM venue_candles WHERE instrument_id='wallex:USDTTMN' "
                                  "AND resolution='1min' AND CAST(v AS REAL) > 0 ORDER BY t").fetchall()
    finally:
        connection.close()
    half = spread_bps / 20000
    days: dict[str, list[BookTop]] = {}
    for stamp, close in rows:
        at = datetime.fromisoformat(stamp) + timedelta(minutes=1)
        local = at.astimezone(TEHRAN)
        if SESSION_OPEN <= local.time() < SESSION_CLOSE:
            price = Decimal(close)
            days.setdefault(local.date().isoformat(), []).append(
                BookTop("USDTTMN", at, price * (1 - half), price * (1 + half), UNLIMITED, UNLIMITED, frozenset()))
    return {day: quotes for day, quotes in days.items() if len(quotes) >= MIN_TRADED_MINUTES}


def cell(days: dict[str, list[BookTop]], fee: Decimal, direction: str, lookback: int, entry: int) -> dict:
    params = Params(direction=direction, lookback=lookback, entry_bps=entry,
                    financing_bps=FINANCING_BPS if direction == "BUY_CHEAP" else Decimal(0))
    results = [run_session(quotes, params, fee_rate=fee) for quotes in days.values()]
    return {"fee": fee, "direction": direction, "lookback": lookback, "entry_bps": entry,
            "net": [float(result["net_usdt"]) for result in results],
            "trips": sum(result["round_trips"] for result in results),
            "stranded": sum(result["state"] == "STRANDED" for result in results),
            "halted": sum(result["halted"] for result in results)}


def evaluate(days: dict[str, list[BookTop]]) -> list[dict]:
    return [cell(days, fee, direction, lookback, entry)
            for fee in FEES for direction in DIRECTIONS for lookback, entry in GRID]


def bar_report(db: Path, spreads: list[Decimal]) -> None:
    for spread in spreads:
        days = bar_sessions(db, spread)
        ranked = {day: quotes for day, quotes in days.items() if day < HOLDOUT_FROM}
        held = {day: quotes for day, quotes in days.items() if day >= HOLDOUT_FROM}
        if len(ranked) < MIN_SESSIONS:
            print(f"bar mode: {len(ranked)} ranking sessions, {MIN_SESSIONS} needed; backfill 1-minute candles first")
            return
        rows = evaluate(ranked)
        verdicts(rows)
        print(f"\nBAR MODE, assumed spread {spread} bps; ranked on {len(ranked)} sessions before {HOLDOUT_FROM}; "
              f"{len(held)} held out; {len(GRID) * len(DIRECTIONS)} trials per fee rate")
        print("fee    direction  look entry  trips strand halt  total-USDT  per-session  win%  deflated")
        for row in rows:
            net = row["net"]
            print(f"{row['fee']:<6} {row['direction']:<10} {row['lookback']:4} {row['entry_bps']:5}  {row['trips']:5} "
                  f"{row['stranded']:6} {row['halted']:4}  {sum(net):10.2f}  {fmean(net):11.3f}  "
                  f"{100 * sum(value > 0 for value in net) / len(net):4.0f}  {row['deflated'] or 0.0:8.3f}")
        for fee in FEES:
            best = max((row for row in rows if row["fee"] == fee), key=lambda row: row["deflated"] or 0.0)
            name = f"{best['direction']} look {best['lookback']} entry {best['entry_bps']}"
            if (best["deflated"] or 0.0) < PASS:
                print(f"fee {fee}: FAIL on the ranking sessions (best {name}, {best['deflated'] or 0.0:.3f} "
                      f"against {PASS}); held-out sessions not scored")
                continue
            once = cell(held, fee, best["direction"], best["lookback"], best["entry_bps"])
            mean, deviation, skew, kurtosis = _moments(once["net"])
            alone = deflated_sharpe(mean / deviation if deviation else 0.0, len(once["net"]), skew, kurtosis, 1, 0.0)
            print(f"fee {fee}: {name} passed ranking ({best['deflated']:.3f}); HELD OUT, scored once: "
                  f"total {sum(once['net']):.2f} USDT over {len(once['net'])} sessions, {once['trips']} trips, "
                  f"{once['stranded']} stranded, probability Sharpe > 0: {alone or 0.0:.3f}")


def compare(db: Path, spread: Decimal) -> None:
    """Both modes on the days that have recorded quotes."""
    quoted = sessions(db, False)
    bars = {day: quotes for day, quotes in bar_sessions(db, spread).items() if day in quoted}
    quoted = {day: quoted[day] for day in bars}
    print(f"\nCOMPARE on {len(bars)} sessions with both quotes and bars ({', '.join(bars)}); bar spread {spread} bps")
    print("fee    direction  look entry  quote-mode: trips total   bar-mode: trips total")
    for a, b in zip(evaluate(quoted), evaluate(bars), strict=True):
        print(f"{a['fee']:<6} {a['direction']:<10} {a['lookback']:4} {a['entry_bps']:5}  "
              f"{a['trips']:17} {sum(a['net']):8.2f}  {b['trips']:15} {sum(b['net']):8.2f}")


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
    parser.add_argument("--bars", action="store_true", help="run on 1-minute venue candles with an assumed spread")
    parser.add_argument("--compare", action="store_true", help="quote mode against bar mode on the same days")
    parser.add_argument("--spread-bps", type=Decimal, nargs="+", default=[Decimal(3), Decimal(10)])
    args = parser.parse_args(argv)
    if any(not 0 < spread < 500 for spread in args.spread_bps):
        parser.error("--spread-bps must be between 0 and 500")
    if args.bars or args.compare:
        if args.bars:
            bar_report(args.db, args.spread_bps)
        if args.compare:
            compare(args.db, args.spread_bps[0])
        return 0
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
