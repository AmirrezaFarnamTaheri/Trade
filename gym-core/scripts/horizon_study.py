"""Multi-horizon paper study: 1-minute to 4-hour bars plus the daily study, under one protocol.

Research only: no account, no orders. Intraday bars of 1, 3, 5, 15, 30, 60 and 240 minutes are
built from Binance 1-minute klines (complete UTC buckets only). Every family runs on every frame,
with lookbacks counted in bars, so one rule is tested at every holding period:

  trend   50/200-bar moving average, 30-bar momentum, their ensemble (long, or long/short)
  rev     mean reversion: enter k rolling standard deviations from the n-bar mean, leave at the mean
  brk     breakout: enter beyond the prior n-bar extreme, leave beyond the n/2 extreme
  ofi     order flow: taker-buy share of volume over n bars beyond a threshold
  mtf     a rev or brk entry kept only while a higher frame's trend agrees (60m above frames
          up to 15m, daily above 30m to 240m), using that frame's last completed bar only

Executions: taker (at the decision close, paying fee plus half the spread) and maker (a limit half a
spread better than the close, filled only if the next bar trades through it). Shorts use the daily
study's margin mechanics (financing, 21-day reopen, liquidation) on Wallex margin markets only.

The report gives each family's gross edge per round trip and the break-even cost per side, runs the
train / validation / test protocol across every frame together, and builds one portfolio from the
best configuration of each horizon band (high: 1-15m, mid: 30-240m, low: the daily study's choice),
weighted by inverse train volatility and scored once on test.

    uv run --no-sync python scripts/long_history_study.py fetch BTCUSDT ETHUSDT --interval 1m --from 2025-11
    uv run --no-sync python scripts/horizon_study.py BTCUSDT ETHUSDT --half-spread BTCUSDT=0.00017,ETHUSDT=0.00053

Limits: Binance prices and order flow with Wallex fee and spreads; a close fill or a traded-through
limit approximates queue position; decisions act one bar later; only intraday history since the
first cached 1-minute month.
"""

import argparse
import bisect
import csv
import io
import math
import sys
import zipfile
from collections import deque
from datetime import UTC, datetime
from itertools import accumulate, pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import long_history_study as daily  # sibling script

FRAMES = (1, 3, 5, 15, 30, 60, 240)  # minutes per bar
BANDS = {"high": (1, 3, 5, 15), "mid": (30, 60, 240)}
FEE = 0.001  # Wallex account fee per side, maker and taker (observed 2026-11-01)
SPLITS = ("2025-11-01", "2026-05-01", "2026-08-01", "2026-11-01")  # train, validation, test boundaries
FAMILIES = (
    ("sma", 50, 0), ("sma", 200, 0), ("mom", 30, 0), ("ens", 0, 0),
    ("rev", 20, 2.0), ("rev", 20, 3.0), ("rev", 60, 2.0), ("rev", 60, 3.0),
    ("brk", 20, 0), ("brk", 60, 0),
    ("ofi", 10, 0.1), ("ofi", 30, 0.05),
    ("mtf-rev", 20, 2.0), ("mtf-brk", 20, 0),
)


def load_minutes(symbol, cache=daily.CACHE):
    """{epoch second: (high, low, close, volume, taker buy volume)} from the cached 1-minute zips."""
    bars = {}
    for path in sorted((cache / "1m").glob(f"{symbol}-1m-*.zip")):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                for row in csv.reader(io.TextIOWrapper(archive.open(name), encoding="utf-8")):
                    if not row or not row[0].isdigit():
                        continue
                    stamp = int(row[0])
                    bars[int(stamp / 1e6 if stamp > 1e14 else stamp / 1e3)] = tuple(float(row[k]) for k in (2, 3, 4, 5, 9))
    if not bars:
        raise SystemExit(f"{symbol}: no 1m data in {cache}; run long_history_study.py fetch --interval 1m first")
    return bars


def resample(minutes, frame):
    """Complete frame-minute buckets aligned to UTC: (times, highs, lows, closes, volumes, taker volumes)."""
    step = frame * 60
    buckets = {}
    for t in sorted(minutes):
        buckets.setdefault(t - t % step, []).append(minutes[t])
    out = ([], [], [], [], [], [])
    for start, rows in buckets.items():
        if len(rows) != frame:  # a hole inside the bucket: skip it rather than invent prices
            continue
        for column, value in zip(out, (start, max(b[0] for b in rows), min(b[1] for b in rows), rows[-1][2],
                                       sum(b[3] for b in rows), sum(b[4] for b in rows)), strict=True):
            column.append(value)
    return out


