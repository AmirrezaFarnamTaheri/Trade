"""Record the venue's top of book once a minute from a hosted runner, so quotes exist when the local collector is off.

Standard library only; no key is sent. Candles can be fetched later, quotes cannot, so this keeps only what is lost:
best bid, best ask and their sizes, with the receipt time. Prices and sizes are kept as the venue's exact text.

    python scripts/venue_recorder.py record --minutes 340 --out quotes.jsonl [--symbols USDTTMN BTCTMN BTCUSDT]
    python scripts/venue_recorder.py import quotes.jsonl [more.jsonl] --db ../data/live/recorder.sqlite3

`import` writes a `book_top` table that `scripts/usdttmn_v1.py --db` reads. Rows are unique per market and receipt
time, so importing the same file twice, or two overlapping runs, changes nothing.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ORIGIN = "https://api.wallex.ir"
SYMBOLS = ("USDTTMN", "BTCTMN", "BTCUSDT")  # the last two give a second USDT/Toman price inside the venue
INTERVAL_S = 60


def top(text: str) -> dict | None:
    """Best bid and ask from a `/v1/depth` answer, as exact text; None when either side is empty."""
    result = json.loads(text, parse_float=str, parse_int=str)["result"]
    bids, asks = result["bid"], result["ask"]
    if not bids or not asks:
        return None
    # The venue lists each side best-first, but the best is taken by price so a reordered answer cannot mislead.
    bid = max(bids, key=lambda level: float(level["price"]))
    ask = min(asks, key=lambda level: float(level["price"]))
    return {"bid": bid["price"], "bid_qty": bid["quantity"], "ask": ask["price"], "ask_qty": ask["quantity"]}


def fetch(symbol: str) -> str:
    request = urllib.request.Request(f"{ORIGIN}/v1/depth?symbol={symbol}", headers={"User-Agent": "TradingGYM-recorder"})
    with urllib.request.urlopen(request, timeout=15) as reply:
        return reply.read(2 * 1024 * 1024).decode("utf-8")


def record(symbols, minutes: int, out: Path, *, fetch=fetch, clock=time.monotonic, sleep=time.sleep) -> tuple[int, int]:
    """Append one line per market per minute; a failed read is counted and skipped, never invented."""
    rows = errors = 0
    end = clock() + minutes * 60
    with out.open("a", encoding="utf-8", newline="\n") as file:
        while clock() < end:
            started = clock()
            for symbol in symbols:
                try:
                    quote = top(fetch(symbol))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    errors += 1
                    print(f"{symbol}: {type(error).__name__}: {error}", file=sys.stderr)
                    continue
                if quote:
                    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                    file.write(json.dumps({"ts": at, "symbol": symbol, **quote}) + "\n")
                    rows += 1
            file.flush()
            sleep(max(0.0, INTERVAL_S - (clock() - started)))
    return rows, errors


def import_files(paths: list[Path], db: Path) -> int:
    """Load recorded lines into `book_top`; returns how many rows were new."""
    connection = sqlite3.connect(db)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS book_top (instrument_id TEXT, ts_avail TEXT, bid TEXT, ask TEXT, "
                           "bid_qty TEXT, ask_qty TEXT, flags TEXT, PRIMARY KEY (instrument_id, ts_avail))")
        before = connection.total_changes
        for path in paths:
            with path.open(encoding="utf-8") as file:
                for line in file:
                    if line.strip():
                        row = json.loads(line)
                        connection.execute("INSERT OR IGNORE INTO book_top VALUES (?,?,?,?,?,?,'')",
                                           (f"wallex:{row['symbol']}", row["ts"], row["bid"], row["ask"],
                                            row["bid_qty"], row["ask_qty"]))
        connection.commit()
        return connection.total_changes - before
    finally:
        connection.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    recorder = commands.add_parser("record")
    recorder.add_argument("--minutes", type=int, required=True)
    recorder.add_argument("--out", type=Path, required=True)
    recorder.add_argument("--symbols", nargs="+", default=list(SYMBOLS))
    importer = commands.add_parser("import")
    importer.add_argument("files", type=Path, nargs="+")
    importer.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "import":
        print(f"{import_files(args.files, args.db)} new rows")
        return 0
    if not 1 <= args.minutes <= 350 or any(not symbol.isalnum() for symbol in args.symbols):
        parser.error("--minutes must be 1 to 350 and symbols alphanumeric")
    rows, errors = record([symbol.upper() for symbol in args.symbols], args.minutes, args.out)
    print(f"{rows} rows, {errors} failed reads")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
