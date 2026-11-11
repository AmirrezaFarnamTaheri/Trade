"""Pre-registration cost gate (report 4.10, TS-3): declare turnover and costs before a test window is used.

A strategy whose declared gross edge per round trip does not clear its declared round-trip cost is arithmetically
dead and is refused at registration, so no trial or test window is spent on it. The declared round-trip cost can
never be below two venue fees.
"""
from __future__ import annotations

from decimal import Decimal

from .market_models import decimal, fields


def cost_gate(declaration, fee_rate: Decimal) -> dict:
    fields(declaration, "trades_per_month roundtrip_cost_bps expected_gross_edge_bps")
    trades = declaration["trades_per_month"]
    if type(trades) is not int or not 1 <= trades <= 10000:
        raise ValueError("trades_per_month must be an integer 1..10000")
    cost = decimal(declaration["roundtrip_cost_bps"], "roundtrip_cost_bps", positive=True)
    edge = decimal(declaration["expected_gross_edge_bps"], "expected_gross_edge_bps")
    floor = 2 * fee_rate * 10000
    if cost < floor:
        raise ValueError(f"roundtrip_cost_bps {cost} is below two venue fees ({floor} bps)")
    if edge <= cost:
        raise ValueError(f"declared gross edge {edge} bps does not clear the {cost} bps round-trip cost: "
                         "arithmetically dead, not registered")
    return {"trades_per_month": trades, "roundtrip_cost_bps": str(cost), "expected_gross_edge_bps": str(edge),
            "break_even_edge_bps": str(cost), "net_edge_bps": str(edge - cost),
            "monthly_cost_drag_bps": str(cost * trades), "basis": "operator declaration before the window"}
