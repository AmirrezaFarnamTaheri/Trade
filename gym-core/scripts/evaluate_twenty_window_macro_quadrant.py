"""CLI runner for the 20 Least-Correlated 7-Day Windows & 4-Quadrant Macro Unified E3_V2 Enhancement Study."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gym.services.experiments.twenty_window_macro_quadrant_study import (
    run_twenty_window_macro_quadrant_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run 20 Least-Correlated 7-Day Windows Benchmark & 4-Quadrant Macro Unified E3_V2 Study",
    )
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("../evidence/studies/v3-adaptive-engine/twenty-window-macro-quadrant-study.md"),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("../evidence/studies/v3-adaptive-engine/twenty-window-macro-quadrant-study.json"),
    )
    args = parser.parse_args()
    res = run_twenty_window_macro_quadrant_study(args.db, report_md=args.report_md, report_json=args.report_json)
    print(json.dumps({
        "window_selection": res["window_selection"],
        "best_sharpe_unified": {k: v for k, v in res["best_sharpe_unified"].items() if k != "w20"} | {"w20_summary": {k: v for k, v in res["best_sharpe_unified"]["w20"].items() if k != "per_window"}},
        "best_return_unified": {k: v for k, v in res["best_return_unified"].items() if k != "w20"} | {"w20_summary": {k: v for k, v in res["best_return_unified"]["w20"].items() if k != "per_window"}},
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
