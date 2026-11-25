"""CLI runner for daily prospective S1+S5 standing-leader forward paper journal."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.leader_forward_journal import record_s1_s5_leader_journal


def main() -> int:
    parser = argparse.ArgumentParser(description="Record daily S1+S5 standing-leader forward paper journal")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument(
        "--journal",
        type=Path,
        default=Path("../data/live/allocation/s1-s5-leader-journal.jsonl"),
    )
    parser.add_argument(
        "--registration",
        type=Path,
        default=Path("../evidence/forward/s1-s5-leader-registration.json"),
    )
    args = parser.parse_args()
    res = record_s1_s5_leader_journal(args.db, args.journal, registration_path=args.registration)
    print(json.dumps(res, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
