from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.market_models import evaluate_artifact
from tests.support import START


def artifact():
    return {"model": "cashflow-returns", "parameters": {"quote_currency": "USDT", "started_at": START.isoformat(),
        "ended_at": (START + timedelta(days=2)).isoformat(), "initial_equity": "100", "final_equity": "231",
        "cashflows": [{"at": (START + timedelta(days=1)).isoformat(), "equity_before_flow": "110",
                       "flow_quote": "100", "equity_after_flow": "210"}]}}


def test_contribution_is_not_profit_and_subperiods_compound():
    result = evaluate_artifact(artifact())["result"]
    assert result["net_profit_quote"] == 31
    assert result["time_weighted_return_percent"] == 21
    assert result["dietz_denominator_quote"] == 150
    assert not result["cashflows_reconciled"]


def test_withdrawal_and_zero_equity_do_not_fabricate_returns():
    item = artifact()
    item["parameters"]["cashflows"][0].update(flow_quote="-110", equity_after_flow="0")
    item["parameters"]["final_equity"] = "0"
    result = evaluate_artifact(item)["result"]
    assert result["net_profit_quote"] == 10 and result["time_weighted_return_percent"] is None
    item["parameters"]["cashflows"] = []
    assert evaluate_artifact(item)["result"]["time_weighted_return_percent"] == Decimal(-100)


@pytest.mark.parametrize("change", ["inconsistent", "duplicate", "future", "nonfinite", "float", "currency"])
def test_unreconciled_or_ambiguous_input_rejects(change):
    item = artifact()
    params, row = item["parameters"], item["parameters"]["cashflows"][0]
    if change == "inconsistent":
        row["equity_after_flow"] = "200"
    elif change == "duplicate":
        params["cashflows"].append(dict(row))
    elif change == "future":
        row["at"] = (START + timedelta(days=3)).isoformat()
    elif change == "nonfinite":
        row["flow_quote"] = "NaN"
    elif change == "float":
        row["flow_quote"] = 100.0
    else:
        params["quote_currency"] = "IRT"
    with pytest.raises(ValueError):
        evaluate_artifact(item)
