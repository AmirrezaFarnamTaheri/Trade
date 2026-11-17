"""Trial `funding-crowding-filter`: the daily trend rule, standing aside while futures funding shows crowded longs.

Registered in docs/trial-log.md before this script ran. Uses every coin Binance lists with both a USDT perpetual and a
spot pair, from its public data archive (data.binance.vision); every file is checked against its published SHA-256.

    uv run --no-sync python scripts/funding_filter.py fetch      # downloads only files not already cached
    uv run --no-sync python scripts/funding_filter.py run
"""
import argparse
import bisect
import csv
import hashlib
import http.client
import io
import re
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from statistics import fmean, median, pvariance

sys.path.insert(0, str(Path(__file__).resolve().parent))
import long_history_study as study  # noqa: E402
from rule_selector import block_probability, total  # noqa: E402

from gym.domain.performance import _moments, deflated_sharpe  # noqa: E402

ARCHIVE = "https://data.binance.vision"
LISTING = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FUNDING_PREFIX, SPOT_PREFIX = "data/futures/um/monthly/fundingRate/", "data/spot/monthly/klines/"
CACHE = study.CACHE
# Coins whose prices from 2024 on were already scored by earlier trials, directly or through Wallex.
USED_AFTER_SPLIT = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT", "TRXUSDT",
                    "LINKUSDT", "ARBUSDT", "AUSDT", "CAKEUSDT", "COPXONUSDT", "DOTUSDT", "PEPEUSDT", "SHIBUSDT",
                    "SLVONUSDT", "USOONUSDT", "XAUTUSDT"}
CAPS = (0.70, 0.80, 0.90)  # stand aside when 7-day funding is above this share of its trailing year
WINDOW, CROWD_DAYS, HISTORY, COST = 50, 7, 365, 0.002
MIN_VOLUME, VOLUME_DAYS = 5_000_000.0, 30  # median daily quote volume, in USDT, over the previous 30 days
SPLIT, HELD_END = "2024-01-01", "2026-11-01"


def get(url, attempts=5):
    """The archive drops a connection now and then under load; retry with backoff, then give up loudly."""
    for attempt in range(attempts):
        try:
            return study.get(url)
        except (OSError, http.client.HTTPException):
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def listing(prefix):
    """Every key or sub-folder name directly under an archive prefix."""
    names, marker = [], ""
    while True:
        url = f"{LISTING}?delimiter=/&prefix={prefix}" + (f"&marker={marker}" if marker else "")
        text = get(url).decode()
        found = re.findall(r"<Prefix>([^<]+)</Prefix>", text)[1:] + re.findall(r"<Key>([^<]+)</Key>", text)
        names += found
        if "<IsTruncated>true" not in text or not found:
            return [name.rstrip("/").rsplit("/", 1)[1] for name in names]
        marker = found[-1]


def universe():
    """USDT perpetuals that also trade spot against USDT."""
    perpetuals = {s for s in listing(FUNDING_PREFIX) if s.endswith("USDT")}
    return sorted(perpetuals & set(listing(SPOT_PREFIX)))


def download(job):
    url, path = job
    body, expected = get(url), get(url + ".CHECKSUM").split()[0].decode()
    if hashlib.sha256(body).hexdigest() != expected:
        raise SystemExit(f"checksum mismatch for {path.name}; file not kept")
    part = path.with_suffix(".part")
    part.write_bytes(body)
    part.replace(path)


def fetch(symbols, workers=16):
    jobs = []
    for symbol in symbols:
        for prefix, folder, suffix in ((f"{FUNDING_PREFIX}{symbol}/", CACHE / "funding", ""),
                                       (f"{SPOT_PREFIX}{symbol}/1d/", CACHE / "1d", "/1d")):
            folder.mkdir(parents=True, exist_ok=True)
            for name in listing(prefix):
                if name.endswith(".zip") and not (folder / name).exists():
                    base = FUNDING_PREFIX if not suffix else SPOT_PREFIX
                    jobs.append((f"{ARCHIVE}/{base}{symbol}{suffix}/{name}", folder / name))
    print(f"{len(symbols)} coins; {len(jobs)} files to download")
    with ThreadPoolExecutor(workers) as pool:
        for done, _ in enumerate(pool.map(download, jobs), 1):
            if done % 1000 == 0:
                print(f"  {done} downloaded")


def read_rows(paths):
    for path in sorted(paths):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                yield from (row for row in csv.reader(io.TextIOWrapper(archive.open(name), encoding="utf-8"))
                            if row and row[0].isdigit())


def stamp_day(value):
    seconds = int(value) / 1e6 if int(value) > 1e14 else int(value) / 1e3  # spot files moved to microseconds in 2025
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d")


def spot_daily(symbol):
    """(days, closes, quote volumes) from cached spot daily candles."""
    rows = {stamp_day(r[0]): (float(r[4]), float(r[7])) for r in read_rows((CACHE / "1d").glob(f"{symbol}-1d-*.zip"))}
    days = sorted(rows)
    return days, [rows[d][0] for d in days], [rows[d][1] for d in days]


def daily_funding(symbol):
    """Mean settled funding rate per UTC day."""
    by_day = {}
    for row in read_rows((CACHE / "funding").glob(f"{symbol}-fundingRate-*.zip")):
        by_day.setdefault(stamp_day(row[0]), []).append(float(row[2]))
    return {day: fmean(rates) for day, rates in by_day.items()}


