"""Run Remaining Cross-Layer Design & Micro-Signal Stress Suite."""
from __future__ import annotations

from pathlib import Path

from gym.services.experiments.remaining_cross_layer_suite_study import (
    run_remaining_cross_layer_suite,
)


def main() -> None:
    repo = Path(__file__).resolve().parents[2]
    res = run_remaining_cross_layer_suite(
        wallex_db=repo / "data" / "live" / "market.db",
        multi_venue_db=repo / "data" / "live" / "multi_venue_quotes.sqlite3",
        report_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "remaining-cross-layer-suite.md",
        receipt_path=repo / "evidence" / "studies" / "v3-adaptive-engine" / "remaining-cross-layer-suite-receipt.json",
    )
    print("Rel Strength & Sensor:", res["rel_strength_selloff_and_sensor"])
    print("Liq Recovery & Adverse Fill:", res["liquidity_recovery_and_adverse_fill"])
    print("TMN/Delist/Gap/Rails:", res["tmn_delist_gap_and_rails"])
    print("Order Reconciliation:", res["order_timeout_late_fill_reconciliation"])


if __name__ == "__main__":
    main()
