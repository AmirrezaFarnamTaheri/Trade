"""Exact after-cost TMN return decomposition into USDT and exchange-rate effects."""
from decimal import Decimal, localcontext


def toman_attribution(out):
    """Show USDT return, TMN/USDT move, and their product without double counting."""
    result = out["result"]
    if result.get("quote") != "TMN":
        return {"status": "NOT_APPLICABLE", "currency": result.get("quote")}
    end = result.get("end")
    valuation = result.get("valuation", {})
    if out.get("mode") == "PORTFOLIO":
        start_rate = (valuation.get("start") or {}).get("rate")
        end_rate = (valuation.get("end") or {}).get("rate")
    else:
        fx = out.get("fx") or {}
        start_rate, end_rate = fx.get("start"), fx.get("end")
    if not end or end.get("equity") is None or start_rate is None or end_rate is None:
        return {"status": "UNAVAILABLE", "reason": "MISSING_POINT_IN_TIME_FX"}
    with localcontext() as context:
        context.prec = 80
        try:
            cash, equity = Decimal(result["start_cash"]), Decimal(end["equity"])
            first, last = Decimal(start_rate), Decimal(end_rate)
        except (ValueError, ArithmeticError, TypeError):
            return {"status": "UNAVAILABLE", "reason": "INVALID_FX_OR_EQUITY"}
        if any(not x.is_finite() or x <= 0 for x in (cash, equity, first, last)):
            return {"status": "UNAVAILABLE", "reason": "INVALID_FX_OR_EQUITY"}
        precision = Decimal("0.0000000000000001")
        total = (equity / cash - 1).quantize(precision)
        usdt = ((equity / last) / (cash / first) - 1).quantize(precision)
        move = (last / first - 1).quantize(precision)
        # Use the exact residual at disclosure precision to keep the displayed sum exact.
        interaction = total - usdt - move
        if abs(interaction - usdt * move) > precision * (3 + abs(usdt) + abs(move)):
            return {"status": "UNAVAILABLE", "reason": "IDENTITY_CHECK_FAILED"}
        return {"status": "AVAILABLE", "currency": "TMN",
                "usdt_return": str(usdt), "toman_move": str(move),
                "interaction": str(interaction), "total_toman_return": str(total),
                "component_sum": str(usdt + move + interaction),
                "precision": str(precision), "funded_authority": False,
                "basis": "(1 + USDT return) * (1 + TMN-per-USDT move) - 1; causal recorded FX midpoints."}
