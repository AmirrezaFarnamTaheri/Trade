"""trend-with-short-side: the btc-daily-trend trend rule, short below its average instead of in USDT, at 1x or 2x of equity.

Registered in docs/trial-log.md before this script ran. Ranks 60 cells on Binance days before 2024-01-01, then
scores the best window and ratio once on Wallex margin markets no trend trial has used.

    uv run --no-sync python scripts/trend_short.py --db ../data/live/market.db
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

from gym.domain.performance import _moments, deflated_sharpe  # noqa: E402

RANK_COINS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT", "TRXUSDT", "LINKUSDT")
HELD_OUT = ("ARBUSDT", "AUSDT", "CAKEUSDT", "COPXONUSDT", "DOTUSDT", "PEPEUSDT", "SHIBUSDT", "SLVONUSDT", "USOONUSDT", "XAUTUSDT")
WINDOWS, RATIOS = (50, 100, 200), (1.0, 2.0)
SPLIT = "2024-01-01"
COST = 0.0025 + 0.001  # margin trade fee plus half the spread, per side
CARRY, ROLL, LIQUIDATION = 0.0009, 21, 0.15  # per day on borrowed notional; days; equity share of the position


def returns(days, closes, window, ratio, *, short=True):
    """Daily (day, return) pairs; the position for day i+1 is decided at close i once the average is warm."""
    targets = [None] * len(closes)
    for i in range(window - 1, len(closes)):
        above = closes[i] > fmean(closes[i - window + 1:i + 1])
        targets[i] = ratio if above else (-ratio if short else 0.0)
    moves = [0.0] + [b / a - 1 for a, b in zip(closes, closes[1:], strict=False)]
    out, _, _, _ = study.run(moves, targets, COST, carry=CARRY, roll=ROLL, liquidation=LIQUIDATION)
    return list(zip(days[window:], out[window:], strict=True))


def probability(series):
    mean, deviation, skew, kurtosis = _moments(series)
    return mean, deviation, (deflated_sharpe(mean / deviation if deviation else 0.0, len(series), skew, kurtosis, 1, 0.0) or 0.0)


def total(series):
    value = 1.0
    for r in series:
        value *= 1 + r
    return value - 1


def pooled(markets, window, ratio, *, short=True):
    """Equal weight across the markets that trade each day; re-equalising is not charged (stated in the trial)."""
    by_day = {}
    for days, closes in markets.values():
        for day, r in returns(days, closes, window, ratio, short=short):
            by_day.setdefault(day, []).append(r)
    return [fmean(by_day[day]) for day in sorted(by_day)]


def verdict(rank_source, held_source) -> bool:
    cells = []
    for symbol in RANK_COINS:
        days, closes = rank_source[symbol]
        for window in WINDOWS:
            for ratio in RATIOS:
                series = [r for day, r in returns(days, closes, window, ratio) if day < SPLIT]
                mean, deviation, skew, kurtosis = _moments(series)
                cells.append({"symbol": symbol, "window": window, "ratio": ratio, "series": series,
                              "moments": (skew, kurtosis), "sharpe": mean / deviation if deviation else 0.0})
    variance = pvariance([cell["sharpe"] for cell in cells])
    print(f"trend-with-short-side ranked before {SPLIT}; cost {100 * COST:.2f}% per side, carry {100 * CARRY:.2f}% a day on borrowed amounts")
    for cell in cells:
        cell["deflated"] = deflated_sharpe(cell["sharpe"], len(cell["series"]), *cell["moments"], len(cells), variance) or 0.0
        long_only = [r for day, r in returns(*rank_source[cell["symbol"]], cell["window"], cell["ratio"], short=False) if day < SPLIT]
        print(f"  {cell['symbol']:9} {cell['window']:3}-day {cell['ratio']:.0f}x: total {100 * total(cell['series']):9.1f}% "
              f"(long or cash {100 * total(long_only):8.1f}%), yearly Sharpe {cell['sharpe'] * sqrt(365):5.2f}, deflated {cell['deflated']:.3f}")
    best = max(cells, key=lambda cell: cell["deflated"])
    if best["deflated"] < 0.95:
        print(f"trend-with-short-side FAIL on ranking days (best {best['symbol']} {best['window']}-day {best['ratio']:.0f}x, {best['deflated']:.3f}); held-out markets not scored")
        return False
    held = pooled(held_source, best["window"], best["ratio"])
    mean, deviation, chance = probability(held)
    print(f"  held out, {best['window']}-day {best['ratio']:.0f}x on {len(held_source)} markets: {len(held)} days, total {100 * total(held):.1f}%, "
          f"yearly Sharpe {mean / deviation * sqrt(365) if deviation else 0:.2f}, probability Sharpe > 0: {chance:.3f}")
    print(f"trend-with-short-side VERDICT: {'PASS' if chance >= 0.90 else 'FAIL'}")
    return chance >= 0.90


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    rank_source = {symbol: study.load(symbol, "1d", study.CACHE) for symbol in RANK_COINS}
    connection = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    held_source = {symbol: venue_daily(connection, symbol) for symbol in HELD_OUT}
    verdict(rank_source, held_source)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
