"""Thin reproducible CLI launcher for S3/S4 fast-sleeve attribution & +1h UTC offset sensitivity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.sleeve_attribution_study import (
    run_fast_sleeve_attribution,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run S3/S4 fast-sleeve attribution & +1h UTC offset sensitivity")
    parser.add_argument("--db", type=Path, default=Path("D:/Github/Trade/data/live/market.db"))
    parser.add_argument("--out", type=Path, default=Path("D:/Github/Trade/evidence/2026-11-24-fast-sleeve-attribution.json"))
    args = parser.parse_args()
    res = run_fast_sleeve_attribution(args.db)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
