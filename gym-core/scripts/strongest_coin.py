"""T14: hold only the strongest qualifying coin, reviewed weekly, or USDT when none qualifies.

Registered in docs/trial-log.md before this script ran. Ranks 3 settings on Binance days before 2024-01-01, then
scores the best once on Wallex margin markets no trial has scored.

    uv run --no-sync python scripts/strongest_coin.py --db ../data/live/market.db
"""
import argparse
import sqlite3
import sys
from math import sqrt
from pathlib import Path
from statistics import fmean, pvariance

sys.path.insert(0, str(Path(__file__).resolve().parent))
import long_history_study as study  # noqa: E402
from edge_screen import venue_daily  # noqa: E402
from rule_selector import block_probability, total  # noqa: E402

from gym.domain.performance import _moments, deflated_sharpe  # noqa: E402

RANK_COINS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT", "TRXUSDT", "LINKUSDT")
HELD_OUT = ("ARBUSDT", "AUSDT", "CAKEUSDT", "COPXONUSDT", "DOTUSDT", "PEPEUSDT", "SHIBUSDT", "SLVONUSDT", "USOONUSDT", "XAUTUSDT")
LOOKBACKS, AVERAGE, ELIGIBLE, WEEK, SPLIT, COST = (30, 90, 180), 100, 181, 7, "2024-01-01", 0.002


def rotate(series, lookback):
    """Daily (day, return, holding) for the strongest-coin rule over every day any coin trades.

    `series` maps a coin to (days, closes). A coin's history is its own list, so a coin is eligible only from its
    181st close, and every value used at a review is a close on or before that day.
    """
    index = {coin: {day: i for i, day in enumerate(days)} for coin, (days, _) in series.items()}
    calendar = sorted({day for days, _ in series.values() for day in days[:-1]})
    out, held = [], None
    for n, day in enumerate(calendar):
        if n % WEEK == 0:
            best, strength = None, 0.0
            for coin, (_, closes) in sorted(series.items()):
                i = index[coin].get(day)
                if i is None or i + 1 < max(ELIGIBLE, lookback + 1, AVERAGE):
                    continue
                gain = closes[i] / closes[i - lookback] - 1
                if gain > strength and closes[i] > fmean(closes[i - AVERAGE + 1:i + 1]):
                    best, strength = coin, gain
            cost = 0.0 if best == held else COST * ((held is not None) + (best is not None))
            held = best
        else:
            cost = 0.0
        move = 0.0
        if held is not None:
            i = index[held].get(day)
            closes = series[held][1]
            if i is not None and i + 1 < len(closes):
                move = closes[i + 1] / closes[i] - 1
        out.append((day, (1 + move) * (1 - cost) - 1, held))
    return out


def verdict(rank_source, held_source) -> bool:
    cells = []
    for lookback in LOOKBACKS:
        rows = [r for r in rotate(rank_source, lookback) if r[0] < SPLIT]
        first = next(i for i, r in enumerate(rows) if r[2] is not None)
        series = [r[1] for r in rows[first:]]
        mean, deviation, skew, kurtosis = _moments(series)
        cells.append({"lookback": lookback, "series": series, "moments": (skew, kurtosis), "sharpe": mean / deviation if deviation else 0.0,
                      "cash": sum(r[2] is None for r in rows[first:]) / len(series),
                      "switches": sum(a[2] != b[2] for a, b in zip(rows[first:], rows[first + 1:], strict=False))})
    variance = pvariance([c["sharpe"] for c in cells])
    print(f"T14 ranked before {SPLIT}; {100 * COST:.2f}% per side on every rotation")
    for c in cells:
        c["deflated"] = deflated_sharpe(c["sharpe"], len(c["series"]), *c["moments"], len(cells), variance) or 0.0
        print(f"  {c['lookback']:3}-day strength: {len(c['series'])} days, total {100 * total(c['series']):10.1f}%, in USDT {100 * c['cash']:4.0f}% of days, "
              f"{c['switches']} changes, yearly Sharpe {c['sharpe'] * sqrt(365):5.2f}, deflated {c['deflated']:.3f}")
    best = max(cells, key=lambda c: c["deflated"])
    if best["deflated"] < 0.95:
        print(f"T14 FAIL on ranking days (best {best['lookback']}-day, deflated {best['deflated']:.3f}); held-out markets not scored")
        return False
    rows = rotate(held_source, best["lookback"])
    counts = {}
    start = None
    for day, _, _ in rows:
        ready = sum(1 for days, _ in held_source.values() if day in days and days.index(day) >= ELIGIBLE - 1)
        counts[day] = ready
        if start is None and ready >= 3:
            start = day
    held = [r[1] for r in rows if start and r[0] >= start]
    chance = block_probability(held)
    mean, deviation, _, _ = _moments(held)
    print(f"  held out from {start}, {best['lookback']}-day strength: {len(held)} days, total {100 * total(held):.1f}%, "
          f"yearly Sharpe {mean / deviation * sqrt(365) if deviation else 0:.2f}, block-bootstrap probability Sharpe > 0: {chance:.3f}")
    print(f"T14 VERDICT: {'PASS' if chance >= 0.90 else 'FAIL'}")
    return chance >= 0.90


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    rank_source = {coin: study.load(coin, "1d", study.CACHE) for coin in RANK_COINS}
    rank_source = {coin: ([d[:10] for d in days], closes) for coin, (days, closes) in rank_source.items()}
    connection = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    held = {coin: venue_daily(connection, coin) for coin in HELD_OUT}
    verdict(rank_source, {coin: ([d[:10] for d in days], closes) for coin, (days, closes) in held.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
