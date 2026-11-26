"""Measure time-weighted booked spot exposure from an archive replay ledger."""

import argparse
import json
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from gym.adapters.run_store import load_verified_run
from gym.adapters.store import MarketDB
from gym.domain.model import iso, parse_ts
from gym.services.data_portal import DataPortal
from scripts.audit_shared_portfolio import _fx_mid

_MICROSECOND = timedelta(microseconds=1)
_BOOK_ROUNDING = Decimal("1e-18")


def _spot_fills(run):
    inputs, result = run["inputs"], run["result"]
    orders = {}
    for symbol, market in result["markets"].items():
        inst = inputs["instruments"][symbol]
        for order in market["orders"]:
            if order["status"] == "FILLED":
                if order["ref"] in orders:
                    raise ValueError("duplicate spot fill reference")
                orders[order["ref"]] = (symbol, inst, order)
    posts = defaultdict(dict)
    for row in result["postings"]:
        ref, asset = row["ref"], row["ccy"]
        if ref in orders:
            _, _, order = orders[ref]
            if parse_ts(row["t"]) != parse_ts(order["fill_time"]):
                raise ValueError(f"spot posting has a different receipt time: {ref}")
            posts[ref][asset] = posts[ref].get(asset, Decimal(0)) + Decimal(row["amount"])
    for ref, (symbol, inst, order) in sorted(orders.items(), key=lambda pair: parse_ts(pair[1][2]["fill_time"])):
        amounts = posts[ref]
        if amounts.keys() != {inst["base"], inst["quote"]}:
            raise ValueError(f"missing booked spot fill legs: {ref}")
        yield parse_ts(order["fill_time"]), symbol, inst["quote"], amounts[inst["base"]], amounts[inst["quote"]], order["side"]


def spot_capital_exposure(run, opening_fx, *, start=None, end=None):
    """Integrate average-cost spot inventory over a half-open subwindow."""
    inputs, result = run["inputs"], run["result"]
    t0, t1 = map(parse_ts, (inputs["from"], inputs["to"]))
    start, end = start or t0, end or t1
    if not t0 <= start < end <= t1:
        raise ValueError("exposure window must be within the saved replay")
    if inputs.get("trade_accounting") != "booked-notional/1" or not inputs.get("cash_by_currency"):
        raise ValueError("exposure requires a booked mixed-currency portfolio")
    if opening_fx <= 0:
        raise ValueError("exposure requires a positive opening FX rate")
    quantity, basis, deployed, area = (defaultdict(Decimal) for _ in range(4))
    cursor = start
    with localcontext() as context:
        context.prec = 80

        def settle_interval(at):
            seconds = Decimal((at - cursor) // _MICROSECOND) / 1_000_000
            for asset, amount in deployed.items():
                area[asset] += amount * seconds

        for at, symbol, quote, units, cash, side in _spot_fills(run):
            if not t0 <= at < t1:
                raise ValueError("spot fill lies outside saved replay")
            boundary = min(max(at, start), end)
            settle_interval(boundary)
            cursor = boundary
            old_qty, old_basis = quantity[symbol], basis[symbol]
            new_qty = old_qty + units
            if side == "BUY" and units > 0 and cash < 0:
                new_basis = old_basis - cash
            elif side == "SELL" and units < 0 and cash > 0 and old_qty > 0 and new_qty >= -_BOOK_ROUNDING:
                new_qty = max(new_qty, Decimal(0))
                new_basis = old_basis * new_qty / old_qty
            else:
                raise ValueError(f"invalid booked spot amounts for {symbol}")
            quantity[symbol], basis[symbol] = new_qty, new_basis
            deployed[quote] += new_basis - old_basis
        settle_interval(end)
        if any(abs(quantity[symbol] - Decimal(market["holding"])) > _BOOK_ROUNDING for symbol, market in result["markets"].items()
               if market.get("mark_status") != "REFERENCE_ONLY"):
            raise ValueError("spot fill quantities do not reconcile to the saved portfolio")
        seconds = Decimal((end - start) // _MICROSECOND) / 1_000_000
        reporting = result["quote"]
        secondary, = inputs["cash_by_currency"].keys() - {reporting}
        average = (area[reporting] + area[secondary] / opening_fx) / seconds
        return {"from": iso(start), "to": iso(end), "reporting_currency": reporting,
                "quote_seconds": {asset: str(area[asset]) for asset in sorted(inputs["cash_by_currency"])},
                "mean_deployed_capital": str(average),
                "mean_deployed_share_of_opening_equity": str(average / Decimal(result["start_cash"])),
                "basis": "Time-weighted remaining spot inventory cost. Average cost on sells. Convert using opening FX."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market_db", type=Path)
    parser.add_argument("runs", type=Path, nargs="+")
    parser.add_argument("--from", dest="start", type=parse_ts)
    parser.add_argument("--to", dest="end", type=parse_ts)
    parser.add_argument("--store", choices=("live", "demo"), default="live")
    args = parser.parse_args()
    db = MarketDB(args.market_db, readonly=True)
    try:
        db.c.execute("BEGIN")
        reference, reports = None, []
        for file in args.runs:
            run = load_verified_run(file.parent, file.stem, store=args.store)
            inputs, result = run["inputs"], run["result"]
            shared = {key: inputs.get(key) for key in ("venue", "symbols", "from", "to", "resolution", "data",
                                                       "cash_by_currency", "universe_selection", "valuation_symbol")}
            shared["cost"] = {key: value for key, value in inputs["cost"].items() if key != "max_fraction"}
            shared["opening_equity"] = result["start_cash"]
            if reference is not None and shared != reference:
                raise ValueError("runs need the same tape, window, opening account, universe and execution costs")
            reference = shared
            conversion = result["valuation"]["conversion"]
            portal = DataPortal(db, venue=inputs.get("venue", "wallex"))
            rate = _fx_mid(portal, conversion["start_at"], conversion["pair"], explicit="valuation_symbol" in inputs)
            reports.append({"run_id": run["run_id"], "output_digest": run["outputs_digest"],
                            "rank_gate": inputs.get("rank_gate"), "max_fraction": inputs["cost"].get("max_fraction"),
                            **spot_capital_exposure(run, rate, start=args.start, end=args.end)})
        print(json.dumps({"qualification": "DEVELOPMENT_COMPARISON", "reports": reports}, indent=2, sort_keys=True))
    finally:
        db.c.close()


if __name__ == "__main__":
    main()
