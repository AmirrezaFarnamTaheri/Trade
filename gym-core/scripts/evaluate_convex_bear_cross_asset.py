"""CLI runner for the Convex Cross-Asset Bear Short (+3%/1d, +5%/3d, +15%/7d) & Unified E3_V2 Absorption Study."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gym.services.experiments.convex_bear_cross_asset_study import (
    run_convex_bear_cross_asset_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate CTA Vol-Targeted Cross-Asset Bear Short (M4 + Gold XAUT) & Unified E3_V2 Absorption",
    )
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("../evidence/studies/v3-adaptive-engine/convex-bear-cross-asset-study.md"),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("../evidence/studies/v3-adaptive-engine/convex-bear-cross-asset-study.json"),
    )
    args = parser.parse_args()
    res = run_convex_bear_cross_asset_study(args.db, report_md=args.report_md, report_json=args.report_json)
    print(json.dumps({
        "best_sharpe_unified_arm": res["best_sharpe_unified_arm"],
        "best_northstar_hit_unified_arm": res["best_northstar_hit_unified_arm"],
        "standalone_cta_bear_benchmarks": res["standalone_cta_bear_benchmarks"],
        "unified_main_engine_absorption": res["unified_main_engine_absorption"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
