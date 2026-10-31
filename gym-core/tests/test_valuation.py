"""Historical valuation cannot borrow a future quote for starting cash."""
from dataclasses import replace
from datetime import timedelta

from gym.services.paper import paper
from tests.support import START, market_db, quote, quote_history


def test_fx_already_known_at_both_boundaries_remains_available(tmp_path):
    observations = [replace(row, symbol="BTCTMN") for row in quote_history(80)]
    observations += [replace(quote(START, "100", "102"), symbol="USDTTMN"),
                     replace(quote(START + timedelta(minutes=10), "110", "112"), symbol="USDTTMN")]
    output = paper(market_db(tmp_path, observations), "BTCTMN", START, START + timedelta(minutes=12),
                   resolution="1min", fast=2, slow=3)
    assert output["fx"]["start"] == "101" and output["fx"]["end"] == "111"
    assert output["numeraire"] == "USDT-equivalent"
    assert "net_usdt_eq" in output["result"]["end"]


def test_future_only_fx_cannot_value_starting_cash(tmp_path):
    observations = [replace(row, symbol="BTCTMN") for row in quote_history(80)]
    observations += [
        replace(quote(START + timedelta(minutes=2), "100", "102"), symbol="USDTTMN"),
        replace(quote(START + timedelta(minutes=10), "110", "112"), symbol="USDTTMN"),
    ]
    output = paper(market_db(tmp_path, observations), "BTCTMN", START, START + timedelta(minutes=12),
                   resolution="1min", fast=2, slow=3)
    assert output["fx"] is None
    assert output["numeraire"] == "TMN"
    assert "net_usdt_eq" not in output["result"]["end"]
    assert any("USDT-equivalent unavailable" in warning for warning in output["warnings"])
