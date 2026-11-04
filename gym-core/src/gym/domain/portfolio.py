"""Joint paper-entry sizing from an explicitly ordered candidate list."""
import re
from decimal import Decimal, ROUND_FLOOR

from .market_models import currency, decimal, fields, position_sizing, rate


def portfolio_sizing(quote_currency, equity, cash, total_risk_fraction, cash_buffer_fraction,
                     max_allocation_fraction, fee_rate, slippage_rate, candidates):
    currency(quote_currency)
    equity, cash = decimal(equity, "equity", positive=True), decimal(cash, "cash")
    risk, reserve, allocation = (rate(value, name) for value, name in (
        (total_risk_fraction, "total_risk_fraction"), (cash_buffer_fraction, "cash_buffer_fraction"),
        (max_allocation_fraction, "max_allocation_fraction")))
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
