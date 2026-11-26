"""The router prices every route at the touch, charges a fee per leg, and never prices beyond displayed size."""
from decimal import Decimal

import pytest

from gym.services import conversion_route
from gym.services.conversion_route import Touch, routes

AT = "2026-11-18T10:00:00.000000Z"


def touch(bid, ask, bid_qty="1000000", ask_qty="1000000"):
    return Touch(Decimal(bid), Decimal(ask), Decimal(bid_qty), Decimal(ask_qty), AT)


def test_a_coin_route_wins_when_its_implied_rate_beats_the_direct_market_by_more_than_the_extra_fee():
    touches = {"USDTTMN": touch("99000", "100000"),
               "BTCTMN": touch("9000000000", "9000000000"), "BTCUSDT": touch("91000", "91100")}
    found = routes(touches, Decimal("1000000"), "TMN_TO_USDT", Decimal("0.001"))
    assert found[0]["route"] == "BTCTMN > BTCUSDT" and found[0]["legs"] == 2
    assert found[0]["received"] == pytest.approx(Decimal("1000000") / 9000000000 * Decimal("0.999") * 91000 * Decimal("0.999"))
    assert found[1]["received"] == Decimal("1000000") / 100000 * Decimal("0.999")


def test_a_route_too_small_for_the_amount_is_ranked_last_and_marked():
    touches = {"USDTTMN": touch("99000", "100000"),
               "BTCTMN": touch("9000000000", "9000000000", ask_qty="0.00001"), "BTCUSDT": touch("91000", "91100")}
    found = routes(touches, Decimal("1000000"), "TMN_TO_USDT", Decimal("0.001"))
    assert found[0]["route"] == "USDTTMN" and found[-1]["fits_displayed_size"] is False


def test_usdt_to_toman_reverses_the_legs_and_bad_requests_are_refused():
    touches = {"USDTTMN": touch("99000", "100000")}
    [direct] = routes(touches, Decimal("10"), "USDT_TO_TMN", Decimal("0"))
    assert direct["received"] == Decimal("990000")
    with pytest.raises(ValueError):
        routes(touches, Decimal("-1"), "USDT_TO_TMN", Decimal("0"))


def test_preview_exposes_ordered_quote_evidence_and_refuses_savings_against_a_too_small_route(monkeypatch):
    touches = {"USDTTMN": touch("99000", "100000", bid_qty="1"),
               "BTCTMN": touch("9000000000", "9010000000"), "BTCUSDT": touch("91000", "91100")}
    monkeypatch.setattr(conversion_route, "latest_touches", lambda *_: touches)
    report = conversion_route.recommend(None, Decimal("10"), "USDT_TO_TMN", AT)
    assert report["depth_scope"] == "TOP_OF_BOOK_ONLY"
    assert report["max_quote_age_seconds"] == 120
    assert report["saving_vs_direct_bps"] is None
    assert not report["direct_route"]["fits_displayed_size"]
    first, second = report["routes"][0]["leg_details"]
    assert (first["symbol"], first["side"], second["symbol"], second["side"]) == ("BTCUSDT", "BUY", "BTCTMN", "SELL")
    assert first["quote_at"] == AT and first["displayed_base_quantity"] == "1000000"
