"""Long-history paper study on Binance public spot klines (data.binance.vision).

Research only: no account, no orders. 'fetch' downloads the official monthly zips once and keeps
only files that match their published SHA-256 (.CHECKSUM). 'study' runs a leakage-free protocol:

  train       configurations are ranked here only
  validation  the train winner must beat buy-and-hold here (risk-adjusted), or it is rejected
  test        scored once for the configuration that passed; never used to choose anything

Signal families (long-only, or long/short with up to 4x credit on margin markets): moving-average
and momentum trend, their ensemble, Donchian breakout, momentum strength, a BTC-regime filter,
cross-sectional momentum, and a pooled ridge forecast refitted every month on samples whose
outcome is already known. Every family runs under the same volatility-target
and rebalance-band overlays. The train winner gets a deflated Sharpe (the luck of picking the best
of all configurations) and its test result a block-bootstrap range.

    uv run --no-sync python scripts/long_history_study.py fetch BTCUSDT ETHUSDT --interval 1d
    uv run --no-sync python scripts/long_history_study.py study BTCUSDT ETHUSDT --interval 1d

Limits the numbers carry: Binance USDT prices, not Wallex toman books; a coin list chosen today
(survivorship); fills at the bar close; minimum order sizes ignored; the daily re-equalising of
the portfolio is not charged.
"""

import argparse
import bisect
import csv
import hashlib
import io
import json
import math
import sys
import urllib.error
import urllib.request
import zipfile
from collections import deque
from datetime import UTC, date, datetime
from itertools import accumulate, pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gym.domain.performance import _bootstrap, _moments, deflated_sharpe

BASE = "https://data.binance.vision/data/spot/monthly/klines"
CACHE = Path(__file__).resolve().parents[2] / "data" / "binance-public"
BARS_PER_DAY = {"1d": 1, "4h": 6, "1h": 24, "1m": 1440}
TREND = (("sma", 50), ("sma", 100), ("sma", 200), ("mom", 30), ("mom", 90), ("mom", 180))  # lookbacks in days
VOL_DAYS = 30
MARKET = "BTCUSDT"  # regime reference for the compound filter
HORIZON_DAYS, REFIT_DAYS, MIN_SAMPLES = 5, 30, 500  # ridge: label length, refit cadence, samples before a first fit
FAMILIES = (
    *TREND, ("ens", 0), ("don", 20), ("don", 55), ("tsm", 90),
    ("btcf", 50), ("xsm", 90), ("ridge", 1), ("ridge", 10), ("ridge", 100),
)
HOLD = ("hold", 0, None, 0.0, "long", 1.0)
MARGIN = {"borrow_rate": 0.20, "roll_days": 21, "liquidation": 0.15}  # Wallex margin: 21-day positions, 15% margin


def configs(margin):
    """Signal family x volatility target x rebalance band, plus short side and 2x/4x credit when margin exists.

    Leverage only applies through a volatility target (without one the exposure never exceeds 1).
    """
    sides = ("long", "ls") if margin else ("long",)
    out = [HOLD]
    for rule, param in FAMILIES:
        for vt in (None, 0.4, 0.6):
            for cap in (1.0, 2.0, 4.0) if vt and margin else (1.0,):
                out += [(rule, param, vt, band, side, cap) for band in (0.0, 0.1, 0.2) for side in sides]
    return out


