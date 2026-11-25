"""Run Cross-Layer Trading Design Diagnostics Study."""
from __future__ import annotations

from pathlib import Path

from gym.services.experiments.cross_layer_diagnostic_study import (
    run_cross_layer_diagnostic_study,
)


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    res = run_cross_layer_diagnostic_study(
        wallex_db=repo / "data" / "live" / "market.db",
        report_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "cross-layer-design-diagnostics.md",
        receipt_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "cross-layer-design-diagnostics-receipt.json",
    )
    print("Exit Specialist:", res["exit_specialist_comparison"])
    print("Confirmation Price:", res["confirmation_price"])
    print("Intrabar Ambiguity:", res["intrabar_ambiguity_bounds"])
    print("2x2 Conflict:", res["capital_conflict_2x2"])
    print("Time-to-Decision:", res["time_to_decision"])
    print("Sham & Funnel:", res["sham_control_and_funnel"])


if __name__ == "__main__":
    main()
