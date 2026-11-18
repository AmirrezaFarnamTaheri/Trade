"""Trial `margin-breakout-long-short`: Wallex spot and margin together on 20-day breakouts, held for days only.

Registered in docs/trial-log.md before this script ran. Long on a close above the previous 20-day high, short on a
close below the previous 20-day low; out after the holding limit or on the opposite signal (which flips the position).
A 1x long uses spot; 2x longs and every short use margin with Wallex's fees, 4-hourly loan fee and liquidation level.
Each position is valued at every daily close as if closed there, so the daily series already carries exit costs.

    uv run --no-sync python scripts/margin_breakout.py      # after `scripts/binance_archive.py fetch`
"""
import sys
from datetime import date
from math import sqrt
from pathlib import Path
from statistics import fmean, pvariance

sys.path.insert(0, str(Path(__file__).resolve().parent))
from binance_archive import daily_funding, liquid, spot_daily, universe  # noqa: E402
from funding_filter import HELD_END, SPLIT, USED_AFTER_SPLIT  # noqa: E402
from margin_hold import hold  # noqa: E402
from rule_selector import block_probability, total  # noqa: E402

from gym.domain.performance import _moments, deflated_sharpe  # noqa: E402

LOOKBACK, HALF_SPREAD, SPOT_FEE, DAY = 20, 0.001, 0.001, 86400
SETTINGS = ((5, 1), (5, 2), (10, 1), (10, 2))  # (most days held, credit ratio)
FUNDING_YEAR = 372  # days of funding needed before a coin counts: 7-day mean plus a year of them


def signal(closes, i):
    """+1 on a close above the previous 20 closes, -1 below them, 0 otherwise."""
    window = closes[i - LOOKBACK:i]
    return 1 if closes[i] > max(window) else -1 if closes[i] < min(window) else 0


def value(side, ratio, entry_close, bars, start, end):
    """Equity (start of trade = 1) of a position opened at close `start`, valued as if closed at close `end`."""
    if side > 0 and ratio == 1:  # spot: buy at the ask, sell at the bid, fee on each side
        units = (1 - SPOT_FEE) / (entry_close * (1 + HALF_SPREAD))
        return units * bars["close"][end] * (1 - HALF_SPREAD) * (1 - SPOT_FEE), False
    entry = entry_close * (1 + HALF_SPREAD * side)
    path = [((k - start) * DAY, bars["low"][k], bars["high"][k]) for k in range(start + 1, end + 1)]
    exit_price = bars["close"][end] * (1 - HALF_SPREAD * side)
    result = hold("long" if side > 0 else "short", ratio, entry, path, exit_price)
    return 1 + result["ret"], result["liquidated_h"] is not None


def coin_returns(bars, counted, most_days, ratio):
    """Daily (day, return) for one coin while it counts; flat days count as zero."""
    out, trade = [], None  # trade: (side, entry index, equity at the previous close)
    closes = bars["close"]
    for j in range(LOOKBACK, len(closes)):
        day = bars["days"][j]
        if trade:
            side, start, before = trade
            equity, liquidated = value(side, ratio, closes[start], bars, start, j)
            out.append((day, equity / before - 1))
            trade = (side, start, equity)
            flip = signal(closes, j) == -side
            if liquidated or j - start >= most_days or flip or not counted[j]:
                trade = None
                if flip and counted[j] and not liquidated:
                    trade = (-side, j, 1.0)
            continue
        if not counted[j]:
            continue
        out.append((day, 0.0))
        side = signal(closes, j)
        if side:
            trade = (side, j, 1.0)
    return out


def pooled(data, most_days, ratio, lo, hi):
    by_day = {}
    for bars, counted in data.values():
        for day, r in coin_returns(bars, counted, most_days, ratio):
            if lo <= day < hi:
                by_day.setdefault(day, []).append(r)
    return [fmean(by_day[day]) for day in sorted(by_day)]


def verdict(rank_data, held_data) -> bool:
    cells = []
    for most_days, ratio in SETTINGS:
        values = pooled(rank_data, most_days, ratio, "2000", SPLIT)
        mean, deviation, skew, kurtosis = _moments(values)
        cells.append({"days": most_days, "ratio": ratio, "values": values, "moments": (skew, kurtosis),
                      "sharpe": mean / deviation if deviation else 0.0})
    variance = pvariance([c["sharpe"] for c in cells])
    print(f"margin-breakout-long-short ranked before {SPLIT} on {len(rank_data)} coins")
    for c in cells:
        c["deflated"] = deflated_sharpe(c["sharpe"], len(c["values"]), *c["moments"], len(cells), variance) or 0.0
        print(f"  hold up to {c['days']:2} days at {c['ratio']}x: {len(c['values'])} days, total {100 * total(c['values']):9.1f}%, "
              f"yearly Sharpe {c['sharpe'] * sqrt(365):5.2f}, deflated {c['deflated']:.3f}")
    best = max(cells, key=lambda c: c["deflated"])
    if best["deflated"] < 0.95:
        print(f"margin-breakout-long-short FAIL on ranking days (best {best['days']} days at {best['ratio']}x, "
              f"deflated {best['deflated']:.3f}); held-out days not scored")
        return False
    values = pooled(held_data, best["days"], best["ratio"], SPLIT, HELD_END)
    mean, deviation, _, _ = _moments(values)
    chance = block_probability(values)
    print(f"  held out, {best['days']} days at {best['ratio']}x: {len(held_data)} coins, {len(values)} days, total {100 * total(values):.1f}%, "
          f"yearly Sharpe {mean / deviation * sqrt(365):.2f}, block-bootstrap probability {chance:.3f}")
    print(f"margin-breakout-long-short verdict: {'PASS' if chance >= 0.90 else 'FAIL'}")
    return chance >= 0.90


def counted_days(bars, funding):
    """A coin counts on a day when it is liquid and a year of funding history exists, as in funding-crowding-filter."""
    first = min(funding) if funding else None
    flags = liquid(bars["volume"])
    start = date.fromisoformat(first) if first else None
    return [flag and start is not None and (date.fromisoformat(day) - start).days >= FUNDING_YEAR
            for flag, day in zip(flags, bars["days"], strict=True)]


def main() -> int:
    data = {}
    for coin in universe():
        bars = spot_daily(coin)
        if len(bars["days"]) > LOOKBACK + 1:
            data[coin] = (bars, counted_days(bars, daily_funding(coin)))
    held = {coin: d for coin, d in data.items() if coin not in USED_AFTER_SPLIT}
    verdict(data, held)
    return 0


if __name__ == "__main__":
    sys.exit(main())
