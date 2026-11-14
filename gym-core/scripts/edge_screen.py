"""Screens T2 to T5 of docs/trial-log.md: where could an edge exist on Wallex at the fees actually paid?

Each screen is a table over recorded data with a pass mark written in the trial log before it ran. Nothing is
fitted. Floating point is used; anything that passes must be replayed in the exact paper engine before it counts.

Run from gym-core: `uv run --no-sync python scripts/edge_screen.py [--db ../data/live/market.db] [T2 T3 T4 T5]`.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from bisect import bisect_right
from itertools import groupby
from math import sqrt
from pathlib import Path
from statistics import fmean, median, pvariance, stdev

from gym.domain.bars import DISQUALIFY
from gym.domain.performance import _moments, deflated_sharpe

ACCOUNT_FEE = 0.001  # per side, read from /v1/account/fee
PUBLISHED = {"TMN": (0.0025, 0.0030), "USDT": (0.0010, 0.0013)}  # level-1 (maker, taker) from /v2/structured-fee
DAY = 86400
SESSION = (8 * 3600, 20 * 3600)  # 11:30 to 23:30 Tehran, as seconds of the UTC day
HORIZON_S, FRESH_S = 300, 120


def usable(flags: str) -> bool:
    return not (set(filter(None, flags.split(","))) & DISQUALIFY)


def quotes_of(connection, symbol: str) -> list[tuple]:
    """(epoch second, bid, ask, bid size, ask size) for one market, usable quotes only, in time order."""
    rows = connection.execute(
        "SELECT CAST(strftime('%s', ts_avail) AS INTEGER), bid, ask, bid_qty, ask_qty, flags FROM book_top "
        "WHERE instrument_id=? ORDER BY ts_avail", (f"wallex:{symbol}",))
    return [(at, float(bid), float(ask), float(bid_size), float(ask_size)) for at, bid, ask, bid_size, ask_size, flags in rows
            if None not in (bid, ask, bid_size, ask_size) and usable(flags) and 0 < float(bid) < float(ask)]


# T2 -----------------------------------------------------------------------------------------------------------------

def maker_results(quotes: list[tuple], trades: list[tuple], fee: float) -> list[float]:
    """What the resting side of each trade made against the mid five minutes later, after two maker fees.

    `trades` are (epoch second, price, aggressor). A trade is skipped when no fresh quote exists at the horizon.
    """
    times = [quote[0] for quote in quotes]
    out = []
    for at, price, aggressor in trades:
        i = bisect_right(times, at + HORIZON_S) - 1
        if i < 0 or times[i] <= at or times[i] < at + HORIZON_S - FRESH_S:
            continue
        mid = (quotes[i][1] + quotes[i][2]) / 2
        # The taker bought, so the maker sold at `price` and can buy back at the later mid; and the reverse.
        out.append((price / mid - 1 if aggressor == "BUY" else mid / price - 1) - 2 * fee)
    return out


def t2_row(symbol: str, quote: str, quotes: list[tuple], trades: list[tuple], usdt_rate: float) -> dict | None:
    if len(quotes) < 100 or not trades:
        return None
    to_usdt = 1 / usdt_rate if quote == "TMN" else 1.0
    days = len({at // DAY for at, _, _ in trades})
    row = {"symbol": symbol, "days": days, "trades_per_day": len(trades) / days,
           "spread": median((ask - bid) / ((ask + bid) / 2) for _, bid, ask, _, _ in quotes),
           "touch_usdt": median(min(bid_size, ask_size) * (ask + bid) / 2 * to_usdt for _, bid, ask, bid_size, ask_size in quotes)}
    for name, fee in (("account", ACCOUNT_FEE), ("published", PUBLISHED[quote][0])):
        results = maker_results(quotes, trades, fee)
        mean = fmean(results) if results else 0.0
        t = mean / (stdev(results) / sqrt(len(results))) if len(results) > 1 and stdev(results) > 0 else 0.0
        row[name] = {"n": len(results), "mean": mean, "t": t}
        row[f"pass_{name}"] = (row["spread"] >= 0.004 and row["trades_per_day"] >= 50 and row["touch_usdt"] >= 50
                               and mean > 0 and t >= 4 and len(results) >= 500 and days >= 5)
    return row


def t2(connection) -> bool:
    markets = {f"wallex:{symbol}": (symbol, quote) for symbol, quote in connection.execute("SELECT symbol, quote FROM instruments")
               if quote in PUBLISHED}
    trades: dict[str, list] = {}
    for market, at, price, aggressor in connection.execute(
            "SELECT instrument_id, CAST(strftime('%s', ts_event) AS INTEGER), price, aggressor FROM trades ORDER BY ts_event"):
        trades.setdefault(market, []).append((at, float(price), aggressor))
    usdt_rate = median((bid + ask) / 2 for _, bid, ask, _, _ in quotes_of(connection, "USDTTMN"))
    stream = connection.execute(
        "SELECT instrument_id, CAST(strftime('%s', ts_avail) AS INTEGER), bid, ask, bid_qty, ask_qty, flags FROM book_top "
        "ORDER BY instrument_id, ts_avail")
    rows = []
    for market, group in groupby(stream, key=lambda row: row[0]):
        quotes = [(at, float(bid), float(ask), float(bid_size), float(ask_size)) for _, at, bid, ask, bid_size, ask_size, flags in group
                  if None not in (bid, ask, bid_size, ask_size) and usable(flags) and 0 < float(bid) < float(ask)]
        if market in markets:
            row = t2_row(*markets[market], quotes, trades.get(market, []), usdt_rate)
            if row:
                rows.append(row)
    wide = [row for row in rows if row["spread"] >= 0.004]
    liquid = [row for row in wide if row["trades_per_day"] >= 50 and row["touch_usdt"] >= 50]
    print(f"T2 quoting: {len(rows)} markets with quotes and trades; {len(wide)} with median spread >= 0.40%; "
          f"{len(liquid)} of those with >= 50 trades a day and touch >= 50 USDT")
    print("market          days trades/day spread% touch-USDT | account fee: n  mean%      t | published fee: mean%      t  pass")
    # The markets liquid enough to quote, then the strongest of the rest (mostly a handful of trades each).
    shown = sorted(liquid, key=lambda row: -row["account"]["t"]) + sorted(
        (row for row in rows if row not in liquid), key=lambda row: -row["account"]["t"])[:8]
    for row in shown:
        a, p = row["account"], row["published"]
        print(f"{row['symbol']:<15} {row['days']:4} {row['trades_per_day']:10.0f} {100 * row['spread']:7.3f} {row['touch_usdt']:10.0f} | "
              f"{a['n']:14} {100 * a['mean']:6.3f} {a['t']:6.1f} | {100 * p['mean']:20.3f} {p['t']:6.1f}  "
              f"{'ACCOUNT' if row['pass_account'] else '-'}{'+PUBLISHED' if row['pass_published'] else ''}")
    passed = [row["symbol"] for row in rows if row["pass_account"]]
    print(f"T2 VERDICT: {'PASS for ' + ', '.join(passed) if passed else 'FAIL: no market meets every condition'}")
    return bool(passed)


# T3 -----------------------------------------------------------------------------------------------------------------

def last_fresh(quotes: list[tuple], times: list[int], at: int):
    i = bisect_right(times, at) - 1
    return quotes[i] if i >= 0 and times[i] >= at - FRESH_S else None


def triangle_gaps(usdt_tmn, coin_tmn, coin_usdt, fees: float) -> list[tuple[int, float]]:
    """(minute, best of the two directions) for a Toman round trip through the coin, at executable prices."""
    series = [(quotes, [quote[0] for quote in quotes]) for quotes in (usdt_tmn, coin_tmn, coin_usdt)]
    if any(not quotes for quotes, _ in series):
        return []
    start = max(times[0] for _, times in series) // 60 * 60 + 60
    end = min(times[-1] for _, times in series)
    out = []
    for at in range(start, end, 60):
        if not SESSION[0] <= at % DAY < SESSION[1]:
            continue
        ut, ct, cu = (last_fresh(quotes, times, at) for quotes, times in series)
        if ut and ct and cu:
            via_coin = cu[1] * ut[1] / ct[2]  # Toman buys the coin, the coin sells for USDT, USDT sells for Toman
            via_usdt = ct[1] / (ut[2] * cu[2])  # Toman buys USDT, USDT buys the coin, the coin sells for Toman
            out.append((at, max(via_coin, via_usdt) - 1 - fees))
    return out


def t3(connection) -> bool:
    usdt_tmn = quotes_of(connection, "USDTTMN")
    passed = False
    for coin in ("BTC", "ETH"):
        coin_tmn, coin_usdt = quotes_of(connection, f"{coin}TMN"), quotes_of(connection, f"{coin}USDT")
        for name, fees in (("account", 3 * ACCOUNT_FEE), ("published", 2 * PUBLISHED["TMN"][1] + PUBLISHED["USDT"][1])):
            gaps = triangle_gaps(usdt_tmn, coin_tmn, coin_usdt, fees)
            if not gaps:
                print(f"T3 {coin} {name}: no minutes with all three quotes")
                continue
            positive = [(at, gap) for at, gap in gaps if gap > 0]
            share, days = len(positive) / len(gaps), len({at // DAY for at, _ in positive})
            ok = share >= 0.01 and days >= 5
            passed = passed or (ok and name == "account")
            print(f"T3 {coin} {name} fees {100 * fees:.2f}%: {len(gaps)} minutes on {len({at // DAY for at, _ in gaps})} days; "
                  f"median gap {100 * median(gap for _, gap in gaps):.3f}%, best {100 * max(gap for _, gap in gaps):.3f}%; "
                  f"positive {100 * share:.2f}% of minutes on {days} days; {'pass' if ok else 'fail'}")
    print(f"T3 VERDICT: {'PASS' if passed else 'FAIL'}")
    return passed


# T4 -----------------------------------------------------------------------------------------------------------------

def trend_returns(closes: list[float], window: int, cost: float) -> list[float]:
    """Daily returns of holding the asset only while yesterday's close was above its `window`-day average."""
    out, held = [], False
    for i in range(window - 1, len(closes) - 1):
        want = closes[i] > fmean(closes[i - window + 1:i + 1])
        out.append((closes[i + 1] / closes[i] - 1 if want else 0.0) - (cost if want != held else 0.0))
        held = want
    return out


