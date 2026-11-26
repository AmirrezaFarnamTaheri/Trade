"""Run the Strategy Promotion, Conditional Capital Admission, Internal Netting & Partial Revivals Study."""
from __future__ import annotations

from pathlib import Path

from gym.services.experiments.strategy_promotion_and_revival_study import (
    run_strategy_promotion_and_revival_study,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "live" / "market.db"
REPORT_PATH = REPO_ROOT / "evidence" / "studies" / "v3-adaptive-engine" / "strategy-promotion-and-revivals.md"
RECEIPT_PATH = REPO_ROOT / "evidence" / "studies" / "v3-adaptive-engine" / "strategy-promotion-and-revivals-receipt.json"


def main() -> None:
    res = run_strategy_promotion_and_revival_study(DB_PATH, REPORT_PATH, RECEIPT_PATH)
    print(f"Wrote {REPORT_PATH}")
    print(f"Wrote {RECEIPT_PATH}")
    for arm in res["exp1_conditional_capital_admission"]["arms"]:
        print(f"  {arm['arm']}: NAV=${arm['ending_nav']:,.2f} ({arm['ret_pct']:+.2f}%) SR={arm['ann_sharpe']:.3f} DD={arm['max_dd_pct']:.2f}%")
    net = res["exp2_standalone_internal_netting"]
    print(f"  Internal Netting: crossed={net['crossed_events']} saved=${net['saved_fees_usdt']:.2f} ({net['fee_reduction_pct']:.2f}%)")


if __name__ == "__main__":
    main()
