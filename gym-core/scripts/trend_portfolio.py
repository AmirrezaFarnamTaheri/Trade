"""T9 of docs/trial-log.md: does spreading the T6 trend rule over ten coins, sized by volatility, beat it on one?

T6 passed on one coin and one good year. This asks whether the same rule held across more coins, each sized so a
calm coin gets more and a wild one less, earns a steadier result. Every number is net of the cost of each change
in weight. Floating point is used; a pass must be replayed in the exact paper engine before it counts.

Run from gym-core: `uv run --no-sync python scripts/trend_portfolio.py`
(needs `python scripts/long_history_study.py fetch SYMBOL... --interval 1d` first).
"""
from __future__ import annotations

import importlib.util
import sys
from math import isfinite, prod, sqrt
from pathlib import Path
from statistics import fmean, pstdev, pvariance

from gym.domain.performance import _moments, deflated_sharpe

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT", "TRXUSDT", "LINKUSDT")
WINDOWS, SIZINGS = (50, 100, 200), ("equal", "vol")
SPLIT = "2024-01-01"
VOL_DAYS, VOL_TARGET = 20, 0.40 / sqrt(365)  # each coin sized toward 40% a year, never above its equal share
COSTS = (("account", 0.002), ("published", 0.0023))  # per side: fee plus 0.10% for half the spread


def weights(closes: list[float], i: int, window: int, sizing: str) -> float:
    """Share of one coin's slot held after the close of day i; 0 when below its average or history is too short."""
    if i + 1 < max(window, VOL_DAYS + 1) or closes[i] <= fmean(closes[i - window + 1:i + 1]):
        return 0.0
    if sizing == "equal":
        return 1.0
    recent = pstdev(closes[j] / closes[j - 1] - 1 for j in range(i - VOL_DAYS + 1, i + 1))
    return min(1.0, VOL_TARGET / recent) if recent else 1.0


def rebalance_fee(held: dict[str, float], wanted: dict[str, float], cost: float) -> float:
    """Fund fees from equity, so target weights apply to the remaining capital."""
    paid = 0.0
    for _ in range(100):
        fee = cost * sum(abs(wanted[symbol] * (1 - paid) - held[symbol]) for symbol in held)
        if abs(fee - paid) < 1e-15:
            return fee
        paid = fee
    raise ValueError("rebalance fees did not converge")


def portfolio(series: dict[str, dict[str, float]], window: int, sizing: str, cost: float) -> list[tuple[str, float, float]]:
    """(day, gross return, fee/equity); fees are paid before the day's return.

    A coin's slot is 1/len(series) whether or not it is listed yet.
    """
    if not series or not isfinite(cost) or not 0 <= cost < 1:
        raise ValueError("need markets and a finite cost in [0, 1)")
    days = sorted(set().union(*series.values()))
    history = {symbol: [] for symbol in series}
    held = dict.fromkeys(series, 0.0)
    out = []
    for day, following in zip(days, days[1:], strict=False):
        wanted = dict.fromkeys(series, 0.0)
        moves = dict.fromkeys(series, 0.0)
        for symbol, closes in series.items():
            if day not in closes:
                if held[symbol]:
                    raise ValueError(f"missing current close for {symbol} on {day}")
                continue
            history[symbol].append(closes[day])
            wanted[symbol] = weights(history[symbol], len(history[symbol]) - 1, window, sizing) / len(series)
            if wanted[symbol]:
                if following not in closes:
                    raise ValueError(f"missing next close for {symbol} on {following}")
                moves[symbol] = closes[following] / closes[day] - 1
        paid = rebalance_fee(held, wanted, cost)
        gross = sum(wanted[symbol] * moves[symbol] for symbol in series)
        held = {symbol: wanted[symbol] * (1 + moves[symbol]) / (1 + gross) for symbol in series}
        out.append((following, gross, paid))
    return out


