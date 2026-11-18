"""Trials `spot-breakout-long` and `funding-confirmed-trend`, scored once on the held-out days only.

Registered in docs/trial-log.md before this script ran. Both reuse the coins, liquidity floor, funding-history condition
and costs of `funding-crowding-filter`; each has one setting, so nothing is selected.

    uv run --no-sync python scripts/held_out_followups.py      # after `scripts/binance_archive.py fetch`
"""
import sys
from math import sqrt
from pathlib import Path
from statistics import fmean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import funding_filter  # noqa: E402
from binance_archive import daily_funding, liquid, spot_daily, universe  # noqa: E402
from margin_breakout import counted_days, signal, value  # noqa: E402
from rule_selector import block_probability, total  # noqa: E402

from gym.domain.performance import _moments  # noqa: E402

LO, HI = funding_filter.SPLIT, funding_filter.HELD_END
MOST_DAYS = 10


def breakout_long(bars, counted):
    """Daily (day, return) of the spot breakout rule and of simply holding the coin, on the days the coin counts."""
    rule, hold, trade = [], [], None  # trade: (entry index, equity at the previous close)
    closes = bars["close"]
    for j in range(funding_filter.WINDOW, len(closes)):
        day = bars["days"][j]
        if counted[j - 1]:
            hold.append((day, closes[j] / closes[j - 1] - 1))
        if trade:
            start, before = trade
            equity, _ = value(1, 1, closes[start], bars, start, j)
            rule.append((day, equity / before - 1))
            trade = (start, equity)
            if j - start >= MOST_DAYS or signal(closes, j) == -1 or not counted[j]:
                trade = None
            continue
        if counted[j]:
            rule.append((day, 0.0))
            if signal(closes, j) == 1:
                trade = (j, 1.0)
    return rule, hold


def pooled(rows_by_coin):
    by_day = {}
    for rows in rows_by_coin:
        for day, r in rows:
            if LO <= day < HI:
                by_day.setdefault(day, []).append(r)
    return [fmean(by_day[day]) for day in sorted(by_day)]


def sharpe(values):
    mean, deviation, _, _ = _moments(values)
    return mean / deviation if deviation else 0.0


def report(name, values, base, base_name):
    chance = block_probability(values)
    passed = chance >= 0.90 and sharpe(values) > sharpe(base)
    print(f"{name} held out {LO} to {HI}: {len(values)} days, total {100 * total(values):.1f}% ({base_name} {100 * total(base):.1f}%), "
          f"yearly Sharpe {sharpe(values) * sqrt(365):.2f} ({base_name} {sharpe(base) * sqrt(365):.2f}), block-bootstrap probability {chance:.3f}")
    print(f"{name} verdict: {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> int:
    coins = [c for c in universe() if c not in funding_filter.USED_AFTER_SPLIT]
    rules, holds, confirmed, plain_gate, data = [], [], [], {}, {}
    for coin in coins:
        bars = spot_daily(coin)
        if len(bars["days"]) <= funding_filter.WINDOW + 1:
            continue
        funding = daily_funding(coin)
        rule, hold = breakout_long(bars, counted_days(bars, funding))
        rules.append(rule)
        holds.append(hold)
        crowded = funding_filter.crowded(bars["days"], funding, 0.70)
        # Hold only when crowded: the filter's "stand aside" flag is the opposite of crowded.
        aside = [None if flag is None else not flag for flag in crowded]
        rows = funding_filter.returns(bars["days"], bars["close"], aside, liquid(bars["volume"]))
        confirmed.append(rows)
        plain_gate[coin] = {day for day, _ in rows if LO <= day < HI}
        data[coin] = bars
    print(f"{len(rules)} held-out coins")
    report("spot-breakout-long", pooled(rules), pooled(holds), "equal-weight holding")
    plain = [[(d, r) for d, r in funding_filter.returns(b["days"], b["close"], None, liquid(b["volume"])) if d in plain_gate[c]]
             for c, b in data.items()]
    report("funding-confirmed-trend", pooled(confirmed), pooled(plain), "unfiltered trend rule")
    return 0


if __name__ == "__main__":
    sys.exit(main())
