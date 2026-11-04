"""Ranked paper entries share one cash reserve and one modeled loss budget."""
import json
from decimal import Decimal

import pytest

from gym.cli import main
from gym.domain.market_models import evaluate_artifact


def request():
    return {"model": "portfolio-sizing", "parameters": {
        "quote_currency": "USDT", "equity": "1000", "cash": "500",
        "total_risk_fraction": "0.03", "cash_buffer_fraction": "0.1",
        "max_allocation_fraction": "0.4", "fee_rate": "0", "slippage_rate": "0",
        "candidates": [{"symbol": symbol, "entry_price": "100", "stop_price": "90",
                        "risk_fraction": "0.02", "max_position_fraction": "0.3",
                        "quantity_step": "0.1"} for symbol in ("BTCUSDT", "ETHUSDT")]}}


def test_joint_risk_budget_prevents_individually_feasible_overspending():
    out = evaluate_artifact(request())["result"]
    assert [r["gross_base_quantity"] for r in out["allocations"]] == [Decimal("2"), Decimal("1")]
    assert out["entry_cash_quote"] == 300 and out["modeled_loss_quote"] == 30
    assert out["remaining_cash_quote"] == 200
    assert out["cash_reserve_quote"] == 100 and not out["existing_exposure_verified"]


def test_shared_cash_reserve_and_rank_order_are_preserved():
    artifact = request()
    artifact["parameters"]["total_risk_fraction"] = "0.9"
    artifact["parameters"]["cash"] = "350"
    out = evaluate_artifact(artifact)["result"]
    assert [r["gross_base_quantity"] for r in out["allocations"]] == [Decimal("2"), Decimal("0.5")]
    assert out["remaining_cash_quote"] == 100
    artifact["parameters"]["candidates"].reverse()
    assert evaluate_artifact(artifact)["result"]["allocations"][0]["symbol"] == "ETHUSDT"


def test_total_allocation_cap_fees_slippage_rounding_and_zero_capacity():
    artifact = request()
    artifact["parameters"].update(max_allocation_fraction="0.15", fee_rate="0.001", slippage_rate="0.005")
    out = evaluate_artifact(artifact)["result"]
    assert out["entry_cash_quote"] <= 150
    assert out["allocations"][0]["gross_base_quantity"] == Decimal("1.4")
    assert out["allocations"][0]["net_base_quantity"] == Decimal("1.3986")
    assert out["allocations"][1]["status"] == "NO_CAPACITY"
    artifact["parameters"]["cash"] = "50"
    assert evaluate_artifact(artifact)["result"]["entry_cash_quote"] == 0


@pytest.mark.parametrize("change", ["duplicate", "mixed_currency", "float", "extra", "empty", "too_many", "zero_risk"])
def test_ambiguous_or_unbounded_portfolios_fail(change):
    artifact = request()
    params = artifact["parameters"]
    if change == "duplicate":
        params["candidates"][1]["symbol"] = "BTCUSDT"
    elif change == "mixed_currency":
        params["candidates"][1]["symbol"] = "ETHTMN"
    elif change == "float":
        params["cash"] = 500.0
    elif change == "extra":
        params["candidates"][0]["approved"] = True
    elif change == "empty":
        params["candidates"] = []
    elif change == "too_many":
        params["candidates"] *= 51
    else:
        params["total_risk_fraction"] = "0"
    with pytest.raises(ValueError):
        evaluate_artifact(artifact)


def test_portfolio_cli_has_no_store_or_order_effect(tmp_path, capsys):
    source = tmp_path / "allocation.json"
    source.write_text(json.dumps(request()))
    data = tmp_path / "unused"
    assert main(["--data", str(data), "paper-research", str(source)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["funded_authority"] is False and report["order_submitted"] is False
    assert not data.exists()
