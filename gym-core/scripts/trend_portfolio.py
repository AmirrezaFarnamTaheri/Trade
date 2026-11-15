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
from math import sqrt
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


def portfolio(series: dict[str, dict[str, float]], window: int, sizing: str, cost: float) -> list[tuple[str, float, float]]:
    """(day, gross return, cost) per day. A coin's slot is 1/len(series) whether or not it is listed yet."""
    days = sorted(set().union(*series.values()))
    history = {symbol: [] for symbol in series}
    held = dict.fromkeys(series, 0.0)
    out = []
    for day, following in zip(days, days[1:], strict=False):
        gross = paid = 0.0
        for symbol, closes in series.items():
            if day not in closes:
                continue
            history[symbol].append(closes[day])
            want = weights(history[symbol], len(history[symbol]) - 1, window, sizing) / len(series)
            if following not in closes:  # no next close to earn: stand aside rather than guess
                want = 0.0
            paid += cost * abs(want - held[symbol])
            held[symbol] = want
            if want:
                gross += want * (closes[following] / closes[day] - 1)
        out.append((following, gross, paid))
    return out


def summary(rows: list[tuple[str, float, float]]) -> dict:
    net = [gross - paid for _, gross, paid in rows]
    mean, deviation, skew, kurtosis = _moments(net)
    total = peak = 1.0
    fall = 0.0
    for value in net:
        total *= 1 + value
        peak = max(peak, total)
        fall = max(fall, 1 - total / peak)
    return {"net": net, "days": len(net), "sharpe": mean / deviation if deviation else 0.0, "moments": (skew, kurtosis),
            "total": total - 1, "fall": fall, "gross": sum(g for _, g, _ in rows), "paid": sum(p for _, _, p in rows)}


def split(rows):
    return [row for row in rows if row[0] < SPLIT], [row for row in rows if row[0] >= SPLIT]


def verdict(series: dict[str, dict[str, float]]) -> bool:
    passed = False
    for name, cost in COSTS:
        cells = []
        for window in WINDOWS:
            for sizing in SIZINGS:
                cells.append({"window": window, "sizing": sizing, **summary(split(portfolio(series, window, sizing, cost))[0])})
        variance = pvariance([cell["sharpe"] for cell in cells])
        print(f"T9 trend portfolio, {name} cost {100 * cost:.2f}% per side; {len(series)} coins; ranked before {SPLIT}")
        for cell in cells:
            cell["deflated"] = deflated_sharpe(cell["sharpe"], cell["days"], *cell["moments"], len(cells), variance) or 0.0
            print(f"  {cell['window']:3}-day {cell['sizing']:5}: {cell['days']} days, total {100 * cell['total']:8.1f}%, yearly Sharpe "
                  f"{cell['sharpe'] * sqrt(365):5.2f}, max fall {100 * cell['fall']:4.1f}%, cost paid {100 * cell['paid']:5.1f}%, "
                  f"deflated {cell['deflated']:.3f}")
        best = max(cells, key=lambda cell: cell["deflated"])
        if best["deflated"] < 0.95:
            print(f"  {name}: FAIL on ranking days (best {best['window']}-day {best['sizing']}, {best['deflated']:.3f}); later days not scored")
            continue
        held = summary(split(portfolio(series, best["window"], best["sizing"], cost))[1])
        one = summary(split(portfolio({"BTCUSDT": series["BTCUSDT"]}, 50, "equal", cost))[1])
        alone = deflated_sharpe(held["sharpe"], held["days"], *held["moments"], 1, 0.0) or 0.0
        ok = alone >= 0.90 and held["sharpe"] > one["sharpe"]
        print(f"  {name}: {best['window']}-day {best['sizing']} passed ranking; days from {SPLIT} scored once: {held['days']} days, "
              f"total {100 * held['total']:.1f}% (gross {100 * held['gross']:.1f}%, cost {100 * held['paid']:.1f}%), "
              f"yearly Sharpe {held['sharpe'] * sqrt(365):.2f}, max fall {100 * held['fall']:.1f}%, probability Sharpe > 0: {alone:.3f}")
        print(f"  {name}: BTCUSDT 50-day alone on the same days: total {100 * one['total']:.1f}%, yearly Sharpe "
              f"{one['sharpe'] * sqrt(365):.2f}, max fall {100 * one['fall']:.1f}%; {'pass' if ok else 'fail'}")
        for year in sorted({day[:4] for day, _, _ in split(portfolio(series, best['window'], best['sizing'], cost))[1]}):
            rows = [row for row in split(portfolio(series, best["window"], best["sizing"], cost))[1] if row[0][:4] == year]
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
