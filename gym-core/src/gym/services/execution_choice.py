"""Retrospective spread-aware paper execution comparison; never funded authority.

One immediate (single public top quote) attempt and one TWAP schedule share the
same frozen public observation window, assumptions, and initial budget.  Future
public quotes can inform a historical replay but never a start-time order choice.
"""
from decimal import Decimal, localcontext


_SHARED_FIELDS = (
    "schema", "symbol", "side", "start", "end_exclusive", "requested_quantity",
    "fee_rate", "participation", "max_delay_seconds", "initial_quote",
    "initial_base", "store", "synthetic", "cost_models",
)


def _quantity(value, name, *, positive=False):
    """Parse exact finite nonnegative economic values and reject forged NaNs."""
    if type(value) not in (str, int, Decimal):
        raise ValueError("invalid paper execution " + name)
    try:
        result = Decimal(value)
    except (ValueError, ArithmeticError):
        raise ValueError("invalid paper execution " + name) from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError("invalid paper execution " + name)
    return result


def _verified_paper_shape(out, expected_slices):
    """Check internal paper receipt shape and conservation before comparison."""
    if (type(out) is not dict or out.get("schema") != "paper-twap/1"
            or out.get("authority") != "PAPER_ONLY"
            or out.get("funded_authority") is not False
            or out.get("order_submitted") is not False
            or out.get("cancel_submitted") is not False
            or out.get("side") not in ("BUY", "SELL")
            or out.get("store") not in ("demo", "live")
            or type(out.get("children")) is not list
            or len(out["children"]) != expected_slices):
        raise ValueError("execution comparison requires bounded paper receipts")
    requested = _quantity(out.get("requested_quantity"), "requested quantity", positive=True)
    filled = _quantity(out.get("filled_quantity"), "filled quantity")
    cancelled = _quantity(out.get("cancelled_quantity"), "cancelled quantity")
    _quantity(out.get("spent_quote"), "spent quote")
    _quantity(out.get("received_base"), "received base")
    _quantity(out.get("received_quote"), "received quote")
    if filled > requested or filled + cancelled != requested:
        raise ValueError("paper preview quantity is not conserved")
    child_filled = Decimal(0)
    for child in out["children"]:
        if type(child) is not dict or child.get("status") not in ("NONFILL", "PARTIAL", "FILLED"):
            raise ValueError("invalid paper child attempt")
        child_filled += _quantity(child.get("filled_quantity"), "child fill")
    if child_filled != filled:
        raise ValueError("paper child fills differ from aggregate")
    return requested, filled


def compare_execution_previews(immediate, twap):
    """Compare *historical* net effective prices only for two matched full fills.

    A partial outcome is explicitly non-comparable.  A cheaper historical
    scenario is not a predictive venue recommendation, forecast, or authority.
    """
    with localcontext() as context:
        context.prec = 160
        if type(twap) is not dict or type(twap.get("children")) is not list:
            raise ValueError("invalid TWAP comparison receipt")
        if not 2 <= len(twap["children"]) <= 100:
            raise ValueError("execution choice needs 2..100 paper TWAP slices")
        requested, fast_filled = _verified_paper_shape(immediate, 1)
        twap_requested, slow_filled = _verified_paper_shape(twap, len(twap["children"]))
        if requested != twap_requested or any(
            immediate.get(key) != twap.get(key) for key in _SHARED_FIELDS
        ):
            raise ValueError("execution choices must share the same frozen historical inputs")
        result = {
            "schema": "historical-execution-choice/1",
            "symbol": immediate["symbol"],
            "side": immediate["side"],
            "store": immediate["store"],
            "synthetic": immediate["synthetic"],
            "from": immediate["start"],
            "to_exclusive": immediate["end_exclusive"],
            "requested_quantity": str(requested),
            "immediate_filled_quantity": str(fast_filled),
            "twap_filled_quantity": str(slow_filled),
            "immediate": immediate,
            "twap": twap,
            "status": "NOT_COMPARABLE",
            "reason": "UNMATCHED_FILLED_QUANTITY",
            "retrospective_lower_cost": None,
            "twap_advantage_bps": None,
            "immediate_effective_quote_per_base": None,
            "twap_effective_quote_per_base": None,
            "funded_authority": False,
            "autonomous_execution": False,
            "order_submitted": False,
            "cancel_submitted": False,
            "decision_available_at_start": False,
            "limitations": [
                "Retrospective only: TWAP quote path was not knowable at the first slot.",
                "One-slice immediate comparison is a top-of-book paper attempt, not a real market order.",
                "Displayed best-level capacity, quote fee, latency and impact models are assumptions, not verified fills.",
                "A historical lower modeled cost does not establish a future advantage or authorize funded execution.",
            ],
        }
        if fast_filled != requested or slow_filled != requested:
            return result

        if immediate["side"] == "BUY":
            immediate_units = _quantity(immediate["received_base"], "immediate net base", positive=True)
            twap_units = _quantity(twap["received_base"], "TWAP net base", positive=True)
            fast_price = _quantity(immediate["spent_quote"], "immediate quote spent") / immediate_units
            slow_price = _quantity(twap["spent_quote"], "TWAP quote spent") / twap_units
            advantage = (fast_price - slow_price) / fast_price * 10000 if fast_price else Decimal(0)
        else:
            fast_price = _quantity(immediate["received_quote"], "immediate net quote") / requested
            slow_price = _quantity(twap["received_quote"], "TWAP net quote") / requested
            advantage = (slow_price - fast_price) / fast_price * 10000 if fast_price else Decimal(0)
        if fast_price <= 0 or slow_price <= 0:
            raise ValueError("fully filled paper comparison requires positive net unit prices")
        result.update({
            "status": "FULL_FILL_HISTORICAL",
            "reason": None,
            "retrospective_lower_cost": ("TWAP" if advantage > 0 else
                                         "IMMEDIATE" if advantage < 0 else "TIE"),
            "twap_advantage_bps": str(+advantage),
            "immediate_effective_quote_per_base": str(+fast_price),
            "twap_effective_quote_per_base": str(+slow_price),
        })
        return result
