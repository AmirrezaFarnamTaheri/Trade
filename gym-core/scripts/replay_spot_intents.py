"""Replay frozen spot intentions against one paper cash book without strategy feedback."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from gym.adapters.store import MarketDB
from gym.domain.bars import qualified
from gym.domain.model import TEHRAN, UTC, iso, parse_ts
from gym.domain.rules import tehran_day
from gym.domain.sim import CashBook, CostModel, market_order
from gym.domain.strategy import digest
from gym.services.data_portal import DataPortal
from gym.services.portfolio import _rule_timeline


def _opening_mid(portal, symbol, start, at):
    midnight = datetime.combine(tehran_day(at), datetime.min.time(), TEHRAN).astimezone(UTC)
    for top in portal.iter_tops(symbol, max(start, midnight), at + timedelta(microseconds=1)):
        if qualified(top):
            return (top.bid + top.ask) / 2
    return None


def _frozen_fx_events(tape, baseline):
    canonical = json.dumps(baseline, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)
    if hashlib.sha256(canonical.encode()).hexdigest() != tape["run_sha256"]:
        raise ValueError("FX source must match the frozen tape's canonical baseline")
    result = baseline["result"]
    refs = {row["ref"] for row in result.get("fx_orders", []) if "ref" in row}
    groups = defaultdict(list)
    for row in result["postings"]:
        if row["ref"] in refs and row["kind"] != "rounding":
            groups[(parse_ts(row["t"]), row["ref"])].append(row)
    return [(at, 1, index, None, rows) for index, ((at, _), rows) in enumerate(groups.items())]


def _settle_frozen_fx(book, reserved, at, rows):
    trial = CashBook(book.balances.copy())
    ref = rows[0]["ref"]
    for row in rows:
        asset, amount = row["ccy"], Decimal(row["amount"])
        if amount < 0 and -amount > trial.get(asset) - reserved[asset]:
            return {"ref": ref, "at": iso(at), "status": "INFEASIBLE"}
        trial.post(at, asset, amount, row["kind"], ref)
    book.balances.update(trial.balances)
    book.postings.extend(trial.postings)
    return {"ref": ref, "at": iso(at), "status": "SETTLED"}


def replay(db, tape, participation, *, reserve=False, fx_baseline=None):
    if not participation.is_finite() or not 0 < participation <= 1:
        raise ValueError("participation must be in (0, 1]")
    intents, inputs = tape["intents"], tape["source_inputs"]
    if tape["schema"] != "spot-intents/1" or digest(intents) != tape["intents_digest"]:
        raise ValueError("invalid frozen spot intention digest")
    if len({row["ref"] for row in intents}) != len(intents):
        raise ValueError("duplicate frozen intention reference")
    portal = DataPortal(db, venue=inputs.get("venue", "wallex"))
    rules, _, _ = _rule_timeline(db, inputs["rules_mode"])
    baseline_cost = CostModel.from_description(inputs["cost"])
    if (baseline_cost.order_type != "market" or baseline_cost.walk_depth or baseline_cost.carry_remainder
            or baseline_cost.impact_models or baseline_cost.hourly_costs or baseline_cost.postfill_costs):
        raise ValueError("frozen settlement requires best-level market orders with fixed fees and no carried remainders")
    receipt_cost = replace(baseline_cost, max_participation=Decimal(1), latency=timedelta(0), max_wait=timedelta(0))
    start, end = map(parse_ts, (inputs["from"], inputs["to"]))
    opening = inputs.get("cash_by_currency") or {inputs["instruments"][inputs["symbols"][0]]["quote"]: inputs["cash"]}
    book = CashBook({asset: Decimal(value) for asset, value in opening.items()})
    quotas, events, results = defaultdict(dict), [], {}
    for index, row in enumerate(intents):
        arrival, deadline = map(parse_ts, (row["arrival_at"], row["deadline"]))
        stop = min(end, deadline + timedelta(microseconds=1))
        top = next((q for q in portal.iter_tops(row["symbol"], arrival, stop) if qualified(q)), None) if arrival < stop else None
        if reserve:
            decision = parse_ts(row["decision_at"])
            if not start <= decision <= arrival <= deadline or decision >= end:
                raise ValueError("invalid frozen reservation window")
            events.append((decision, 0, index, None, row))
        events.append((stop if top is None else top.ts_avail, 2, index, top, row))
    if fx_baseline is not None:
        events.extend(_frozen_fx_events(tape, fx_baseline))
    used, reserved = defaultdict(Decimal), defaultdict(Decimal)
    reservations, opening_mids, fx_outcomes = [], {}, []
    for at, phase, _, top, row in sorted(events):
        if phase == 1:
            fx_outcomes.append(_settle_frozen_fx(book, reserved, at, row))
            continue
        symbol, ref, side = row["symbol"], row["ref"], row["side"]
        inst = portal.instrument(symbol)
        asset = inst.quote if side == "BUY" else inst.base
        amount = Decimal(row["amount"])
        if side not in ("BUY", "SELL") or asset != row["amount_asset"] or not amount.is_finite() or amount <= 0:
            raise ValueError("invalid frozen sizing")
        if phase == 0:
            if amount > book.get(asset) - reserved[asset]:
                results[ref] = {"status": "INFEASIBLE", "reason": "INSUFFICIENT_UNRESERVED_BALANCE"}
            else:
                reserved[asset] += amount
                reservations.append({"at": iso(at), "ref": ref, "asset": asset, "amount": str(amount), "event": "RESERVE"})
            continue
        if reserve:
            if ref in results:
                continue
            reserved[asset] -= amount
            reservations.append({"at": iso(at), "ref": ref, "asset": asset, "amount": str(amount), "event": "RELEASE"})
        if top is None:
            results[ref] = {"status": "NONFILL", "reason": "NO_QUALIFIED_QUOTE"}
            continue
        if amount > book.get(asset) - reserved[asset]:
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
        cost = receipt_cost.for_market(symbol, zero_fee=raw.get("isZeroFee", raw.get("is_zero_fee")) is True)
        day_key = (symbol, tehran_day(at))
        if day_key not in opening_mids:
            opening_mids[day_key] = _opening_mid(portal, symbol, start, at)
        result = market_order(book, inst, side, Decimal(1), at, Decimal(row["decision_price"]), [top], 0,
                              cost, portal.spec_at(symbol, at), rules(at), quotas[symbol], ref,
                              opening_mids[day_key], fixed_amount=amount)
        results[ref] = result
        if result["status"] == "FILLED":
            used[key] += Decimal(result["qty"])
    return {"schema": "frozen-spot-settlement/1", "source_run": tape["run_id"], "intents_digest": tape["intents_digest"],
            "scope": ("Shared reservation from decision through first matching receipt or expiry. " if reserve else
                      "Spot settlement with balance checks at receipt. ") + "Daily marks use the first qualified archive quote. "
            + ("FX settles from frozen baseline postings." if fx_baseline is not None else "Excludes FX legs."),
            **({"reservations": reservations} if reserve else {}),
            **({"fx_outcomes": fx_outcomes} if fx_baseline is not None else {}),
            "participation": str(participation), "counts": dict(Counter(row["status"] for row in results.values())),
            "balances": book.balances, "postings": book.postings, "orders": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market_db", type=Path)
    parser.add_argument("tape", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--participation", type=Decimal, nargs="+", required=True)
    parser.add_argument("--reserve", action="store_true")
    parser.add_argument("--fx-baseline", type=Path)
    args = parser.parse_args()
    tape = json.loads(args.tape.read_text(encoding="utf-8"))
    baseline = json.loads(args.fx_baseline.read_text(encoding="utf-8")) if args.fx_baseline else None
    db = MarketDB(args.market_db, readonly=True)
    try:
        db.c.execute("BEGIN")
        reports = [replay(db, tape, cap, reserve=args.reserve, fx_baseline=baseline) for cap in args.participation]
    finally:
        db.c.close()
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(reports, stream, indent=2, default=str)


if __name__ == "__main__":
    main()
