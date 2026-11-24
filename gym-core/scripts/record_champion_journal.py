"""CLI runner for freezing GRU-Ignition weights, recording Champion Ensemble forward shadow journal, and scoring live forward NAV."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gym.services.experiments.champion_forward_journal import (
    record_champion_ensemble_journal,
    score_champion_forward_journal,
    train_and_freeze_gru_ignition,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record & score v1 Champion Ensemble prospective forward paper journal")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--multi-venue-db", type=Path, default=Path("../data/live/multi_venue_quotes.sqlite3"))
    parser.add_argument("--journal", type=Path, default=Path("../data/live/allocation/champion-ensemble-journal.jsonl"))
    parser.add_argument("--model", type=Path, default=Path("../data/live/models/gru-ignition-v1.json"))
    parser.add_argument(
        "--registration",
        type=Path,
        default=Path("../evidence/2026-11-25-champion-ensemble-registration.json"),
    )
    parser.add_argument(
        "--score-out",
        type=Path,
        default=Path("../evidence/2026-11-25-champion-forward-score.json"),
    )
    parser.add_argument("--gold-symbol", type=str, default="XAUTUSDT")
    parser.add_argument("--freeze-model", action="store_true", help="Train and freeze GRU-Ignition JSON weights first")
    args = parser.parse_args()

    if args.freeze_model or not args.model.is_file():
        frozen = train_and_freeze_gru_ignition(args.db, args.model, gold_symbol=args.gold_symbol)
        print("FROZEN MODEL:", json.dumps({k: v for k, v in frozen.items() if k != "metadata"}, indent=2))

    rec = record_champion_ensemble_journal(
        args.db,
        args.journal,
        args.model,
        multi_venue_db=args.multi_venue_db,
        registration_path=args.registration,
        gold_symbol=args.gold_symbol,
    )
    score = score_champion_forward_journal(args.journal, args.db)
    args.score_out.parent.mkdir(parents=True, exist_ok=True)
    args.score_out.write_text(json.dumps(score, indent=2) + "\n", encoding="utf-8")
    print("RECORD:", json.dumps({"status": rec.get("status"), "slot_key": rec.get("slot_key"), "cash_weight": rec.get("cash_weight"), "triggers": rec.get("ignition_triggers", [])}, indent=2))
    print("SCORE:", json.dumps(score, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
