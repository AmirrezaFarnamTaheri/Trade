"""CLI runner for matched live multi-venue execution-cost audit (Wallex vs Nobitex)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.venue_execution_audit import (
    run_venue_execution_cost_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit live Wallex vs Nobitex execution costs")
    parser.add_argument("--wallex-db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--multi-venue-db", type=Path, default=Path("../data/live/multi_venue_quotes.sqlite3"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../evidence/studies/execution-and-venues/venue-execution-cost.md"),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("../evidence/studies/execution-and-venues/venue-execution-cost.json"),
    )
    args = parser.parse_args()
    summary = run_venue_execution_cost_audit(args.wallex_db, args.multi_venue_db, args.report, args.receipt)
    print(json.dumps({"symbols_audited": len(summary.get("symbols", []))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
