"""CLI runner for the 6-Finding Multi-Horizon Adaptive Portfolio & Execution Ablation Study."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gym.services.experiments.multi_horizon_adaptive_study import (
    run_multi_horizon_adaptive_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate all 6 structural fixes (F1-F6) head-to-head vs V2_CHAMPION")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("../evidence/studies/v3-adaptive-engine/multi-horizon-adaptive-engine.md"),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("../evidence/studies/v3-adaptive-engine/multi-horizon-adaptive-engine.json"),
    )
    args = parser.parse_args()
    res = run_multi_horizon_adaptive_study(args.db, report_md=args.report_md, report_json=args.report_json)
    print(json.dumps({
        "v2_reference": res["v2_reference"],
        "best_arm": res["best_arm"],
        "ablation_arms": res["ablation_arms"],
        "live_audits_summary": {
            "tightest_hour": res["live_audits"]["tehran_clock"]["tightest_hour"],
            "widest_hour": res["live_audits"]["tehran_clock"]["widest_hour"],
            "tmn_triangle_routing": res["live_audits"]["tmn_triangle_routing"],
            "dynamic_borrow_currency": res["live_audits"]["dynamic_borrow_currency"],
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
