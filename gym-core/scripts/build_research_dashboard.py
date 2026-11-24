"""CLI runner to generate the 100% offline interactive HTML research dashboard."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.research_dashboard import generate_research_dashboard


def main() -> int:
    parser = argparse.ArgumentParser(description="Build offline interactive TradingGYM research dashboard HTML")
    parser.add_argument("--evidence-dir", type=Path, default=Path("../evidence"))
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("../evidence/2026-11-24-research-dashboard.html"),
    )
    args = parser.parse_args()
    summary = generate_research_dashboard(args.evidence_dir, args.output, db_path=args.db)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