def months(start, end):
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def get(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def fetch(symbols, start, interval, cache):
    today = datetime.now(UTC).date()
    last = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    folder = cache / interval
    folder.mkdir(parents=True, exist_ok=True)
    for symbol in symbols:
        kept = 0
        for y, m in months(start, last):
            name = f"{symbol}-{interval}-{y}-{m:02d}.zip"
            path = folder / name
            if not path.exists():
                url = f"{BASE}/{symbol}/{interval}/{name}"
                try:
                    body, expected = get(url), get(url + ".CHECKSUM").split()[0].decode()
                except urllib.error.HTTPError as error:
                    if error.code == 404:  # month before the listing
                        continue
                    raise
                if hashlib.sha256(body).hexdigest() != expected:
                    raise SystemExit(f"checksum mismatch for {name}; file not kept")
                part = path.with_suffix(".part")
                part.write_bytes(body)
                part.replace(path)
            kept += 1
        print(f"{symbol}: {kept} verified monthly files in {folder}")


def load(symbol, interval, cache):
    """Bar-close prices keyed by ISO open time; refuses holes so returns never span a gap silently."""
    closes = {}
    for path in sorted((cache / interval).glob(f"{symbol}-{interval}-*.zip")):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                for row in csv.reader(io.TextIOWrapper(archive.open(name), encoding="utf-8")):
                    if not row or not row[0].isdigit():  # some files carry a header row
                        continue
                    stamp = int(row[0])
                    seconds = stamp / 1e6 if stamp > 1e14 else stamp / 1e3  # spot files moved to µs in 2025
                    closes[int(seconds)] = float(row[4])
    stamps = sorted(closes)
    if not stamps:
        raise SystemExit(f"{symbol}: no {interval} data in {cache}; run fetch first")
    step = 86400 // BARS_PER_DAY[interval]
    gaps = [b for a, b in pairwise(stamps) if b - a != step]
    if len(gaps) > len(stamps) // 1000:  # shortcut: exchange outages leave a few holes; more means a broken cache
        raise SystemExit(f"{symbol}: {len(gaps)} holes in {interval} bars, first {gaps[:3]}")
    times = [datetime.fromtimestamp(s, UTC).strftime("%Y-%m-%dT%H:%M") for s in stamps]
    return times, [closes[s] for s in stamps]


# ---- per-asset inputs; every value at bar i uses closes[:i+1] only ----


def trend_signals(closes, bars_per_day):
    """Each trend rule's 0/1 signal at close i (None while warming up), plus their average. O(n) per rule."""
    prefix = list(accumulate(closes, initial=0.0))
    out = {}
    for rule, days in TREND:
        p = days * bars_per_day
        if rule == "sma":
            out[rule, days] = [
                None if i < p - 1 else float(c * p > prefix[i + 1] - prefix[i + 1 - p]) for i, c in enumerate(closes)
            ]
        else:
            out[rule, days] = [None if i < p else float(c > closes[i - p]) for i, c in enumerate(closes)]
    out["ens", 0] = [None if None in xs else sum(xs) / len(xs) for xs in zip(*out.values(), strict=True)]
    return out


def realized_vol(closes, bars_per_day, days=VOL_DAYS):
    """Annualised volatility of the last days days of log returns, ending at close i. O(n)."""
    n = days * bars_per_day
    logs = [0.0] + [math.log(b / a) for a, b in pairwise(closes)]
    s1 = list(accumulate(logs, initial=0.0))
    s2 = list(accumulate((x * x for x in logs), initial=0.0))
    scale = 365 * bars_per_day
    out = []
    for i in range(len(closes)):
        if i < n:
            out.append(None)
            continue
        mean = (s1[i + 1] - s1[i + 1 - n]) / n
        out.append(math.sqrt(max((s2[i + 1] - s2[i + 1 - n]) / n - mean * mean, 0.0) * scale))
    return out


def donchian(closes, bars_per_day, days):
    """In after a close above the prior days high; out after a close below the prior days/2 low. O(n)."""
    entry, leave = days * bars_per_day, days * bars_per_day // 2
    highs, lows, out, pos = deque(), deque(), [], 0.0  # monotonic deques of indices in the prior windows
    for i, c in enumerate(closes):
        while highs and highs[0] < i - entry:
            highs.popleft()
        while lows and lows[0] < i - leave:
            lows.popleft()
        if i >= entry:
            if c > closes[highs[0]]:
                pos = 1.0
            elif c < closes[lows[0]]:
                pos = 0.0
            out.append(pos)
        else:
            out.append(None)
        while highs and closes[highs[-1]] <= c:
            highs.pop()
        highs.append(i)
        while lows and closes[lows[-1]] >= c:
            lows.pop()
        lows.append(i)
    return out


def strength(closes, vol, bars_per_day, days):
    """Momentum t-score: log return over days divided by the volatility expected over that span."""
    p = days * bars_per_day
    return [
        None if i < p or not vol[i] else math.log(c / closes[i - p]) / (vol[i] * math.sqrt(days / 365))
        for i, c in enumerate(closes)
    ]


def features(closes, vol, bars_per_day):
    """Ridge inputs at close i, in volatility units so assets pool on one scale (None while warming up)."""
    prefix = list(accumulate(closes, initial=0.0))
    moms = [strength(closes, vol, bars_per_day, d) for d in (10, 30, 90, 180)]
    slow = realized_vol(closes, bars_per_day, 180)
    rows = []
    for i, c in enumerate(closes):
        v = vol[i]
        if i < 200 * bars_per_day - 1 or not v or not slow[i] or any(m[i] is None for m in moms):
            rows.append(None)
            continue
        gaps = [
            math.log(c * p / (prefix[i + 1] - prefix[i + 1 - p])) / (v * math.sqrt(d / 365))
            for d in (50, 200)
            for p in (d * bars_per_day,)
        ]
        rows.append([1.0, *(m[i] for m in moms), *gaps, math.log(v / slow[i])])
    return rows


def solve(matrix, vector):
    """Gaussian elimination with partial pivoting for the small ridge normal equations."""
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        if abs(a[col][col]) < 1e-12:
            return None
        for r in range(col + 1, n):
            f = a[r][col] / a[col][col]
            for k in range(col, n + 1):
                a[r][k] -= f * a[col][k]
    x = [0.0] * n
    for r in reversed(range(n)):
        x[r] = (a[r][n] - sum(a[r][k] * x[k] for k in range(r + 1, n))) / a[r][r]
    return x


def ridge(data, inputs, vols, bars_per_day, lambdas):
    """Pooled ridge forecast of the next HORIZON_DAYS return (volatility units), long when it is positive.

    A sample enters the fit only at the bar its outcome closes, and each prediction uses the last
    monthly fit, so no forecast ever sees its own or any later outcome. Returns the signals per
    lambda and the (time, prediction, outcome) pairs used to score forecast skill.
    """
    h = HORIZON_DAYS * bars_per_day
    arrivals = {}  # time the label closes -> samples becoming usable then
    index = {}
    for symbol, (times, closes) in data.items():
        index[symbol] = {t: i for i, t in enumerate(times)}
        for i in range(len(times) - h):
            if inputs[symbol][i] is not None:
                y = math.log(closes[i + h] / closes[i]) / (vols[symbol][i] * math.sqrt(HORIZON_DAYS / 365))
                arrivals.setdefault(times[i + h], []).append((inputs[symbol][i], y))
    k = len(next(row for rows in inputs.values() for row in rows if row is not None))
    xtx, xty, count = [[0.0] * k for _ in range(k)], [0.0] * k, 0
    coef, last_fit = {lam: None for lam in lambdas}, None
    signals = {lam: {s: [None] * len(data[s][0]) for s in data} for lam in lambdas}
    skill = {lam: [] for lam in lambdas}
    for t in sorted({t for times, _ in data.values() for t in times}):
        for x, y in arrivals.get(t, ()):
            count += 1
            for a in range(k):
                xty[a] += x[a] * y
                row = xtx[a]
                for b in range(k):
                    row[b] += x[a] * x[b]
        day = date.fromisoformat(t[:10]).toordinal()
        if count >= MIN_SAMPLES and (last_fit is None or day - last_fit >= REFIT_DAYS):
            for lam in lambdas:  # the intercept is not shrunk
                penalised = [[v + (lam if a == b and a else 0.0) for b, v in enumerate(row)] for a, row in enumerate(xtx)]
                coef[lam] = solve(penalised, xty) or coef[lam]
            last_fit = day
        for symbol, (times, closes) in data.items():
            i = index[symbol].get(t)
            if i is None or inputs[symbol][i] is None:
                continue
            for lam in lambdas:
                if coef[lam] is None:
                    continue
                forecast = sum(c * x for c, x in zip(coef[lam], inputs[symbol][i], strict=True))
                signals[lam][symbol][i] = float(forecast > 0)
                if i + h < len(times):
                    outcome = math.log(closes[i + h] / closes[i]) / (vols[symbol][i] * math.sqrt(HORIZON_DAYS / 365))
                    skill[lam].append((t, forecast, outcome))
    return signals, skill


def signals(data, bars_per_day):
    """{(family, param): {symbol: exposure in [0, 1] or None}} for every family the data supports."""
    out, vols, inputs, scores = {}, {}, {}, {}
    for symbol, (times, closes) in data.items():
        vols[symbol] = vol = realized_vol(closes, bars_per_day)
        vols[symbol, "moves"] = [0.0] + [b / a - 1 for a, b in pairwise(closes)]
        for family, values in trend_signals(closes, bars_per_day).items():
            out.setdefault(family, {})[symbol] = values
        for days in (20, 55):
            out.setdefault(("don", days), {})[symbol] = donchian(closes, bars_per_day, days)
        scores[symbol] = strength(closes, vol, bars_per_day, 90)
        out.setdefault(("tsm", 90), {})[symbol] = [None if z is None else min(1.0, max(0.0, z / 2)) for z in scores[symbol]]
        inputs[symbol] = features(closes, vol, bars_per_day)
    if MARKET in data:  # compound: an asset's 50-day trend, only while BTC is above its 200-day average
        regime = dict(zip(data[MARKET][0], out["sma", 200][MARKET], strict=True))
        out["btcf", 50] = {
            s: [None if x is None or regime.get(t) is None else x * regime[t] for t, x in zip(times, out["sma", 50][s], strict=True)]
            for s, (times, _) in data.items()
        }
    if len(data) > 1:  # compound: 50-day trend, only in the stronger half of assets by 90-day momentum
        by_time = {}
        for symbol, (times, _) in data.items():
            for t, z in zip(times, scores[symbol], strict=True):
                if z is not None:
                    by_time.setdefault(t, []).append((z, symbol))
        leaders = {t: {s for _, s in sorted(row, reverse=True)[: math.ceil(len(row) / 2)]} for t, row in by_time.items()}
        out["xsm", 90] = {
            s: [None if x is None or t not in leaders else x * (s in leaders[t]) for t, x in zip(times, out["sma", 50][s], strict=True)]
            for s, (times, _) in data.items()
        }
    lambdas = [param for family, param in FAMILIES if family == "ridge"]
    model, skill = ridge(data, inputs, vols, bars_per_day, lambdas)
    for lam in lambdas:
        out["ridge", lam] = model[lam]
    return out, vols, skill


# ---- execution overlay and scoring ----


def target(signal, vol, vol_target, side="long", cap=1.0):
    """Signal to exposure: 'ls' maps [0, 1] onto [-1, 1]; a volatility target scales size up to cap times equity."""
    out = []
    for x, v in zip(signal, vol, strict=True):
        if x is None:
            out.append(None)
            continue
        if side == "ls":
            x = 2 * x - 1
        if vol_target and x:
            x = None if v is None else x * min(cap, vol_target / v)
        out.append(x)
    return out


def run(moves, target, cost, band=0.0, carry=0.0, roll=0, liquidation=None):
    """Exposure decided at close i-1 earns moves[i] (close-to-close return); each change pays cost * |change|.

    Changes smaller than the band are skipped unless they enter, leave or flip. Borrowed notional (any
    short, and longs above 1x) pays carry per bar, must be reopened every roll bars (a round trip),
    and is liquidated at the bar close when equity falls to the liquidation share of the position.
    """
    pos, age, returns, exposure, trades, liquidations = 0.0, 0, [0.0], [0.0], 0, 0
    for i in range(1, len(moves)):
        t = target[i - 1] or 0.0
        move, charge = abs(t - pos), 0.0
        if move > 1e-9 and (move >= band or t == 0 or pos == 0 or (t > 0) != (pos > 0)):
            charge, pos, trades, age = cost * move, t, trades + 1, 0
        borrowed = max(pos - 1.0, 0.0) + max(-pos, 0.0)
        if borrowed and roll and age >= roll:
            charge, age = charge + 2 * cost * abs(pos), 0
        r = moves[i]
        growth = 1 + pos * r
        held = pos
        if borrowed and liquidation is not None and growth <= liquidation * abs(pos) * (1 + r):
            growth, pos, liquidations = max(growth, 0.0), 0.0, liquidations + 1  # closed at this close, never below zero
        returns.append((1 - charge) * growth - carry * borrowed - 1)
        exposure.append(held)
        age += 1
    return returns, exposure, trades, liquidations


def stats(returns, exposure, bars_per_year):
    n = len(returns)
    if n < 2:
        return None
    equity = peak = 1.0
    drawdown = 0.0
    for r in returns:
        equity *= 1 + r
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
    mean = sum(returns) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in returns) / n)
    return {
        "cagr": equity ** (bars_per_year / n) - 1 if equity > 0 else -1.0,
        "vol": sd * math.sqrt(bars_per_year),
        "sharpe": mean / sd * math.sqrt(bars_per_year) if sd else 0.0,
        "maxdd": drawdown,
        "exposure": sum(abs(x) for x in exposure) / n,
    }


