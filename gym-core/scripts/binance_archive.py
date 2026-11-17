"""Binance public data archive (data.binance.vision): the coin universe, checked downloads and daily loaders.

Every downloaded file is checked against its published SHA-256 before it is kept. Files already cached are not fetched
again, so `fetch` can be rerun after an interruption.

    uv run --no-sync python scripts/binance_archive.py fetch
"""
import csv
import hashlib
import http.client
import io
import re
import sys
import time
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, median

sys.path.insert(0, str(Path(__file__).resolve().parent))
import long_history_study as study  # noqa: E402

ARCHIVE = "https://data.binance.vision"
LISTING = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FUNDING_PREFIX, SPOT_PREFIX = "data/futures/um/monthly/fundingRate/", "data/spot/monthly/klines/"
CACHE = study.CACHE
MIN_VOLUME, VOLUME_DAYS = 5_000_000.0, 30  # median daily quote volume, in USDT, over the previous 30 days


def get(url, attempts=5):
    """The archive drops a connection now and then under load; retry with backoff, then give up loudly."""
    for attempt in range(attempts):
        try:
            return study.get(url)
        except (OSError, http.client.HTTPException):
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def listing(prefix):
    """Every key or sub-folder name directly under an archive prefix."""
    names, marker = [], ""
    while True:
        url = f"{LISTING}?delimiter=/&prefix={urllib.parse.quote(prefix)}" + (f"&marker={urllib.parse.quote(marker)}" if marker else "")
        text = get(url).decode()
        found = re.findall(r"<Prefix>([^<]+)</Prefix>", text)[1:] + re.findall(r"<Key>([^<]+)</Key>", text)
        names += found
        if "<IsTruncated>true" not in text or not found:
            return [urllib.parse.unquote(name.rstrip("/").rsplit("/", 1)[1]) for name in names]
        marker = found[-1]


def universe():
    """USDT perpetuals that also trade spot against USDT."""
    perpetuals = {s for s in listing(FUNDING_PREFIX) if s.endswith("USDT")}
    return sorted(perpetuals & set(listing(SPOT_PREFIX)))


def _download(job):
    url, path = job
    body, expected = get(url), get(url + ".CHECKSUM").split()[0].decode()
    if hashlib.sha256(body).hexdigest() != expected:
        raise SystemExit(f"checksum mismatch for {path.name}; file not kept")
    part = path.with_suffix(".part")
    part.write_bytes(body)
    part.replace(path)


def _missing(symbol):
    jobs = []
    for prefix, folder in ((f"{FUNDING_PREFIX}{symbol}/", CACHE / "funding"), (f"{SPOT_PREFIX}{symbol}/1d/", CACHE / "1d")):
        folder.mkdir(parents=True, exist_ok=True)
        jobs += [(f"{ARCHIVE}/{urllib.parse.quote(prefix + name)}", folder / name) for name in listing(prefix)
                 if name.endswith(".zip") and not (folder / name).exists()]
    return jobs


def fetch(symbols, workers=16):
    with ThreadPoolExecutor(workers) as pool:
        jobs = [job for found in pool.map(_missing, symbols) for job in found]
        print(f"{len(symbols)} coins; {len(jobs)} files to download", flush=True)
        for done, _ in enumerate(pool.map(_download, jobs), 1):
            if done % 1000 == 0:
                print(f"  {done} downloaded", flush=True)


def _rows(paths):
    for path in sorted(paths):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                yield from (row for row in csv.reader(io.TextIOWrapper(archive.open(name), encoding="utf-8"))
                            if row and row[0].isdigit())


def _day(value):
    seconds = int(value) / 1e6 if int(value) > 1e14 else int(value) / 1e3  # spot files moved to microseconds in 2025
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d")


def spot_daily(symbol):
    """Daily bars as columns: days, open, high, low, close, quote volume (USDT)."""
    rows = {_day(r[0]): tuple(float(r[k]) for k in (1, 2, 3, 4, 7)) for r in _rows((CACHE / "1d").glob(f"{symbol}-1d-*.zip"))}
    days = sorted(rows)
    columns = list(zip(*(rows[d] for d in days), strict=True)) if days else [(), (), (), (), ()]
    return {"days": days, "open": list(columns[0]), "high": list(columns[1]), "low": list(columns[2]),
            "close": list(columns[3]), "volume": list(columns[4])}


def daily_funding(symbol):
    """Mean settled funding rate per UTC day."""
    by_day = {}
    for row in _rows((CACHE / "funding").glob(f"{symbol}-fundingRate-*.zip")):
        by_day.setdefault(_day(row[0]), []).append(float(row[2]))
    return {day: fmean(rates) for day, rates in by_day.items()}


def liquid(volumes):
    """Whether each day's previous 30 days had a median quote volume of at least MIN_VOLUME."""
    return [i >= VOLUME_DAYS and median(volumes[i - VOLUME_DAYS:i]) >= MIN_VOLUME for i in range(len(volumes))]


if __name__ == "__main__":
    if sys.argv[1:] != ["fetch"]:
        raise SystemExit("usage: binance_archive.py fetch")
    fetch(universe())
