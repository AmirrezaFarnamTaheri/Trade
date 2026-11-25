"""CLI runner for Track I Core Engine Ablations (#1 Amended, #7, #8, #11A)."""
from __future__ import annotations

import argparse
from pathlib import Path

from gym.services.experiments.core_engine_ablation_study import (
    run_core_engine_ablation_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Track I 1d Core Engine ablations")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--report", type=Path, default=Path("../evidence/studies/core-ensemble/core-engine-ablation.md"))
    parser.add_argument("--receipt", type=Path, default=Path("../evidence/studies/core-ensemble/core-engine-ablation.json"))
    args = parser.parse_args()
    res = run_core_engine_ablation_study(args.db, args.report, args.receipt)
    print(f"Wrote {args.report} ({len(res['arms'])} arms)")
    for r in res["arms"]:
        print(f"  {r['label']:28s} NAV=${r['full']['ending_nav']:7.2f} SR={r['full']['ann_sharpe']:.3f} DD={r['full']['max_dd_pct']:5.2f}% Bear={r['stress']['ret_pct']:+6.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
