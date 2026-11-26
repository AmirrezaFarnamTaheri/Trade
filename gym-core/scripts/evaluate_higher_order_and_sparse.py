"""CLI runner for the 4-part Higher-Order Momentum, Tiered Sparse Expansion, Sleeve Weighting & Structural Bear Short study."""
from __future__ import annotations

import argparse
from pathlib import Path

from gym.services.experiments.higher_order_and_sparse_study import (
    run_higher_order_and_sparse_study,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 4-part higher-order momentum, sparse expansion, risk-parity & structural short study")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--report", type=Path, default=Path("../evidence/studies/core-ensemble/higher-order-and-sparse.md"))
    parser.add_argument("--receipt", type=Path, default=Path("../evidence/studies/core-ensemble/higher-order-and-sparse.json"))
    args = parser.parse_args()
    res = run_higher_order_and_sparse_study(args.db, args.report, args.receipt)
    print(f"Wrote {args.report} and {args.receipt}")
    p1b = res["part_1b_gru_ignition_second_order"]
    print("1B AUC 6-feat vs 8-feat:", p1b["gru_6feat_baseline"]["oos_roc_auc"], "vs", p1b["gru_8feat_second_order"]["oos_roc_auc"])
    print("Part 2 rows:", len(res["part_2_tiered_sparse_38"]), "Part 3 rows:", len(res["part_3_sleeve_weighting"]), "Part 4 rows:", len(res["part_4_structural_breakdown_short"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
