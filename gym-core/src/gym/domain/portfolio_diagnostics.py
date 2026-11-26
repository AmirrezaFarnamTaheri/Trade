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
    if not quote or quote not in (res.get("balances") or {}) or (res.get("end") or {}).get("equity") is None:
        return {"currency": quote, "reconciled": False, "errors": ["MISSING_TERMINAL_ACCOUNTING"],
                "causal_alpha_claim": False}
    start_cash = Decimal(res["start_cash"])
    end_cash = Decimal(res["balances"][quote])
    end_equity = Decimal(res["end"]["equity"])
    postings = res.get("postings") or []
    quote_fees = sum((-Decimal(p["amount"]) for p in postings if p["ccy"] == quote and p["kind"] == "fee"), Decimal(0))
    reconstructed = {quote: start_cash}
    for posting in postings:
        currency = posting["ccy"]
        reconstructed[currency] = reconstructed.get(currency, Decimal(0)) + Decimal(posting["amount"])
    reported = {currency: Decimal(value) for currency, value in res["balances"].items()}
    balance_residuals = {currency: reconstructed.get(currency, Decimal(0)) - reported.get(currency, Decimal(0))
                         for currency in sorted(reconstructed.keys() | reported.keys())}
    errors = []
    if "postings" not in res:
        errors.append("MISSING_POSTINGS")
    realized = open_cost = inventory_mark_value = Decimal(0)
    covered = {quote}
    for symbol, market in sorted((res.get("markets") or {}).items()):
        if not symbol.endswith(quote) or symbol == quote:
            errors.append(f"UNKNOWN_QUOTE:{symbol}")
            continue
        base = symbol[:-len(quote)]
        quantity = reconstructed.get(base, Decimal(0))
        if base in covered:
            errors.append(f"DUPLICATE_ASSET:{base}")
            continue
        covered.add(base)
        try:
            ledger = trade_ledger(market.get("orders", []), base, quote=quote,
                                  postings=[p for p in postings if p["ref"].startswith(f"{symbol}#")])
        except ValueError:
            errors.append(f"INVALID_TRADE_LEDGER:{symbol}")
            continue
        if quantity != Decimal(ledger["open"]["quantity"]) or (
            market.get("holding") is not None and quantity != Decimal(market["holding"])
        ):
            errors.append(f"INVENTORY_MISMATCH:{symbol}")
        realized += sum((Decimal(trade["pnl"]) for trade in ledger["trades"]), Decimal(0))
        open_cost += Decimal(ledger["open"]["cost"])
        if quantity:
            if market.get("last_bid") is None or Decimal(market["last_bid"]) <= 0:
                errors.append(f"MISSING_MARK:{symbol}")
            else:
                inventory_mark_value += quantity * Decimal(market["last_bid"])
    if any(balance for asset, balance in reconstructed.items() if asset not in covered):
        errors.append("UNVALUED_ASSETS")
    net_change = end_equity - start_cash
    unrealized_plus_basis = inventory_mark_value - open_cost
    residual = reconstructed[quote] + inventory_mark_value - end_equity
    pnl_residual = start_cash + realized + unrealized_plus_basis - end_equity
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
        "open_inventory_cost": str(open_cost),
        "balance_residuals": {currency: str(value) for currency, value in balance_residuals.items()},
        "pnl_residual": str(pnl_residual),
        "errors": errors,
        "reconciliation_residual": "0" if residual == 0 else format(residual, "f"),
        "reconciled": residual == 0 and pnl_residual == 0 and not any(balance_residuals.values()) and not errors,
        "fx_attribution": _fx_attribution(res, start_cash, reconstructed[quote] + inventory_mark_value),
        "directional_attribution": _directional_attribution(res, net_change),
        "causal_alpha_claim": False,
    }


def _directional_attribution(result, net_change):
    """Value gross trade flows and signed fees separately at the same terminal bids."""
    quote = result["quote"]
    marks = {symbol[:-len(quote)]: market.get("last_bid")
             for symbol, market in result.get("markets", {}).items() if symbol.endswith(quote)}
    marks[quote] = "1"
    flows = {"gross_directional_quote": {}, "signed_fees_at_terminal_bid": {}}
    if "postings" not in result:
        return {"status": "MISSING_POSTINGS"}
    for posting in result["postings"]:
        if posting["kind"] not in ("buy", "sell", "fee"):
            continue
        bucket = flows["signed_fees_at_terminal_bid" if posting["kind"] == "fee" else "gross_directional_quote"]
        asset = posting["ccy"]
        bucket[asset] = bucket.get(asset, Decimal(0)) + Decimal(posting["amount"])
    components = {}
    for name, amounts in flows.items():
        total = Decimal(0)
        for asset, amount in amounts.items():
            if amount:
                if marks.get(asset) is None or Decimal(marks[asset]) <= 0:
                    return {"status": "MISSING_TERMINAL_MARK", "asset": asset}
                total += amount * Decimal(marks[asset])
        components[name] = total
    residual = net_change - sum(components.values())
    return {"status": "RECONCILED" if not residual else "RESIDUAL", "currency": quote,
            **{name: str(total) for name, total in components.items()}, "unexplained_quote": str(residual)}


def _fx_attribution(result, start_cash, reconstructed_equity):
    """Translate quote movements at the opening rate and isolate revaluation at the closing rate."""
    valuation = result.get("valuation") or {}
    opening, closing = valuation.get("start") or {}, valuation.get("end") or {}
    reported = result["end"].get("net_usdt_eq")
    if opening.get("rate") is None or closing.get("rate") is None or reported is None:
        return {"status": "MISSING_FX_EVIDENCE"}
    start_rate, end_rate = Decimal(opening["rate"]), Decimal(closing["rate"])
    if not all(rate.is_finite() and rate > 0 for rate in (start_rate, end_rate)):
        return {"status": "INVALID_FX_EVIDENCE"}
    quote_pnl = (reconstructed_equity - start_cash) / start_rate
    translation = reconstructed_equity / end_rate - reconstructed_equity / start_rate
    expected = quote_pnl + translation
    if result["quote"] != "USDT":
        expected = expected.quantize(Decimal("0.0001"))
    residual = expected - Decimal(reported)
    return {"status": "DIAGNOSTIC_ONLY", "open_rate_status": opening.get("status"),
            "close_rate_status": closing.get("status"), "quote_pnl_at_open_fx_usdt": str(quote_pnl),
            "terminal_fx_translation_usdt": str(translation), "reported_net_usdt": str(reported),
            "reconstructed_net_usdt": str(expected), "translation_residual_usdt": str(residual)}


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
