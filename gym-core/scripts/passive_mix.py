"""Trial `passive-multi-asset-mix`: a fixed, risk-balanced mix of gold, silver, oil, copper, Apple and BTC, rest in USDT.

Registered in docs/trial-log.md before this script ran. Yahoo Finance daily closes stand in for the Wallex tokens
(XAUT, SLVON, USOON, COPXON, AAPLX, BTC). Prints the smallest detectable edge before the result.

    uv run --no-sync python scripts/passive_mix.py
"""
import json
import math
import sys
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import fmean

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detectable_edge import bootstrap_test, smallest  # noqa: E402
from rule_selector import block_probability, total  # noqa: E402

from gym.domain.performance import _moments  # noqa: E402

ASSETS = {"gold": "GC=F", "silver": "SI=F", "oil": "CL=F", "copper": "HG=F", "apple": "AAPL", "btc": "BTC-USD"}
START, END = "2016-11-18", "2026-11-17"
LOOKBACK, TARGET_VOL, BAND, COST = 60, 0.15, 0.05, 0.005
CACHE = Path(__file__).resolve().parents[2] / "data" / "yahoo"


def fetch(ticker):
    """Daily closes {day: close}, cached; Yahoo's chart API, no key."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{ticker.replace('=', '_')}.json"
    if not path.exists():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1=1451606400&period2=1795000000&interval=1d"
        body = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
        result = json.loads(body)["chart"]["result"][0]
        closes = {datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d"): c
                  for t, c in zip(result["timestamp"], result["indicators"]["quote"][0]["close"], strict=True) if c}
        path.write_text(json.dumps(closes), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def aligned(closes_by_asset):
    """Calendar days from START to END with every asset's last close carried forward over closed markets."""
    days, day = [], date.fromisoformat(START)
    while day <= date.fromisoformat(END):
        days.append(day.isoformat())
        day += timedelta(days=1)
    table, last = {a: [] for a in closes_by_asset}, {}
    for d in days:
        for asset, closes in closes_by_asset.items():
            if d in closes:
                last[asset] = closes[d]
            table[asset].append(last.get(asset))
    first = next(i for i in range(len(days)) if all(table[a][i] is not None for a in table))
    return days[first:], {a: v[first:] for a, v in table.items()}


def targets(returns, i):
    """Inverse-volatility weights over the last 60 days, scaled to 15% yearly volatility, at most fully invested."""
    names = list(returns)
    window = {a: returns[a][i - LOOKBACK:i] for a in names}
    vols = {a: math.sqrt(sum(x * x for x in window[a]) / LOOKBACK) or 1e-9 for a in names}
    raw = {a: (1 / vols[a]) / sum(1 / v for v in vols.values()) for a in names}
    daily = [sum(raw[a] * window[a][k] for a in names) for k in range(LOOKBACK)]
    portfolio_vol = math.sqrt(sum(x * x for x in daily) / LOOKBACK) * math.sqrt(365)
    scale = min(1.0, TARGET_VOL / portfolio_vol) if portfolio_vol else 1.0
    return {a: raw[a] * scale for a in names}


def run(days, prices):
    """Daily returns of the mix: drift between rebalances, rebalance on a month's first day past the 5-point band."""
    returns = {a: [0.0] + [p[k] / p[k - 1] - 1 for k in range(1, len(p))] for a, p in prices.items()}
    weights, out, turnover = {a: 0.0 for a in prices}, [], 0.0
    for i in range(LOOKBACK, len(days)):
        if days[i][8:] == "01" or i == LOOKBACK:
            wanted = targets(returns, i)
            if i == LOOKBACK or max(abs(wanted[a] - weights[a]) for a in weights) > BAND:
                change = sum(abs(wanted[a] - weights[a]) for a in weights)
                turnover += change
                cost = COST * change
                weights = wanted
            else:
                cost = 0.0
        else:
            cost = 0.0
        if i + 1 >= len(days):
            break
        gain = sum(weights[a] * returns[a][i + 1] for a in weights)
        out.append((days[i + 1], (1 + gain) * (1 - cost) - 1))
        grown = {a: weights[a] * (1 + returns[a][i + 1]) for a in weights}
        equity = 1 + gain
        weights = {a: grown[a] / equity for a in grown}
    return out, turnover


def main() -> int:
    days, prices = aligned({name: fetch(ticker) for name, ticker in ASSETS.items()})
    rows, turnover = run(days, prices)
    values = [r for _, r in rows]
    found, _ = smallest(values, bootstrap_test(20), 20)
    print(f"passive-multi-asset-mix: {len(values)} days from {rows[0][0]} to {rows[-1][0]}; smallest detectable edge "
          f"{found if found is not None else '>300'} bps a day")
    mean, deviation, _, _ = _moments(values)
    chance = block_probability(values)
    years = len(values) / 365
    print(f"  total {100 * total(values):.1f}% ({100 * ((1 + total(values)) ** (1 / years) - 1):.1f}% a year), yearly Sharpe "
          f"{mean / deviation * math.sqrt(365):.2f}, turnover {turnover:.1f}x, block-bootstrap probability {chance:.3f}, "
          f"average daily {fmean(values) * 10000:.2f} bps")
    print(f"passive-multi-asset-mix verdict: {'PASS' if chance >= 0.90 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
