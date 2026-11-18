"""Could each trial have found an edge? The smallest edge its own pass test would detect 80% of the time.

For each trial's winning return series: remove its average (keeping its real noise, streaks and tails), add a known edge,
resample in blocks, and apply the trial's registered pass test. Exploration about the tests, not a new trial: it scores
no strategy and selects nothing.

    uv run --no-sync python scripts/detectable_edge.py --db ../data/live/market.db [--only name ...]
"""
import argparse
import sqlite3
import sys
from pathlib import Path
from random import Random
from statistics import fmean, pvariance

sys.path.insert(0, str(Path(__file__).resolve().parent))
import long_history_study as study  # noqa: E402

from gym.domain.performance import _moments, deflated_sharpe  # noqa: E402

EDGES_BPS = (1, 2, 3, 5, 7, 10, 15, 20, 30, 50, 75, 100, 150, 200, 300)
TARGET, DRAWS = 0.80, 200


def resample(series, block, rng):
    """Stationary block bootstrap of the same length."""
    n, out = len(series), []
    i = rng.randrange(n)
    while len(out) < n:
        out.append(series[i])
        i = rng.randrange(n) if rng.random() < 1 / block else (i + 1) % n
    return out


def deflated_test(trials, sharpe_variance):
    def passes(series):
        mean, deviation, skew, kurtosis = _moments(series)
        return (deflated_sharpe(mean / deviation if deviation else 0.0, len(series), skew, kurtosis, trials, sharpe_variance) or 0) >= 0.95
    return passes


def bootstrap_test(block, threshold=0.90, draws=300):
    def passes(series):
        rng, _n, above = Random(1), len(series), 0
        for _ in range(draws):
            sample = resample(series, block, rng)
            above += fmean(sample) > 0
        return above / draws >= threshold
    return passes


def detection(series, edge, passes, block, seed=0):
    base = fmean(series)
    planted = [r - base + edge for r in series]
    rng = Random(seed)
    return sum(passes(resample(planted, block, rng)) for _ in range(DRAWS)) / DRAWS


def smallest(series, passes, block):
    """(smallest edge in bps per period detected at least 80% of the time, the curve)."""
    curve = []
    for bps in EDGES_BPS:
        rate = detection(series, bps / 10000, passes, block)
        curve.append((bps, rate))
        if rate >= TARGET:
            return bps, curve
    return None, curve


def cells_variance(series_list):
    sharpes = []
    for series in series_list:
        mean, deviation, _, _ = _moments(series)
        sharpes.append(mean / deviation if deviation else 0.0)
    return pvariance(sharpes)


# ---- each trial's winning series and its pass test, rebuilt with the trial's own code -------------------------------

def btc_daily_trend(_):
    import edge_screen as screen
    binance = {s: study.load(s, "1d", study.CACHE) for s in screen.TREND_MARKETS}
    cost = screen.ACCOUNT_FEE + 0.001
    cells = {(s, w): screen.window_returns(*binance[s], w, cost)[0] for s in screen.TREND_MARKETS for w in screen.TREND_WINDOWS}
    best = max(cells, key=lambda k: _sharpe(cells[k]))
    return [("ranking", cells[best], deflated_test(len(cells), cells_variance(cells.values())), 20, "day")]


def trend_with_short_side(_):
    import trend_short as t
    src = {s: study.load(s, "1d", study.CACHE) for s in t.RANK_COINS}
    cells = {(s, w, x): [r for d, r in t.returns(*src[s], w, x) if d < t.SPLIT] for s in t.RANK_COINS for w in t.WINDOWS for x in t.RATIOS}
    best = max(cells, key=lambda k: _sharpe(cells[k]))
    return [("ranking", cells[best], deflated_test(len(cells), cells_variance(cells.values())), 20, "day")]


def rule_selector_with_cash(_):
    import rule_selector as rs
    src = {s: study.load(s, "1d", study.CACHE) for s in rs.RANK_COINS}
    cells = {(s, lb): rs.ranked(*src[s], lb)[0] for s in rs.RANK_COINS for lb in rs.LOOKBACKS}
    best = max(cells, key=lambda k: _sharpe(cells[k]))
    return [("ranking", cells[best], deflated_test(len(cells), cells_variance(cells.values())), 20, "day")]


def strongest_coin_or_cash(db):
    import strongest_coin as sc
    from edge_screen import venue_daily
    src = {c: ([d[:10] for d in ds], cs) for c, (ds, cs) in ((c, study.load(c, "1d", study.CACHE)) for c in sc.RANK_COINS)}
    cells = {}
    for lb in sc.LOOKBACKS:
        rows = [r for r in sc.rotate(src, lb) if r[0] < sc.SPLIT]
        first = next(i for i, r in enumerate(rows) if r[2] is not None)
        cells[lb] = [r[1] for r in rows[first:]]
    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    held_src = {c: ([d[:10] for d in ds], cs) for c, (ds, cs) in ((c, venue_daily(connection, c)) for c in sc.HELD_OUT)}
    held = [r[1] for r in sc.rotate(held_src, 180) if r[0] >= "2022-07-27"]
    return [("ranking", cells[180], deflated_test(len(cells), cells_variance(cells.values())), 20, "day"),
            ("held out", held, bootstrap_test(20), 20, "day")]


