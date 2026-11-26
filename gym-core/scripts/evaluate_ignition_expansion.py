"""CLI runner for 18-market ignition expansion, 2h shared-ledger blends, and 15m/30m sub-hourly probe."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.ignition_expansion_study import (
    run_ignition_expansion_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 18-market & sub-hourly ignition expansion study")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../evidence/studies/ignition-and-ml/ignition-expansion.md"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("../evidence/studies/ignition-and-ml/ignition-expansion.json"),
    )
    args = parser.parse_args()
    summary = run_ignition_expansion_study(args.db, args.report, args.receipt)
    print(json.dumps({"corr_2h": summary["corr_s1s5_vs_ign18_2h"], "subhourly": len(summary["part_c_subhourly_15m_30m_25d_probe"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
