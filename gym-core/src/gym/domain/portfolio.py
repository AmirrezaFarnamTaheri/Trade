"""Joint paper-entry sizing from an explicitly ordered candidate list."""
import re
from decimal import ROUND_FLOOR, Decimal, localcontext

from .market_models import (
    currency,
    decimal,
    elapsed,
    fields,
    instant,
    position_sizing,
    rate,
)


def rebalance_preview(request):
    """Supplied holdings and targets only; sale proceeds are conditional, never settled cash."""
    fields(request, "quote_currency cash reserved_cash fee_rate positions")
    quote = currency(request["quote_currency"])
    cash, reserved = decimal(request["cash"], "cash"), decimal(request["reserved_cash"], "reserved_cash")
    fee = rate(request["fee_rate"], "fee_rate")
    positions = request["positions"]
    if reserved > cash or type(positions) is not list or not 1 <= len(positions) <= 100:
        raise ValueError("need reserved cash <= cash and 1..100 positions")
    with localcontext() as ctx:
        ctx.prec = 160
        parsed, symbols = [], set()
        for row in positions:
            fields(row, "symbol held reserved target_weight bid ask quantity_step minimum_quote")
            symbol = row["symbol"]
            if (type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol)
                    or not symbol.endswith(quote) or len(symbol) <= len(quote) or symbol in symbols):
                raise ValueError("need unique symbols in the declared quote currency")
            symbols.add(symbol)
            p = {key: decimal(row[key], key, positive=key in ("bid", "ask", "quantity_step"))
                 for key in ("held", "reserved", "bid", "ask", "quantity_step")}
            p.update(symbol=symbol, target_weight=decimal(row["target_weight"], "target_weight"),
                     minimum_quote=None if row["minimum_quote"] is None else decimal(row["minimum_quote"], "minimum_quote"))
            if p["bid"] > p["ask"] or p["reserved"] > p["held"] or p["target_weight"] > 1:
                raise ValueError("crossed quote or reserved quantity exceeds holding")
            parsed.append(p)
        if sum(p["target_weight"] for p in parsed) > 1:
            raise ValueError("target weights exceed one shared portfolio")
        equity = cash + sum(p["held"] * p["bid"] for p in parsed)
        if equity <= 0:
            raise ValueError("need positive supplied portfolio equity")
        available, sale_proceeds, turnover, legs = cash - reserved, Decimal(0), Decimal(0), []
        projected = {p["symbol"]: p["held"] for p in parsed}
        for side in ("SELL", "BUY"):
            for p in parsed:
                target = equity * p["target_weight"]
                current = p["held"] * p["bid"]
                if (side == "SELL") != (current > target) or current == target:
                    continue
                price, step = p["bid" if side == "SELL" else "ask"], p["quantity_step"]
                desired = ((current - target) / price if side == "SELL" else (target - current) / (p["bid"] * (1 - fee)))
                capacity = p["held"] - p["reserved"] if side == "SELL" else available / price
                quantity = (min(desired, capacity) / step).to_integral_value(rounding=ROUND_FLOOR) * step
                notional = quantity * price
                status = ("UNKNOWN_MINIMUM" if p["minimum_quote"] is None else "NO_CAPACITY" if not quantity
                          else "BELOW_MINIMUM" if notional < p["minimum_quote"] else "PLANNED")
                before = available
                if status == "PLANNED":
                    turnover += notional
                    if side == "SELL":
                        received = notional * (1 - fee)
                        sale_proceeds += received
                        available += received
                        projected[p["symbol"]] -= quantity
                    else:
                        available -= notional
                        projected[p["symbol"]] += quantity * (1 - fee)
                legs.append({"symbol": p["symbol"], "side": side, "status": status,
                             "gross_quantity": str(quantity), "notional_quote": str(notional),
                             "net_base_quantity": str(quantity * (1 - fee) if side == "BUY" else quantity),
                             "fee_currency": p["symbol"][:-len(quote)] if side == "BUY" else quote,
                             "fee_amount": str(quantity * fee if side == "BUY" else notional * fee),
                             "conditional_on_sale_settlement": side == "BUY" and notional > max(Decimal(0), before - sale_proceeds)})
        if available < 0:
            raise ValueError("precision cannot establish shared cash capacity")
        projected_equity = available + reserved + sum(projected[p["symbol"]] * p["bid"] for p in parsed)
        return {"schema": "rebalance-preview/1", "quote_currency": quote, "equity_at_supplied_bid": str(equity),
                "available_cash_before_sales": str(cash - reserved), "reserved_cash": str(reserved),
                "conditional_sale_proceeds": str(sale_proceeds), "conditional_remaining_cash": str(available),
                "turnover_quote": str(turnover), "turnover_fraction": str(turnover / equity), "legs": legs,
                "conditional_equity_after_costs": str(projected_equity),
                "concentration": [{"symbol": p["symbol"], "current_weight": str(p["held"] * p["bid"] / equity),
                                   "target_weight": str(p["target_weight"]), "conditional_held": str(projected[p["symbol"]]),
                                   "conditional_weight": str(projected[p["symbol"]] * p["bid"] / projected_equity) if projected_equity else None,
                                   "target_quantity_shortfall": str(equity * p["target_weight"] / p["bid"] - projected[p["symbol"]])} for p in parsed],
                "fee_assumption": "RECEIVED_ASSET", "holdings_authenticated": False,
                "cost_basis_known": False, "settlement_verified": False, "funded_authority": False}


