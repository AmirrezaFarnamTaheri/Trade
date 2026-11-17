"""T13: does top-of-book quantity imbalance predict a mid move large enough to pay for crossing the spread?

Registered in docs/trial-log.md before this script ran. `rank` uses quotes recorded before 2026-11-18T00:00Z.
`score` reads the prospective quotes (2026-11-18 to 2026-12-18) and refuses to run before that window has closed.

    uv run --no-sync python scripts/book_imbalance.py rank --db ../data/live/market.db
    uv run --no-sync python scripts/book_imbalance.py score --db ../data/live/market.db --threshold 0.8 --hold 5
"""
import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from statistics import fmean, pvariance

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gym.domain.performance import _moments, deflated_sharpe  # noqa: E402

MARKETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BTCTMN", "USDTTMN")
THRESHOLDS, HOLDS = (0.6, 0.8), (1, 5, 15)  # minutes
REGISTERED, PROSPECT_END = "2026-11-18T00:00:00.000000Z", "2026-12-18T00:00:00.000000Z"
FEE = 0.001
BAD = ("STALE", "CROSSED", "ZERO_SPREAD", "NON_FINITE", "NON_POSITIVE")


def quotes(connection, symbol, start, end):
    """Qualified (seconds, bid, ask, bid_qty, ask_qty) in receipt order."""
    out = []
    for ts, bid, ask, bq, aq, flags in connection.execute(
            "SELECT ts_avail, bid, ask, bid_qty, ask_qty, flags FROM book_top WHERE instrument_id=? AND ts_avail>=? AND ts_avail<? "
            "ORDER BY ts_avail", (f"wallex:{symbol}", start, end)):
        if None in (bid, ask, bq, aq) or any(flag in (flags or "") for flag in BAD):
            continue
        bid, ask, bq, aq = float(bid), float(ask), float(bq), float(aq)
        if 0 < bid < ask and bq + aq > 0:
            out.append((datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp(), bid, ask, bq, aq))
    return out


def trades(book, threshold, hold_minutes):
    """(day, net return) per trade; one open trade at a time, exit at the opposite touch after the holding time."""
    out, i, hold = [], 0, hold_minutes * 60
    while i < len(book):
        at, bid, ask, bq, aq = book[i]
        imbalance = (bq - aq) / (bq + aq)
        if abs(imbalance) < threshold:
            i += 1
            continue
        j = i + 1
        while j < len(book) and book[j][0] < at + hold:
            j += 1
        if j == len(book):
            break
        _, exit_bid, exit_ask, _, _ = book[j]
        gross = exit_bid / ask - 1 if imbalance > 0 else bid / exit_ask - 1
        out.append((datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d"), gross - 2 * FEE))
        i = j + 1
    return out


def day_block_probability(rows, draws=2000, seed=0):
    """Share of day resamples whose mean net trade is above zero."""
    by_day = {}
    for day, value in rows:
        by_day.setdefault(day, []).append(value)
    days, rng, above = list(by_day.values()), Random(seed), 0
    if len(days) < 5:
        return 0.0
    for _ in range(draws):
        sample = [v for _ in days for v in rng.choice(days)]
        above += fmean(sample) > 0
    return above / draws


def rank(connection) -> bool:
    books = {m: quotes(connection, m, "2026-01-01T00:00:00Z", REGISTERED) for m in MARKETS}
    cells = []
    for threshold in THRESHOLDS:
        for hold in HOLDS:
            rows = [row for book in books.values() for row in trades(book, threshold, hold)]
            values = [v for _, v in rows]
            mean, deviation, skew, kurtosis = _moments(values) if len(values) > 2 else (0.0, 0.0, 0.0, 3.0)
            cells.append({"threshold": threshold, "hold": hold, "n": len(values), "mean": mean,
                          "gross": mean + 2 * FEE, "sharpe": mean / deviation if deviation else 0.0, "moments": (skew, kurtosis)})
    variance = pvariance([c["sharpe"] for c in cells])
    print(f"T13 ranked on quotes before {REGISTERED}; {', '.join(f'{m} {len(b)}' for m, b in books.items())} qualified quotes")
    for c in cells:
        c["deflated"] = deflated_sharpe(c["sharpe"], c["n"], *c["moments"], len(cells), variance) or 0.0 if c["n"] > 2 else 0.0
        print(f"  imbalance {c['threshold']:.1f}, hold {c['hold']:2} min: {c['n']:6} trades, mean gross {10000 * c['gross']:7.1f} bps, "
              f"net {10000 * c['mean']:7.1f} bps, Sharpe per trade {c['sharpe']:6.3f}, deflated {c['deflated']:.3f}")
    best = max(cells, key=lambda c: c["deflated"])
    ok = best["deflated"] >= 0.95 and best["n"] >= 200
    print(f"T13 ranking {'PASS' if ok else 'FAIL'}: best imbalance {best['threshold']}, hold {best['hold']} min, "
          f"deflated {best['deflated']:.3f}, {best['n']} trades{'' if ok else '; prospective quotes will not be scored'}")
    return ok


def score(connection, threshold, hold, now=None) -> bool:
    now = now or datetime.now(UTC)
    if now < datetime.fromisoformat(PROSPECT_END.replace("Z", "+00:00")):
        raise SystemExit(f"T13 prospective window closes {PROSPECT_END}; scoring before then would peek")
    rows = [row for m in MARKETS for row in trades(quotes(connection, m, REGISTERED, PROSPECT_END), threshold, hold)]
    chance = day_block_probability(rows)
    mean = fmean(v for _, v in rows) if rows else 0.0
    passed = chance >= 0.90 and len(rows) >= 100
    print(f"T13 prospective: {len(rows)} trades, mean net {10000 * mean:.1f} bps, day-block probability mean > 0: {chance:.3f}")
    print(f"T13 VERDICT: {'PASS' if passed else 'FAIL'}")
    return passed


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("action", choices=("rank", "score"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--threshold", type=float, choices=THRESHOLDS)
    parser.add_argument("--hold", type=int, choices=HOLDS)
    args = parser.parse_args(argv)
    connection = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    if args.action == "rank":
        rank(connection)
    else:
        if args.threshold is None or args.hold is None:
            parser.error("score needs the ranking's --threshold and --hold")
        score(connection, args.threshold, args.hold)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