def sharpe(returns, bars_per_year):
    """Annualised Sharpe alone, for ranking: one pass in C-level sums instead of full statistics."""
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns) / n
    var = sum(r * r for r in returns) / n - mean * mean
    return mean / math.sqrt(var) * math.sqrt(bars_per_year) if var > 0 else 0.0


def label(config):
    rule, days, vt, band, side, cap = config
    if rule == "hold":
        return "hold"
    name = f"ridge l{days}" if rule == "ridge" else f"{rule}{days or ''}"
    return (f"{name}{f' vt{int(vt * 100)}' if vt else ''}{f' b{band:g}' if band else ''}"
            f"{' ls' if side == 'ls' else ''}{f' x{cap:g}' if cap != 1 else ''}")


class Grid:
    """Union of all bar times, and where each asset's bars sit in it, so portfolios blend in O(bars)."""

    def __init__(self, data):
        self.times = sorted({t for times, _ in data.values() for t in times})
        where = {t: i for i, t in enumerate(self.times)}
        self.slots = {s: [where[t] for t in times] for s, (times, _) in data.items()}


def sleeves(data, costs, bars_per_day, margin=frozenset(), terms=MARGIN):
    """Configurations one at a time as (config, {symbol: (returns, exposure, trades, liquidations)}), plus skill.

    A generator, so a universe of many assets never holds every configuration's runs at once.
    Assets without a margin market stay long-only spot at most 1x whatever the configuration asks.
    """
    families, vols, skill = signals(data, bars_per_day)
    bars_per_year = 365 * bars_per_day
    carry = terms["borrow_rate"] / bars_per_year
    roll = terms["roll_days"] * bars_per_day

    def each():
        for config in configs(margin & set(data)):
            rule, param, vt, band, side, cap = config
            if rule != "hold" and (rule, param) not in families:
                continue
            per = {}
            for symbol, (_, closes) in data.items():
                signal = [1.0] * len(closes) if rule == "hold" else families[rule, param][symbol]
                ok = symbol in margin
                exposure = target(signal, vols[symbol], vt, side if ok else "long", cap if ok else 1.0)
                per[symbol] = run(vols[symbol, "moves"], exposure, costs[symbol], band, carry, roll, terms["liquidation"])
            yield config, per

    return each(), skill