def portfolio_sizing(quote_currency, equity, cash, total_risk_fraction, cash_buffer_fraction,
                     max_allocation_fraction, fee_rate, slippage_rate, candidates):
    currency(quote_currency)
    equity, cash = decimal(equity, "equity", positive=True), decimal(cash, "cash")
    risk, reserve = rate(total_risk_fraction, "total_risk_fraction"), rate(cash_buffer_fraction, "cash_buffer_fraction")
    allocation = decimal(max_allocation_fraction, "max_allocation_fraction")
    if allocation > 1:
        raise ValueError("max_allocation_fraction must not exceed one")
    fee, slip = rate(fee_rate, "fee_rate"), rate(slippage_rate, "slippage_rate")
    if cash > equity or not risk or not allocation:
        raise ValueError("need cash <= equity and positive total risk/allocation fractions")
    if type(candidates) is not list or not 1 <= len(candidates) <= 100:
        raise ValueError("need 1..100 explicitly ordered candidates")
    spent, loss, seen, outputs = Decimal(0), Decimal(0), set(), []
    for candidate in candidates:
        fields(candidate, "symbol entry_price stop_price risk_fraction max_position_fraction quantity_step")
        symbol = candidate["symbol"]
        if (type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol)
                or not symbol.endswith(quote_currency) or len(symbol) <= len(quote_currency) or symbol in seen):
            raise ValueError("candidates must have unique symbols in the declared quote currency")
        seen.add(symbol)
        sizing = position_sizing(quote_currency, equity, cash - spent,
                                 candidate["entry_price"], candidate["stop_price"], candidate["risk_fraction"],
                                 candidate["max_position_fraction"], reserve, candidate["quantity_step"], fee, slip)
        unit_cash = sizing["entry_price"] * (1 + slip)
        unit_loss = unit_cash - sizing["stop_price"] * (1 - slip) * (1 - fee)**2
        step = sizing["quantity_step"]
        quantity = min(sizing["gross_base_quantity"], max(Decimal(0), equity * risk - loss) / unit_loss,
                       max(Decimal(0), equity * allocation - spent) / unit_cash)
        quantity = (quantity / step).to_integral_value(rounding=ROUND_FLOOR) * step
        entry_cash, modeled_loss = quantity * unit_cash, quantity * unit_loss
        spent += entry_cash
        loss += modeled_loss
        outputs.append({"symbol": symbol, "rank": len(outputs) + 1,
                        "status": "SIZED" if quantity else "NO_CAPACITY",
                        "gross_base_quantity": quantity, "net_base_quantity": quantity * (1 - fee),
                        "entry_cash_quote": entry_cash, "modeled_loss_quote": modeled_loss})
    if spent > min(max(Decimal(0), cash - equity * reserve), equity * allocation) or loss > equity * risk:
        raise ValueError("precision cannot establish joint allocation limits")
    return {"quote_currency": quote_currency, "allocations": outputs,
            "entry_cash_quote": spent, "modeled_loss_quote": loss,
            "remaining_cash_quote": cash - spent, "cash_reserve_quote": equity * reserve,
            "risk_budget_quote": equity * risk, "allocation_budget_quote": equity * allocation,
            "existing_exposure_verified": False, "stop_execution_verified": False,
            "venue_minimums_verified": False,
            "assumptions": "new paper entries only, in supplied rank order; shared cash reserve and modeled "
                           "stop-loss budget; received-asset fees and adverse slippage; existing positions, "
                           "correlations, settlement and executable protection are not verified"}


def cashflow_returns(quote_currency, started_at, ended_at, initial_equity, final_equity, cashflows):
    """Time-weighted return requires an observed equity mark immediately before each flow."""
    currency(quote_currency)
    start, end = instant(started_at), instant(ended_at)
    initial, final = decimal(initial_equity, "initial_equity", positive=True), decimal(final_equity, "final_equity")
    if not start < end or type(cashflows) is not list or len(cashflows) > 1000:
        raise ValueError("need a positive period and at most 1000 ordered flows")
    previous, base, factor, total, weighted, available = start, initial, Decimal(1), Decimal(0), Decimal(0), True
    for row in cashflows:
        fields(row, "at equity_before_flow flow_quote equity_after_flow")
        at = instant(row["at"])
        before = decimal(row["equity_before_flow"], "equity_before_flow")
        after = decimal(row["equity_after_flow"], "equity_after_flow")
        # Flow is signed; validate its magnitude through the canonical exact-number boundary.
        raw = row["flow_quote"]
        if type(raw) is not str:
            raise ValueError("flow_quote must be an exact decimal string")
        flow = -decimal(raw[1:], "flow_quote") if raw.startswith("-") else decimal(raw, "flow_quote")
        if not previous < at < end or after != before + flow:
            raise ValueError("flows must be strictly ordered inside the period with after = before + flow")
        if base:
            factor *= before / base
        else:
            available = False
        total += flow
        weighted += flow * elapsed(at, end) / elapsed(start, end)
        previous, base = at, after
    if base:
        factor *= final / base
    else:
        available = False
    net, denominator = final - initial - total, initial + weighted
    return {"quote_currency": quote_currency, "external_flow_quote": total, "net_profit_quote": net,
            "time_weighted_return_percent": (factor - 1) * 100 if available else None,
            "time_weighted_status": "CALCULATED" if available else "UNAVAILABLE_ZERO_EQUITY",
            "modified_dietz_return_percent": net / denominator * 100 if denominator > 0 else None,
            "dietz_denominator_quote": denominator, "flow_count": len(cashflows),
            "inputs_verified": False, "cashflows_reconciled": False,
            "assumptions": "single quote currency; pre/post-flow equity marks at each external contribution or withdrawal; "
                           "fees and unrealized holdings belong in supplied equity, not external flows; "
                           "Dietz assumes linear time weights and is an approximation. No prices or missing equity marks are synthesized."}
