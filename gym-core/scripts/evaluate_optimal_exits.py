"""CLI runner for the Optimal Position-Closing & Exit-Timing Study (E1-E4)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gym.services.experiments.optimal_exit_study import run_optimal_exit_study


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate optimal position-closing mechanisms E1-E4 head-to-head")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("../evidence/studies/execution-and-venues/optimal-position-closing.md"),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("../evidence/studies/execution-and-venues/optimal-position-closing.json"),
    )
    args = parser.parse_args()
    res = run_optimal_exit_study(args.db, report_md=args.report_md, report_json=args.report_json)
    print(json.dumps({
        "v2_reference": res["v2_reference"],
        "best_arm": res["best_arm"],
        "arms": res["arms"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
