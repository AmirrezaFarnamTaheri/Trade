"""rule-selector-with-cash: each month hold the daily rule with the best trailing after-cost return, or USDT when none made money.

Registered in docs/trial-log.md before this script ran. Ranks 30 cells (ten coins x three lookbacks) on Binance
days before 2024-01-01, then scores the best lookback once on Wallex margin markets no trend trial has scored.

    uv run --no-sync python scripts/rule_selector.py --db ../data/live/market.db
"""
import argparse
import sqlite3
import sys
from math import sqrt
from pathlib import Path
from random import Random
from statistics import fmean, pvariance

sys.path.insert(0, str(Path(__file__).resolve().parent))
import long_history_study as study  # noqa: E402
from edge_screen import venue_daily  # noqa: E402

from gym.domain.performance import _moments, deflated_sharpe  # noqa: E402

RANK_COINS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT", "TRXUSDT", "LINKUSDT")
HELD_OUT = ("ARBUSDT", "AUSDT", "CAKEUSDT", "COPXONUSDT", "DOTUSDT", "PEPEUSDT", "SHIBUSDT", "SLVONUSDT", "USOONUSDT", "XAUTUSDT")
LOOKBACKS, MONTH, SPLIT, COST = (90, 180, 365), 30, "2024-01-01", 0.002
WARM = 200  # the longest rule needs 200 closes before its first decision


def positions(closes):
    """Each rule's position (1 held, 0 cash) decided at every close, None before it is warm."""
    n, rules = len(closes), {}
    for window in (50, 100, 200):
        rules[f"sma{window}"] = [None if i < window - 1 else float(closes[i] > fmean(closes[i - window + 1:i + 1])) for i in range(n)]
    for window in (30, 90):
        rules[f"mom{window}"] = [None if i < window else float(closes[i] > closes[i - window]) for i in range(n)]
    for window in (20, 55):
        held, out = 0.0, []
        for i in range(n):
            if i < window:
                out.append(None)
                continue
            if closes[i] > max(closes[i - window:i]):
                held = 1.0
            elif closes[i] < min(closes[i - 20:i]):
                held = 0.0
            out.append(held)
        rules[f"don{window}"] = out
    return rules


def earn(closes, position):
    """Daily returns: the position set at close i-1 earns close i, and every change pays COST."""
    out, held = [0.0] * len(closes), 0.0
    for i in range(1, len(closes)):
        want = position[i - 1] or 0.0
        out[i] = want * (closes[i] / closes[i - 1] - 1) - COST * abs(want - held)
        held = want
    return out


def select(closes, lookback):
    """The selector's position each day, and the rule (or 'cash') it was following."""
    rules = positions(closes)
    alone = {name: earn(closes, pos) for name, pos in rules.items()}
    chosen, position, current = [], [None] * len(closes), "cash"
    for i in range(len(closes)):
        if i < WARM + lookback:
            chosen.append(None)
            continue
        if (i - WARM - lookback) % MONTH == 0:
            trailing = {name: sum(r[i - lookback + 1:i + 1]) for name, r in alone.items()}
            best = max(sorted(trailing), key=trailing.get)
            current = best if trailing[best] > 0 else "cash"
        chosen.append(current)
        position[i] = 0.0 if current == "cash" else rules[current][i]
    return position, chosen, alone


def total(series):
    value = 1.0
    for r in series:
        value *= 1 + r
    return value - 1


def block_probability(series, block=20, draws=2000, seed=0):
    """Share of day-block resamples whose mean return is above zero."""
    rng, n = Random(seed), len(series)
    if n < block * 3:
        return 0.0
    above = 0
    for _ in range(draws):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n - block + 1)
            sample.extend(series[start:start + block])
        above += fmean(sample[:n]) > 0
    return above / draws


def ranked(days, closes, lookback):
    """Selector and single-rule returns on days before SPLIT, from the first selection on."""
    position, chosen, alone = select(closes, lookback)
    mine = earn(closes, position)
    keep = [i for i in range(WARM + lookback + 1, len(days)) if days[i] < SPLIT]
    return [mine[i] for i in keep], {name: [r[i] for i in keep] for name, r in alone.items()}, [chosen[i] for i in keep]


def verdict(rank_source, held_source) -> bool:
    cells = []
    for symbol in RANK_COINS:
        for lookback in LOOKBACKS:
            series, singles, chosen = ranked(*rank_source[symbol], lookback)
            mean, deviation, skew, kurtosis = _moments(series)
            best_rule = max(singles, key=lambda name: total(singles[name]))
            cells.append({"symbol": symbol, "lookback": lookback, "series": series, "moments": (skew, kurtosis),
                          "sharpe": mean / deviation if deviation else 0.0, "best_rule": best_rule,
                          "best_rule_total": total(singles[best_rule]), "cash_share": chosen.count("cash") / len(chosen)})
    variance = pvariance([cell["sharpe"] for cell in cells])
    print(f"rule-selector-with-cash ranked before {SPLIT}; {100 * COST:.2f}% per side on every change")
    for cell in cells:
        cell["deflated"] = deflated_sharpe(cell["sharpe"], len(cell["series"]), *cell["moments"], len(cells), variance) or 0.0
        print(f"  {cell['symbol']:9} {cell['lookback']:3}-day lookback: total {100 * total(cell['series']):9.1f}% "
              f"(best single rule {cell['best_rule']} {100 * cell['best_rule_total']:9.1f}%), in USDT {100 * cell['cash_share']:4.0f}% of days, "
              f"yearly Sharpe {cell['sharpe'] * sqrt(365):5.2f}, deflated {cell['deflated']:.3f}")
    best = max(cells, key=lambda cell: cell["deflated"])
    beats = total(best["series"]) > best["best_rule_total"]
    if best["deflated"] < 0.95 or not beats:
        print(f"rule-selector-with-cash FAIL on ranking days (best {best['symbol']} {best['lookback']}-day, deflated {best['deflated']:.3f}, "
              f"{'beats' if beats else 'below'} its best single rule); held-out markets not scored")
        return False
    by_day = {}
    for days, closes in held_source.values():
        position, _, _ = select(closes, best["lookback"])
        for day, r in list(zip(days, earn(closes, position), strict=True))[WARM + best["lookback"] + 1:]:
            by_day.setdefault(day, []).append(r)
    held = [fmean(by_day[day]) for day in sorted(by_day)]
    chance = block_probability(held)
    mean, deviation, _, _ = _moments(held)
    print(f"  held out, {best['lookback']}-day lookback on {len(held_source)} markets: {len(held)} days, total {100 * total(held):.1f}%, "
          f"yearly Sharpe {mean / deviation * sqrt(365) if deviation else 0:.2f}, block-bootstrap probability Sharpe > 0: {chance:.3f}")
    print(f"rule-selector-with-cash VERDICT: {'PASS' if chance >= 0.90 else 'FAIL'}")
    return chance >= 0.90


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    rank_source = {symbol: study.load(symbol, "1d", study.CACHE) for symbol in RANK_COINS}
    connection = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    verdict(rank_source, {symbol: venue_daily(connection, symbol) for symbol in HELD_OUT})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
