"""B1 manual account observations never become funded balances or fills."""
import pytest
from gym.domain.account_observations import project_account, journal_changes, parse_wallex_balances


def test_balances_and_external_orders_never_become_funded_cash():
    v = project_account("main", "2026-10-31T15:00:00Z",
        balances={"USDT": {"value": "10.500", "locked": "4.00"}},
        orders=[{"client_id": "manual-1", "symbol": "BTCUSDT", "status": "X-UNDOCUMENTED", "filled": "0.001"}],
        exposure=[{"product": "MARGIN", "account_id": "margin-1", "obligation_asset": "USDT", "obligation": "20.5"}])
    assert v["state"] == "OBSERVED" and v["authority"] == "READ_ONLY" and v["source"] == "VENUE_EXTERNAL"
    assert v["balances"] == [{"asset": "USDT", "venue_value": "10.500", "venue_locked": "4.00",
                              "spendable": None, "protectable": None}]
    assert v["orders"][0]["raw_status"] == "X-UNDOCUMENTED"
    assert v["orders"][0]["settlement"] == "UNKNOWN"
    assert v["orders"][0]["origin"] == "EXTERNAL_MANUAL_UNVERIFIED"
    assert v["exposure"][0]["managed"] is False and v["exposure"][0]["obligation"] == "20.5"
    assert "api_key" not in str(v).lower()


def test_credit_wallet_never_merged_with_main_wallet():
    a = project_account("main", "2026-10-31T15:00:00Z", balances={"USDT": {"value": "3", "locked": "0"}})
    b = project_account("subaccount:credit-a", "2026-10-31T15:00:00Z",
        balances={"USDT": {"value": "10", "locked": "7"}})
    assert a["balances"][0]["venue_value"] == "3" and b["balances"][0]["venue_value"] == "10"
    assert b["account_scope"] == "TRADE_CREDIT" and a["account_id"] != b["account_id"]


def test_invalid_amounts_are_not_rounded_or_fabricated():
    for x in (float("nan"), float("inf"), 1.25, "NaN", "Infinity", "-0.001", "bad"):
        with pytest.raises((ValueError, TypeError)):
            project_account("main", "2026-10-31T15:00:00Z", balances={"USDT": {"value": x, "locked": "0"}})
    with pytest.raises(ValueError):
        project_account("main", "2026-10-31T15:00:00Z", balances={"USDT": {"value": "1"}})


def test_closed_manual_order_is_not_inferred_settled():
    v = project_account("main", "2026-10-31T15:00:00Z",
                        orders=[{"client_id": "manual-z", "status": "closed", "filled": "1"}])
    assert v["orders"][0]["settlement"] == "UNKNOWN"
    assert v["orders"][0]["economic_effect"] == "UNVERIFIED"
    assert v["orders"][0]["funded_trade"] is False


def test_journal_only_emits_new_observed_state_not_order_disappearance():
    a = project_account("main", "2026-10-31T15:00:00Z", orders=[{"client_id": "manual-1", "status": "new"}])
    b = project_account("main", "2026-10-31T15:01:00Z", orders=[{"client_id": "manual-1", "status": "new"}])
    c = project_account("main", "2026-10-31T15:02:00Z", orders=[{"client_id": "manual-1", "status": "mystery"}])
    assert journal_changes(a, b) == []
    event, = journal_changes(b, c)
    assert event["raw_status"] == "mystery" and event["settlement"] == "UNKNOWN"
    assert journal_changes(c, project_account("main", "2026-10-31T15:03:00Z")) == []


def test_only_documented_wallex_balance_fields_survive():
    assert parse_wallex_balances({"success": True, "result": {
        "BTC": {"value": "1.3", "locked": "0.1", "api_key": "SECRET"}}}) == {
        "BTC": {"value": "1.3", "locked": "0.1"}}
    with pytest.raises(ValueError):
        parse_wallex_balances({"success": False, "result": {}})
