"""Trial `funding-crowding-filter`: the daily trend rule, standing aside while futures funding shows crowded longs.

Registered in docs/trial-log.md before this script ran. Uses every coin Binance lists with both a USDT perpetual and a
spot pair, from its public data archive (data.binance.vision); every file is checked against its published SHA-256.

    uv run --no-sync python scripts/funding_filter.py fetch      # downloads only files not already cached
    uv run --no-sync python scripts/funding_filter.py run
"""
import argparse
import bisect
import sys
from math import sqrt
from pathlib import Path
from statistics import fmean, pvariance

sys.path.insert(0, str(Path(__file__).resolve().parent))
from binance_archive import daily_funding, fetch, liquid, spot_daily, universe  # noqa: E402
from rule_selector import block_probability, total  # noqa: E402

from gym.domain.performance import _moments, deflated_sharpe  # noqa: E402

# Coins whose prices from 2024 on were already scored by earlier trials, directly or through Wallex.
USED_AFTER_SPLIT = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT", "TRXUSDT",
                    "LINKUSDT", "ARBUSDT", "AUSDT", "CAKEUSDT", "COPXONUSDT", "DOTUSDT", "PEPEUSDT", "SHIBUSDT",
                    "SLVONUSDT", "USOONUSDT", "XAUTUSDT"}
CAPS = (0.70, 0.80, 0.90)  # stand aside when 7-day funding is above this share of its trailing year
WINDOW, CROWD_DAYS, HISTORY, COST = 50, 7, 365, 0.002
SPLIT, HELD_END = "2024-01-01", "2026-11-01"


def crowded(days, funding, cap):
    """True when the trailing 7-day mean funding is in the top (1 - cap) of its trailing 365 days; None until known.

    Uses only funding settled on or before each day.
    """
    known = sorted(funding)
    means, out = [], []
    for day in days:
        i = bisect.bisect_right(known, day)
        recent = [funding[d] for d in known[max(0, i - CROWD_DAYS):i]]
        if len(recent) < CROWD_DAYS:
            out.append(None)
            continue
        level = fmean(recent)
        means.append(level)
        past = means[-HISTORY - 1:-1]
        out.append(None if len(past) < HISTORY else sum(x < level for x in past) / len(past) >= cap)
    return out


def returns(days, closes, flags, eligible=None):
    """Daily (day, return): long when above the 50-day average and not crowded, decided at the close.

    A day counts only when the filter is known and the coin is liquid; an open position is closed (and charged) on
    the first day the coin stops counting.
    """
    out, held = [], 0.0
    for i in range(WINDOW - 1, len(closes) - 1):
        usable = (flags is None or flags[i] is not None) and (eligible is None or eligible[i])
        if not usable:
            if held:
                out.append((days[i + 1], -COST))
                held = 0.0
            continue
        want = float(closes[i] > fmean(closes[i - WINDOW + 1:i + 1]) and not (flags and flags[i]))
        out.append((days[i + 1], want * (closes[i + 1] / closes[i] - 1) - COST * abs(want - held)))
        held = want
    return out


def pooled(source, funding, cap, lo, hi, *, gate=None):
    """Equal-weight daily mean across counted coins; `gate` limits the unfiltered rule to the coin-days the filter counted."""
    by_day, used = {}, set()
    for coin, (days, closes, volumes) in source.items():
        flags = crowded(days, funding[coin], cap) if cap is not None else None
        for day, r in returns(days, closes, flags, liquid(volumes)):
            if lo <= day < hi and (gate is None or (coin, day) in gate):
                by_day.setdefault(day, []).append(r)
                used.add((coin, day))
    return {day: fmean(v) for day, v in sorted(by_day.items())}, used


def compare(source, funding, cap, lo, hi):
    filtered, used = pooled(source, funding, cap, lo, hi)
    plain, _ = pooled(source, funding, None, lo, hi, gate=set(used))
    return list(filtered.values()), list(plain.values()), len({coin for coin, _ in used})


def verdict(rank_source, held_source, funding) -> bool:
    cells = []
    for cap in CAPS:
        values, plain, coins = compare(rank_source, funding, cap, "2000", SPLIT)
        mean, deviation, skew, kurtosis = _moments(values)
        pm, pd, _, _ = _moments(plain)
        cells.append({"cap": cap, "values": values, "coins": coins, "moments": (skew, kurtosis),
                      "sharpe": mean / deviation if deviation else 0.0, "plain_sharpe": pm / pd if pd else 0.0,
                      "plain_total": total(plain)})
    variance = pvariance([c["sharpe"] for c in cells])
    print(f"funding-crowding-filter ranked before {SPLIT} on {len(rank_source)} coins; {100 * COST:.2f}% per side")
    for c in cells:
        c["deflated"] = deflated_sharpe(c["sharpe"], len(c["values"]), *c["moments"], len(cells), variance) or 0.0
        print(f"  stand aside above {100 * c['cap']:.0f}%: {c['coins']} coins, {len(c['values'])} days, total {100 * total(c['values']):8.1f}% "
              f"(unfiltered {100 * c['plain_total']:8.1f}%), yearly Sharpe {c['sharpe'] * sqrt(365):5.2f} "
              f"(unfiltered {c['plain_sharpe'] * sqrt(365):5.2f}), deflated {c['deflated']:.3f}")
    best = max(cells, key=lambda c: c["deflated"])
    if best["deflated"] < 0.95 or best["sharpe"] <= best["plain_sharpe"]:
        print(f"funding-crowding-filter FAIL on ranking days (best cap {best['cap']}, deflated {best['deflated']:.3f}, "
              f"{'above' if best['sharpe'] > best['plain_sharpe'] else 'not above'} the unfiltered rule); held-out coins not scored")
        return False
    values, plain, coins = compare(held_source, funding, best["cap"], SPLIT, HELD_END)
    mean, deviation, _, _ = _moments(values)
    pm, pd, _, _ = _moments(plain)
    chance = block_probability(values)
    passed = chance >= 0.90 and mean / deviation > pm / pd
    print(f"  held out, cap {best['cap']}: {coins} coins, {len(values)} days, total {100 * total(values):.1f}% "
          f"(unfiltered {100 * total(plain):.1f}%), yearly Sharpe {mean / deviation * sqrt(365):.2f} "
          f"(unfiltered {pm / pd * sqrt(365):.2f}), block-bootstrap probability {chance:.3f}")
    print(f"funding-crowding-filter verdict: {'PASS' if passed else 'FAIL'}")
    return passed


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("action", choices=("fetch", "run"))
    args = parser.parse_args(argv)
    coins = universe()
    if args.action == "fetch":
        fetch(coins)
        return 0
    bars = {coin: spot_daily(coin) for coin in coins}
    data = {coin: (b["days"], b["close"], b["volume"]) for coin, b in bars.items() if len(b["days"]) > WINDOW + HISTORY}
    funding = {coin: daily_funding(coin) for coin in data}
    held = {coin: series for coin, series in data.items() if coin not in USED_AFTER_SPLIT}
    verdict(data, held, funding)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
