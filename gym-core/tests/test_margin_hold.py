"""Margin holds charge the venue's fees, carry every 4 hours, and liquidate on the first one-minute extreme."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("margin_hold", Path(__file__).resolve().parents[1] / "scripts/margin_hold.py")
margin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(margin)


def test_a_flat_2x_buy_loses_exactly_its_fees():
    result = margin.hold("long", 2, 100.0, [(60, 100.0, 100.0)], 100.0)
    assert result["ret"] == pytest.approx(-(0.0025 * 2 + 0.00015 * 2 + 0.001 * 2 * 0.9975))
    assert result["liquidated_h"] is None


def test_carry_is_charged_once_per_four_hours_held():
    short = margin.hold("short", 1, 100.0, [(4 * 3600, 100.0, 100.0)], 100.0)
    assert short["ret"] == pytest.approx(-0.0025 - 2 * 0.00015 - 0.001)


def test_the_first_extreme_past_the_floor_liquidates_each_side():
    assert margin.hold("long", 2, 100.0, [(60, 50.0, 100.0), (120, 100.0, 200.0)], 200.0) == {"ret": -0.85, "liquidated_h": 0.0}
    assert margin.hold("short", 2, 100.0, [(7200, 100.0, 150.0)], 50.0) == {"ret": -0.85, "liquidated_h": 2.0}


def test_a_falling_price_pays_the_short():
    assert margin.hold("short", 1, 100.0, [(60, 90.0, 100.0)], 90.0)["ret"] > 0.09


def test_venue_terms_set_fees_and_liquidate_at_the_quoted_price(tmp_path):
    preview = {"rule": {"symbol": "CAKEUSDT", "base": "CAKE", "quote": "USDT"},
               "request": {"side": "long", "risk_coef": "2"},
               "answer": {"success": True, "result": {"open_price": "2", "loan": {"value": "200", "currency": "USDT"},
                          "trade_fee": {"value": "0.25", "currency": "CAKE"}, "extend_fee": {"value": "0.03", "currency": "USDT"},
                          "extend_time": 14400, "liquidity_price": "1.2"}}}
    path = tmp_path / "margin-terms.jsonl"
    path.write_text(__import__("json").dumps(preview) + "\n", encoding="utf-8")
    terms = margin.venue_terms([path])[("CAKEUSDT", "long", 2.0)]
    assert terms == pytest.approx({"entry_fee": 0.0025, "loan_fee": 0.00015, "period": 14400, "liquidation": 0.6})
    assert margin.hold("long", 2, 100.0, [(60, 61.0, 100.0)], 100.0, terms)["liquidated_h"] is None
    assert margin.hold("long", 2, 100.0, [(3600, 60.0, 100.0)], 100.0, terms)["liquidated_h"] == 1.0
