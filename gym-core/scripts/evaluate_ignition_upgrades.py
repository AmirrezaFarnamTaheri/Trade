"""CLI runner for Track II 2h Ignition & GRU Upgrade Ablations."""
from __future__ import annotations

import argparse
from pathlib import Path

from gym.services.experiments.ignition_upgrade_ablation_study import (
    run_ignition_upgrade_ablation_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Track II 2h Ignition & GRU upgrade ablations")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--report", type=Path, default=Path("../evidence/2026-11-25-ignition-upgrade-ablation-report.md"))
    parser.add_argument("--receipt", type=Path, default=Path("../evidence/2026-11-25-ignition-upgrade-ablation.json"))
    args = parser.parse_args()
    res = run_ignition_upgrade_ablation_study(args.db, args.report, args.receipt)
    print(f"Wrote {args.report} | AUC:", res["gru_model_auc"])
    for r in res["ablation_arms"][:10]:
        print(f"  {r['label']:34s} NAV=${r['ending_nav']:7.2f} SR={r['ann_sharpe']:.3f} DD={r['max_dd_pct']:5.2f}% Bear={r['stress_ret_pct']:+6.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
