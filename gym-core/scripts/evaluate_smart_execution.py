"""CLI runner for the live Side-Asymmetric Smart Execution Audit."""
from __future__ import annotations

import argparse
from pathlib import Path

from gym.services.experiments.smart_execution_sim import run_smart_execution_simulation


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate side-asymmetric smart execution on matched Wallex+Nobitex books")
    parser.add_argument("--wallex-db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--multi-venue-db", type=Path, default=Path("../data/live/multi_venue_quotes.sqlite3"))
    parser.add_argument("--report", type=Path, default=Path("../evidence/2026-11-25-smart-execution-report.md"))
    parser.add_argument("--receipt", type=Path, default=Path("../evidence/2026-11-25-smart-execution.json"))
    parser.add_argument("--notional", type=float, default=250.0)
    args = parser.parse_args()
    res = run_smart_execution_simulation(
        args.wallex_db, args.multi_venue_db, args.report, args.receipt, notional_usdt=args.notional,
    )
    print(f"Evaluated {len(res.get('rows', []))} symbols -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
