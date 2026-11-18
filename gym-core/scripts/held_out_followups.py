"""Trials `spot-breakout-long` and `funding-confirmed-trend` on the held-out days, and `funding-confirmed-trend-forward`.

Registered in docs/trial-log.md before this script ran. Both reuse the coins, liquidity floor, funding-history condition
and costs of `funding-crowding-filter`; each has one setting, so nothing is selected.

    uv run --no-sync python scripts/held_out_followups.py              # after `scripts/binance_archive.py fetch`
    uv run --no-sync python scripts/held_out_followups.py --forward    # only once the archive covers 2027-02-08
"""
import sys
from datetime import UTC, datetime
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
FORWARD_LO, FORWARD_HI = "2026-11-18", "2027-02-09"  # last scored day 2027-02-08, the product checkpoint
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


def pooled(rows_by_coin, lo=LO, hi=HI):
    by_day = {}
    for rows in rows_by_coin:
        for day, r in rows:
            if lo <= day < hi:
                by_day.setdefault(day, []).append(r)
    return [fmean(by_day[day]) for day in sorted(by_day)]


def sharpe(values):
    mean, deviation, _, _ = _moments(values)
    return mean / deviation if deviation else 0.0


def report(name, values, base, base_name, lo=LO, hi=HI, block=20):
    chance = block_probability(values, block=block)
    passed = chance >= 0.90 and sharpe(values) > sharpe(base)
    print(f"{name} {lo} to {hi}: {len(values)} days, total {100 * total(values):.1f}% ({base_name} {100 * total(base):.1f}%), "
          f"yearly Sharpe {sharpe(values) * sqrt(365):.2f} ({base_name} {sharpe(base) * sqrt(365):.2f}), block-bootstrap probability {chance:.3f}")
    print(f"{name} verdict: {'PASS' if passed else 'FAIL'}")
    return passed


def confirmed_trend(coin, lo, hi):
    """(rule rows, unfiltered rows on the same coin-days) for one coin, or None without enough history."""
    bars = spot_daily(coin)
    if len(bars["days"]) <= funding_filter.WINDOW + 1:
        return None
    crowded = funding_filter.crowded(bars["days"], daily_funding(coin), 0.70)
    aside = [None if flag is None else not flag for flag in crowded]  # hold only when crowded
    rows = funding_filter.returns(bars["days"], bars["close"], aside, liquid(bars["volume"]))
    gate = {day for day, _ in rows if lo <= day < hi}
    plain = [(d, r) for d, r in funding_filter.returns(bars["days"], bars["close"], None, liquid(bars["volume"])) if d in gate]
    return rows, plain


def forward(today=None) -> int:
    today = today or datetime.now(UTC).strftime("%Y-%m-%d")
    if today < FORWARD_HI:
        raise SystemExit(f"funding-confirmed-trend-forward scores from {FORWARD_HI}; scoring earlier would read unfinished days")
    coins = [c for c in universe() if c not in funding_filter.USED_AFTER_SPLIT]
    covered = max((max(daily_funding(c), default="") for c in ("ETHUSDT", "BTCUSDT")), default="")
    if covered < "2027-02-08":
        raise SystemExit(f"funding-confirmed-trend-forward scores after 2027-02-08 once funding is published through it; archive covers {covered or 'nothing'}")
    pairs = [pair for pair in (confirmed_trend(c, FORWARD_LO, FORWARD_HI) for c in coins) if pair]
    report("funding-confirmed-trend-forward", pooled([p[0] for p in pairs], FORWARD_LO, FORWARD_HI),
           pooled([p[1] for p in pairs], FORWARD_LO, FORWARD_HI), "unfiltered trend rule", FORWARD_LO, FORWARD_HI, block=10)
    return 0


def main() -> int:
    if sys.argv[1:] == ["--forward"]:
        return forward()
    coins = [c for c in universe() if c not in funding_filter.USED_AFTER_SPLIT]
    rules, holds, confirmed, plain = [], [], [], []
    for coin in coins:
        bars = spot_daily(coin)
        if len(bars["days"]) <= funding_filter.WINDOW + 1:
            continue
        rule, hold = breakout_long(bars, counted_days(bars, daily_funding(coin)))
        rules.append(rule)
        holds.append(hold)
        rows, base = confirmed_trend(coin, LO, HI)
        confirmed.append(rows)
        plain.append(base)
    print(f"{len(rules)} held-out coins")
    report("spot-breakout-long", pooled(rules), pooled(holds), "equal-weight holding")
    report("funding-confirmed-trend", pooled(confirmed), pooled(plain), "unfiltered trend rule")
    return 0


if __name__ == "__main__":
    sys.exit(main())
