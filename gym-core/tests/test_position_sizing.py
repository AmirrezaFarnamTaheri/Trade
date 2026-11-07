"""Explicit paper sizing assumptions, exact limits and the offline command path."""
import json
from decimal import Decimal

import pytest

from gym.cli import main
from gym.domain.market_models import evaluate_artifact


def parameters(**changes):
    return {"quote_currency": "USDT", "equity": "1000", "cash": "500",
            "entry_price": "100", "stop_price": "90", "risk_fraction": "0.02",
            "max_position_fraction": "0.3", "cash_buffer_fraction": "0.1",
            "quantity_step": "0.01", "fee_rate": "0.001", "slippage_rate": "0.005", **changes}


def evaluate(**changes):
    return evaluate_artifact({"model": "position-sizing", "parameters": parameters(**changes)})


def test_risk_sizing_rounds_down_and_includes_both_fees_and_slippage():
    report = evaluate()
    out = report["result"]
    quantity = out["gross_base_quantity"]
    loss_per_unit = Decimal(100) * Decimal("1.005") - Decimal(90) * Decimal("0.995") * Decimal("0.999")**2
    assert quantity == Decimal("1.79")
    assert out["modeled_loss_quote"] <= 20 < (quantity + Decimal("0.01")) * loss_per_unit
    assert out["net_base_quantity"] == quantity * Decimal("0.999")
    assert out["entry_price"] == Decimal(100) and out["stop_price"] == Decimal(90)
    assert out["limiting_constraints"] == ["risk"]
    assert report["funded_authority"] is False and report["order_submitted"] is False
    assert out["stop_execution_verified"] is False and out["venue_minimums_verified"] is False


@pytest.mark.parametrize("changes,quantity,binding", [
    ({"cash": "110"}, "0.09", "cash_buffer"),
    ({"max_position_fraction": "0.05"}, "0.49", "position"),
    ({"cash": "100"}, "0", "cash_buffer"),
    ({"quantity_step": "2"}, "0", "risk"),
])
def test_cash_reserve_position_cap_and_insufficient_step(changes, quantity, binding):
    out = evaluate(**changes)["result"]
    assert out["gross_base_quantity"] == Decimal(quantity)
    assert out["status"] == ("SIZED" if Decimal(quantity) else "NO_CAPACITY")
    assert out["limiting_constraints"] == [binding]
    assert out["entry_cash_quote"] <= out["spendable_cash_quote"]


@pytest.mark.parametrize("changes", [
    {"equity": "0"}, {"cash": "1001"}, {"cash": "-1"}, {"entry_price": "0"},
    {"stop_price": "100"}, {"stop_price": "101"}, {"stop_price": "0"},
    {"risk_fraction": "0"}, {"risk_fraction": "1"}, {"risk_fraction": "NaN"},
    {"max_position_fraction": "1"}, {"cash_buffer_fraction": "1"},
    {"quantity_step": "0"}, {"quantity_step": 0.01}, {"fee_rate": "1"},
    {"fee_rate": True}, {"slippage_rate": "-0.1"}, {"quote_currency": "IRT"},
])
def test_invalid_or_unbounded_assumptions_fail(changes):
    with pytest.raises(ValueError):
        evaluate(**changes)


def test_explicit_assumptions_reach_offline_cli_without_touching_store(tmp_path, capsys):
    source, output = tmp_path / "sizing.json", tmp_path / "sizing-report.json"
    source.write_text(json.dumps({"model": "position-sizing", "parameters": parameters()}), encoding="utf-8")
    data = tmp_path / "absent-store"
    command = ["--data", str(data), "paper-research", str(source), "--output", str(output)]
    assert main(command) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(output.read_text(encoding="utf-8"))
    assert report["result"]["gross_base_quantity"] == "1.79"
    assert not data.exists()
    assert main(command) == 2
    assert "error:" in capsys.readouterr().err