def implied_toman_rate(db):
    import implied_rate as ir
    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    rows = ir.gaps(*(ir.closes(connection, s) for s in ("USDTTMN", "BTCTMN", "BTCUSDT")))
    rank = [r for r in rows if r[0] < ir.SPLIT]
    cells = {(h, th): [t[1] for t in ir.trades(rank, h, th, ir.COST)] for h in ir.HOURS for th in ir.THRESHOLDS}
    cells = {k: v for k, v in cells.items() if len(v) > 2}
    best = max(cells, key=lambda k: _sharpe(cells[k]))
    return [("ranking", cells[best], deflated_test(len(cells), cells_variance(cells.values())), 1, "trade")]


def book_imbalance(db):
    import book_imbalance as bi
    connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    books = {m: bi.quotes(connection, m, "2026-01-01T00:00:00Z", bi.REGISTERED) for m in bi.MARKETS}
    cells = {(th, h): [v for b in books.values() for _, v in bi.trades(b, th, h)] for th in bi.THRESHOLDS for h in bi.HOLDS}
    best = max(cells, key=lambda k: _sharpe(cells[k]))
    return [("ranking", cells[best], deflated_test(len(cells), cells_variance(cells.values())), 1, "trade")]


def broad_binance(_):
    import funding_filter as ff
    import held_out_followups as ho
    import margin_breakout as mb
    from binance_archive import daily_funding, spot_daily, universe
    coins = universe()
    bars = {c: spot_daily(c) for c in coins}
    funding = {c: daily_funding(c) for c in coins}
    data = {c: (b["days"], b["close"], b["volume"]) for c, b in bars.items() if len(b["days"]) > ff.WINDOW + ff.HISTORY}
    caps = {cap: ff.compare(data, funding, cap, "2000", ff.SPLIT)[0] for cap in ff.CAPS}
    best_cap = max(caps, key=lambda k: _sharpe(caps[k]))
    counted = {c: (b, mb.counted_days(b, funding[c])) for c, b in bars.items() if len(b["days"]) > mb.LOOKBACK + 1}
    settings = {s: mb.pooled(counted, *s, "2000", ff.SPLIT) for s in mb.SETTINGS}
    best_setting = max(settings, key=lambda k: _sharpe(settings[k]))
    held = [c for c in coins if c not in ff.USED_AFTER_SPLIT and len(bars[c]["days"]) > ff.WINDOW + 1]
    rules = [ho.breakout_long(bars[c], mb.counted_days(bars[c], funding[c]))[0] for c in held]
    confirmed = [ho.confirmed_trend(c, ho.LO, ho.HI)[0] for c in held]
    return {"funding-crowding-filter": [("ranking", caps[best_cap], deflated_test(len(caps), cells_variance(caps.values())), 20, "day")],
            "margin-breakout-long-short": [("ranking", settings[best_setting], deflated_test(len(settings), cells_variance(settings.values())), 20, "day")],
            "spot-breakout-long": [("held out", ho.pooled(rules), bootstrap_test(20), 20, "day")],
            "funding-confirmed-trend": [("held out", ho.pooled(confirmed), bootstrap_test(20), 20, "day")]}


def _sharpe(series):
    mean, deviation, _, _ = _moments(series)
    return mean / deviation if deviation else 0.0


TRIALS = {"btc-daily-trend": btc_daily_trend, "implied-toman-rate": implied_toman_rate, "trend-with-short-side": trend_with_short_side,
          "rule-selector-with-cash": rule_selector_with_cash, "book-imbalance": book_imbalance, "strongest-coin-or-cash": strongest_coin_or_cash}


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--broad", action="store_true", help="also the four trials on the full Binance universe (slow)")
    args = parser.parse_args(argv)
    work = {name: fn(args.db) for name, fn in TRIALS.items() if not args.only or name in args.only}
    if args.broad:
        work.update(broad_binance(args.db))
    print("trial | stage | periods | actual edge (bps/period) | smallest detectable edge (bps/period) | per year")
    for name, stages in work.items():
        for stage, series, passes, block, unit in stages:
            found, curve = smallest(series, passes, block)
            actual = fmean(series) * 10000
            per_year = "" if found is None or unit != "day" else f"{(1 + found / 10000) ** 365 * 100 - 100:,.0f}%"
            print(f"{name} | {stage} | {len(series)} {unit}s | {actual:.2f} | {found if found is not None else '>300'} | {per_year}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
