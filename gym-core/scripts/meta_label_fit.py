"""Trial logistic-entry-gate of docs/trial-log.md, run exactly as registered: does a logistic gate on the daily feature table
beat taking every proposal, net of costs, on days it never saw?

The "proposal" is the simplest base: every symbol-day is a candidate 5-day hold. The model may only gate
(veto or rank); it sizes nothing and places nothing. Fit and every selection choice use days before the split;
the later days are scored once. Pass needs all three registered marks:

  1. gated mean net return beats the ungated mean on the scored days;
  2. calibration honest: |predicted - observed win rate| <= 0.10 in every populated decile, >= 5 populated;
  3. the gated mean's lower 95% confidence bound is above zero.

Research only (PRODUCT.md 2026-11-14): needs `uv sync --group research`. Deterministic: no sampling, fixed solver.
Every gated decision row is written out as a decision receipt.

Run from gym-core:
    uv run --no-sync python scripts/meta_label_fit.py [--table ../data/research/features_1d.csv]
        [--split 2025-01-01] [--receipts ../data/research/meta-label-receipts.csv]
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sklearn.calibration import CalibratedClassifierCV

FEATURES = ("ret_1d", "ret_5d", "ret_20d", "sma20_gap", "sma50_gap", "sma200_gap",
            "vol20", "vol60", "vol_ratio", "dd_from_high_200", "range_pos_20")
THRESHOLD = 0.5  # fixed before scoring: the gate takes a day only when the calibrated win probability exceeds it
HORIZON = 5
Sample = tuple[list[float], int, float, str, str, str]


def load(table: Path, split: str) -> tuple[list[Sample], list[Sample]]:
    """Purge five-close labels reaching the split; include the unlabeled tail for dates."""
    split = date.fromisoformat(split).isoformat()
    with table.open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    symbols = defaultdict(list)
    for row in rows:
        row["day"] = date.fromisoformat(row["day"]).isoformat()
        symbols[row["symbol"]].append(row)
    train, held = [], []
    for symbol_rows in symbols.values():
        days = [row["day"] for row in symbol_rows]
        if days != sorted(set(days)):
            raise ValueError("feature dates must be unique and ordered per symbol")
        if any(row["label_net_fwd"] == "" for row in symbol_rows[:-HORIZON]) or any(
                row["label_net_fwd"] != "" for row in symbol_rows[-HORIZON:]):
            raise ValueError("fixed five-close labels need a complete five-row unlabeled tail")
        for index, row in enumerate(symbol_rows):
            if row["label_net_fwd"] == "":
                continue
            label_end = days[index + HORIZON]
            parsed = ([float(row[name]) for name in FEATURES], int(row["label_win"]), float(row["label_net_fwd"]),
                      row["symbol"], row["day"], label_end)
            if label_end < split:
                train.append(parsed)
            elif row["day"] >= split:
                held.append(parsed)
    train.sort(key=lambda row: (row[4], row[3]))
    held.sort(key=lambda row: (row[4], row[3]))
    return train, held


def calibration_folds(train: list[Sample]) -> list[tuple[list[int], list[int]]]:
    """Five expanding date folds; every training label ends before calibration starts."""
    days = sorted({row[4] for row in train})
    width = len(days) // 6
    if width == 0:
        raise ValueError("need at least six distinct training days for calibration")
    folds = []
    for fold in range(1, 6):
        first = days[fold * width]
        last = days[(fold + 1) * width] if fold < 5 else None
        trained = [index for index, row in enumerate(train) if row[5] < first]
        validated = [index for index, row in enumerate(train) if row[4] >= first and (last is None or row[4] < last)]
        if not trained or not validated:
            raise ValueError("not enough non-overlapping label history for calibration")
        folds.append((trained, validated))
    return folds


def fit_model(train: list[Sample]) -> CalibratedClassifierCV:
    """Fit scaling, classification and calibration within purged chronological folds."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    classifier = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=1000))
    model = CalibratedClassifierCV(classifier, method="isotonic", cv=calibration_folds(train))
    model.fit([row[0] for row in train], [row[1] for row in train])
    return model


