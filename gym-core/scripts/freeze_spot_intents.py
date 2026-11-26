"""Export decision-time spot intentions from the shared-account paper scheduler calculation."""
import argparse
import hashlib
import json
from pathlib import Path

from gym.adapters.store import MarketDB
from gym.domain.model import parse_ts
from gym.domain.strategy import digest
from gym.services.research_ledger import _scheduled_replay


def freeze(db, spec, end, store, root):
    intents = []
    run, _ = _scheduled_replay(db, spec["job"], spec["hyp"], end, store, root, intent_sink=intents.append)
    refs = [row["ref"] for row in intents]
    orders = {row["ref"]: row for market in run["result"]["markets"].values() for row in market["orders"]}
    if len(set(refs)) != len(refs) or set(refs) != orders.keys():
        raise ValueError("the portfolio generated spot orders outside the frozen intent capture")
    canonical = json.dumps(run, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)
    return {"schema": "spot-intents/1", "run_id": run["run_id"], "outputs_digest": run["outputs_digest"],
            "run_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "source_inputs": run["inputs"],
            "intents_digest": digest(intents), "intents": intents,
            "baseline_outcomes": {ref: {key: orders[ref][key] for key in ("status", "reason", "fill_time", "qty")
                                        if key in orders[ref]} for ref in refs}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market_db", type=Path)
    parser.add_argument("reproduction", type=Path, help="JSON with the scheduler job and its hypothesis")
    parser.add_argument("out", type=Path)
    parser.add_argument("--end", required=True, type=parse_ts)
    parser.add_argument("--store", choices=("live", "demo"), default="live")
    args = parser.parse_args()
    spec = json.loads(args.reproduction.read_text(encoding="utf-8"))
    db = MarketDB(args.market_db, readonly=True)
    try:
        tape = freeze(db, spec, args.end, args.store, args.reproduction.parent)
    finally:
        db.c.close()
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(tape, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