def t4(connection, split: str = "2024-01-01") -> bool:
    cells = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        rows = connection.execute("SELECT t, c FROM venue_candles WHERE instrument_id=? AND resolution='1d' "
                                  "AND CAST(v AS REAL) > 0 ORDER BY t", (f"wallex:{symbol}",)).fetchall()
        if len(rows) < 400:
            print(f"T4 {symbol}: {len(rows)} traded daily candles; run `gymctl history {symbol} --resolution 1d` first")
            return False
        days, closes = [row[0] for row in rows], [float(row[1]) for row in rows]
        for window in (50, 100, 200):
            cells.append({"symbol": symbol, "window": window, "days": days[window:], "closes": closes})
    passed = False
    for name, cost in (("account", ACCOUNT_FEE + 0.001), ("published", PUBLISHED["USDT"][1] + 0.001)):
        for cell in cells:
            returns = trend_returns(cell["closes"], cell["window"], cost)
            cut = bisect_right(cell["days"], split)
            cell["rank"], cell["held"] = returns[:cut], returns[cut:]
            mean, deviation, skew, kurtosis = _moments(cell["rank"])
            cell["sharpe"], cell["moments"] = (mean / deviation if deviation else 0.0), (skew, kurtosis)
        variance = pvariance([cell["sharpe"] for cell in cells])
        print(f"T4 trend, {name} cost {100 * cost:.2f}% per side (fee plus 0.10% for half the spread); ranked before {split}")
        for cell in cells:
            cell["deflated"] = deflated_sharpe(cell["sharpe"], len(cell["rank"]), *cell["moments"], len(cells), variance) or 0.0
            total = 1.0
            for value in cell["rank"]:
                total *= 1 + value
            print(f"  {cell['symbol']} {cell['window']:3}-day: {len(cell['rank'])} days, total {100 * (total - 1):8.1f}%, "
                  f"yearly Sharpe {cell['sharpe'] * sqrt(365):5.2f}, deflated {cell['deflated']:.3f}")
        best = max(cells, key=lambda cell: cell["deflated"])
        if best["deflated"] < 0.95:
            print(f"  {name}: FAIL on ranking days (best {best['symbol']} {best['window']}-day, {best['deflated']:.3f}); later days not scored")
            continue
        mean, deviation, skew, kurtosis = _moments(best["held"])
        alone = deflated_sharpe(mean / deviation if deviation else 0.0, len(best["held"]), skew, kurtosis, 1, 0.0) or 0.0
        print(f"  {name}: {best['symbol']} {best['window']}-day passed ranking; days from {split} scored once: "
              f"{len(best['held'])} days, yearly Sharpe {mean / deviation * sqrt(365) if deviation else 0:.2f}, "
              f"probability Sharpe > 0: {alone:.3f}; {'pass' if alone >= 0.90 else 'fail'}")
        passed = passed or (alone >= 0.90 and name == "account")
    print(f"T4 VERDICT: {'PASS' if passed else 'FAIL'}")
    return passed


