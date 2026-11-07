"""Conservative, exact-decimal, one-shot paper TWAP preview.

No venue transport, credential, privileged IPC, live order or scheduling authority.
"""
from bisect import bisect_left
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal, localcontext
from itertools import pairwise

from ..domain.bars import qualified
from ..domain.market_models import rate
from ..domain.model import iso
from ..domain.strategy import digest

MAX_QUOTES = 100000


def _floor(value, decimals):
    """Floor an exact child quantity to an instrument's recorded base precision."""
    if decimals is None:
        return value
    if type(decimals) is not int or not 0 <= decimals <= 18:
        raise ValueError("invalid quantity precision")
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)


def simulate_twap(instrument, quotes, spec, start, end, *, side, quantity, slices,
                  participation, fee_rate, available_quote, available_base,
                  max_delay_seconds, store):
    """Model bounded child attempts without reusing observed top-of-book capacity."""
    if store not in ("live", "demo") or side not in ("BUY", "SELL"):
        raise ValueError("unsupported paper TWAP mode")
    if type(slices) is not int or not 1 <= slices <= 100:
        raise ValueError("TWAP needs 1..100 slices")
    if type(max_delay_seconds) is not int or not 0 <= max_delay_seconds <= 3600:
        raise ValueError("invalid maximum fill delay")
    if not start < end or end - start > timedelta(days=1):
        raise ValueError("TWAP requires a positive window of at most one day")
    for name, value, positive in (
        ("quantity", quantity, True), ("participation", participation, True),
        ("available_quote", available_quote, False), ("available_base", available_base, False)
    ):
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0 or (positive and value == 0):
            raise ValueError("invalid exact " + name)
    if participation > 1:
        raise ValueError("participation cannot exceed one")
    fee = rate(str(fee_rate))
    if len(quotes) > MAX_QUOTES or any(q.symbol != instrument.symbol for q in quotes):
        raise ValueError("invalid quote series")
    if any(a.ts_avail > b.ts_avail for a, b in pairwise(quotes)):
        raise ValueError("quotes are not availability ordered")
    if any(not start <= q.ts_avail < end for q in quotes):
        raise ValueError("quote outside preview window")
    times = [q.ts_avail for q in quotes]
    remaining_quote, remaining_base = available_quote, available_base
    filled = received_base = received_quote = fee_base = fee_quote = spent_quote = Decimal(0)
    children = []
    last_used = -1
    with localcontext() as context:
        context.prec = 80
        unit = _floor(quantity / Decimal(slices), spec.qty_decimals)
        if unit <= 0:
            raise ValueError("slice quantity below supported precision")
        for idx in range(slices):
            slot = start + (end - start) * idx / slices
            target = unit if idx < slices - 1 else quantity - unit * (slices - 1)
            target = _floor(target, spec.qty_decimals)
            first = bisect_left(times, slot)
            chosen = None
            if first < len(quotes) and first != last_used:
                candidate = quotes[first]
                if candidate.ts_avail - slot <= timedelta(seconds=max_delay_seconds):
                    chosen = candidate
                    last_used = first
            reason = "NO_TIMELY_QUOTE"
            qty = Decimal(0)
            price = None
            if chosen is not None:
                if not qualified(chosen) or "CLOSED" in chosen.flags:
                    reason = "UNQUALIFIED_OR_CLOSED"
                else:
                    price = chosen.ask if side == "BUY" else chosen.bid
                    displayed = chosen.ask_qty if side == "BUY" else chosen.bid_qty
                    if displayed is None or not displayed.is_finite() or displayed <= 0:
                        reason = "UNKNOWN_DISPLAYED_CAPACITY"
                    else:
                        available = remaining_quote / price if side == "BUY" else remaining_base
                        qty = _floor(min(target, displayed * participation, available), spec.qty_decimals)
                        notional = qty * price
                        if (qty <= 0 or (spec.min_qty is not None and qty < spec.min_qty)
                                or (spec.min_notional is not None and notional < spec.min_notional)):
                            qty = Decimal(0)
                            reason = "BELOW_LIMIT_OR_BALANCE"
                        else:
                            reason = "MODELED_FILL"
                            if side == "BUY":
                                remaining_quote -= notional
                                spent_quote += notional
                                fee_base += qty * fee
                                received_base += qty * (1 - fee)
                                remaining_base += qty * (1 - fee)
                            else:
                                remaining_base -= qty
                                gross = qty * price
                                fee_quote += gross * fee
                                received_quote += gross * (1 - fee)
                                remaining_quote += gross * (1 - fee)
            filled += qty
            status = "NONFILL" if qty == 0 else "FILLED" if qty == target else "PARTIAL"
            children.append({"slice": idx + 1, "scheduled_at": iso(slot),
                             "observation_at": iso(chosen.ts_avail) if chosen else None,
                             "requested_quantity": str(target), "filled_quantity": str(qty),
                             "unfilled_quantity": str(target - qty), "status": status,
                             "reason": reason, "price": str(price) if price is not None else None})
    # The child split can contain 80-digit repeating fractions when a market
    # has no known quantity precision; Python's default 28 digits are unsafe.
    with localcontext() as context:
        context.prec = 160
        cancelled = quantity - filled
        if cancelled < 0 or remaining_quote < 0 or remaining_base < 0:
            raise ArithmeticError("paper TWAP reservation conservation violated")
        total_children = sum((Decimal(child["requested_quantity"]) for child in children), Decimal(0))
        if total_children + (quantity - _floor(quantity, spec.qty_decimals)) != quantity:
            raise ArithmeticError("TWAP children do not conserve requested quantity")
    result = {"schema": "paper-twap/1", "symbol": instrument.symbol, "side": side, "store": store,
              "synthetic": store == "demo", "start": iso(start), "end_exclusive": iso(end),
              "requested_quantity": str(quantity), "filled_quantity": str(filled),
              "cancelled_quantity": str(cancelled), "spent_quote": str(spent_quote),
              "received_base": str(received_base), "received_quote": str(received_quote),
              "fee_base": str(fee_base), "fee_quote": str(fee_quote),
              "remaining_quote": str(remaining_quote), "remaining_base": str(remaining_base),
              "initial_quote": str(available_quote), "initial_base": str(available_base),
              "fee_rate": str(fee), "participation": str(participation),
              "max_delay_seconds": max_delay_seconds, "children": children,
              "authority": "PAPER_ONLY", "funded_authority": False, "order_submitted": False,
              "cancel_submitted": False,
              "limitations": ["Simulated child attempts at fixed slots; unused quantity expires, never resubmitted.",
                              "Only the first eligible post-slot public top quote is considered; no matching-engine fills or queue priority.",
                              "No proof of venue open state, fees, settlement, live reservations, cancellation, latency or executable capacity.",
                              "Independent research budgets; no protected-executor IPC or venue writes."]}
    result["report_id"] = digest(result)[:16]
    return result
