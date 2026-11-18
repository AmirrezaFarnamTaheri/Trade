"""Wallex tokenised assets against the asset each tracks: daily premium, its spread and how fast it closes.

Descriptive only; no strategy is scored. Wallex closes are taken at 00:00 UTC and Yahoo closes at the New York close,
so measured gaps are wider than gaps at the same moment.

    uv run --no-sync python scripts/token_premium.py --db ../data/live/market.db
"""
import argparse
import math
import sqlite3
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from passive_mix import fetch  # noqa: E402

TRACKS = {"XAUTUSDT": "GC=F", "SLVONUSDT": "SLV", "USOONUSDT": "USO", "COPXONUSDT": "COPX", "AAPLXUSDT": "AAPL"}


def premium_stats(premiums):
    """Median, 10th and 90th percentiles, lag-one persistence and the implied half-life in days."""
    ordered = sorted(premiums)
    mean = statistics.fmean(premiums)
    centred = [p - mean for p in premiums]
    persistence = sum(centred[i] * centred[i - 1] for i in range(1, len(centred))) / sum(c * c for c in centred[:-1])
    half_life = math.log(0.5) / math.log(persistence) if 0 < persistence < 1 else math.inf
    return {"median": statistics.median(premiums), "p10": ordered[len(ordered) // 10], "p90": ordered[9 * len(ordered) // 10],
            "persistence": persistence, "half_life_days": half_life}


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    connection = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    for token, ticker in TRACKS.items():
        reference = fetch(ticker)
        premiums = [float(close) / reference[t[:10]] - 1 for t, close in connection.execute(
            "SELECT t, c FROM venue_candles WHERE instrument_id=? AND resolution='1d' ORDER BY t", (f"wallex:{token}",)) if t[:10] in reference]
        if len(premiums) < 20:
            print(f"{token}: only {len(premiums)} matching days")
            continue
        s = premium_stats(premiums)
        print(f"{token} vs {ticker}: {len(premiums)} days, median {100 * s['median']:+.2f}%, 10% to 90% {100 * s['p10']:+.2f}% to "
              f"{100 * s['p90']:+.2f}%, persistence {s['persistence']:.2f}, half-life {s['half_life_days']:.1f} days")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
