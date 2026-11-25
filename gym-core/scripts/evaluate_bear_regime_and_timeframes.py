"""CLI runner for Task 1 (Bear-Regime Discovery & Unified E3_V2 Absorption) and Task 2 (1h & 0.5h Matrix)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gym.services.experiments.bear_regime_and_timeframe_study import (
    run_bear_regime_and_timeframe_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Bear-Regime Discovery (+1%/2%/5% Northstar + 1,085d OOS), Unified E3_V2 Absorption, and 1h/30m Matrix",
    )
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("../evidence/studies/v3-adaptive-engine/bear-regime-and-timeframe-study.md"),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("../evidence/studies/v3-adaptive-engine/bear-regime-and-timeframe-study.json"),
    )
    args = parser.parse_args()
    res = run_bear_regime_and_timeframe_study(args.db, report_md=args.report_md, report_json=args.report_json)
    print(json.dumps({
        "best_absorbed_arm": res["best_absorbed_arm"],
        "task1_bear_majors_standalone": res["task1_bear_majors_standalone"],
        "task1_main_engine_absorption": res["task1_main_engine_absorption"],
        "task2a_1h_gru_oos_auc": res["task2a_1h_gru_oos_auc"],
        "task2a_1h_full_1085d": res["task2a_1h_full_1085d"],
        "task2b_timeframe_fee_vol_barrier": res["task2b_timeframe_fee_vol_barrier"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
