"""Run Rare Micro-Signal Portfolio Weekly Opportunity, Fragility & Gold Two-Leg Tape Study."""
from __future__ import annotations

from pathlib import Path

from gym.services.experiments.rare_micro_signal_portfolio_study import (
    run_rare_micro_signal_portfolio_study,
)


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    res = run_rare_micro_signal_portfolio_study(
        wallex_db=repo / "data" / "live" / "market.db",
        multi_venue_db=repo / "data" / "live" / "multi_venue_quotes.sqlite3",
        report_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "rare-micro-signal-portfolio-study.md",
        receipt_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "rare-micro-signal-portfolio-receipt.json",
    )
    print("Raw intents:", res["raw_intent_counts"])
    for r in res["weekly_opportunity_table"]:
        print(
            f"  {r['label']:30s} wk={r['active_weeks']}/{r['total_weeks']} ({r['addl_active_weeks_vs_ign']:+d}) "
            f"drought={r['longest_drought_weeks']}w eps={r['unique_episodes']} net/int={r['net_bps_per_intended']:+.2f}bp "
            f"ret={r['ret_pct']:+.2f}% sr={r['ann_sharpe']:.3f} ex3={r['ex_top3_ret_pct']:+.2f}% ({r['ex_top3_sharpe']:.3f})"
        )
    print("Gold Two-Leg Tape:", res["live_gold_two_leg_tape"])


if __name__ == "__main__":
    main()
