"""Score prespecified paired portfolio blocks with explicit valuation coverage."""
import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from gym.domain.model import parse_ts
from gym.domain.statistical_inference import paired_baseline_uplift


def score(blocks, *, threshold_bps, block_length, seed):
    if block_length < 1 or not threshold_bps.is_finite():
        raise ValueError("invalid paired study parameters")
    strategy, benchmark, receipts = {}, {}, []
    previous_end, duration, contiguous = None, None, True
    for row in blocks:
        start, end = map(parse_ts, (row["from"], row["to"]))
        if start >= end or (previous_end is not None and start < previous_end):
            raise ValueError("blocks must be ordered, nonempty and disjoint")
        if duration is None:
            duration = end - start
        contiguous &= (previous_end is None or start == previous_end) and end - start == duration
        previous_end = end
        status = "SCORED" if row["candidate_status"] == row["benchmark_status"] == "CURRENT" else "UNSCORED_VALUATION"
        a, b = (Decimal(row[key]) if row.get(key) is not None else None for key in ("candidate_bps", "benchmark_bps"))
        if any(value is not None and not value.is_finite() for value in (a, b)):
            raise ValueError("paired returns must be finite when supplied")
        if status == "SCORED":
            if a is None or b is None:
                raise ValueError("current paired valuations require two finite returns")
            strategy[start.isoformat()], benchmark[start.isoformat()] = float(a), float(b)
        receipts.append({**row, "status": status, "marked_difference_bps": str(a - b) if a is not None and b is not None else None})
    counts = dict(Counter(row["status"] for row in receipts))
    complete = contiguous and len(strategy) == len(blocks)
    inference = (paired_baseline_uplift(strategy, benchmark, min_detectable_effect=float(threshold_bps),
                                       block_length=block_length, seed=seed) if complete else
                 {"status": "INCOMPLETE_CALENDAR_OR_VALUATION", "independent_final_evidence": False})
    verdict = inference["status"] if inference["status"] in {"BELOW_THRESHOLD", "POSITIVE_EXPLORATORY"} else "INCONCLUSIVE"
    return {"schema": "paired-research-blocks/1", "verdict": verdict, "counts": counts, "inference": inference,
            "threshold_bps": str(threshold_bps), "blocks": receipts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("blocks", type=Path)
    parser.add_argument("--threshold-bps", required=True, type=Decimal)
    parser.add_argument("--block-length", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    args = parser.parse_args()
    blocks = json.loads(args.blocks.read_text(encoding="utf-8"))
    print(json.dumps(score(blocks, threshold_bps=args.threshold_bps, block_length=args.block_length, seed=args.seed),
                     indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
