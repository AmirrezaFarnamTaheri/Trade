"""Deterministic portfolio replay output/receipt construction from explicit inputs."""
from __future__ import annotations

from decimal import Decimal

from ...domain.model import iso
from ...domain.performance import performance
from ...domain.strategy import digest


def build_portfolio_output(
    *,
    quote: str,
    cash: Decimal,
    t1,
    end_equity: Decimal,
    valuation_status: str,
    curve: list,
    valuation: dict,
    inputs: dict,
    markets: dict,
    balances: dict,
    booked_accounting: bool,
    postings: list | None,
    variable_routes: bool,
    route_changes: list | None,
    funding_result,
    fx_rebalance,
    fx_orders: list | None,
    mixed_residuals: dict | None,
    margin_report: list | None,
    risk_state,
    rank_gate_events: list | None,
    policy_active: bool,
    policy_events: list | None,
    policy_weights: dict | None,
    multicurrency: bool,
) -> dict:
    """Assemble exact portfolio replay receipt, performance block, and deterministic digests."""
    first_fx, last_fx = valuation["start"], valuation["end"]
    result = {
        "quote": quote,
        "start_cash": str(cash),
        "curve": curve,
        "orders": [],
        "markets": markets,
        "valuation": valuation,
        "balances": {k: str(v) for k, v in balances.items()},
        "end": {
            "mark_time": iso(t1),
            "equity": str(end_equity),
            "net": str(end_equity - cash),
            "valuation_status": valuation_status,
        },
    }
    if booked_accounting:
        result["postings"] = postings
    if variable_routes:
        result["route_changes"] = route_changes
    if funding_result is not None:
        result["opening_funding"] = funding_result
    if fx_rebalance is not None:
        result["fx_orders"] = fx_orders
    if mixed_residuals is not None:
        result["mixed_route_residuals"] = {asset: str(amount) for asset, amount in mixed_residuals.items()}
    if margin_report is not None:
        result["margin_positions"] = margin_report
        result["margin_risk_state"] = risk_state
    if rank_gate_events is not None:
        result["rank_gate"] = rank_gate_events
    if policy_active:
        result["policy_events"] = policy_events
        result["policy_state"] = {
            "risk": risk_state,
            "weights": policy_weights,
            "clock": "Asia/Tehran",
            "scope": (
                "Targets use prior closed returns. Optional rebalancing adjusts at subsequent decisions "
                "through normal fill/rule/cost checks; it does not assume unsettled sale proceeds. "
                "Risk exits use the next decision and executable quote. Limits can overshoot across gaps, fees or closures."
            ),
        }
        if multicurrency:
            result["policy_state"].update(
                weights={"status": policy_weights["status"]},
                scope="Spot entries apply the weight cap and cash buffer within each quote currency.",
            )
    if quote == "USDT":
        result["end"]["net_usdt_eq"] = str(end_equity - cash)
    elif first_fx["rate"] and last_fx["rate"]:
        result["end"]["net_usdt_eq"] = str(
            (end_equity / Decimal(last_fx["rate"]) - cash / Decimal(first_fx["rate"])).quantize(Decimal("0.0001"))
        )
    else:
        result["end"]["net_usdt_eq"] = None

    out = {"run_id": digest(inputs)[:16], "mode": "PORTFOLIO", "inputs": inputs, "result": result}
    from ..reports import sampled_drawdown

    out["performance"] = {
        k: v for k, v in performance(out, sampled_drawdown(out)).items() if k not in ("ledger", "trades")
    }
    out["outputs_digest"] = digest(result)[:16]
    return out
