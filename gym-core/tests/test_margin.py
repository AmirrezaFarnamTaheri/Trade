"""Wallex-specific credit grids, currency-aware fees and causal paper positions."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.margin import margin_request, market_rule, preview_terms, replay_margin
from gym.domain.model import iso
from tests.support import START, quote


def rule():
    return {"symbol": "BTCUSDT", "base": "BTC", "quote": "USDT", "min_risk_coef": "1", "max_risk_coef": "10",
            "risk_coef_step": "0.5", "liquidity_margin": "0.15", "max_age": 1814400}


def request(side="long"):
    return {"market": "BTCUSDT", "side": side, "collateral": "100", "risk_coef": "2", "open_price": "100"}


def preview(side="long"):
    return {**request(side), "collateral": {"currency": "USDT", "value": "100"},
            "loan": {"currency": "USDT" if side == "long" else "BTC", "value": "200" if side == "long" else "2"},
            "trade_fee": {"currency": "BTC" if side == "long" else "USDT", "value": "0.005" if side == "long" else "0.5"},
            "open_fee": {"currency": "USDT" if side == "long" else "BTC", "value": "0.03" if side == "long" else "0.0004"},
            "extend_fee": {"currency": "USDT" if side == "long" else "BTC", "value": "0.03" if side == "long" else "0.0004"},
            "extend_time": 14400, "max_age": 1814400,
            "call_price": "70" if side == "long" else "130", "liquidity_price": "60" if side == "long" else "140"}


def path(side="long", end_price="110", hours=1):
    def top(at, bid, ask):
        return replace(quote(at, bid, ask), bid_qty=Decimal(10), ask_qty=Decimal(10))
    return [(top(START, "99", "100"), False),
            (top(START + timedelta(hours=hours), end_price, str(Decimal(end_price) + 1)), False)] if side == "long" else [
        (top(START, "100", "101"), False),
        (top(START + timedelta(hours=hours), str(Decimal(end_price) - 1), end_price), False)]


@pytest.mark.parametrize("value", ["0.5", "10.5", "2.25", "NaN", "2e0", 2, True])
def test_invalid_credit_ratios_reject_without_coercion(value):
    with pytest.raises(ValueError):
        margin_request({**request(), "risk_coef": value}, rule())


def test_decimal_grid_uses_market_minimum_and_preserves_optional_protection():
    changed = {**rule(), "min_risk_coef": "1.1", "risk_coef_step": "0.2"}
    assert margin_request({**request(), "risk_coef": "1.3", "stop_loss": "90", "take_profit": "110"}, changed)["risk_coef"] == "1.3"
    for change in ({"side": "BUY"}, {"market": "ETHUSDT"}, {"stop_loss": "101"}, {"take_profit": "99"}, {"api_key": "never"}):
        with pytest.raises(ValueError):
            margin_request({**request(), **change}, rule())


@pytest.mark.parametrize("change", [{"risk_coef_step": "0"}, {"liquidity_margin": "1"}, {"max_age": True}, {"quote": "IRT"}])
def test_malformed_market_limits_fail_closed(change):
    with pytest.raises(ValueError):
        market_rule({**rule(), **change})


def test_preview_echo_and_fee_currencies_are_not_silently_reinterpreted():
    assert preview_terms(preview(), request(), rule())["loan"]["currency"] == "USDT"
    assert preview_terms(preview(), {**request(), "open_price": "100.00", "risk_coef": "2.0", "collateral": "100.00"}, rule())
    for change in ({"risk_coef": "3"}, {"market": "ETHUSDT"}, {"loan": {"currency": "BTC", "value": "200"}},
                   {"open_fee": {"currency": "ETH", "value": "1"}}, {"extend_time": 0}, {"call_price": "50"}):
        with pytest.raises(ValueError):
            preview_terms({**preview(), **change}, request(), rule())


def test_long_uses_loan_not_collateral_plus_loan_and_exact_exit_fee():
    out = replay_margin(preview(), rule(), path(), START + timedelta(hours=1, seconds=1), "0.001", 3600)
    assert out["state"] == "CLOSED" and out["entry"]["gross_base_quantity"] == "2"
    assert Decimal(out["cash_quote"]) == Decimal("119.20055")
    assert out["debt_quote"] == "0" and out["fees_by_currency"]["BTC"] == "0.005"
    assert out["events"][-1]["action"] == "PAPER_TIME_EXIT"


def test_short_keeps_base_denomination_opening_and_extension_debt():
    out = replay_margin(preview("short"), rule(), path("short", "90", 4), START + timedelta(hours=4, seconds=1), "0.001", 14400)
    assert out["state"] == "CLOSED" and out["extension_periods"] == 1
    assert Decimal(out["cash_quote"]) == Decimal("119.247928")
    assert Decimal(out["fees_by_currency"]["BTC"]) == Decimal("0.0008")
    assert out["debt_base"] == "0"


def test_limit_entry_does_not_fill_against_price_or_insufficient_top_quantity():
    top = quote(START, "101", "102")
    for candidate in (top, replace(top, ask=Decimal(100), ask_qty=Decimal("0.1"))):
        out = replay_margin(preview(), rule(), [(candidate, False)], START + timedelta(seconds=1), "0", None)
        assert out["state"] == "ENTRY_PENDING" and out["entry"] is None and out["fees_by_currency"] == {}


def test_stop_target_liquidation_and_expiry_close_only_at_observed_executable_side():
    for change, price, expected in (({"stop_loss": "90"}, "89", "PAPER_STOP"),
                                     ({"take_profit": "110"}, "111", "PAPER_TARGET"),
                                     ({}, "50", "PAPER_LIQUIDATION"),
                                     ({"max_age": 3600}, "100", "PAPER_EXPIRY")):
        out = replay_margin({**preview(), **change}, rule(), path(end_price=price), START + timedelta(hours=1, seconds=1), "0", None)
        assert out["events"][-1]["action"] == expected and out["state"].startswith("CLOSED")
    first, second = path(end_price="50")
    out = replay_margin(preview(), rule(), [first, (second[0], True)], START + timedelta(hours=1, seconds=1), "0", None)
    assert out["state"] == "CLOSE_PENDING" and out["debt_quote"] == "200"
    assert out["events"][-1]["action"] == "CLOSURE_LIQUIDATION_UNKNOWN"


def test_no_quote_at_expiry_cannot_synthesize_a_close_and_debt_survives_gap_loss():
    out = replay_margin({**preview(), "max_age": 3600}, rule(), path()[:1], START + timedelta(hours=2), "0", None)
    assert out["state"] == "CLOSE_PENDING" and out["mark"]["status"] == "STALE"
    out = replay_margin(preview("short"), rule(), path("short", "1000"), START + timedelta(hours=1, seconds=1), "0", None)
    assert out["state"] == "CLOSED_WITH_DEBT" and Decimal(out["debt_quote"]) > 0
    assert out["cash_quote"] == "0"


def test_fee_clock_stops_at_close_and_source_order_is_enforced():
    points = path()
    points.append((quote(START + timedelta(days=1), "200", "201"), False))
    out = replay_margin(preview(), rule(), points, START + timedelta(days=1, seconds=1), "0", 3600)
    assert out["extension_periods"] == 0 and len(out["events"]) == 2
    with pytest.raises(ValueError):
        replay_margin(preview(), rule(), list(reversed(points)), START + timedelta(days=2), "0", 1)
    assert out["entry"]["at"] == iso(START)


def test_later_bad_quote_invalidates_earlier_good_mark_without_inventing_a_close():
    top, _ = path()[0]
    bad = replace(top, ts_avail=START + timedelta(seconds=10), flags=frozenset({"STALE"}))
    out = replay_margin(preview(), rule(), [(top, False), (bad, False)], START + timedelta(seconds=11), "0", None)
    assert out["state"] == "OPEN" and out["equity_quote"] is None
    assert out["mark"]["status"] == "STALE" and out["nonfills"]["UNQUALIFIED_QUOTE"] == 1