def summary(rows: list[tuple[str, float, float]]) -> dict:
    net = [(1 - paid) * (1 + gross) - 1 for _, gross, paid in rows]
    mean, deviation, skew, kurtosis = _moments(net)
    total = peak = 1.0
    fall = 0.0
    fees_paid = 0.0
    for value, (_, _, paid) in zip(net, rows, strict=True):
        fees_paid += total * paid
        total *= 1 + value
        peak = max(peak, total)
        fall = max(fall, 1 - total / peak)
    gross = prod(1 + value for _, value, _ in rows) - 1
    return {"net": net, "days": len(net), "sharpe": mean / deviation if deviation else 0.0, "moments": (skew, kurtosis),
            "total": total - 1, "fall": fall, "gross": gross, "paid": fees_paid, "cost_drag": gross - (total - 1)}


def split(rows):
    return [row for row in rows if row[0] < SPLIT], [row for row in rows if row[0] >= SPLIT]


def verdict(series: dict[str, dict[str, float]]) -> bool:
    passed = False
    for name, cost in COSTS:
        cells = []
        for window in WINDOWS:
            for sizing in SIZINGS:
                rows = portfolio(series, window, sizing, cost)
                cells.append({"window": window, "sizing": sizing, "rows": rows, **summary(split(rows)[0])})
        variance = pvariance([cell["sharpe"] for cell in cells])
        print(f"T9 trend portfolio, {name} cost {100 * cost:.2f}% per side; {len(series)} coins; ranked before {SPLIT}")
        for cell in cells:
            cell["deflated"] = deflated_sharpe(cell["sharpe"], cell["days"], *cell["moments"], len(cells), variance) or 0.0
            print(f"  {cell['window']:3}-day {cell['sizing']:5}: {cell['days']} days, total {100 * cell['total']:8.1f}%, yearly Sharpe "
                  f"{cell['sharpe'] * sqrt(365):5.2f}, max fall {100 * cell['fall']:4.1f}%, fees/initial capital {100 * cell['paid']:5.1f}%, "
                  f"deflated {cell['deflated']:.3f}")
        best = max(cells, key=lambda cell: cell["deflated"])
        if best["deflated"] < 0.95:
            print(f"  {name}: FAIL on ranking days (best {best['window']}-day {best['sizing']}, {best['deflated']:.3f}); later days not scored")
            continue
        held_rows = split(best["rows"])[1]
        held = summary(held_rows)
        one = summary(split(portfolio({"BTCUSDT": series["BTCUSDT"]}, 50, "equal", cost))[1])
        alone = deflated_sharpe(held["sharpe"], held["days"], *held["moments"], 1, 0.0) or 0.0
        ok = alone >= 0.90 and held["sharpe"] > one["sharpe"]
        print(f"  {name}: {best['window']}-day {best['sizing']} passed ranking; days from {SPLIT} scored once: {held['days']} days, "
              f"compounded net {100 * held['total']:.1f}%, compounded gross {100 * held['gross']:.1f}%, "
              f"cost drag {100 * held['cost_drag']:.1f} percentage points, fees/initial capital {100 * held['paid']:.1f}%, "
              f"yearly Sharpe {held['sharpe'] * sqrt(365):.2f}, max fall {100 * held['fall']:.1f}%, probability Sharpe > 0: {alone:.3f}")
        print(f"  {name}: BTCUSDT 50-day alone on the same days: total {100 * one['total']:.1f}%, yearly Sharpe "
              f"{one['sharpe'] * sqrt(365):.2f}, max fall {100 * one['fall']:.1f}%; {'pass' if ok else 'fail'}")
        for year in sorted({day[:4] for day, _, _ in held_rows}):
            rows = [row for row in held_rows if row[0][:4] == year]
            print(f"    {year}: {100 * summary(rows)['total']:6.1f}% over {len(rows)} days")
        passed = passed or (ok and name == "account")
    print(f"T9 VERDICT: {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> int:
    spec = importlib.util.spec_from_file_location("long_history_study", Path(__file__).with_name("long_history_study.py"))
    study = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(study)
    series = {}
    for symbol in SYMBOLS:
        days, closes = study.load(symbol, "1d", study.CACHE)
        series[symbol] = dict(zip((str(day)[:10] for day in days), closes, strict=True))
    verdict(series)
    return 0


if __name__ == "__main__":
    sys.exit(main())
