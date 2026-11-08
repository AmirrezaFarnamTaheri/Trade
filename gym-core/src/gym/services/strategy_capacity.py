"""Capacity diagnostics: impact-eats-half-edge estimate for verified paper runs."""
from decimal import Decimal, localcontext

from ..domain.model import parse_ts


def _missing(status, reason):
    """Return an explicit unavailable capacity diagnosis without inventing size."""
    return {"status": status, "reason": reason, "capacity_usdt": None,
            "funded_authority": False}


def scorecard_capacity(out):
    """Estimate maximum *modeled* base quantity from run net USDT per filled turnover.

    Not independent evidence of alpha, executable liquidity, or funded capacity.
    A TMN fill requires point-in-time FX at the fill; boundary FX is insufficient.
    """
    inputs, result = out.get("inputs", {}), out.get("result", {})
    if inputs.get("store") != "live":
        return _missing("SYNTHETIC", "Synthetic or unverified store is not capacity evidence")
    if result.get("quote") != "USDT":
        return _missing("FX_AT_FILL_UNAVAILABLE", "No causal USDT conversion for every individual filled TMN trade")
    symbol = inputs.get("symbol")
    profile = (inputs.get("cost", {}).get("impact_models") or {}).get(symbol)
    if not profile or profile.get("schema") != "sqrt-impact/1":
        return _missing("NO_IMPACT_MODEL", "An eligible dated public-print impact fit is required")
    try:
        if parse_ts(profile["trained_until"]) > parse_ts(inputs["from"]):
            return _missing("FUTURE_FIT", "The fit was not available at the replay start")
        with localcontext() as context:
            context.prec = 60
            end = result.get("end") or {}
            if end.get("net_usdt_eq") is None:
                return _missing("NO_USDT_VALUATION", "No verified USDT net outcome")
            net = Decimal(end["net_usdt_eq"])
            fills = [row for row in result.get("orders", [])
                     if row.get("status") == "FILLED"]
            notional = sum((Decimal(row["qty"]) * Decimal(row["price"]) for row in fills),
                           Decimal(0))
            if not fills or notional <= 0:
                return _missing("NO_TRADES", "No finite realized paper turnover")
            if not net.is_finite() or not notional.is_finite():
                return _missing("INVALID_INPUT", "Non-finite scorecard evidence")
            edge = net / notional * 10000
            if edge <= 0:
                return _missing("NO_POSITIVE_NET_EDGE", "Net after-cost edge is not positive")
            beta, sigma, volume = (Decimal(profile[key]) for key in
                                   ("b", "volatility_bps", "volume_base"))
            if (beta <= 0 or sigma <= 0 or volume <= 0
                    or not all(x.is_finite() for x in (beta, sigma, volume))):
                return _missing("UNIDENTIFIABLE_IMPACT", "Missing strictly positive impact slope and liquidity")
            half = edge / 2
            heldout = Decimal(profile["holdout_rmse_bps"])
            if not heldout.is_finite() or heldout >= half:
                return _missing("IMPACT_FIT_UNCERTAIN", "Fit error exceeds half the measured net edge")
            quantity = volume * (half / (beta * sigma)) ** 2
            if quantity > volume:
                return _missing("OUTSIDE_FIT_VOLUME", "Capacity extrapolates beyond recorded volume")
            average_price = notional / sum((Decimal(row["qty"]) for row in fills), Decimal(0))
            capacity = quantity * average_price
            return {"status": "MODELED_ESTIMATE", "capacity_usdt": str(+capacity),
                    "capacity_base": str(+quantity), "edge_bps": str(+edge),
                    "half_edge_impact_bps": str(+half),
                    "impact_fit_holdout_rmse_bps": profile["holdout_rmse_bps"],
                    "samples": profile["sample_count"], "model": "sqrt-impact/1",
                    "basis": "Public-print impact proxy against net USDT paper turnover; not independently verified funded fills or scalable alpha.",
                    "funded_authority": False}
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return _missing("INVALID_INPUT", "Impact or verified run fields are invalid")