def honest_deciles(pairs: list[tuple[float, int]], width: float = 0.10, need: int = 5):
    """(ok, table): per probability decile, |mean predicted - observed win rate|; empty deciles do not count."""
    table = []
    for decile in range(10):
        inside = [(p, y) for p, y in pairs if decile / 10 <= p < (decile + 1) / 10 or (decile == 9 and p == 1.0)]
        if len(inside) >= 30:  # fewer rows cannot measure a rate to within the 10-point width
            predicted = sum(p for p, _ in inside) / len(inside)
            observed = sum(y for _, y in inside) / len(inside)
            table.append((decile, len(inside), predicted, observed))
    ok = len(table) >= need and all(abs(p - o) <= width for _, _, p, o in table)
    return ok, table


def mean_lcb(values: list[float]):
    """Mean and its one-sided 95% lower confidence bound (normal approximation; returns are overlapping,
    so this understates the variance -- stated as a limit, not hidden)."""
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    return mean, mean - 1.645 * sd / math.sqrt(n)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--table", type=Path, default=Path(__file__).resolve().parents[2] / "data/research/features_1d.csv")
    parser.add_argument("--split", default="2025-01-01")
    parser.add_argument("--receipts", type=Path, default=Path(__file__).resolve().parents[2] / "data/research/meta-label-receipts.csv")
    args = parser.parse_args(argv)
    if args.receipts.exists():
        parser.error("receipt file already exists; historical decisions cannot be overwritten")
    train, held = load(args.table, args.split)
    if len(train) < 1000 or len(held) < 100:
        print(f"not enough rows (train {len(train)}, held {len(held)})")
        return 1
    model = fit_model(train)

    probabilities = model.predict_proba([x for x, *_ in held])[:, 1]
    rows = [(float(p), y, net, symbol, day) for p, (_, y, net, symbol, day, _) in zip(probabilities, held, strict=True)]
    gated = [r for r in rows if r[0] > THRESHOLD]
    ungated_mean, _ = mean_lcb([net for _, _, net, _, _ in rows])
    gated_mean, gated_lcb = mean_lcb([net for _, _, net, _, _ in gated]) if gated else (0.0, 0.0)
    calibration_ok, deciles = honest_deciles([(p, y) for p, y, *_ in rows])

    args.receipts.parent.mkdir(parents=True, exist_ok=True)
    with args.receipts.open("x", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["day", "symbol", "p_win", "decision", "label_net_fwd"])
        writer.writerows((day, symbol, f"{p:.4f}", "TAKE" if p > THRESHOLD else "ABSTAIN", net)
                         for p, _, net, symbol, day in rows)

    print(f"logistic-entry-gate: fit on {len(train)} rows before {args.split}; scored once on {len(held)} rows; "
          f"gate p > {THRESHOLD}; receipts -> {args.receipts}")
    print("decile  n     predicted  observed")
    for decile, count, predicted, observed in deciles:
        print(f"  {decile}    {count:6}   {predicted:.3f}      {observed:.3f}")
    print(f"ungated: n {len(rows)}, mean net {100 * ungated_mean:.3f}%")
    print(f"gated:   n {len(gated)}, mean net {100 * gated_mean:.3f}%, lower 95% bound {100 * gated_lcb:.3f}%")
    marks = {"gated_beats_ungated": gated_mean > ungated_mean, "calibration_honest": calibration_ok,
             "gated_lcb_above_zero": gated_lcb > 0}
    for name, passed in marks.items():
        print(f"{name}: {'pass' if passed else 'FAIL'}")
    print("overlapping 5-day labels understate the confidence-bound variance; the bound is optimistic")
    print(f"logistic-entry-gate VERDICT: {'PASS' if all(marks.values()) else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
