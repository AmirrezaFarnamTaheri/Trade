"""CLI runner for 3-part validation: ignition spread stress, 70/30 shared-ledger blend, and true intraday 3h exit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.ignition_validation_study import (
    run_ignition_validation_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 3-part ignition & true intraday 3h exit validation")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../evidence/2026-11-24-ignition-validation-report.md"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("../evidence/2026-11-24-ignition-validation.json"),
    )
    args = parser.parse_args()
    summary = run_ignition_validation_study(args.db, args.report, args.receipt)
    print(json.dumps(summary["correlation_s1s5_vs_ignition1h"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