# ---- signals in [-1, 1]; the value at bar i uses bars[:i+1] only ----


def reversion(closes, n, k):
    """Long below mean - k sd, short above mean + k sd; each held until price crosses back to the mean."""
    s1 = list(accumulate(closes, initial=0.0))
    s2 = list(accumulate((c * c for c in closes), initial=0.0))
    out, pos = [], 0.0
    for i, c in enumerate(closes):
        if i < n - 1:
            out.append(None)
            continue
        mean = (s1[i + 1] - s1[i + 1 - n]) / n
        sd = math.sqrt(max((s2[i + 1] - s2[i + 1 - n]) / n - mean * mean, 0.0))
        z = (c - mean) / sd if sd else 0.0
        if pos == 0:
            pos = 1.0 if z < -k else -1.0 if z > k else 0.0
        elif pos * z >= 0:  # back at or across the mean
            pos = 0.0
        out.append(pos)
    return out


def breakout(closes, n):
    """+1 after a close above the prior n-bar high, -1 below the prior n-bar low; flat after a close back
    through the prior n/2-bar opposite extreme. O(n) with monotonic deques."""
    spans = {"hi": n, "lo": n, "hi2": max(1, n // 2), "lo2": max(1, n // 2)}
    queues = {key: deque() for key in spans}
    out, pos = [], 0.0
    for i, c in enumerate(closes):
        for key, q in queues.items():
            while q and q[0] < i - spans[key]:
                q.popleft()
        if i >= n:
            if c > closes[queues["hi"][0]]:
                pos = 1.0
            elif c < closes[queues["lo"][0]]:
                pos = -1.0
            elif (pos > 0 and c < closes[queues["lo2"][0]]) or (pos < 0 and c > closes[queues["hi2"][0]]):
                pos = 0.0
            out.append(pos)
        else:
            out.append(None)
        for key, q in queues.items():
            while q and ((closes[q[-1]] <= c) if key.startswith("hi") else (closes[q[-1]] >= c)):
                q.pop()
            q.append(i)
    return out


def order_flow(volume, taker, n, threshold):
    """Taker-buy imbalance over n bars, (buy - sell) / total: enter beyond threshold, leave when it flips sign."""
    sv, st = list(accumulate(volume, initial=0.0)), list(accumulate(taker, initial=0.0))
    out, pos = [], 0.0
    for i in range(len(volume)):
        if i < n - 1:
            out.append(None)
            continue
        total = sv[i + 1] - sv[i + 1 - n]
        imbalance = (2 * (st[i + 1] - st[i + 1 - n]) - total) / total if total else 0.0
        if imbalance > threshold:
            pos = 1.0
        elif imbalance < -threshold:
            pos = -1.0
        elif pos * imbalance <= 0:
            pos = 0.0
        out.append(pos)
    return out


def higher_trend(minutes, frame):
    """{bar end epoch: +1/-1} of a higher frame: last completed close above or below its 24-bar average."""
    times, _, _, closes, _, _ = resample(minutes, frame)
    prefix = list(accumulate(closes, initial=0.0))
    return {t + frame * 60: (1.0 if c * 24 > prefix[i + 1] - prefix[i - 23] else -1.0)
            for i, (t, c) in enumerate(zip(times, closes, strict=True)) if i >= 23}


def gate(signal, times, frame, trend, higher):
    """Keep a position only while the higher frame's latest completed trend (by this bar's close) agrees."""
    step = higher * 60
    out = []
    for t, x in zip(times, signal, strict=True):
        close = t + frame * 60
        direction = trend.get(close - close % step)
        out.append(None if x is None or direction is None else (x if x * direction > 0 else 0.0))
    return out


def signals(minutes, bars, frame):
    times, _, _, closes, volume, taker = bars
    trend_rules = daily.trend_signals(closes, 1)  # lookbacks counted in bars of this frame
    higher = 60 if frame <= 15 else 1440
    trend = higher_trend(minutes, higher)
    out = {}
    for family, n, k in FAMILIES:
        if family in ("sma", "mom", "ens"):
            # long when the rule is on, short when it is off (the long-only view clips shorts away)
            out[family, n, k] = [None if x is None else 2 * x - 1 for x in trend_rules[family, n]]
        elif family == "rev":
            out[family, n, k] = reversion(closes, n, k)
        elif family == "brk":
            out[family, n, k] = breakout(closes, n)
        elif family == "ofi":
            out[family, n, k] = order_flow(volume, taker, n, k)
        else:
            base = reversion(closes, n, k) if family == "mtf-rev" else breakout(closes, n)
            out[family, n, k] = gate(base, times, frame, trend, higher)
    return out


# ---- execution ----


def maker(highs, lows, closes, target, fee, half_spread, carry=0.0):
    """Limit orders half a spread better than the decision close, filled only if the next bar trades through.

    An unfilled order is dropped and the decision is taken again at the next close. Short exposure pays
    carry per bar.
    """
    pos, returns, exposure, trades = 0.0, [0.0], [0.0], 0
    for i in range(1, len(closes)):
        t = target[i - 1] or 0.0
        r = pos * (closes[i] / closes[i - 1] - 1)
        if t != pos:
            buy = t > pos
            limit = closes[i - 1] * (1 - half_spread if buy else 1 + half_spread)
            if (lows[i] < limit) if buy else (highs[i] > limit):
                r += (t - pos) * (closes[i] / limit - 1) - fee * abs(t - pos)
                pos, trades = t, trades + 1
        returns.append(r - carry * max(-pos, 0.0))
        exposure.append(pos)
    return returns, exposure, trades


def epoch(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp())


def window(times, series, start, end):
    a, b = bisect.bisect_left(times, start), bisect.bisect_left(times, end)
    return [x[a:b] for x in series]


def by_day(times, returns):
    """Compound bar returns into UTC-day returns: {day start epoch: return}."""
    days = {}
    for t, r in zip(times, returns, strict=True):
        day = t - t % 86400
        days[day] = (1 + days.get(day, 0.0)) * (1 + r) - 1
    return days


def label(config):
    frame, family, n, k, side, execution = config
    return f"{frame}m {family}{n or ''}{f'/{k:g}' if k else ''} {side} {execution}"


def simulate(minutes_by_symbol, half_spreads, margin, fee, terms, bounds):
    """Each configuration reduced at once to its equal-weight daily returns and mean gross exposure per split.

    Configurations are kept as {day epoch: return} (a few hundred numbers) instead of bar series, so a
    year of 1-minute bars across every frame and family fits in memory. Also returns each family's
    gross edge on train: (bps per round trip, round trips per day, minutes held per round trip).
    """
    results, edges = {}, {}

    def record(config, symbol, times, returns, exposure):
        days, gross = results.setdefault(config, ({}, [[0.0, 0] for _ in range(3)]))
        for day, r in by_day(times, returns).items():
            days.setdefault(day, []).append(r)
        for split in range(3):
            part = window(times, (exposure,), bounds[split], bounds[split + 1])[0]
            if part:
                gross[split][0] += sum(abs(x) for x in part) / len(part)
                gross[split][1] += 1

    for frame in FRAMES:
        year = 365 * 1440 // frame
        carry, roll = terms["borrow_rate"] / year, terms["roll_days"] * 1440 // frame
        for symbol, minutes in minutes_by_symbol.items():
            bars = resample(minutes, frame)
            times, highs, lows, closes = bars[:4]
            moves = [0.0] + [b / a - 1 for a, b in pairwise(closes)]
            a, b = bisect.bisect_left(times, bounds[0]), bisect.bisect_left(times, bounds[1])
            days = max((times[b - 1] - times[a]) / 86400, 1.0) if b > a else 1.0
            record((frame, "hold", 0, 0, "long", "taker"), symbol, times, *daily.run(moves, [1.0] * len(moves), 0.0)[:2])
            for family, signal in signals(minutes, bars, frame).items():
                for side in ("long", "ls") if symbol in margin else ("long",):
                    goal = signal if side == "ls" else [None if x is None else max(x, 0.0) for x in signal]
                    gross = daily.run(moves, goal, 0.0)[0]
                    changes = sum(1 for x, y in pairwise(goal[a:b]) if (x or 0.0) != (y or 0.0))
                    trips = max(changes / 2, 0.5)
                    held = sum(1 for x in goal[a:b] if x) * frame
                    edges.setdefault((frame, family, side), []).append(
                        (sum(math.log1p(r) for r in gross[a:b]) / trips * 1e4, trips / days, held / trips))
                    cost = fee + half_spreads[symbol]
                    record((frame, *family, side, "taker"), symbol, times,
                           *daily.run(moves, goal, cost, 0.0, carry, roll, terms["liquidation"])[:2])
                    record((frame, *family, side, "maker"), symbol, times,
                           *maker(highs, lows, closes, goal, fee, half_spreads[symbol], carry)[:2])
    summary = {}
    for config, (days, gross) in results.items():
        summary[config] = ({d: sum(v) / len(v) for d, v in sorted(days.items())},
                           [g / n if n else 0.0 for g, n in gross])
    return summary, edges


def combine(sleeves, bounds):
    """Inverse-train-volatility blend of daily sleeves {name: {day: return}} on the days they all share."""
    days = sorted(set.intersection(*(set(s) for s in sleeves.values())))
    weights = {}
    for name, series in sleeves.items():
        train = [series[d] for d in days if bounds[0] <= d < bounds[1]]
        mean = sum(train) / len(train)
        weights[name] = 1 / max(math.sqrt(sum((r - mean) ** 2 for r in train) / len(train)), 1e-9)
    total = sum(weights.values())
    weights = {name: w / total for name, w in weights.items()}
    return days, [sum(weights[n] * sleeves[n][d] for n in sleeves) for d in days], weights


def report(minutes_by_symbol, half_spreads, margin=frozenset(), fee=FEE, splits=SPLITS, terms=daily.MARGIN,
           daily_sleeve=None):
    """Gross edges, then train-only selection across all frames, a validation gate, one test score, and the
    multi-horizon portfolio. daily_sleeve is an optional {day epoch: return} series from the daily study."""
    bounds = [epoch(d) for d in splits]
    names = ("train", "validation", "test")
    results, edges = simulate(minutes_by_symbol, half_spreads, frozenset(margin), fee, terms, bounds)
    print(f"{len(minutes_by_symbol)} assets, frames {', '.join(f'{f}m' for f in FRAMES)}, fee {fee:.2%} per side, half spread "
          + ", ".join(f"{s} {h:.3%}" for s, h in half_spreads.items()))
    print("  " + "  ".join(f"{names[i]} {splits[i]}..{splits[i + 1]}" for i in range(3)))
    print("\nGross edge before costs on train (mean over assets): bps per round trip | round trips per day | minutes held")
    print("  every configuration is scored on equal-weight daily returns, so Sharpe ratios compare across frames")
    print(f"  break-even cost per side is half the gross edge; Wallex taker cost here is "
          f"{(fee + min(half_spreads.values())) * 1e4:.0f}-{(fee + max(half_spreads.values())) * 1e4:.0f} bps per side")
    for (frame, family, side), rows in sorted(edges.items()):
        g, f, h = (sum(v) / len(v) for v in zip(*rows, strict=True))
        name = f"{family[0]}{family[1] or ''}{f'/{family[2]:g}' if family[2] else ''}"
        print(f"  {frame:>3}m {name:<12} {side:<4} {g:8.1f} bps | {f:7.2f}/day | {h:8.0f} min")

    def split_days(config, split):
        days = results[config][0]
        return [r for d, r in days.items() if bounds[split] <= d < bounds[split + 1]]

    def score(config, split):
        r = split_days(config, split)
        return daily.stats(r, [results[config][1][split]] * len(r), 365) if len(r) > 1 else None

    def rank(config):
        value = daily.sharpe(split_days(config, 0), 365)
        return -9.0 if value is None else value

    def line(name, s):
        return (f"  {name:<36} CAGR {s['cagr']:8.1%}  Sharpe {s['sharpe']:5.2f}  maxDD {s['maxdd']:6.1%}  "
                f"gross {s['exposure']:4.0%}") if s else f"  {name:<36} (no bars)"

    candidates = [c for c in results if c[1] != "hold"]
    ranked = sorted(candidates, key=rank, reverse=True)
    print(f"\nTop 8 of {len(candidates)} configurations on train, after costs | validation Sharpe")
    for config in ranked[:8]:
        va = score(config, 1)
        print(f"  {label(config):<36} train Sharpe {rank(config):6.2f} | {va['sharpe'] if va else float('nan'):6.2f}")

    chosen = {"all": ranked[0]} | {band: max((c for c in candidates if c[0] in frames), key=rank)
                                     for band, frames in BANDS.items()}
    train = split_days(chosen["all"], 0)
    _, _, skew, kurt = daily._moments(train)
    per_period = [rank(c) / math.sqrt(365) for c in candidates]
    mean = sum(per_period) / len(per_period)
    dsr = daily.deflated_sharpe(rank(chosen["all"]) / math.sqrt(365), len(train), skew, kurt, len(candidates),
                                sum((s - mean) ** 2 for s in per_period) / (len(per_period) - 1))
    outcome = {"deflated_sharpe": dsr}
    for band, config in chosen.items():
        hold = (config[0], "hold", 0, 0, "long", "taker")
        valid = daily.passes(score(config, 1), score(hold, 1))
        extra = f"  deflated Sharpe probability {'n/a' if dsr is None else f'{dsr:.3f}'} over {len(candidates)} tries" \
            if band == "all" else ""
        print(f"\nBest on train, {band} frequency: {label(config)}{extra}  -> validation {'PASSED' if valid else 'FAILED'}")
        for split in range(3 if valid else 2):
            print(line(f"{names[split]} {label(config)}", score(config, split)))
            print(line(f"{names[split]} buy & hold {config[0]}m", score(hold, split)))
        outcome[band] = {"chosen": label(config), "validated": valid}

    # Multi-horizon portfolio: high and mid band winners plus the daily study's choice, as daily returns.
    sleeves = {band: results[chosen[band]][0] for band in BANDS}
    if daily_sleeve:
        sleeves["low"] = daily_sleeve
    days, returns, weights = combine(sleeves, bounds)
    print("\nMulti-horizon portfolio (weights from train volatility: "
          + ", ".join(f"{n} {w:.0%}" for n, w in weights.items()) + ")")
    for split in range(3):
        r = [x for d, x in zip(days, returns, strict=True) if bounds[split] <= d < bounds[split + 1]]
        if len(r) > 1:
            print(line(f"{names[split]} combined", daily.stats(r, [0.0] * len(r), 365)).rsplit("  gross", 1)[0])
    outcome["weights"] = weights
    return outcome


def daily_sleeve(symbols, config, costs, margin=frozenset(), cache=daily.CACHE):
    """The daily study's portfolio for one configuration, as {day epoch: return}, over its full history."""
    data = {s: daily.load(s, "1d", cache) for s in symbols}
    each, _ = daily.sleeves(data, costs, 1, frozenset(margin))
    per = next(per for c, per in each if c == config)
    times, returns, _ = daily.blend(per, daily.Grid(data))
    return {epoch(t[:10]): r for t, r in zip(times, returns, strict=True)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--half-spread", default="", help="SYMBOL=fraction,... (default 0.0005 each)")
    parser.add_argument("--margin", default="", help="symbols allowed to short (Wallex margin markets)")
    parser.add_argument("--cache", type=Path, default=daily.CACHE)
    parser.add_argument("--daily", default="sma,50,0.4,0.2,long,1",
                        help="daily study configuration for the low-frequency sleeve: rule,param,vt,band,side,cap")
    args = parser.parse_args(argv)
    symbols = [s.upper() for s in args.symbols]
    spreads = dict.fromkeys(symbols, 0.0005) | {
        k.upper(): float(v) for k, v in (item.split("=") for item in args.half_spread.split(",") if item)}
    margin = {s.strip().upper() for s in args.margin.split(",") if s.strip()}
    rule, param, vt, band, side, cap = args.daily.split(",")
    config = (rule, int(param), float(vt) if vt != "none" else None, float(band), side, float(cap))
    low = daily_sleeve(symbols, config, {s: FEE + spreads[s] for s in symbols}, margin, args.cache)
    report({s: load_minutes(s, args.cache) for s in symbols}, spreads, margin, daily_sleeve=low)


if __name__ == "__main__":
    main()