def crowded(days, funding, cap):
    """True when the trailing 7-day mean funding is in the top (1 - cap) of its trailing 365 days; None until known.

    Uses only funding settled on or before each day.
    """
    known = sorted(funding)
    means, out = [], []
    for day in days:
        i = bisect.bisect_right(known, day)
        recent = [funding[d] for d in known[max(0, i - CROWD_DAYS):i]]
        if len(recent) < CROWD_DAYS:
            out.append(None)
            continue
        level = fmean(recent)
        means.append(level)
        past = means[-HISTORY - 1:-1]
        out.append(None if len(past) < HISTORY else sum(x < level for x in past) / len(past) >= cap)
    return out


def liquid(volumes):
    """Whether each day's previous 30 days had a median quote volume of at least MIN_VOLUME."""
    return [i >= VOLUME_DAYS and median(volumes[i - VOLUME_DAYS:i]) >= MIN_VOLUME for i in range(len(volumes))]


def returns(days, closes, flags, eligible=None):
    """Daily (day, return): long when above the 50-day average and not crowded, decided at the close.

    A day counts only when the filter is known and the coin is liquid; an open position is closed (and charged) on
    the first day the coin stops counting.
    """
    out, held = [], 0.0
    for i in range(WINDOW - 1, len(closes) - 1):
        usable = (flags is None or flags[i] is not None) and (eligible is None or eligible[i])
        if not usable:
            if held:
                out.append((days[i + 1], -COST))
                held = 0.0
            continue
        want = float(closes[i] > fmean(closes[i - WINDOW + 1:i + 1]) and not (flags and flags[i]))
        out.append((days[i + 1], want * (closes[i + 1] / closes[i] - 1) - COST * abs(want - held)))
        held = want
    return out


def pooled(source, funding, cap, lo, hi, *, gate=None):
    """Equal-weight daily mean across counted coins; `gate` limits the unfiltered rule to the coin-days the filter counted."""
    by_day, used = {}, set()
    for coin, (days, closes, volumes) in source.items():
        flags = crowded(days, funding[coin], cap) if cap is not None else None
        for day, r in returns(days, closes, flags, liquid(volumes)):
            if lo <= day < hi and (gate is None or (coin, day) in gate):
                by_day.setdefault(day, []).append(r)
                used.add((coin, day))
    return {day: fmean(v) for day, v in sorted(by_day.items())}, used


def compare(source, funding, cap, lo, hi):
    filtered, used = pooled(source, funding, cap, lo, hi)
    plain, _ = pooled(source, funding, None, lo, hi, gate=set(used))
    return list(filtered.values()), list(plain.values()), len({coin for coin, _ in used})


def verdict(rank_source, held_source, funding) -> bool:
    cells = []
    for cap in CAPS:
        values, plain, coins = compare(rank_source, funding, cap, "2000", SPLIT)
        mean, deviation, skew, kurtosis = _moments(values)
        pm, pd, _, _ = _moments(plain)
        cells.append({"cap": cap, "values": values, "coins": coins, "moments": (skew, kurtosis),
                      "sharpe": mean / deviation if deviation else 0.0, "plain_sharpe": pm / pd if pd else 0.0,
                      "plain_total": total(plain)})
    variance = pvariance([c["sharpe"] for c in cells])
    print(f"funding-crowding-filter ranked before {SPLIT} on {len(rank_source)} coins; {100 * COST:.2f}% per side")
    for c in cells:
        c["deflated"] = deflated_sharpe(c["sharpe"], len(c["values"]), *c["moments"], len(cells), variance) or 0.0
        print(f"  stand aside above {100 * c['cap']:.0f}%: {c['coins']} coins, {len(c['values'])} days, total {100 * total(c['values']):8.1f}% "
              f"(unfiltered {100 * c['plain_total']:8.1f}%), yearly Sharpe {c['sharpe'] * sqrt(365):5.2f} "
              f"(unfiltered {c['plain_sharpe'] * sqrt(365):5.2f}), deflated {c['deflated']:.3f}")
    best = max(cells, key=lambda c: c["deflated"])
    if best["deflated"] < 0.95 or best["sharpe"] <= best["plain_sharpe"]:
        print(f"funding-crowding-filter FAIL on ranking days (best cap {best['cap']}, deflated {best['deflated']:.3f}, "
              f"{'above' if best['sharpe'] > best['plain_sharpe'] else 'not above'} the unfiltered rule); held-out coins not scored")
        return False
    values, plain, coins = compare(held_source, funding, best["cap"], SPLIT, HELD_END)
    mean, deviation, _, _ = _moments(values)
    pm, pd, _, _ = _moments(plain)
    chance = block_probability(values)
    passed = chance >= 0.90 and mean / deviation > pm / pd
    print(f"  held out, cap {best['cap']}: {coins} coins, {len(values)} days, total {100 * total(values):.1f}% "
          f"(unfiltered {100 * total(plain):.1f}%), yearly Sharpe {mean / deviation * sqrt(365):.2f} "
          f"(unfiltered {pm / pd * sqrt(365):.2f}), block-bootstrap probability {chance:.3f}")
    print(f"funding-crowding-filter verdict: {'PASS' if passed else 'FAIL'}")
    return passed


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    parser.add_argument("action", choices=("fetch", "run"))
    args = parser.parse_args(argv)
    coins = universe()
    if args.action == "fetch":
        fetch(coins)
        return 0
    data = {coin: spot_daily(coin) for coin in coins}
    data = {coin: series for coin, series in data.items() if len(series[0]) > WINDOW + HISTORY}
    funding = {coin: daily_funding(coin) for coin in data}
    held = {coin: series for coin, series in data.items() if coin not in USED_AFTER_SPLIT}
    verdict(data, held, funding)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
