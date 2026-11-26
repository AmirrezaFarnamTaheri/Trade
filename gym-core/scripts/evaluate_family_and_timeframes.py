"""CLI runner for 2h/3h/6h crash breakers, family-differentiated 18/33-asset cores, and rare 1h/2h/3h ignition."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.family_and_timeframe_study import (
    run_family_and_timeframe_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multi-timeframe & family-differentiated research study")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../evidence/studies/core-ensemble/family-and-timeframes.md"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("../evidence/studies/core-ensemble/family-and-timeframes.json"),
    )
    args = parser.parse_args()
    summary = run_family_and_timeframe_study(args.db, args.report, args.receipt)
    print(json.dumps({"arms": len(summary["portfolio_arms"]), "ignition": len(summary["ignition_sleeves"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
