"""Record the venue's top of book once a minute from a hosted runner, so quotes exist when the local collector is off.

Standard library only; no key is sent. Candles can be fetched later, quotes cannot, so this keeps only what is lost:
best bid, best ask and their sizes, with the receipt time. Prices and sizes are kept as the venue's exact text.

    python scripts/venue_recorder.py record --minutes 340 --out quotes.jsonl [--symbols USDTTMN BTCTMN BTCUSDT]
    python scripts/venue_recorder.py margin --out margin-terms.jsonl
    python scripts/venue_recorder.py import quotes.jsonl [more.jsonl] --db ../data/live/recorder.sqlite3

`import` writes a `book_top` table that `scripts/usdttmn_v1.py --db` reads. Rows are unique per market and receipt
time, so importing the same file twice, or two overlapping runs, changes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
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
                        if (set(row) != {"symbol", "ts", "bid", "ask", "bid_qty", "ask_qty"}
                                or not re.fullmatch(r"[A-Z0-9]{2,24}", row["symbol"])
                                or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", row["ts"])):
                            raise ValueError("invalid recorder identity or timestamp")
                        datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
                        values = [row[k] for k in ("bid", "ask", "bid_qty", "ask_qty")]
                        if any(type(v) is not str or len(v) > 80 for v in values):
                            raise ValueError("recorder amounts require bounded exact text")
                        bid, ask, bid_qty, ask_qty = map(Decimal, values)
                        if not all(v.is_finite() and v >= 0 for v in (bid, ask, bid_qty, ask_qty)) or not 0 < bid < ask:
                            raise ValueError("invalid recorder quote")
                        connection.execute("INSERT OR IGNORE INTO book_top VALUES (?,?,?,?,?,?,'')",
                                           (f"wallex:{row['symbol']}", row["ts"], row["bid"], row["ask"],
                                            row["bid_qty"], row["ask_qty"]))
        connection.commit()
        return connection.total_changes - before
    finally:
        connection.close()


def github_api(path):
    return subprocess.check_output(["gh", "api", path], timeout=60,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def sync_artifacts(repo, db, *, api=github_api):
    """Fetch retained recorder artifacts using existing gh authentication; import each ID once."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("invalid GitHub repository")
    db.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with sqlite3.connect(db) as journal:
        journal.execute("CREATE TABLE IF NOT EXISTS recorder_imports (artifact_id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL)")
        seen = {r[0] for r in journal.execute("SELECT artifact_id FROM recorder_imports")}
        for page in range(1, 1001):
            batch = json.loads(api(f"repos/{repo}/actions/artifacts?per_page=100&page={page}"))["artifacts"]
            for item in batch:
                identity = item["id"]
                if item["expired"] or identity in seen or not re.fullmatch(r"venue-quotes-[0-9]+", item["name"]):
                    continue
                if type(identity) is not int or not 0 < item["size_in_bytes"] <= 20_000_000:
                    raise ValueError("recorder artifact exceeds limit")
                raw = api(f"repos/{repo}/actions/artifacts/{identity}/zip")
                if len(raw) > 20_000_000:
                    raise ValueError("recorder archive exceeds limit")
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    if archive.namelist() != ["quotes.jsonl"] or archive.getinfo("quotes.jsonl").file_size > 20_000_000:
                        raise ValueError("unexpected recorder archive contents")
                    with archive.open("quotes.jsonl") as member:
                        content = member.read(20_000_001)
                    if len(content) > 20_000_000:
                        raise ValueError("recorder quotes exceed limit")
                with tempfile.TemporaryDirectory() as directory:
                    source = Path(directory) / "quotes.jsonl"
                    source.write_bytes(content)
                    total += import_files([source], db)
                journal.execute("INSERT INTO recorder_imports VALUES (?,?)", (identity, hashlib.sha256(content).hexdigest()))
                journal.commit()
                seen.add(identity)
            if len(batch) < 100:
                return total
    raise ValueError("artifact listing exceeded page limit")


RATIOS = ("1", "2", "3", "5", "10")
COLLATERAL = {"USDT": "100", "TMN": "30000000"}


def post_margin(path: str, body: dict | None = None) -> str:
    request = urllib.request.Request(ORIGIN + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"User-Agent": "TradingGYM-recorder", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as reply:
        return reply.read(1024 * 1024).decode("utf-8")


def margin_terms(out: Path, *, post=post_margin, fetch=fetch, sleep=time.sleep) -> tuple[int, int]:
    """The venue's own margin preview for every margin market, both sides and each allowed credit ratio, at the
    current touch. Public calculators only; nothing is opened. Venue answers are kept whole, as received."""
    markets = json.loads(post("/margin-trade/v1/public/markets"), parse_float=str, parse_int=str)["result"]
    rows = errors = 0
    with out.open("a", encoding="utf-8", newline="\n") as file:
        for market in markets:
            try:
                quote = top(fetch(market["symbol"]))
            except (OSError, ValueError, KeyError, TypeError):
                quote, errors = None, errors + 1
            if not quote:
                continue
            lo, hi, step = (Decimal(market[k]) for k in ("min_risk_coef", "max_risk_coef", "risk_coef_step"))
            for side in ("long", "short"):
                for ratio in RATIOS:
                    if not lo <= Decimal(ratio) <= hi or (Decimal(ratio) - lo) % step:
                        continue
                    body = {"market": market["symbol"], "side": side, "risk_coef": ratio, "collateral": COLLATERAL[market["quote"]],
                            "open_price": quote["ask" if side == "long" else "bid"]}
                    try:
                        answer = json.loads(post("/margin-trade/v1/public/dry-run", body), parse_float=str, parse_int=str)
                    except (OSError, ValueError) as error:
                        errors += 1
                        print(f"{market['symbol']} {side} {ratio}: {type(error).__name__}: {error}", file=sys.stderr)
                        continue
                    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                    file.write(json.dumps({"ts": at, "rule": market, "request": body, "answer": answer}) + "\n")
                    rows += 1
                    sleep(0.3)
    return rows, errors


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
    margin = commands.add_parser("margin", help="save the venue's margin previews for every market, side and ratio")
    margin.add_argument("--out", type=Path, required=True)
    sync = commands.add_parser("sync", help="import retained GitHub recorder artifacts using gh authentication")
    sync.add_argument("--repo", required=True)
    sync.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "sync":
        print(f"{sync_artifacts(args.repo, args.db)} new hosted rows")
        return 0
    if args.command == "margin":
        rows, errors = margin_terms(args.out)
        print(f"{rows} margin previews, {errors} failed reads")
        return 0 if rows else 1
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