def blend(parts, grid):
    """Equal weight across the sleeves alive at each bar: (times, returns, gross exposure)."""
    n = len(grid.times)
    total, gross, count = [0.0] * n, [0.0] * n, [0] * n
    for symbol, (returns, exposure, *_) in parts.items():
        for k, r, x in zip(grid.slots[symbol], returns, exposure, strict=True):
            total[k] += r
            gross[k] += abs(x)
            count[k] += 1
    keep = [k for k in range(n) if count[k]]
    return [grid.times[k] for k in keep], [total[k] / count[k] for k in keep], [gross[k] / count[k] for k in keep]


def window(series, start, end):
    times, returns, exposure = series[:3]
    a, b = bisect.bisect_left(times, start), bisect.bisect_left(times, end)
    return returns[a:b], exposure[a:b]


def line(name, s, extra=""):
    if s is None:
        return f"  {name:<28} (no bars in this window)"
    return (
        f"  {name:<28} CAGR {s['cagr']:7.1%}  vol {s['vol']:6.1%}  Sharpe {s['sharpe']:5.2f}  "
        f"maxDD {s['maxdd']:6.1%}  gross {s['exposure']:4.0%}{extra}"
    )


def passes(candidate, hold):
    """Validation gate: better risk-adjusted return and a shallower drawdown than buy-and-hold."""
    return candidate is not None and hold is not None and candidate["sharpe"] > hold["sharpe"] and candidate["maxdd"] < hold["maxdd"]


