"""A trading-credit package is replayed with its own fee and its own warning and liquidation levels."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.credit import package_terms, replay_credit
from gym.domain.model import BookTop
from tests.support import START

ROW = {"id": 122, "title": "1000 USDT", "currency": "USDT", "assurance": "100", "loan": "1000",
       "warning_limit": "1070", "liquidity_limit": "1040", "status": "ACTIVE", "expire_days": 30,
       "daily_fee_after_discount": "0.5", "final_fee_after_discount": "15", "extra": "ignored"}


def point(hours, bid, ask, size="100000", closed=False):
    return BookTop("BTCUSDT", START + timedelta(hours=hours), Decimal(bid), Decimal(ask), Decimal(size), Decimal(size), frozenset()), closed


def replay(points, exposure="1", end_hours=24 * 40):
    return replay_credit(package_terms(ROW), "BTC", points, START, START + timedelta(hours=end_hours),
                         exposure=Decimal(exposure), fee_rate=Decimal("0.001"))


def test_package_terms_keep_only_validated_fields_and_refuse_inverted_levels():
    terms = package_terms(ROW)
    assert terms == {"id": 122, "currency": "USDT", "assurance": "100", "loan": "1000", "warning_limit": "1070",
                     "liquidity_limit": "1040", "status": "ACTIVE", "expire_days": 30, "daily_fee": "0.5", "final_fee": "15"}
    for change in ({"liquidity_limit": "1080"}, {"warning_limit": "1200"}, {"loan": "0"}, {"expire_days": 0}, {"currency": "usdt"},
                   {"assurance": 100}):
        with pytest.raises(ValueError):
            package_terms(ROW | change)


def test_flat_price_costs_the_spread_the_trade_fees_and_one_fee_per_completed_day():
    result = replay([point(0, 99.9, 100), point(49, 100, 100.1)], end_hours=50)
    # 1100 buys 11 units, 0.011 goes in fee; two completed days cost 1.0; the mark is 10.989 * 100 - 1.0
    assert result["state"] == "OPEN_AT_WINDOW_END"
    assert Decimal(result["account_value"]) == Decimal("1097.9")
    assert Decimal(result["trader_equity"]) == Decimal("97.9") and Decimal(result["trader_pnl"]) == Decimal("-2.1")
    assert result["fees"] == {"package": "1.0", "trade_base": "0.011", "trade_quote": "0"}


def test_warning_is_recorded_once_and_liquidation_sells_at_the_bid_and_repays_the_loan_first():
    result = replay([point(0, 99.9, 100), point(1, 97, 97.1), point(2, 96.9, 97), point(3, 94, 94.1), point(4, 120, 121)])
    assert [event["action"] for event in result["events"]] == ["PAPER_OPEN", "WARNING_LEVEL", "PAPER_LIQUIDATION"]
    assert result["state"] == "CLOSED_LIQUIDATION"
    # 10.989 * 94 = 1032.966, less 0.1% exit fee
    assert Decimal(result["account_value"]) == Decimal("1032.966") * Decimal("0.999")
    assert Decimal(result["trader_equity"]) == Decimal(result["account_value"]) - 1000
    assert Decimal(result["return_on_collateral_pct"]) < -67


def test_half_exposure_survives_the_same_fall_and_expiry_closes_the_package():
    falling = [point(0, 99.9, 100), point(3, 94, 94.1)]
    assert replay(falling, exposure="0.5", end_hours=4)["state"] == "OPEN_AT_WINDOW_END"
    expired = replay([point(0, 99.9, 100), point(24 * 30, 110, 110.1), point(24 * 31, 50, 51)])
    assert expired["state"] == "CLOSED_EXPIRY" and expired["fees"]["package"] == "15.0"
    assert Decimal(expired["trader_pnl"]) > 90


def test_a_closed_market_or_a_thin_bid_cannot_settle_a_liquidation():
    closed = replay([point(0, 99.9, 100), point(3, 94, 94.1, closed=True)])
    assert closed["state"] == "LIQUIDATION_UNSETTLED" and closed["events"][-1]["action"] == "CLOSE_UNAVAILABLE"
    thin = replay([point(0, 99.9, 100), point(3, 94, 94.1, size="1")])
    assert thin["state"] == "LIQUIDATION_UNSETTLED" and thin["events"][-1]["action"] == "CLOSE_DEPTH_UNAVAILABLE"


def test_no_entry_without_a_quote_and_invalid_inputs_are_refused():
    assert replay([])["state"] == "ENTRY_PENDING"
    for exposure in ("0", "1.01"):
        with pytest.raises(ValueError):
            replay([point(0, 99.9, 100)], exposure=exposure)
    with pytest.raises(ValueError):
        replay([point(2, 99.9, 100), point(1, 99.9, 100)])


def test_packages_receipt_feeds_a_replay_and_a_wrong_currency_market_is_refused(tmp_path, monkeypatch):
    from gym.services import credit
    from gym.services.research_actions import research_action
    from tests.support import market_db, quote_history

    market_db(tmp_path, quote_history(n=400)).c.close()
    monkeypatch.setattr(credit, "public_margin", lambda path: ([ROW, ROW | {"id": 165, "currency": "TMN"}], "0" * 64))
    monkeypatch.setattr(credit, "now_utc", lambda: START + timedelta(days=2))
    receipt = research_action(tmp_path, "credit-packages", None, store="live")
    assert [row["id"] for row in receipt["packages"]] == [122, 165] and receipt["funded_authority"] is False
    order = {"packages_id": receipt["run_id"], "package_id": 122, "symbol": "BTCUSDT", "from": "2026-10-29T09:00:00Z",
             "to": "2026-10-29T10:00:00Z", "exposure": "0.00005", "fee_rate": "0.001"}
    replayed = research_action(tmp_path, "credit-replay", order, store="live")
    assert replayed["result"]["state"] == "OPEN_AT_WINDOW_END" and replayed["terms_known_at_window_start"] is False
    assert replayed["order_submitted"] is False
    with pytest.raises(ValueError, match="package currency"):
        research_action(tmp_path, "credit-replay", order | {"package_id": 165}, store="live")
    with pytest.raises(ValueError, match="live observation store"):
        research_action(tmp_path, "credit-packages", None, store="demo")
