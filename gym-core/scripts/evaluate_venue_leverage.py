"""CLI runner for the 4-part Nobitex Pay-As-You-Go Margin vs. Wallex Margin & Trade-Credit study."""
from __future__ import annotations

import argparse
from pathlib import Path

from gym.services.experiments.venue_leverage_study import run_venue_leverage_study


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Nobitex margin vs Wallex margin & fixed trade-credit")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../evidence/studies/execution-and-venues/nobitex-margin-vs-wallex-credit.md"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("../evidence/studies/execution-and-venues/nobitex-margin-vs-wallex-credit.json"),
    )
    args = parser.parse_args()
    res = run_venue_leverage_study(args.db, args.report, args.receipt)
    print(f"Wrote {args.report} and {args.receipt}")
    print("Part 1 (Bull Core):", len(res["part_1_bull_levered_1d_core"]), "arms")
    print("Part 2 (2h Ignition):", len(res["part_2_event_levered_2h_ignition"]), "arms")
    print("Part 3 (Bear Short):", len(res["part_3_structural_bear_short"]), "arms")
    print("Part 4 (Wallex Credit):", len(res["part_4_wallex_5x_trade_credit_stress"]), "scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
