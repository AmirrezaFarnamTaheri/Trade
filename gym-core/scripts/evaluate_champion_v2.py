"""CLI runner for Unified v2 Champion vs. v1 Champion end-to-end single shared-ledger verification."""
from __future__ import annotations

import argparse
from pathlib import Path

from gym.services.experiments.champion_v2_verification import (
    run_v2_champion_verification,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Unified v2 Champion vs v1 Champion on single shared ledger")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--report", type=Path, default=Path("../evidence/2026-11-25-v2-champion-verification-report.md"))
    parser.add_argument("--receipt", type=Path, default=Path("../evidence/2026-11-25-v2-champion-verification.json"))
    args = parser.parse_args()
    res = run_v2_champion_verification(args.db, args.report, args.receipt)
    print(f"Wrote {args.report} | AUCs:", res["oos_aucs"])
    for r in res["arms"]:
        print(f"  {r['name']:30s} NAV=${r['full']['ending_nav']:7.2f} SR={r['full']['ann_sharpe']:.3f} DD={r['full']['max_dd_pct']:5.2f}% Bear={r['stress']['ret_pct']:+6.2f}% vsV1={r['vs_v1_bps']:+.2f}bp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
