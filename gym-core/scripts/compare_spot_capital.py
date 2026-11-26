"""Compare booked deployment and execution across saved mixed-currency spot replays."""
import argparse
import json
from collections import Counter, defaultdict
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from gym.adapters.store import MarketDB
from gym.domain.bars import qualified
from gym.domain.model import iso, parse_ts
from gym.domain.sim import CashBook, CostModel, market_order
from gym.services.data_portal import DataPortal
from gym.services.portfolio import _rule_timeline
from scripts.audit_shared_portfolio import audit
from scripts.spot_capital_exposure import spot_capital_exposure


def liquidation_window(run, portal, end):
    inputs = run["inputs"]
    start, cutoff = map(parse_ts, (inputs["from"], inputs["to"]))
    if end <= cutoff:
        raise ValueError("exit observation window must end after the replay cutoff")
    model = CostModel.from_description(inputs["cost"])
    arrival = cutoff + model.latency
    if arrival >= end or model.order_type != "market" or model.walk_depth or model.max_participation is None:
        raise ValueError("exit window requires capped best-level matching and time after arrival")
    rules, _, _ = _rule_timeline(portal.db, inputs["rules_mode"])
    rows = []
    for symbol, market in run["result"]["markets"].items():
        quantity = Decimal(market["holding"])
        if not quantity:
            continue
        inst = portal.instrument(symbol)
        raw = (portal.metadata_at(symbol, start) or {}).get("raw", {})
        cost = replace(model.for_market(symbol, zero_fee=raw.get("isZeroFee", raw.get("is_zero_fee")) is True),
                       latency=model.latency * 0, max_wait=model.max_wait * 0)
        book, first, last, receipts = CashBook({inst.base: quantity}), None, None, 0
        previous = None
        for top in portal.iter_tops(symbol, arrival, end):
            if top.ts_avail == previous:
                continue
            previous = top.ts_avail
            if not qualified(top) or "CLOSED" in top.flags:
                continue
            at = top.ts_avail
            receipts += 1
            fill = market_order(book, inst, "SELL", Decimal(1), at, top.bid, [top], 0, cost,
                                portal.spec_at(symbol, at), rules(at), {}, f"{symbol}/exit/{receipts}")
            if fill["status"] == "FILLED":
                elapsed = (at - cutoff).total_seconds()
                first = elapsed if first is None else first
                last = elapsed
                if not book.get(inst.base):
                    break
        residual = book.get(inst.base)
        rows.append({"symbol": symbol, "quote_currency": inst.quote, "starting_units": quantity,
                     "residual_units": residual, "seconds_to_first_fill": first,
                     "seconds_to_flat": None if residual else last, "net_proceeds": book.get(inst.quote),
                     "qualified_receipts_checked": receipts})
    return {"through_exclusive": iso(end), "model": "One retry per distinct qualified receipt using displayed best bid",
            "positions": rows}


def summarize(run, portal, *, exit_end=None):
    reconciled = audit(run, portal)
    exposure = spot_capital_exposure(run, Decimal(reconciled["start_tmn_per_usdt"]))
    markets = run["result"]["markets"]
    counts = Counter()
    known_unfilled = defaultdict(Decimal)
    exits = []
    for symbol, market in markets.items():
        for order in market["orders"]:
            counts[order["status"]] += 1
            if "requested_qty" in order:
                key = (symbol, order["side"])
                known_unfilled[key] += Decimal(order["requested_qty"]) - Decimal(order.get("qty", "0"))
            if order["side"] == "SELL" and order["status"] == "FILLED":
                elapsed = parse_ts(order["fill_time"]) - parse_ts(order["decision_time"])
                exits.append({"ref": order["ref"], "seconds_to_first_fill": elapsed.total_seconds()})
    opening, ending = (Decimal(reconciled[key]) for key in ("opening_equity", "ending_equity"))
    return {"run_id": run["run_id"], "outputs_digest": run["outputs_digest"], "markets": len(markets),
            "observations": sum(market["observations"] for market in markets.values()),
            "cost": run["inputs"]["cost"], "archive_digest": run["inputs"]["data"],
            "opening_cash": run["inputs"]["cash_by_currency"], "opening_equity": opening, "ending_equity": ending,
            "marked_return": ending / opening - 1, "valuation_status": reconciled["valuation_status"],
            "cash_benchmark_excess": reconciled["excess_vs_cash"], "booked_deployment": exposure,
            "order_counts": dict(counts), "known_unfilled_base_by_market_and_side": [
                {"symbol": symbol, "side": side, "quantity": amount} for (symbol, side), amount in sorted(known_unfilled.items())],
            "filled_sell_delays": exits, "terminal_exit_snapshot": reconciled["terminal_spot_exit_snapshot"],
            **({"post_cutoff_exit": liquidation_window(run, portal, exit_end)} if exit_end is not None else {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market_db", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--exit-end", type=parse_ts)
    args = parser.parse_args()
    db = MarketDB(args.market_db, readonly=True)
    try:
        db.c.execute("BEGIN")
        rows = []
        for path in args.runs:
            run = json.loads(path.read_text(encoding="utf-8"))
            portal = DataPortal(db, venue=run["inputs"].get("venue", "wallex"))
            rows.append(summarize(run, portal, exit_end=args.exit_end))
    finally:
        db.c.close()
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump({"schema": "spot-capital-comparison/1", "runs": rows}, stream, indent=2, default=str, allow_nan=False)


if __name__ == "__main__":
    main()
