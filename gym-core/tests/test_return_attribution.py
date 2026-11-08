"""TMN and USDT attribution obeys the exact multiplicative identity."""

from decimal import Decimal

from gym.services.attribution import toman_attribution


def test_toman_gain_can_hide_a_usdt_loss_without_rounding_residual():
    out = {"mode": "PAPER", "result": {"quote": "TMN", "start_cash": "100",
                                        "end": {"equity": "110"}},
           "fx": {"start": "100", "end": "120"}}
    row = toman_attribution(out)
    assert row["status"] == "AVAILABLE"
    assert Decimal(row["usdt_return"]) < 0
    assert Decimal(row["toman_move"]) > 0
    assert Decimal(row["total_toman_return"]) == Decimal("0.1")
    assert (Decimal(row["usdt_return"]) + Decimal(row["toman_move"]) +
            Decimal(row["interaction"])) == Decimal(row["total_toman_return"])


def test_portfolio_uses_its_own_point_in_time_fx_and_refuses_missing_data():
    out = {"mode": "PORTFOLIO", "result": {
        "quote": "TMN", "start_cash": "100", "end": {"equity": "120"},
        "valuation": {"start": {"rate": "100"}, "end": {"rate": "120"}}}}
    assert toman_attribution(out)["total_toman_return"] == "0.2000000000000000"
    assert toman_attribution({"mode": "PORTFOLIO", "result": {
        "quote": "TMN", "start_cash": "100", "end": {"equity": "120"}, "valuation": {}}})["status"] == "UNAVAILABLE"
