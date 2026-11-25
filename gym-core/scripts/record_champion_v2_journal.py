"""CLI runner for freezing v2 GRU-Ignition (11-feat Path-PnL), recording v2 Champion shadow journal, and scoring forward NAV."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.champion_forward_journal import (
    score_champion_forward_journal,
)
from gym.services.experiments.champion_v2_journal import (
    record_champion_v2_journal,
    train_and_freeze_v2_gru,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record & score parallel v2 Champion prospective forward paper journal")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--multi-venue-db", type=Path, default=Path("../data/live/multi_venue_quotes.sqlite3"))
    parser.add_argument("--journal", type=Path, default=Path("../data/live/allocation/champion-v2-journal.jsonl"))
    parser.add_argument("--model", type=Path, default=Path("../data/live/models/gru-ignition-v2-pathpnl.json"))
    parser.add_argument("--registration", type=Path, default=Path("../evidence/forward/champion-v2-registration.json"))
    parser.add_argument("--score-out", type=Path, default=Path("../evidence/forward/champion-v2-forward-score.json"))
    parser.add_argument("--freeze-model", action="store_true")
    args = parser.parse_args()

    if args.freeze_model or not args.model.is_file():
        frozen = train_and_freeze_v2_gru(args.db, args.model)
        print("FROZEN V2 MODEL:", json.dumps({k: v for k, v in frozen.items() if k != "metadata"}, indent=2))

    rec = record_champion_v2_journal(
        args.db, args.journal, args.model,
        multi_venue_db=args.multi_venue_db, registration_path=args.registration,
    )
    score = score_champion_forward_journal(args.journal, args.db)
    args.score_out.parent.mkdir(parents=True, exist_ok=True)
    args.score_out.write_text(json.dumps(score, indent=2) + "\n", encoding="utf-8")
    print("RECORD V2:", json.dumps({
        "status": rec.get("status"), "slot_key": rec.get("slot_key"),
        "cash_weight": rec.get("cash_weight"), "metals_reserve": rec.get("metals_reserve", {}),
        "triggers": rec.get("ignition_triggers", []),
    }, indent=2))
    print("SCORE V2:", json.dumps(score, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
