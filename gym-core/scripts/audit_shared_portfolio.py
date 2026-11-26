"""Audit a saved mixed-currency paper replay against its archived market database."""

import argparse
import json
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from gym.adapters.run_store import load_verified_run
from gym.adapters.store import MarketDB
from gym.domain.bars import qualified
from gym.domain.model import iso, parse_ts
from gym.domain.rules import is_closed
from gym.domain.sim import CashBook, CostModel, market_order
from gym.services.data_portal import DataPortal
from gym.services.rules import RuleService


def _fx_mid(portal, stamp, pair, *, explicit):
    at = parse_ts(stamp)
    top = None
    for receipt in portal.iter_tops(pair, at, at + timedelta(microseconds=1)):
        if qualified(receipt) and (not explicit or "CLOSED" not in receipt.flags):
            top = receipt
    if top is None:
        raise ValueError(f"archived FX mark missing at {stamp}")
    return (top.bid + top.ask) / 2


def audit(run, portal):
    """Separate opening cash exposure, booked spot P&L and conversion cash flows."""
    inputs, result = run["inputs"], run["result"]
    if inputs.get("trade_accounting") != "booked-notional/1" or not inputs.get("cash_by_currency"):
        raise ValueError("audit requires a booked mixed-currency portfolio")
    if portal.venue != inputs.get("venue", "wallex"):
        raise ValueError("audit portal venue does not match saved replay")
    conversion = result["valuation"]["conversion"]
    explicit = "valuation_symbol" in inputs
    with localcontext() as ctx:
        ctx.prec = 400
        start_fx = _fx_mid(portal, conversion["start_at"], conversion["pair"], explicit=explicit)
        end_fx = _fx_mid(portal, conversion["end_at"], conversion["pair"], explicit=explicit)
        if explicit and (start_fx != Decimal(conversion["opening_rate"]) or end_fx != Decimal(conversion["closing_rate"])):
            raise ValueError("archived marks do not match saved rates")
        report = _reconcile(run, start_fx, end_fx)
    return {**report, "terminal_spot_exit_snapshot": terminal_exit_snapshot(run, portal)}


def terminal_exit_snapshot(run, portal):
    """Quote a single modeled exit per held market from the latest pre-cutoff receipt."""
    inputs, result = run["inputs"], run["result"]
    model = CostModel.from_description(inputs["cost"])
    if model.order_type != "market" or model.max_participation is None or model.walk_depth:
        return {"status": "UNSUPPORTED_EXECUTION_MODEL"}
    if model.impact_models or model.hourly_costs or model.postfill_costs:
        return {"status": "UNSUPPORTED_EXECUTION_MODEL"}
    start, cutoff = parse_ts(inputs["from"]), parse_ts(inputs["to"])
    spot_cost = replace(model, latency=timedelta(0), max_wait=timedelta(0))
    rules = RuleService(portal.db).load(cutoff if inputs["rules_mode"] == "point-in-time" else None)[1]
    rows, totals = [], defaultdict(Decimal)
    for symbol, market in result["markets"].items():
        quantity = Decimal(market["holding"])
        if not quantity:
            continue
        row = _spot_exit(portal, rules, spot_cost, symbol, quantity, start, cutoff)
        totals[row["quote_currency"]] += Decimal(row["net_proceeds"])
        rows.append(row)
    return {"status": "DISPLAYED_BOOK_ESTIMATE", "cutoff": iso(cutoff), "max_age_seconds": 120,
            "basis": "One best bid per market before cutoff. No order submissions or FX conversion.",
            "net_proceeds_by_currency": {asset: str(proceeds) for asset, proceeds in totals.items()},
            "positions": rows}


def _spot_exit(portal, rules, cost, symbol, quantity, start, cutoff):
    inst = portal.instrument(symbol)
    row = {"symbol": symbol, "quote_currency": inst.quote, "units": str(quantity),
           "residual_units": str(quantity), "net_proceeds": "0", "receipt": None}
    top = None
    for receipt in portal.iter_tops(symbol, cutoff - timedelta(seconds=120), cutoff):
        top = receipt
    if top is None:
        return {**row, "status": "NO_FRESH_RECEIPT"}
    row.update(receipt=iso(top.ts_avail), bid=str(top.bid) if top.bid is not None else None,
               displayed_bid_units=str(top.bid_qty) if top.bid_qty is not None else None)
    if "CLOSED" in top.flags or is_closed(rules, inst, cutoff):
        return {**row, "status": "CLOSED"}
    if not qualified(top):
        return {**row, "status": "UNQUALIFIED_RECEIPT"}
    metadata = portal.metadata_at(symbol, start)
    flags = metadata["raw"] if metadata else {}
    model = cost.for_market(symbol, zero_fee=flags.get("isZeroFee", flags.get("is_zero_fee")) is True)
    book = CashBook({inst.base: quantity})
    fill = market_order(book, inst, "SELL", Decimal(1), cutoff, top.bid, [replace(top, ts_avail=cutoff)], 0,
                        model, portal.spec_at(symbol, cutoff), rules, {}, f"{symbol}/indicative-exit")
    residual = book.get(inst.base)
    status = (("PARTIAL" if residual else "COVERED") if fill["status"] == "FILLED" else fill["reason"])
    return {**row, "status": status, "residual_units": str(residual), "net_proceeds": str(book.get(inst.quote)),
            "modeled_fee": fill.get("fee"), "fee_currency": fill.get("fee_ccy")}


