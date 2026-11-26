"""CLI runner for rare 2h short-ignition, event-scoped levered long-ignition, and 3-engine blends."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.short_and_leverage_study import (
    run_short_and_leverage_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate 2h short-ignition and event-scoped leverage")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../evidence/studies/ignition-and-ml/short-and-leverage.md"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("../evidence/studies/ignition-and-ml/short-and-leverage.json"),
    )
    args = parser.parse_args()
    summary = run_short_and_leverage_study(args.db, args.report, args.receipt)
    print(json.dumps(summary["correlations"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
