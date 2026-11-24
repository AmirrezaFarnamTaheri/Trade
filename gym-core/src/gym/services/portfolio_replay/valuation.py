"""Read-only portfolio valuation helpers accepting explicit minimal inputs."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal


def equity_in_quote(
    quote: str,
    book,
    instruments: dict,
    marks: dict,
    held_order: list,
    margin=None,
) -> Decimal:
    """Value paper cash, spot holdings, and optional margin equity in one quote currency."""
    equity = book.get(quote) + sum(
        (book.get(instruments[s].base) * marks[s] for s in held_order if instruments[s].quote == quote),
        Decimal(0),
    )
    return equity + margin.equity(quote) if margin else equity


def reserved_in_quote(
    quote: str,
    reserved: dict,
    instruments: dict,
    *,
    exclude=None,
    otc_reserved: Decimal = Decimal(0),
) -> Decimal:
    """Sum reserved cash in one quote currency, optionally excluding one symbol."""
    return sum(
        (value for s, value in reserved.items() if s != exclude and instruments[s].quote == quote),
        otc_reserved,
    )


def valuation_status_at(
    at,
    *,
    multicurrency: bool,
    fx_mark,
    fx_valuation_closed_fn,
    margin_stale: bool,
    has_otc_residuals: bool,
    held_order: list,
    mark_times: dict,
) -> str:
    """Return STALE_VALUATION when any held market or FX translation mark is stale or closed."""
    stale_fx = multicurrency and (
        "CLOSED" in fx_mark.flags
        or at - fx_mark.ts_avail > timedelta(seconds=120)
        or fx_valuation_closed_fn(at)
    )
    return (
        "STALE_VALUATION"
        if stale_fx
        or margin_stale
        or has_otc_residuals
        or any(at - mark_times[s] > timedelta(seconds=120) for s in held_order)
        else "CURRENT"
    )
