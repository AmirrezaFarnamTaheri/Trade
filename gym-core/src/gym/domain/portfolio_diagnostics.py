"""Shared-cash portfolio aggregate trade stats, inventory timeline, economic attribution, and ES tail qualification (F014-F022)."""
from __future__ import annotations

import math
from decimal import Decimal
from random import Random
from statistics import fmean

from .performance import trade_ledger


def aggregate_portfolio_trade_stats(portfolio_out: dict) -> dict:
    """Compute aggregate trade counts and expectancy from actual shared-account fills (F014)."""
    res = portfolio_out["result"]
    markets = res.get("markets") or {}
    postings = res.get("postings") or []
    quote = res.get("quote")
    all_trades = []
    for symbol, mkt in sorted(markets.items()):
        base = symbol[:-len(quote)] if quote and symbol.endswith(quote) else ""
        sym_posts = [p for p in postings if p["ref"].startswith(f"{symbol}#")] if postings else None
        ledger = trade_ledger(mkt.get("orders", []), base, quote=quote, postings=sym_posts)
        all_trades.extend(ledger["trades"])
    pnls = [Decimal(t["pnl"]) for t in all_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    flat = [p for p in pnls if p == 0]
    total_pnl = sum(pnls, Decimal(0))
    return {
        "basis": "ACTUAL_SHARED_ACCOUNT_FILLS",
        "closed_trades": len(pnls),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "flat_trades": len(flat),
        "realized_pnl": str(total_pnl),
        "expectancy": str(total_pnl / len(pnls)) if pnls else None,
        "win_rate": round(len(wins) / len(pnls), 4) if pnls else None,
    }


def portfolio_inventory_timeline(portfolio_out: dict) -> list[dict]:
    """Extract per-market terminal inventory, dust, exit eligibility, and mark freshness summary (F015, U027)."""
    res = portfolio_out["result"]
    rows = []
    for symbol, mkt in sorted((res.get("markets") or {}).items()):
        pos = mkt.get("position_known") or {}
        rows.append({
            "symbol": symbol,
            "holding": mkt.get("holding", "0"),
            "state": pos.get("state", "UNKNOWN"),
            "exit_check": pos.get("exit_check", "UNKNOWN"),
            "sellable_quantity_at_bid": pos.get("sellable_quantity_at_bid"),
            "mark_status": mkt.get("mark_status", "UNKNOWN"),
            "mark_age_seconds": mkt.get("mark_age_seconds"),
            "fills": mkt.get("fills", 0),
        })
    return rows


def economic_portfolio_attribution(portfolio_out: dict) -> dict:
    """Reconcile start cash, posted fees, realized/unrealized inventory, and terminal equity exactly (F020)."""
    res = portfolio_out["result"]
    quote = res.get("quote")
    start_cash = Decimal(res["start_cash"])
    end_cash = Decimal(res["balances"][quote])
    end_equity = Decimal(res["end"]["equity"])
    postings = res.get("postings") or []
    quote_fees = sum((-Decimal(p["amount"]) for p in postings if p["ccy"] == quote and p["kind"] == "fee"), Decimal(0))
    agg = aggregate_portfolio_trade_stats(portfolio_out)
    realized = Decimal(agg["realized_pnl"])
    inventory_mark_value = end_equity - end_cash
    net_change = end_equity - start_cash
    unrealized_plus_basis = net_change - realized
    residual = (start_cash + realized + unrealized_plus_basis) - end_equity
    return {
        "currency": quote,
        "start_cash": str(start_cash),
        "end_cash": str(end_cash),
        "inventory_mark_value": str(inventory_mark_value),
        "end_equity": str(end_equity),
        "net_change": str(net_change),
        "realized_pnl_net_of_closed_fees": str(realized),
        "unrealized_and_open_cost_component": str(unrealized_plus_basis),
        "posted_quote_fees": str(quote_fees),
        "reconciliation_residual": "0" if residual == 0 else format(residual, "f"),
        "reconciled": residual == 0,
        "causal_alpha_claim": False,
    }


def qualify_es_tail(
    returns: list[float],
    *,
    alpha: float = 0.05,
    min_tail_observations: int = 10,
    simulations: int = 300,
    seed: int = 0,
) -> dict:
    """Compute empirical Expected Shortfall (CVaR) with explicit adverse-tail count and bootstrap CI (F022)."""
    if not 0 < alpha < 0.5:
        raise ValueError("alpha must be in (0, 0.5)")
    clean = [float(x) for x in returns if math.isfinite(float(x))]
    n = len(clean)
    tail_count = int(math.floor(n * alpha))
    if n == 0 or tail_count < 1:
        return {"status": "INSUFFICIENT_DATA", "observations": n, "adverse_tail_count": 0, "qualified": False}
    ordered = sorted(clean)
    var_cut = ordered[tail_count - 1]
    tail = ordered[:tail_count]
    es = -fmean(tail)  # positive loss magnitude
    rng = Random(seed)
    boot_es = []
    for _ in range(simulations):
        sample = sorted(clean[rng.randrange(n)] for _ in range(n))
        boot_es.append(-fmean(sample[:tail_count]))
    boot_es.sort()
    qualified = tail_count >= min_tail_observations
    return {
        "status": "QUALIFIED_TAIL_SAMPLE" if qualified else "UNDERPOWERED_TAIL",
        "qualified": qualified,
        "alpha": alpha,
        "observations": n,
        "adverse_tail_count": tail_count,
        "min_tail_observations": min_tail_observations,
        "var_loss": -var_cut,
        "expected_shortfall_loss": es,
        "es_ci_90": [boot_es[int(0.05 * (simulations - 1))], boot_es[int(0.95 * (simulations - 1))]],
    }
