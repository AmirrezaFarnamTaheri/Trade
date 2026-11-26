"""Run Post-Repair Treasury, Substitutes, Liquidity & FX Study (Menu Ideas 7, 8, 9, and 10)."""
from __future__ import annotations

from pathlib import Path

from gym.services.experiments.treasury_liquidity_and_fx_study import (
    run_treasury_liquidity_and_fx_study,
)


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    res = run_treasury_liquidity_and_fx_study(
        wallex_db=repo / "data" / "live" / "market.db",
        multi_venue_db=repo / "data" / "live" / "multi_venue_quotes.sqlite3",
        report_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "treasury-liquidity-and-fx-study.md",
        receipt_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "treasury-liquidity-and-fx-receipt.json",
    )
    print("Idea 7 Prefunding:", res["idea_7_prefunding_sweep"])
    print("Idea 8 Gold Sub:", res["idea_8_gold_substitution"])
    print("Idea 9 Liq Deadlines:", res["idea_9_liquidation_deadlines"])
    print("Idea 10 TMN FX:", res["idea_10_tmn_fx_separation"])


if __name__ == "__main__":
    main()
