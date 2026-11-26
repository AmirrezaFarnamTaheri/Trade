"""CLI runner for Standing Leader Deep-Dive (S2 hysteresis, factor/2x2 attribution, causal execution)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.leader_deep_dive import run_leader_deep_dive


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Standing Leader Deep-Dive studies")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../evidence/studies/core-ensemble/leader-deep-dive.md"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("../evidence/studies/core-ensemble/leader-deep-dive.json"),
    )
    args = parser.parse_args()
    summary = run_leader_deep_dive(args.db, args.report, args.receipt)
    print(json.dumps({"eval_days": summary["eval_days"], "study_a_keys": list(summary["study_a_s2_hysteresis"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
