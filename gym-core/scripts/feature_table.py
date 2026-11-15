"""Build the causal daily feature table for the meta-labeling work from verified Binance daily candles.

One row per symbol and day. Every feature at day t uses closes up to and including t; the label is the forward
`--horizon`-day return minus a round-trip cost, which no feature may see. Research data preparation only: nothing
here fits a model. A fit is registered in docs/trial-log.md before it runs (PRODUCT.md).

Run from gym-core, after `long_history_study.py fetch SYMBOLS --interval 1d`:
    uv run --no-sync python scripts/feature_table.py BTCUSDT ETHUSDT ... [--horizon 5] [--cost 0.004]
        [--out ../data/research/features_1d.csv]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import sys
from itertools import pairwise
from pathlib import Path

spec = importlib.util.spec_from_file_location("long_history_study", Path(__file__).with_name("long_history_study.py"))
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)

WARMUP = 200  # days before the first emitted row, so every feature is fully formed

FEATURES = ("ret_1d", "ret_5d", "ret_20d", "sma20_gap", "sma50_gap", "sma200_gap",
            "vol20", "vol60", "vol_ratio", "dd_from_high_200", "range_pos_20")


def rows_for(symbol: str, days: list[str], closes: list[float], *, horizon: int, cost: float) -> list[dict]:
    """Feature rows with labels; the last `horizon` days are emitted with an empty label, never a guessed one."""
    if len({len(days), len(closes)}) != 1:
        raise ValueError("days and closes differ in length")
    logs = [math.log(b / a) for a, b in pairwise(closes)]
    out = []
    for t in range(WARMUP, len(closes)):
        close = closes[t]
        sma = {n: sum(closes[t - n + 1:t + 1]) / n for n in (20, 50, 200)}
        vol = {n: math.sqrt(sum(x * x for x in logs[t - n:t]) / n * 365) for n in (20, 60)}
        high = max(closes[t - 199:t + 1])
        low20, high20 = min(closes[t - 19:t + 1]), max(closes[t - 19:t + 1])
        row = {"symbol": symbol, "day": days[t][:10],
               "ret_1d": close / closes[t - 1] - 1, "ret_5d": close / closes[t - 5] - 1,
               "ret_20d": close / closes[t - 20] - 1,
               "sma20_gap": close / sma[20] - 1, "sma50_gap": close / sma[50] - 1,
               "sma200_gap": close / sma[200] - 1,
               "vol20": vol[20], "vol60": vol[60], "vol_ratio": vol[20] / vol[60] if vol[60] else 1.0,
               "dd_from_high_200": close / high - 1,
               "range_pos_20": (close - low20) / (high20 - low20) if high20 > low20 else 0.5}
        if t + horizon < len(closes):
            net = closes[t + horizon] / close - 1 - cost
            row["label_net_fwd"] = net
            row["label_win"] = int(net > 0)
        else:
            row["label_net_fwd"] = row["label_win"] = ""
        out.append(row)
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--horizon", type=int, default=5, help="label: net return this many days forward")
    parser.add_argument("--cost", type=float, default=0.004, help="round-trip cost subtracted from the label")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "data/research/features_1d.csv")
    parser.add_argument("--cache", type=Path, default=study.CACHE)
    args = parser.parse_args(argv)
    if not 1 <= args.horizon <= 60 or not 0 <= args.cost < 0.1:
        parser.error("--horizon must be 1..60 and --cost in [0, 0.1)")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with args.out.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, ["symbol", "day", *FEATURES, "label_net_fwd", "label_win"])
        writer.writeheader()
        for symbol in args.symbols:
            days, closes = study.load(symbol.upper(), "1d", args.cache)
            rows = rows_for(symbol.upper(), days, closes, horizon=args.horizon, cost=args.cost)
            writer.writerows(rows)
            total += len(rows)
            print(f"{symbol.upper()}: {len(rows)} rows ({days[WARMUP][:10]} .. {days[-1][:10]})", file=sys.stderr)
    print(f"{total} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
