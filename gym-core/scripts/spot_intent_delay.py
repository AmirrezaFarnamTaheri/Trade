"""Measure the observed quote opportunities remaining after delay on a frozen spot tape."""
import argparse
import json
from bisect import bisect_left
from collections import Counter
from datetime import timedelta
from pathlib import Path

from gym.adapters.store import MarketDB
from gym.domain.bars import qualified
from gym.domain.model import iso, parse_ts
from gym.domain.rules import is_closed
from gym.domain.strategy import digest
from gym.services.data_portal import DataPortal
from gym.services.portfolio import _rule_timeline


def delay_study(db, tape, delays_ms):
    if not delays_ms or any(type(delay) is not int or not 0 <= delay <= 86_400_000 for delay in delays_ms):
        raise ValueError("delay must be between zero and 86400000 milliseconds")
    intents = tape["intents"]
    if tape["schema"] != "spot-intents/1" or digest(intents) != tape["intents_digest"]:
        raise ValueError("invalid frozen spot intention digest")
    inputs = tape["source_inputs"]
    portal = DataPortal(db, venue=inputs.get("venue", "wallex"))
    rules_for, _, _ = _rule_timeline(db, inputs["rules_mode"])
    horizon = parse_ts(inputs["to"])
    scenarios = {delay: [] for delay in sorted(set(delays_ms))}
    for intent in intents:
        symbol = intent["symbol"]
        arrival, deadline = parse_ts(intent["arrival_at"]), parse_ts(intent["deadline"])
        stop = min(deadline + timedelta(microseconds=1), horizon)
        quotes = ([quote for quote in portal.iter_tops(symbol, arrival, stop) if qualified(quote)]
                  if arrival < stop else [])
        times = [quote.ts_avail for quote in quotes]
        instrument = portal.instrument(symbol)
        for delay, rows in scenarios.items():
            delayed = arrival + timedelta(milliseconds=delay)
            index = bisect_left(times, delayed)
            quote = quotes[index] if index < len(quotes) else None
            status = "DEADLINE_PASSED" if delayed > deadline else _quote_status(rules_for, instrument, quote)
            rows.append({"ref": intent["ref"], "symbol": symbol, "side": intent["side"], "status": status,
                         "arrival_at": iso(delayed), "quote_at": iso(quote.ts_avail) if quote else None,
                         "quote_price": str(quote.ask if intent["side"] == "BUY" else quote.bid) if quote else None})
    return {"schema": "spot-intent-delay/1", "source_run": tape["run_id"], "intents_digest": tape["intents_digest"],
            "scenarios": [{"extra_delay_ms": delay, "counts": dict(Counter(row["status"] for row in rows)), "rows": rows}
                          for delay, rows in scenarios.items()]}


def _quote_status(rules_for, instrument, quote):
    if quote is None:
        return "NO_QUALIFIED_QUOTE"
    if "CLOSED" in quote.flags or is_closed(rules_for(quote.ts_avail), instrument, quote.ts_avail):
        return "FIRST_QUOTE_CLOSED"
    return "QUOTE_AVAILABLE"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market_db", type=Path)
    parser.add_argument("tape", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--delay-ms", nargs="+", type=int, required=True)
    args = parser.parse_args()
    if any(delay < 0 or delay > 86_400_000 for delay in args.delay_ms):
        parser.error("delay must be between zero and 86400000 milliseconds")
    tape = json.loads(args.tape.read_text(encoding="utf-8"))
    db = MarketDB(args.market_db, readonly=True)
    try:
        db.c.execute("BEGIN")
        report = delay_study(db, tape, args.delay_ms)
    finally:
        db.c.close()
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
