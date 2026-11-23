"""Compare a frozen spot replay with continuous orders at the same decision times."""
import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from gym.domain.model import iso, parse_ts
from gym.domain.strategy import digest


def _key(symbol, side, at):
    return iso(parse_ts(at)), symbol, side


def _outcome(order):
    return {"status": order["status"], "reason": order.get("reason"),
            "receipt_at": iso(parse_ts(order["fill_time"])) if order.get("fill_time") else None,
            "quantity": Decimal(order["qty"]) if order.get("qty") is not None else None}


def _index(pairs):
    index = {}
    for key, order in pairs:
        if key in index:
            raise ValueError(f"ambiguous decision identity {key}")
        index[key] = _outcome(order)
    return index


def compare(tape, frozen, continuous):
    inputs, intents = tape["source_inputs"], tape["intents"]
    candidate = continuous["inputs"]
    if (digest(intents) != tape["intents_digest"] or frozen["intents_digest"] != tape["intents_digest"]
            or frozen["source_run"] != tape["run_id"]):
        raise ValueError("frozen report does not match the intention tape")
    for field in ("from", "to", "data", "symbols", "venue", "rules_mode", "metadata", "universe_selection",
                  "resolution", "strategy", "strategy_version", "params", "policy", "rank_gate", "dynamic_routes",
                  "cash_by_currency", "fx_rebalance", "trade_accounting"):
        if candidate.get(field) != inputs.get(field):
            raise ValueError(f"continuous replay differs in {field}")
    cost = {**inputs["cost"], "max_participation": frozen["participation"]}
    if candidate["cost"] != cost:
        raise ValueError("continuous replay uses different costs")
    left = _index((_key(row["symbol"], row["side"], row["decision_at"]), frozen["orders"][row["ref"]]) for row in intents)
    right = _index((_key(symbol, row["side"], row["decision_time"]), row)
                   for symbol, market in continuous["result"]["markets"].items() for row in market["orders"])
    counts = Counter()
    differences = []
    for key in sorted(left.keys() | right.keys()):
        a, b = left.get(key), right.get(key)
        label = "MATCH" if a == b else "FROZEN_ONLY" if b is None else "CONTINUOUS_ONLY" if a is None else "OUTCOME_DIFFERS"
        counts[label] += 1
        if label != "MATCH":
            at, symbol, side = key
            differences.append({"decision_at": at, "symbol": symbol, "side": side, "difference": label,
                                "frozen": a, "continuous": b})
    return {"participation": frozen["participation"], "continuous_run": continuous["run_id"],
            "counts": dict(counts), "differences": differences}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tape", type=Path)
    parser.add_argument("frozen", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("continuous", type=Path, nargs="+")
    args = parser.parse_args()
    tape = json.loads(args.tape.read_text(encoding="utf-8"))
    frozen = {Decimal(row["participation"]): row for row in json.loads(args.frozen.read_text(encoding="utf-8"))}
    reports = []
    for path in args.continuous:
        run = json.loads(path.read_text(encoding="utf-8"))
        cap = Decimal(run["inputs"]["cost"]["max_participation"])
        reports.append(compare(tape, frozen[cap], run))
    with args.out.open("x", encoding="utf-8") as target:
        json.dump(reports, target, indent=2, default=str, allow_nan=False)


if __name__ == "__main__":
    main()
