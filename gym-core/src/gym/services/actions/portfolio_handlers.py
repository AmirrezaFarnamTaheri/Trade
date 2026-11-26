"""Portfolio, margin, OOS-combination, and retirement action handlers extracted from research_actions."""
from __future__ import annotations


def handle_portfolio_replay(root, action, value, store, at):
    from ..portfolio_research import portfolio_action

    return portfolio_action(root, action, value, store=store)


def handle_combine_oos(root, action, value, store, at):
    from ..oos_combination import combine_verified_oos

    return combine_verified_oos(root, value, store=store)


def handle_strategy_retirement_screen(root, action, value, store, at):
    from ..strategy_retirement import screen_verified_retirement

    return screen_verified_retirement(root, value, store=store)


def handle_margin_pairs_replay(root, action, value, store, at):
    from ..margin_pairs import margin_pairs_research

    return margin_pairs_research(root, value, store=store)


def handle_margin_markets(root, action, value, store, at):
    from ..margin import margin_action

    return margin_action(root, action, value, store=store)
