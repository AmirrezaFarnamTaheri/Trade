"""Hypothetical trade economics must disclose missing inference costs."""
import json
from decimal import Decimal

import pytest

from gym.cli import main
from gym.domain.market_models import evaluate_artifact


def parameters(**changes):
    return {"quote_currency": "USDT", "entry_price": "100", "stop_price": "90",
            "target_price": "120", "gross_base_quantity": "2", "fee_rate": "0",
            "slippage_rate": "0", "inference_cost_quote": None, **changes}


def evaluate(**changes):
    return evaluate_artifact({"model": "trade-economics", "parameters": parameters(**changes)})


def test_unknown_inference_cost_is_not_zero_and_known_cost_changes_both_outcomes():
    out = evaluate()["result"]
    before = out["before_inference"]
    assert before["gain_quote"] == 40 and before["loss_quote"] == 20
    assert before["reward_to_risk"] == 2
    assert Decimal("0.3333") < before["break_even_win_fraction"] < Decimal("0.3334")
    assert out["after_inference"]["status"] == "UNAVAILABLE"
    assert out["after_inference"]["gain_quote"] is None
    assert evaluate(inference_cost_quote="0")["result"]["after_inference"] == before
    after = evaluate(inference_cost_quote="10")["result"]["after_inference"]
    assert after["gain_quote"] == after["loss_quote"] == 30
    assert after["reward_to_risk"] == 1 and after["break_even_win_fraction"] == Decimal("0.5")


def test_fees_and_adverse_slippage_reduce_reward_and_cost_domination_has_no_feasible_probability():
    out = evaluate(fee_rate="0.01", slippage_rate="0.01", inference_cost_quote="100")["result"]
    assert out["net_base_quantity"] == Decimal("1.98")
    assert out["entry_cash_quote"] == 202
    assert out["before_inference"]["gain_quote"] == Decimal("30.87176")
    assert out["before_inference"]["loss_quote"] == Decimal("27.34618")
    assert out["after_inference"]["status"] == "COST_DOMINATED"
    assert out["after_inference"]["break_even_win_fraction"] is None
    assert out["inputs_verified"] is False and out["stop_execution_verified"] is False


@pytest.mark.parametrize("changes", [
    {"entry_price": "0"}, {"stop_price": "100"}, {"target_price": "100"},
    {"gross_base_quantity": "0"}, {"gross_base_quantity": True}, {"fee_rate": "1"},
    {"slippage_rate": "NaN"}, {"inference_cost_quote": "-1"}, {"inference_cost_quote": 0},
    {"quote_currency": "USD"},
])
def test_invalid_assumptions_fail(changes):
    with pytest.raises(ValueError):
        evaluate(**changes)


def test_trade_economics_reaches_offline_cli(tmp_path, capsys):
    source = tmp_path / "economics.json"
    source.write_text(json.dumps({"model": "trade-economics", "parameters": parameters()}), encoding="utf-8")
    assert main(["--data", str(tmp_path / "absent"), "paper-research", str(source)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["result"]["after_inference"]["status"] == "UNAVAILABLE"
    assert report["funded_authority"] is False and report["order_submitted"] is False
    assert not (tmp_path / "absent").exists()
