"""CLI entrypoint for the Orthogonal Alpha Study (3A: Flush Rebound & Dead-Cat Short, 3B: Cov-Only GRU-Vol, 3C: PAXG & Macro)."""
from __future__ import annotations

import argparse
from pathlib import Path

from gym.services.experiments.orthogonal_alpha_study import run_orthogonal_alpha_study


def main() -> int:
    parser = argparse.ArgumentParser(description="Run orthogonal alpha study (3A + 3B + 3C)")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--report", type=Path, default=Path("../evidence/studies/core-ensemble/orthogonal-alpha.md"))
    parser.add_argument("--receipt", type=Path, default=Path("../evidence/studies/core-ensemble/orthogonal-alpha.json"))
    args = parser.parse_args()
    res = run_orthogonal_alpha_study(args.db, args.report, args.receipt)
    print(f"Wrote {args.report} and {args.receipt}")
    print("3A flush arms:", len(res["study_3a_flush_rebound"]), "deadcat arms:", len(res["study_3a_deadcat_short"]))
    print("3B cov-only Sharpe:", res["study_3b_gru_vol_cov_only"]["gru_vol_cov_only"]["full"]["ann_sharpe"])
    print("3C PAXG13 Sharpe:", res["study_3c_gold_and_macro"]["paxg_base_13"]["full"]["ann_sharpe"],
          "Macro Sharpe:", res["study_3c_gold_and_macro"]["macro_standalone"]["ann_sharpe"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
