"""CLI runner for all 3 strictly causal walk-forward GRU prototypes (GRU-Vol, GRU-Ignition, GRU-Exec)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.gru_prototypes_study import run_gru_prototypes_study


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate GRU-Vol, GRU-Ignition, and GRU-Exec prototypes")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../evidence/studies/ignition-and-ml/gru-prototypes.md"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("../evidence/studies/ignition-and-ml/gru-prototypes.json"),
    )
    args = parser.parse_args()
    summary = run_gru_prototypes_study(args.db, args.report, args.receipt)
    print(
        json.dumps(
            {
                "gru_vol_r2": summary["prototype_1_gru_vol"]["r2_gru_vol"],
                "gru_ign_auc": summary["prototype_2_gru_ignition"]["oos_roc_auc"],
                "gru_exec_auc": summary["prototype_3_gru_exec"].get("oos_5m_direction_auc"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