def _margin_attribution(positions, cash_posts, start):
    rows, by_currency = [], defaultdict(Decimal)
    for position in positions:
        ref, currency = position["id"], position["currency"]
        outcome = position["outcome"]
        collateral = Decimal(position["reserved_collateral"])
        release_at = position["release_at"]
        release = Decimal(outcome["cash_quote"]) if release_at else Decimal(0)
        expected = [("margin_collateral", start, currency, -collateral)]
        if release_at:
            expected.append(("margin_release", release_at, currency, release))
        actual = [(p["kind"], p["t"], p["ccy"], Decimal(p["amount"])) for p in cash_posts[ref] if p["kind"] != "rounding"]
        if actual != expected:
            raise ValueError(f"margin collateral or release posting mismatch: {ref}")
        if release_at:
            margin_mark = -Decimal(outcome["debt_quote"])
        elif outcome["equity_quote"] is not None:
            margin_mark = Decimal(outcome["equity_quote"])
        else:
            raise ValueError(f"unreleased margin position lacks a reported closing mark: {ref}")
        rounding = sum((Decimal(p["amount"]) for p in cash_posts[ref] if p["kind"] == "rounding"), Decimal(0))
        net = release + margin_mark - collateral + rounding
        by_currency[currency] += net
        rows.append({"id": ref, "symbol": position["symbol"], "currency": currency, "state": outcome["state"],
                     "collateral": str(collateral), "released_cash": str(release), "release_at": release_at,
                     "retained_equity": str(margin_mark), "retained_quote_debt": outcome["debt_quote"],
                     "retained_base_debt": outcome["debt_base"], "fees_by_currency": outcome["fees_by_currency"],
                     "net_quote": str(net)})
    return rows, by_currency


