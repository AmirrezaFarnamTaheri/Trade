"""Thin reproducible CLI launcher for the First Paper Experiment service."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.ensemble_study import (
    render_first_ensemble_markdown,
    run_first_ensemble_experiment,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run First Paper Experiment on read-only market.db")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--report", type=Path, default=Path("../evidence/studies/core-ensemble/first-ensemble-experiment.md"))
    parser.add_argument("--receipt", type=Path, default=Path("../evidence/studies/core-ensemble/first-ensemble-decision-receipt.json"))
    args = parser.parse_args()

    receipt = run_first_ensemble_experiment(args.db)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_first_ensemble_markdown(receipt), encoding="utf-8")
    print(f"Wrote {args.report} & {args.receipt} | verdict={receipt['verdict']}")


if __name__ == "__main__":
    main()