def correlation(pairs):
    if len(pairs) < 30:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in pairs) / (sx * sy) if sx and sy else None


def walk_forward(portfolio, bars_per_year):
    """From each 1 January after two years, trade the configuration with the best Sharpe on all earlier bars."""
    times = next(iter(portfolio.values()))[0]
    sums = {c: list(accumulate(series[1], initial=0.0)) for c, series in portfolio.items()}
    squares = {c: list(accumulate((r * r for r in series[1]), initial=0.0)) for c, series in portfolio.items()}

    def sharpe_before(c, a):  # O(1) from running sums instead of re-scanning every prefix
        mean = sums[c][a] / a
        var = squares[c][a] / a - mean * mean
        return mean / math.sqrt(var) if var > 0 else 0.0

    returns, exposure, picks = [], [], []
    for y in sorted({t[:4] for t in times}):
        a, b = bisect.bisect_left(times, y), bisect.bisect_left(times, str(int(y) + 1))
        if a < 2 * bars_per_year:
            continue
        best = max(portfolio, key=lambda c: sharpe_before(c, a))
        returns += portfolio[best][1][a:b]
        exposure += portfolio[best][2][a:b]
        picks.append(f"{y}:{label(best)}")
    return returns, exposure, picks


def report(data, costs, interval, train_end, test_start, end="9999", margin=frozenset(), terms=MARGIN,
           holdout=None, rescore=False):
    """Run the protocol and print it. costs is one cost per side for all assets or {symbol: cost}.

    `holdout` (a HoldoutLedger) records each look at the test window; a repeat look is withheld unless
    `rescore`, and then the deflated Sharpe counts the configurations tried across every look.
    """
    bars_per_day = BARS_PER_DAY[interval]
    year = 365 * bars_per_day
    costs = costs if isinstance(costs, dict) else dict.fromkeys(data, costs)
    grid = Grid(data)
    first = grid.times[0]
    splits = (("train", first, train_end), ("validation", train_end, test_start), ("test", test_start, end))

    def score(series, split):
        return stats(*window(series, *split[1:]), year)

    def rank(series, split):
        value = sharpe(window(series, *split[1:])[0], year)
        return -9.0 if value is None else value

    each, skill = sleeves(data, costs, bars_per_day, frozenset(margin), terms)
    portfolio, counts, tailored = {}, {}, {}  # per asset: (train Sharpe, its run) of the best configuration so far
    for config, per in each:
        portfolio[config] = blend(per, grid)
        counts[config] = (sum(r[2] for r in per.values()), sum(r[3] for r in per.values()))
        if config[0] == "hold":
            continue
        for symbol, result in per.items():
            value = rank((data[symbol][0], *result[:2]), splits[0])
            if symbol not in tailored or value > tailored[symbol][0]:
                tailored[symbol] = (value, result)
    candidates = [c for c in portfolio if c[0] != "hold"]

    margined = sorted(set(margin) & set(data))
    print(f"{len(data)} assets ({len(margined)} with margin: short and up to 4x credit), {interval} bars, "
          f"cost per side {min(costs.values()):.2%}..{max(costs.values()):.2%}, {len(candidates)} configurations tried")
    if margined:
        print(f"  margin terms: borrow {terms['borrow_rate']:.0%}/yr, reopen every {terms['roll_days']} days, "
              f"liquidation at {terms['liquidation']:.0%} margin")
    print("  " + "  ".join(f"{name} {a[:10]}..{b[:10]}" for name, a, b in splits))

    # 0. Each family's best train configuration, for information only (selection is section 1).
    print("\nBest configuration per family on train  | its validation Sharpe (information only)")
    for family in dict.fromkeys(c[:2] for c in candidates):
        best = max((c for c in candidates if c[:2] == family), key=lambda c: rank(portfolio[c], splits[0]))
        va = score(portfolio[best], splits[1])
        print(line(label(best), score(portfolio[best], splits[0]), f"  | {va['sharpe']:5.2f}" if va else ""))

    # 1. One shared configuration for the whole portfolio, ranked on train only.
    train_sharpe = {c: rank(portfolio[c], splits[0]) for c in candidates}
    chosen = max(candidates, key=train_sharpe.get)
    train_returns = window(portfolio[chosen], *splits[0][1:])[0]
    _, _, skew, kurt = _moments(train_returns)
    per_period = [s / math.sqrt(year) for s in train_sharpe.values()]
    mean = sum(per_period) / len(per_period)
    dsr = deflated_sharpe(train_sharpe[chosen] / math.sqrt(year), len(train_returns), skew, kurt, len(candidates),
                          sum((s - mean) ** 2 for s in per_period) / (len(per_period) - 1))
    valid = passes(score(portfolio[chosen], splits[1]), score(portfolio[HOLD], splits[1]))
    custody = None
    if valid and holdout is not None:
        from gym.services.holdout_ledger import HoldoutRefused, window_id
        prices = [(f"{sym}@{t}", p) for sym, (times, closes) in sorted(data.items())
                  for t, p in zip(times, closes) if test_start <= t < end]
        spec = {"costs": costs, "margin": sorted(margin), "terms": terms, "train_end": train_end,
                "chosen": label(chosen)}
        try:
            custody = holdout.look(window_id(data, interval, test_start, end, prices), spec, len(candidates),
                                   rescore=rescore)
        except HoldoutRefused as refused:
            print(f"\nTest window withheld: {refused}. Rerun with --rescore-holdout to look again; the look is "
                  "recorded and every configuration tried at this window counts toward the deflated Sharpe.")
            valid = False
        if custody and custody["look"] > 1:
            dsr = deflated_sharpe(train_sharpe[chosen] / math.sqrt(year), len(train_returns), skew, kurt,
                                  custody["configurations_all_looks"],
                                  sum((s - mean) ** 2 for s in per_period) / (len(per_period) - 1))
    shown = "n/a" if dsr is None else f"{dsr:.3f}"
    tries = (f"{custody['configurations_all_looks']} tries across {custody['look']} looks at this test window"
             if custody and custody["look"] > 1 else f"{len(candidates)} tries")
    print(f"\nShared configuration: {label(chosen)}  deflated Sharpe probability {shown} over {tries}"
          f"  -> validation {'PASSED' if valid else 'FAILED or withheld (not taken to test)'}")
    for split in splits if valid else splits[:2]:
        print(f" {split[0]}")
        print(line(label(chosen), score(portfolio[chosen], split)))
        print(line("buy & hold", score(portfolio[HOLD], split)))
    if valid:
        test_returns = window(portfolio[chosen], *splits[2][1:])[0]
        low, high = (s * math.sqrt(year) for s in _bootstrap(test_returns)["sharpe_per_period"])
        print(f"  test Sharpe 90% block-bootstrap range {low:.2f} .. {high:.2f}")
        print(f"  {counts[chosen][0]} trades and {counts[chosen][1]} liquidations across all assets and years")

    # 2. Tailored per asset: each asset takes its own train winner; same gate, same untouched test.
    mixed = blend({symbol: result for symbol, (_, result) in tailored.items()}, grid)
    va_mixed, va_shared = score(mixed, splits[1]), score(portfolio[chosen], splits[1])
    better = va_mixed and va_shared and va_mixed["sharpe"] > va_shared["sharpe"]
    print(f"\nTailoring per asset {'beats' if better else 'does not beat'} the shared configuration on validation")
    print(line("tailored (validation)", va_mixed))
    if better and valid:
        print(line("tailored (test)", score(mixed, splits[2])))

    # 3. Forecast skill of the statistical model: correlation of forecast with the realised outcome.
    print(f"\nRidge forecast skill (correlation with the next {HORIZON_DAYS}-day outcome, out of sample by construction)")
    for lam, pairs in skill.items():
        cells = []
        for name, a, b in splits:
            ic = correlation([(f, o) for t, f, o in pairs if a <= t < b])
            cells.append(f"{name} {'n/a' if ic is None else f'{ic:+.3f}'}")
        print(f"  lambda {lam:<5} " + "  ".join(cells))

    # 4. Yearly walk-forward on the portfolio: each year trades the best Sharpe on all earlier bars.
    returns, exposure, picks = walk_forward(portfolio, year)
    if picks:
        start = picks[0][:4]
        print(f"\nWalk-forward from {start}: " + " ".join(picks))
        print(line("walk-forward", stats(returns, exposure, year)))
        print(line("buy & hold", stats(*window(portfolio[HOLD], start, end), year)))
    return {"chosen": label(chosen), "validated": valid, "deflated_sharpe": dsr, "holdout": custody,
            "tailoring_better": bool(better), "walk_forward": picks}


