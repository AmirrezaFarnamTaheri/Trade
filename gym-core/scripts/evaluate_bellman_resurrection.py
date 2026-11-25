"""CLI runner for the Bellman Optimal-Stopping V2 & Defeated-Strategy Resurrection Study."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gym.services.experiments.bellman_resurrection_study import (
    run_bellman_resurrection_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Nonlinear Bellman Stopping V2 & Defeated-Strategy Resurrection")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("../evidence/studies/execution-and-venues/bellman-stopping-and-resurrection.md"),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("../evidence/studies/execution-and-venues/bellman-stopping-and-resurrection.json"),
    )
    args = parser.parse_args()
    res = run_bellman_resurrection_study(args.db, report_md=args.report_md, report_json=args.report_json)
    print(json.dumps({
        "v2_reference": res["v2_reference"],
        "best_arm": res["best_arm"],
        "part1_and_3_portfolio_arms": res["part1_and_3_portfolio_arms"],
        "part2_resurrection_ablation": res["part2_resurrection_ablation"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
