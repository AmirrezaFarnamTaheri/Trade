"""How fast does a quote-level signal fade? Mid-price move in the signal's direction when entry comes late.

Exploration, not a trial: it measures, it does not select. For each recorded quote where the signal fires, the move is
taken from the quote `delay` updates later to the first quote `horizon` seconds after that, and set against the median
spread a taker would pay. A signal that is gone before a realistic fill is an observation, not a strategy.

    uv run --no-sync python scripts/signal_decay.py --db ../data/live/market.db --markets BTCTMN USDTTMN --to 2026-11-18T00:00:00Z
"""
import argparse
import sqlite3
import sys
from bisect import bisect_left
from pathlib import Path
from statistics import fmean, median

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_imbalance import quotes  # noqa: E402

DELAYS = (0, 1, 5, 20)  # quote updates between the signal and entry


def imbalance(quote, threshold=0.8):
    """+1 when the best bid quantity dominates, -1 when the ask does, else 0."""
    _, _, _, bid_qty, ask_qty = quote
    value = (bid_qty - ask_qty) / (bid_qty + ask_qty)
    return 1 if value >= threshold else -1 if value <= -threshold else 0


def decay(book, signal=imbalance, horizon=300, delays=DELAYS, stride=5):
    """{delay: (signals, mean move in bps)} and the median spread in bps; every `stride`-th quote is examined."""
    times = [q[0] for q in book]
    moves, spreads = {d: [] for d in delays}, []
    for i in range(0, len(book), stride):
        side = signal(book[i])
        if not side:
            continue
        spreads.append((book[i][2] / book[i][1] - 1) * 10000)
        for delay in delays:
            start = i + delay
            end = bisect_left(times, times[start] + horizon) if start < len(book) else len(book)
            if end >= len(book):
                continue
            mid0, mid1 = (book[start][1] + book[start][2]) / 2, (book[end][1] + book[end][2]) / 2
            moves[delay].append(side * (mid1 / mid0 - 1) * 10000)
    return {d: (len(v), fmean(v) if v else None) for d, v in moves.items()}, median(spreads) if spreads else None


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--markets", nargs="+", required=True)
    parser.add_argument("--from", dest="start", default="2026-01-01T00:00:00Z")
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--horizon", type=int, default=300, help="seconds after entry")
    args = parser.parse_args(argv)
    connection = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    print(f"Order-book imbalance, {args.horizon} s after entry; move in bps in the signal's direction, by entry delay in quote updates")
    for market in args.markets:
        by_delay, spread = decay(quotes(connection, market, args.start, args.end), horizon=args.horizon)
        cells = "  ".join(f"delay {d:2}: {v:6.2f} ({n})" if v is not None else f"delay {d:2}: n/a" for d, (n, v) in by_delay.items())
        print(f"  {market:9} median spread {spread:6.1f}  {cells}" if spread is not None else f"  {market:9} no signals")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
