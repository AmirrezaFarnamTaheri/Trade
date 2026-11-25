"""Run Post-Repair Cross-Venue Clocks, Cadence, Blind Bake-Off & Cost Break-Even Study."""
from __future__ import annotations

from pathlib import Path

from gym.services.experiments.venue_clocks_cadence_and_breakeven_study import (
    run_venue_clocks_cadence_and_breakeven_study,
)


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    res = run_venue_clocks_cadence_and_breakeven_study(
        wallex_db=repo / "data" / "live" / "market.db",
        multi_venue_db=repo / "data" / "live" / "multi_venue_quotes.sqlite3",
        report_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "venue-clocks-cadence-and-breakeven-study.md",
        receipt_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "venue-clocks-cadence-and-breakeven-receipt.json",
        sealed_key_path=repo / "data" / "live" / "private" / "blind-bakeoff-sealed-key.json",
    )
    print("Idea 12 Price Discovery:", res["idea_12_price_discovery"])
    print("Idea 13 Event Cadence:", res["idea_13_event_vs_fixed_cadence"])
    print("Idea 14 Blind Bakeoff:", res["idea_14_blind_bakeoff"]["blinded_arms"])
    print("Break-even Sweep rows:", len(res["cost_and_slow40_breakeven_sweep"]))


if __name__ == "__main__":
    main()
