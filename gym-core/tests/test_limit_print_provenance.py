"""Trade prints without venue IDs remain modeled, with duplicate exposure disclosed."""

from decimal import Decimal

from gym.services.paper import session_result
from gym.services.session import ENGINE_VERSION
from tests.test_simulation import _limit_session


def test_identical_trade_prints_are_kept_but_counted_for_each_limit_fill(tmp_path):
    # Wallex supplies no trade ID: these could be two real trades or a duplicated push.
    order, session = _limit_session(tmp_path, [
        (7, "100", "3", "SELL"),
        (7, "100", "3", "SELL"),
    ])
    assert order["status"] == "FILLED"
    assert Decimal(order["qty"]) == 4  # queue=2 then two prints of quantity 3
    assert order["limit_prints_considered"] == 2
    assert order["suspected_identical_prints"] == 1
    assert Decimal(order["identical_print_capacity_qty"]) == 3
    evidence = session_result(session, [], Decimal(1000))["limit_fill_diagnostics"]
    assert evidence["suspected_identical_prints"] == 1
    assert evidence["affected_fills"] == 1
    assert Decimal(evidence["identical_print_capacity_qty"]) == 3
    assert evidence["trade_ids_available"] is False
    assert evidence["identical_prints_deduplicated"] is False


def test_distinct_trade_times_do_not_trigger_identical_print_alert(tmp_path):
    order, session = _limit_session(tmp_path, [
        (3, "100", "1", "SELL"),
        (7, "100", "2", "SELL"),
    ])
    assert order["status"] == "FILLED"
    assert order["limit_prints_considered"] == 2
    assert order["suspected_identical_prints"] == 0
    assert session_result(session, [], Decimal(1000))["limit_fill_diagnostics"]["affected_fills"] == 0


def test_price_band_reference_is_explicitly_an_estimate(tmp_path):
    _, session = _limit_session(tmp_path, [])
    result = session_result(session, [], Decimal(1000))
    reference = result["session"]["price_band_reference"]
    assert reference["status"] == "ESTIMATED"
    assert reference["basis"] == "FIRST_OBSERVED_TEHRAN_DAY_MID"
    assert reference["venue_reference_documented"] is False
    assert ENGINE_VERSION == "paper-session/9"