# T5 -----------------------------------------------------------------------------------------------------------------

def best_round_trip(quotes: list[tuple]) -> float | None:
    """Buy at the lowest ask so far, sell at a later bid: the most one same-day round trip at the touch could make."""
    lowest, best = quotes[0][2], None
    for _, bid, ask, _, _ in quotes[1:]:
        trip = bid / lowest - 1
        best = trip if best is None else max(best, trip)
        lowest = min(lowest, ask)
    return best


def t5(connection, symbol: str = "USDSUSDT") -> bool:
    quotes = quotes_of(connection, symbol)
    days = [list(group) for _, group in groupby(quotes, key=lambda quote: quote[0] // DAY)]
    trips = [trip for trip in (best_round_trip(day) for day in days if len(day) > 100) if trip is not None]
    if not trips:
        print(f"T5 {symbol}: no usable days")
        return False
    touch = median(min(bid_size, ask_size) * (bid + ask) / 2 for _, bid, ask, bid_size, ask_size in quotes)
    spread = median((ask - bid) / ((ask + bid) / 2) for _, bid, ask, _, _ in quotes)
    passed = median(trips) >= 0.002 and touch >= 100
    print(f"T5 {symbol}: {len(trips)} days; median spread {100 * spread:.3f}%; median touch {touch:.0f} USDT; "
          f"best same-day round trip: median {100 * median(trips):.3f}%, largest {100 * max(trips):.3f}%")
    print(f"T5 VERDICT: {'PASS' if passed else 'FAIL'}")
    return passed


SCREENS = {"T2": t2, "T3": t3, "T4": t4, "T5": t5}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("screens", nargs="*", choices=[*SCREENS, []], default=list(SCREENS))
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parents[2] / "data/live/market.db")
    args = parser.parse_args(argv)
    connection = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    try:
        for name in args.screens or SCREENS:
            SCREENS[name](connection)
            print()
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
