"""CLI runner for the 4-way v3 Dynamic Per-Moment Instrument Resolver head-to-head study."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gym.services.experiments.dynamic_resolver_study import run_dynamic_resolver_study


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate all 4 v3 Dynamic Per-Moment Instrument Resolvers head-to-head")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report-md",
        type=Path,
        default=Path("../evidence/studies/v3-adaptive-engine/dynamic-instrument-resolver.md"),
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=Path("../evidence/studies/v3-adaptive-engine/dynamic-instrument-resolver.json"),
    )
    args = parser.parse_args()
    res = run_dynamic_resolver_study(args.db, report_md=args.report_md, report_json=args.report_json)
    print(json.dumps({
        "v2_reference": res["v2_reference"],
        "best_local_arm": res["best_local_arm"],
        "local_5x_summary": [
            {k: r[k] for k in ("label", "ending_nav", "ret_pct", "stress_ret_pct", "ann_sharpe", "max_dd_pct", "liquidations_sum", "max_leverage_used", "vs_v2_bps")}
            for r in res["local_5x_arms"]
        ],
        "local_2x_summary": [
            {k: r[k] for k in ("label", "ending_nav", "ret_pct", "stress_ret_pct", "ann_sharpe", "max_dd_pct", "liquidations_sum", "max_leverage_used", "vs_v2_bps")}
            for r in res["local_2x_arms"]
        ],
        "perp_ready_summary": [
            {k: r[k] for k in ("label", "ending_nav", "ret_pct", "stress_ret_pct", "ann_sharpe", "max_dd_pct", "liquidations_sum", "perp_short_entries_avg", "funding_net_usdt_avg")}
            for r in res["perp_plugin_readiness_arms"]
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