def _reconcile(run, start_fx, end_fx):
    inputs, result = run["inputs"], run["result"]
    explicit = "valuation_symbol" in inputs
    valuation = result["valuation"]["conversion"]
    reporting, secondary = (valuation["reporting_currency"], valuation["secondary_currency"]) if explicit else ("USDT", "TMN")
    units_key = "reporting_currency" if explicit else "usdt"
    opening = {asset: Decimal(amount) for asset, amount in inputs["cash_by_currency"].items()}
    closing = {asset: Decimal(amount) for asset, amount in result["balances"].items()}
    realized, unrealized, fees = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    fx = defaultdict(lambda: defaultdict(Decimal))
    booked, spot_flows = defaultdict(Decimal), defaultdict(Decimal)
    margin_positions = result.get("margin_positions", [])
    margin_posts = {position["id"]: [] for position in margin_positions}
    for post in result["postings"]:
        asset, amount = post["ccy"], Decimal(post["amount"])
        booked[asset] += amount
        if post["ref"] in margin_posts:
            margin_posts[post["ref"]].append(post)
            continue
        symbol, separator, _ = post["ref"].partition("#")
        if asset in opening:
            if separator and symbol in result["markets"]:
                spot_flows[symbol] += amount
            else:
                model, _, _ = post["ref"].partition("/")
                if model not in ("opening-funding", "otc-fx-rebalance", "otc-fx-route", "mixed-fx-route", "fx-rebalance"):
                    raise ValueError(f"unrecognized cash posting reference: {post['ref']}")
                fx[model][asset] += amount
    margin_rows, margin_net = _margin_attribution(margin_positions, margin_posts, inputs["from"])
    route_residuals = result.get("mixed_route_residuals", {})

    holdings = defaultdict(Decimal)
    net_quantity = defaultdict(Decimal)
    directional = []
    for symbol, market in result["markets"].items():
        inst = inputs["instruments"][symbol]
        base, quote = inst["base"], inst["quote"]
        quantity = Decimal(market["holding"])
        mark = quantity * Decimal(market["last_bid"]) if quantity else Decimal(0)
        holdings[quote] += mark
        net_quantity[base] += quantity
        net_realized = Decimal(market.get("realized_pnl", 0))
        net_unrealized = mark + spot_flows[symbol] - net_realized
        realized[quote] += net_realized
        unrealized[quote] += net_unrealized
        if quantity:
            directional.append((symbol, quote, quantity, net_unrealized, market["mark_status"]))
        for order in market["orders"]:
            if "fee" in order:
                fee = Decimal(order["fee"])
                fees[quote] += fee * Decimal(order["price"]) if order["fee_ccy"] == base else fee
    for asset, amount in route_residuals.items():
        net_quantity[asset] += Decimal(amount)

    def value_in_reporting(amounts, rate):
        return amounts.get(reporting, Decimal(0)) + amounts.get(secondary, Decimal(0)) / rate

    cash_end = value_in_reporting(opening, end_fx)
    initial = Decimal(result["start_cash"])
    terminal = Decimal(result["end"]["equity"])
    conversion = {model: value_in_reporting(flows, end_fx) for model, flows in fx.items()}
    legs = {"passive_cash_fx": cash_end - initial, "realized_spot_net": value_in_reporting(realized, end_fx),
            "unrealized_spot_net": value_in_reporting(unrealized, end_fx), "conversion_net": sum(conversion.values(), Decimal(0))}
    strategy_books = {"realized_spot_net": realized, "unrealized_spot_net": unrealized,
                      "conversion_net": {asset: sum((flows.get(asset, 0) for flows in fx.values()), Decimal(0))
                                         for asset in opening}}
    if margin_rows:
        legs["margin_net"] = value_in_reporting(margin_net, end_fx)
        strategy_books["margin_net"] = margin_net
    residual = terminal - initial - sum(legs.values(), Decimal(0))
    scale = Decimal("0.000000000000000001")
    cash_mismatch = {asset: str(closing.get(asset, 0) - booked[asset] - opening.get(asset, 0))
                     for asset in closing.keys() | booked.keys() | opening.keys()
                     if abs(closing.get(asset, 0) - booked[asset] - opening.get(asset, 0)) > scale}
    inventory_mismatch = {asset: str(closing.get(asset, 0) - net_quantity[asset])
                          for asset in closing.keys() | net_quantity.keys()
                          if asset not in opening and abs(closing.get(asset, 0) - net_quantity[asset]) > scale}
    if cash_mismatch or inventory_mismatch or abs(value_in_reporting(opening, start_fx) - initial) > scale or abs(residual) > scale:
        raise ValueError(f"portfolio attribution failed: postings={cash_mismatch}, inventory={inventory_mismatch}, residual={residual}")
    rounded_legs = {key: amount.quantize(scale) for key, amount in legs.items()}
    fx_basis = {}
    for key, amounts in strategy_books.items():
        opening_basis = value_in_reporting(amounts, start_fx)
        fx_basis[key] = {"booked_currencies": {asset: str(amounts.get(asset, 0)) for asset in opening},
                         f"opening_fx_{units_key}": str(opening_basis.quantize(scale)),
                         f"translation_to_terminal_fx_{units_key}": str((legs[key] - opening_basis).quantize(scale))}
    net = (terminal - initial).quantize(scale)
    ranked = sorted(((value_in_reporting({quote: pnl}, end_fx), symbol, quantity, freshness)
                     for symbol, quote, quantity, pnl, freshness in directional))
    rates = ({"conversion_pair": valuation["pair"], "secondary_currency": secondary,
              "opening_rate": str(start_fx), "closing_rate": str(end_fx)} if explicit else
             {"start_tmn_per_usdt": str(start_fx), "end_tmn_per_usdt": str(end_fx)})
    return {"run_id": run["run_id"], "outputs_digest": run["outputs_digest"], "currency": reporting,
            "valuation_status": result["end"]["valuation_status"], **rates,
            "opening_equity": str(initial), "ending_equity": str(terminal),
            "cash_only_end_equity": str(cash_end.quantize(scale)),
            "excess_vs_cash": str((terminal - cash_end).quantize(scale)),
            "net": str(net), "components": {key: str(amount) for key, amount in rounded_legs.items()},
            "strategy_fx_basis_by_component": fx_basis,
            **({"margin_positions": margin_rows} if margin_rows else {}),
            **({"unvalued_route_residual_units": route_residuals} if route_residuals else {}),
            "conversion_net_by_model": {key: str(amount.quantize(scale)) for key, amount in conversion.items()},
            "residual_at_display_precision": str(net - sum(rounded_legs.values(), Decimal(0))),
            f"raw_reconciliation_residual_{units_key}": str(residual.quantize(Decimal("1e-30"))),
            "closing_cash_by_currency": {asset: str(closing.get(asset, 0)) for asset in opening},
            "spot_inventory_value_by_quote": {asset: str(amount) for asset, amount in holdings.items()},
            "spot_fees_by_quote_at_fill_embedded_in_spot_pnl": {asset: str(amount) for asset, amount in fees.items()},
            "held_markets": len(ranked), "held_markets_with_stale_marks": sum(row[3] != "CURRENT" for row in ranked),
            "lowest_marked_open_position_pnl": [{"symbol": symbol, "quantity": str(quantity), "mark_status": freshness,
                                                f"net_{units_key}": str(pnl.quantize(scale))}
                                               for pnl, symbol, quantity, freshness in ranked[:10]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("market_db", type=Path)
    parser.add_argument("--store", choices=["live", "demo"], default="live")
    args = parser.parse_args()
    run = load_verified_run(args.run.parent, args.run.stem, store=args.store)
    db = MarketDB(args.market_db, readonly=True)
    try:
        print(json.dumps(audit(run, DataPortal(db, venue=run["inputs"].get("venue", "wallex"))), indent=2, sort_keys=True))
    finally:
        db.c.close()


if __name__ == "__main__":
    main()
