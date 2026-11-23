"""Replay frozen spot intentions against one paper cash book without strategy feedback."""
import argparse
import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from gym.adapters.store import MarketDB
from gym.domain.bars import qualified
from gym.domain.model import parse_ts
from gym.domain.sim import CashBook, CostModel, market_order
from gym.domain.strategy import digest
from gym.services.data_portal import DataPortal
from gym.services.portfolio import _rule_timeline


def replay(db, tape, participation):
    if not participation.is_finite() or not 0 < participation <= 1:
        raise ValueError("participation must be in (0, 1]")
    intents, inputs = tape["intents"], tape["source_inputs"]
    if tape["schema"] != "spot-intents/1" or digest(intents) != tape["intents_digest"]:
        raise ValueError("invalid frozen spot intention digest")
    if len({row["ref"] for row in intents}) != len(intents):
        raise ValueError("duplicate frozen intention reference")
    portal = DataPortal(db, venue=inputs.get("venue", "wallex"))
    rules, _, _ = _rule_timeline(db, inputs["rules_mode"])
    start, end = map(parse_ts, (inputs["from"], inputs["to"]))
    opening = inputs.get("cash_by_currency") or {inputs["instruments"][inputs["symbols"][0]]["quote"]: inputs["cash"]}
    book = CashBook({asset: Decimal(value) for asset, value in opening.items()})
    quotas, events, results = defaultdict(dict), [], {}
    for index, row in enumerate(intents):
        arrival, deadline = map(parse_ts, (row["arrival_at"], row["deadline"]))
        stop = min(end, deadline + timedelta(microseconds=1))
        top = next((q for q in portal.iter_tops(row["symbol"], arrival, stop) if qualified(q)), None) if arrival < stop else None
        if top is None:
            results[row["ref"]] = {"status": "NONFILL", "reason": "NO_QUALIFIED_QUOTE"}
        else:
            events.append((top.ts_avail, index, top, row))
    used = defaultdict(Decimal)
    for at, _, top, row in sorted(events):
        symbol, ref, side = row["symbol"], row["ref"], row["side"]
        inst = portal.instrument(symbol)
        asset = inst.quote if side == "BUY" else inst.base
        amount = Decimal(row["amount"])
        if side not in ("BUY", "SELL") or asset != row["amount_asset"] or not amount.is_finite() or amount <= 0:
            raise ValueError("invalid frozen sizing")
        if amount > book.get(asset):
            results[ref] = {"status": "INFEASIBLE", "reason": "INSUFFICIENT_SETTLED_BALANCE"}
            continue
        key = (symbol, at, side)
        shown = top.ask_qty if side == "BUY" else top.bid_qty
        remaining = None if shown is None else shown * participation - used[key]
        if remaining is not None and remaining <= 0:
            results[ref] = {"status": "NONFILL", "reason": "DISPLAYED_CAPACITY_EXHAUSTED"}
            continue
        top = replace(top, ask_qty=remaining) if side == "BUY" else replace(top, bid_qty=remaining)
        raw = (portal.metadata_at(symbol, start) or {}).get("raw", {})
        cost = CostModel(fee_rate=Decimal(inputs["cost"]["fee_rate"]), max_participation=Decimal(1),
                         latency=timedelta(0), max_wait=timedelta(0)).for_market(
                             symbol, zero_fee=raw.get("isZeroFee", raw.get("is_zero_fee")) is True)
        result = market_order(book, inst, side, Decimal(1), at, Decimal(row["decision_price"]), [top], 0,
                              cost, portal.spec_at(symbol, at), rules(at), quotas[symbol], ref, fixed_amount=amount)
        results[ref] = result
        if result["status"] == "FILLED":
            used[key] += Decimal(result["qty"])
    return {"schema": "frozen-spot-settlement/1", "source_run": tape["run_id"], "intents_digest": tape["intents_digest"],
            "scope": "Spot settlement with balance checks at receipt. Excludes FX legs, reservations and daily opening marks.",
            "participation": str(participation), "counts": dict(Counter(row["status"] for row in results.values())),
            "balances": book.balances, "postings": book.postings, "orders": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market_db", type=Path)
    parser.add_argument("tape", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--participation", type=Decimal, nargs="+", required=True)
    args = parser.parse_args()
    tape = json.loads(args.tape.read_text(encoding="utf-8"))
    db = MarketDB(args.market_db, readonly=True)
    try:
        db.c.execute("BEGIN")
        reports = [replay(db, tape, cap) for cap in args.participation]
    finally:
        db.c.close()
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(reports, stream, indent=2, default=str)


if __name__ == "__main__":
    main()
