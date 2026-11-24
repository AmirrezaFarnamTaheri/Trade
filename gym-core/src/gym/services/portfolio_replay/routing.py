"""Pure route configuration and selection helpers for shared-cash portfolio replay."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from ...domain.bars import qualified
from ...domain.rules import is_closed
from ...domain.sim import sellable_quantity


def configure_routes(
    *,
    symbols,
    instruments: dict,
    quotes,
    primary_quote: str,
    book,
    margin_symbols: set[str],
    mixed_bases: set[str],
    mixed_symbols: set[str],
    variable_routes: bool,
) -> tuple[dict, dict, dict, dict]:
    """Build initial route_candidates, reference_routes, trade_routes, and quote_market_counts."""
    if (margin_symbols | mixed_symbols) - instruments.keys():
        raise ValueError("margin and mixed spot execution require a selected portfolio symbol")
    if margin_symbols & mixed_symbols:
        raise ValueError("a mixed spot route cannot share its symbol with margin")

    owners: dict = {}
    route_candidates: dict = defaultdict(list)
    reference_routes: dict = {}

    for symbol in sorted(
        symbols,
        key=lambda s: (not book.get(instruments[s].quote), instruments[s].quote != primary_quote, s),
    ):
        inst = instruments[symbol]
        if symbol in margin_symbols:
            reference_routes[symbol] = {"reason": "MARGIN_POSITION", "trade_route": None}
        elif inst.base in mixed_bases:
            reference_routes[symbol] = {"reason": "MIXED_ROUTE_INTERMEDIATE", "trade_route": None}
        elif inst.base in quotes:
            reference_routes[symbol] = {"reason": "QUOTE_CURRENCY_REFERENCE", "trade_route": None}
        elif inst.base in owners and not variable_routes:
            reference_routes[symbol] = {"reason": "ALTERNATE_ROUTE", "trade_route": owners[inst.base]}
        else:
            owners[inst.base] = symbol
            route_candidates[inst.base].append(symbol)

    trade_routes = {} if variable_routes else owners
    if not route_candidates:
        raise ValueError("multi-currency replay requires at least one traded underlying")
    quote_market_counts = {
        quote: sum(instruments[s].quote == quote for choices in route_candidates.values() for s in choices)
        for quote in quotes
    }
    return route_candidates, reference_routes, trade_routes, quote_market_counts


def select_route_for_base(
    *,
    base: str,
    symbols: list[str],
    at,
    dynamic_routes: bool,
    entry_windows: bool,
    listed: dict,
    trade_routes: dict,
    primary_quote: str,
    secondary_currency: str | None,
    book,
    sessions: dict,
    instruments: dict,
    rules_for,
    reserved_in,
    equity_in,
    quote_market_counts: dict,
    portal,
    fx_mark,
) -> tuple[bool, str | None]:
    """Choose the best route for ``base`` at ``at``. Returns ``(should_update, selected_symbol)``."""
    if book.get(base) > 0 or any(sessions[s].pending for s in symbols):
        return False, None
    eligible = [s for s in symbols if s in listed] if entry_windows else symbols
    if not dynamic_routes:
        previous = trade_routes.get(base)
        if previous not in eligible:
            choice = min(
                eligible,
                key=lambda s: (not book.get(instruments[s].quote), instruments[s].quote != primary_quote, s),
                default=None,
            )
            return True, choice
        return False, None

    candidates = []
    for symbol in eligible:
        session, instrument = sessions[symbol], instruments[symbol]
        top = session.last_quote
        if (
            top is None
            or not qualified(top)
            or top.ts_avail >= at
            or "CLOSED" in top.flags
            or (entry_windows and top.ts_avail < listed[symbol])
            or at - top.ts_avail > timedelta(seconds=120)
            or is_closed(rules_for(at), instrument, at)
            or top.ask_qty is None
            or top.ask_qty <= 0
        ):
            continue
        free = book.get(instrument.quote) - reserved_in(instrument.quote)
        target = equity_in(instrument.quote) / quote_market_counts[instrument.quote]
        clip = min(top.ask_qty * session.cost.max_participation, min(free, target) / top.ask)
        if not sellable_quantity(clip, top.ask, portal.spec_at(symbol, at)):
            continue
        fx = fx_mark.bid if instrument.quote == secondary_currency else Decimal(1)
        unit_cost = top.ask / fx / (1 - session.cost.fee_rate)
        candidates.append((unit_cost, symbol))
    choice = min(candidates)[1] if candidates else None
    return True, choice


def count_listed_routes(
    *,
    dynamic_routes: bool,
    route_candidates: dict,
    trade_routes: dict,
    listed: dict,
    instruments: dict,
) -> defaultdict:
    """Count currently listed routes per quote currency."""
    counts: defaultdict = defaultdict(int)
    symbols = (
        (s for routes in route_candidates.values() for s in routes)
        if dynamic_routes
        else trade_routes.values()
    )
    for symbol in symbols:
        if symbol in listed:
            counts[instruments[symbol].quote] += 1
    return counts
