"""Run Post-Repair Signal & Model Diagnostics Study (Menu Ideas 2, 3, 4, 5, and 15)."""
from __future__ import annotations

from pathlib import Path

from gym.services.experiments.signal_and_model_diagnostics_study import (
    run_signal_and_model_diagnostics_study,
)


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    res = run_signal_and_model_diagnostics_study(
        wallex_db=repo / "data" / "live" / "market.db",
        report_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "signal-and-model-diagnostics-study.md",
        receipt_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "signal-and-model-diagnostics-receipt.json",
    )
    print("Idea 2 Disagreement:", res["idea_2_sleeve_disagreement"])
    print("Idea 3 Replica:", res["idea_3_cheap_replica"])
    print("Idea 4 Concentration:", res["idea_4_episode_concentration"])
    print("Idea 5 Narrow ML Wait:", res["idea_5_narrow_ml_wait"])
    print("Idea 15 GRU Distill:", res["idea_15_gru_distillation"])


if __name__ == "__main__":
    main()