def symbol(text):
    if not text.isalnum():
        raise argparse.ArgumentTypeError(f"not a symbol: {text!r}")
    return text.upper()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    pull = commands.add_parser("fetch", help="download and checksum-verify monthly klines")
    pull.add_argument("--from", dest="start", default="2017-08", help="first month, YYYY-MM")
    study = commands.add_parser("study", help="train / validation / test study on the cached history")
    study.add_argument("--cost", type=float, default=0.003, help="cost per side (fee + half spread + slippage)")
    study.add_argument("--costs", type=Path, help='JSON {"SYMBOL": cost per side}; overrides --cost per asset')
    study.add_argument("--margin", default="", help="comma-separated symbols that may short and borrow (margin markets)")
    study.add_argument("--borrow-rate", type=float, default=MARGIN["borrow_rate"], help="yearly cost of borrowed notional")
    study.add_argument("--roll-days", type=int, default=MARGIN["roll_days"], help="days before a margin position must reopen")
    study.add_argument("--liquidation", type=float, default=MARGIN["liquidation"], help="margin ratio that liquidates")
    study.add_argument("--train-end", default="2022-01-01", help="first bar of validation")
    study.add_argument("--test-start", default="2024-01-01", help="first bar of test (scored once)")
    study.add_argument("--holdout-ledger", type=Path, default=CACHE.parent / "holdout_ledger.sqlite3",
                       help="append-only record of every look at a test window")
    study.add_argument("--rescore-holdout", action="store_true",
                       help="look at an already scored test window again (recorded; deflation counts every look)")
    for sub in (pull, study):
        sub.add_argument("symbols", nargs="+", type=symbol)
        sub.add_argument("--interval", choices=BARS_PER_DAY, default="1d")
        sub.add_argument("--cache", type=Path, default=CACHE)
    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(args.symbols, tuple(int(v) for v in args.start.split("-")), args.interval, args.cache)
    else:
        data = {s: load(s, args.interval, args.cache) for s in args.symbols}
        costs = {s: args.cost for s in data}
        if args.costs:
            costs |= {s: float(c) for s, c in json.loads(args.costs.read_text()).items() if s in data}
        margin = {s.strip().upper() for s in args.margin.split(",") if s.strip()}
        terms = {"borrow_rate": args.borrow_rate, "roll_days": args.roll_days, "liquidation": args.liquidation}
        from gym.services.holdout_ledger import HoldoutLedger
        ledger = HoldoutLedger(args.holdout_ledger)
        try:
            report(data, costs, args.interval, args.train_end, args.test_start, margin=margin, terms=terms,
                   holdout=ledger, rescore=args.rescore_holdout)
        finally:
            ledger.close()


if __name__ == "__main__":
    main()
