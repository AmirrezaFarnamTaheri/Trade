"""Audit a saved mixed-currency paper replay against its archived market database."""

import argparse
import json
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, localcontext
from pathlib import Path

from gym.adapters.run_store import load_verified_run
from gym.adapters.store import MarketDB
from gym.domain.bars import qualified
from gym.domain.model import parse_ts
from gym.services.data_portal import DataPortal


def _fx_mid(portal, stamp):
    at = parse_ts(stamp)
    top = None
    for receipt in portal.iter_tops("USDTTMN", at, at + timedelta(microseconds=1)):
        if qualified(receipt):
            top = receipt
    if top is None:
        raise ValueError(f"archived FX mark missing at {stamp}")
    return (top.bid + top.ask) / 2


def audit(run, portal):
    """Separate opening cash exposure, booked spot P&L and conversion cash flows."""
    inputs, result = run["inputs"], run["result"]
    if inputs.get("trade_accounting") != "booked-notional/1" or not inputs.get("cash_by_currency"):
        raise ValueError("audit requires a booked mixed-currency portfolio")
    if result.get("margin_positions") or result.get("mixed_route_residuals"):
        raise ValueError("audit requires a cash and spot account without margin or residual route inventory")
    conversion = result["valuation"]["conversion"]
    with localcontext() as ctx:
        ctx.prec = 400
        start_fx = _fx_mid(portal, conversion["start_at"])
        end_fx = _fx_mid(portal, conversion["end_at"])
        return _reconcile(run, start_fx, end_fx)


def _reconcile(run, start_fx, end_fx):
    inputs, result = run["inputs"], run["result"]
    opening = {asset: Decimal(amount) for asset, amount in inputs["cash_by_currency"].items()}
    closing = {asset: Decimal(amount) for asset, amount in result["balances"].items()}
    realized, unrealized, fees = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    fx = defaultdict(lambda: defaultdict(Decimal))
    booked, spot_flows = defaultdict(Decimal), defaultdict(Decimal)
    for post in result["postings"]:
        asset, amount = post["ccy"], Decimal(post["amount"])
        booked[asset] += amount
        symbol, separator, _ = post["ref"].partition("#")
        if asset in opening:
            if separator and symbol in result["markets"]:
                spot_flows[symbol] += amount
            else:
                model, _, _ = post["ref"].partition("/")
                if model not in ("opening-funding", "otc-fx-rebalance", "otc-fx-route", "mixed-fx-route", "fx-rebalance"):
                    raise ValueError(f"unrecognized cash posting reference: {post['ref']}")
                fx[model][asset] += amount

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

    def usdt(amounts, rate):
        return amounts.get("USDT", Decimal(0)) + amounts.get("TMN", Decimal(0)) / rate

    cash_end = usdt(opening, end_fx)
    initial = Decimal(result["start_cash"])
    terminal = Decimal(result["end"]["equity"])
    conversion = {model: usdt(flows, end_fx) for model, flows in fx.items()}
    legs = {"passive_cash_fx": cash_end - initial, "realized_spot_net": usdt(realized, end_fx),
            "unrealized_spot_net": usdt(unrealized, end_fx), "conversion_net": sum(conversion.values(), Decimal(0))}
    residual = terminal - initial - sum(legs.values(), Decimal(0))
    scale = Decimal("0.000000000000000001")
    cash_mismatch = {asset: str(closing.get(asset, 0) - booked[asset] - opening.get(asset, 0))
                     for asset in closing.keys() | booked.keys() | opening.keys()
                     if abs(closing.get(asset, 0) - booked[asset] - opening.get(asset, 0)) > scale}
    inventory_mismatch = {asset: str(closing.get(asset, 0) - net_quantity[asset])
                          for asset in closing.keys() | net_quantity.keys()
                          if asset not in opening and abs(closing.get(asset, 0) - net_quantity[asset]) > scale}
    if cash_mismatch or inventory_mismatch or abs(usdt(opening, start_fx) - initial) > scale or abs(residual) > scale:
        raise ValueError(f"portfolio attribution failed: postings={cash_mismatch}, inventory={inventory_mismatch}, residual={residual}")
    rounded_legs = {key: amount.quantize(scale) for key, amount in legs.items()}
    net = (terminal - initial).quantize(scale)
    ranked = sorted(((usdt({quote: pnl}, end_fx), symbol, quantity, freshness)
                     for symbol, quote, quantity, pnl, freshness in directional))
    return {"run_id": run["run_id"], "outputs_digest": run["outputs_digest"], "currency": "USDT",
            "valuation_status": result["end"]["valuation_status"], "start_tmn_per_usdt": str(start_fx),
            "end_tmn_per_usdt": str(end_fx), "opening_equity": str(initial), "ending_equity": str(terminal),
            "cash_only_end_equity": str(cash_end.quantize(scale)),
            "excess_vs_cash": str((terminal - cash_end).quantize(scale)),
            "net": str(net), "components": {key: str(amount) for key, amount in rounded_legs.items()},
            "conversion_net_by_model": {key: str(amount.quantize(scale)) for key, amount in conversion.items()},
            "residual_at_display_precision": str(net - sum(rounded_legs.values(), Decimal(0))),
            "raw_reconciliation_residual_usdt": str(residual.quantize(Decimal("1e-30"))),
            "closing_cash_by_currency": {asset: str(closing.get(asset, 0)) for asset in opening},
            "spot_inventory_value_by_quote": {asset: str(amount) for asset, amount in holdings.items()},
            "spot_fees_by_quote_at_fill_embedded_in_spot_pnl": {asset: str(amount) for asset, amount in fees.items()},
            "held_markets": len(ranked), "held_markets_with_stale_marks": sum(row[3] != "CURRENT" for row in ranked),
            "lowest_marked_open_position_pnl": [{"symbol": symbol, "quantity": str(quantity), "mark_status": freshness,
                                                "net_usdt": str(pnl.quantize(scale))}
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
        print(json.dumps(audit(run, DataPortal(db)), indent=2, sort_keys=True))
    finally:
        db.c.close()


if __name__ == "__main__":
    main()
