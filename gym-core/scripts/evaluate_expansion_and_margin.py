"""CLI runner for Experiments A, B, and C (33-market expansion, ML tilt + 4h exit, paper margin)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.expansion_and_margin_study import (
    run_expansion_and_margin_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Experiments A, B, and C paper evaluation")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../evidence/studies/core-ensemble/expansion-and-margin.md"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("../evidence/studies/core-ensemble/expansion-and-margin.json"),
    )
    args = parser.parse_args()
    summary = run_expansion_and_margin_study(args.db, args.report, args.receipt)
    print(json.dumps({"eval_days": summary["eval_days"], "arms": len(summary["spot_and_overlay_arms"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
