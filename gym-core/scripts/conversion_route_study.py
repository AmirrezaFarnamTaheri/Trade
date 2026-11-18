"""How often does converting through a coin beat converting directly, and by how much? Recorded quotes, every 15 minutes.

Exploration of a cost saving, not a trial: it predicts nothing. For each sample time and size it asks the same question
`gymctl convert-route` answers live, and reports how often a coin route was cheaper, the median saving when it was, and
what was possible while USDTTMN had no fresh quote (for example during its nightly closure).

    uv run --no-sync python scripts/conversion_route_study.py --db ../data/live/market.db
"""
import argparse
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gym.adapters.store import MarketDB  # noqa: E402
from gym.domain.model import iso, parse_ts  # noqa: E402
from gym.services.conversion_route import latest_touches, routes  # noqa: E402

SIZES = {"TMN_TO_USDT": (Decimal(5_000_000), Decimal(50_000_000), Decimal(500_000_000)),
         "USDT_TO_TMN": (Decimal(20), Decimal(200), Decimal(2_000))}
FEE, STEP = Decimal("0.001"), timedelta(minutes=15)


def paired_symbols(db):
    current = {row[0][7:] for row in db.c.execute("SELECT DISTINCT instrument_id FROM instrument_specs WHERE valid_to IS NULL")}
    coins = {s[:-3] for s in current if s.endswith("TMN")} & {s[:-4] for s in current if s.endswith("USDT")}
    return ["USDTTMN"] + [c + q for c in sorted(coins) if c != "USDT" for q in ("TMN", "USDT")]


def next_direct(db, at, size, direction):
    """What converting directly would have delivered at USDTTMN's next fresh quote, within 14 hours."""
    for ts in db.c.execute("SELECT ts_avail FROM book_top WHERE instrument_id='wallex:USDTTMN' AND ts_avail>? AND ts_avail<? "
                           "ORDER BY ts_avail LIMIT 50", (iso(at), iso(at + timedelta(hours=14)))):
        touches = latest_touches(db, ts[0], ["USDTTMN"])
        found = [r for r in routes(touches, size, direction, FEE) if r["fits_displayed_size"]]
        if found:
            return found[0]["received"]
    return None


def study(db, start, end):
    symbols, at, stats = paired_symbols(db), start, {}
    while at < end:
        touches = latest_touches(db, at, symbols)
        for direction, sizes in SIZES.items():
            for size in sizes:
                found = [r for r in routes(touches, size, direction, FEE) if r["fits_displayed_size"]]
                key = (direction, size)
                row = stats.setdefault(key, {"samples": 0, "coin_wins": [], "no_direct": 0, "no_direct_but_coin": 0, "now_vs_wait": []})
                direct = next((r for r in found if r["route"] == "USDTTMN"), None)
                if not found:
                    continue
                row["samples"] += 1
                if direct is None:
                    row["no_direct"] += 1
                    row["no_direct_but_coin"] += 1
                    later = next_direct(db, at, size, direction)
                    if later is not None:  # converting through a coin now, against waiting for USDTTMN to quote again
                        row["now_vs_wait"].append(float((found[0]["received"] / later - 1) * 10000))
                elif found[0]["route"] != "USDTTMN":
                    row["coin_wins"].append(float((found[0]["received"] / direct["received"] - 1) * 10000))
        at += STEP
    return stats


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--from", dest="start", default="2026-10-31T00:00:00Z")
    parser.add_argument("--to", dest="end", default=None)
    args = parser.parse_args(argv)
    db = MarketDB(args.db, readonly=True)
    end = parse_ts(args.end) if args.end else parse_ts(db.c.execute("SELECT max(ts_avail) FROM book_top").fetchone()[0])
    stats = study(db, parse_ts(args.start), end)
    print(f"Conversion routes, {args.start} to {iso(end)}, every 15 minutes, {FEE * 100}% fee per leg")
    for (direction, size), row in stats.items():
        wins = row["coin_wins"]
        share = len(wins) / max(1, row["samples"] - row["no_direct"])
        print(f"  {direction} {size}: {row['samples']} samples; a coin route was cheaper {100 * share:.1f}% of the time"
              f"{f', median saving {median(wins):.1f} bps, best {max(wins):.1f} bps' if wins else ''}; "
              f"USDTTMN unavailable {row['no_direct']} times, a coin route available then {row['no_direct_but_coin']}"
              + (f"; converting through a coin then, against waiting for USDTTMN: median {median(row['now_vs_wait']):+.1f} bps, "
                 f"better {100 * sum(v > 0 for v in row['now_vs_wait']) / len(row['now_vs_wait']):.0f}% of the time"
                 if row["now_vs_wait"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
