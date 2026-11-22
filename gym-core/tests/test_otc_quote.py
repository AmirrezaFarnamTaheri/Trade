import json
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.cli import main
from gym.services.operator_actions import operator_action
from tests.support import START, market_db, quote, supplied_otc_route


@pytest.fixture
def request_body():
    at = "2026-11-22T00:00:00Z"
    return {"symbol": "BTCUSDT", "side": "BUY", "base_quantity": "0.1", "decision_at": at,
            "quote": {"symbol": "BTCUSDT", "side": "BUY", "received_at": at, "price": "100.12",
                      "price_expires_at": "2026-11-22T00:00:30Z"},
            "market": {"symbol": "BTCUSDT", "received_at": at, "buyStatus": "ENABLE", "sellStatus": "DISABLE",
                       "minQty": "0.1", "minNotional": "10.012", "maxNotional": "30"}}


def test_otc_exact_observed_price_and_side(tmp_path, request_body):
    preview = operator_action(tmp_path, "otc-quote-preview", request_body)
    assert preview["gross_quote_amount"] == "10.012" and not preview["settled"]
    request_body["side"] = "SELL"
    with pytest.raises(ValueError, match="match"):
        operator_action(tmp_path, "otc-quote-preview", request_body)
    request_body["quote"]["side"] = "SELL"
    assert operator_action(tmp_path, "otc-quote-preview", request_body)["reasons"] == ["SIDE_UNAVAILABLE"]


@pytest.mark.parametrize("key,value,reason", [
    ("decision_at", "2026-11-22T00:00:30Z", "QUOTE_EXPIRED"),
    ("decision_at", "2026-11-21T23:59:59Z", "OBSERVATION_UNAVAILABLE"),
    ("base_quantity", "0.09", "OUTSIDE_QUANTITY_OR_NOTIONAL_LIMITS"),
    ("base_quantity", "0.30", "OUTSIDE_QUANTITY_OR_NOTIONAL_LIMITS"),
])
def test_otc_unusable_quote_has_no_value(tmp_path, request_body, key, value, reason):
    request_body[key] = value
    preview = operator_action(tmp_path, "otc-quote-preview", request_body)
    assert reason in preview["reasons"] and preview["gross_quote_amount"] is None


@pytest.mark.parametrize("submit_at,reason", [
    ("2026-11-22T00:00:03Z", None),
    ("2026-11-22T00:00:30Z", "QUOTE_EXPIRED"),
])
def test_two_leg_route_preserves_settled_intermediate_cash(tmp_path, request_body, submit_at, reason):
    initial = {**request_body, "symbol": "USDTTMN", "base_quantity": "20",
               "quote": {**request_body["quote"], "symbol": "USDTTMN", "price": "2"},
               "market": {**request_body["market"], "symbol": "USDTTMN", "maxNotional": "100"}}
    route = {"opening_balances": {"TMN": "100"}, "legs": [
        {"base": "USDT", "quote_asset": "TMN", "submit_at": "2026-11-22T00:00:01Z",
         "modeled_settle_at": "2026-11-22T00:00:02Z", "fee_rate": "0.01", "request": initial},
        {"base": "BTC", "quote_asset": "USDT", "submit_at": submit_at,
         "modeled_settle_at": "2026-11-22T00:00:31Z", "fee_rate": "0.01", "request": request_body},
    ]}
    result = operator_action(tmp_path, "otc-route-replay", route)
    assert operator_action(tmp_path, "otc-route-replay", route) == result
    balances = {k: Decimal(v) for k, v in result["closing_balances"].items()}
    reconstructed = {"TMN": Decimal(100)}
    for posting in result["postings"]:
        asset = posting["asset"]
        reconstructed[asset] = reconstructed.get(asset, Decimal(0)) + Decimal(posting["amount"])
    assert balances == reconstructed
    assert not result["venue_settlement_verified"]
    if reason:
        assert result["status"] == "STOPPED" and result["legs"][1]["reasons"] == [reason]
        assert balances == {"TMN": Decimal(60), "USDT": Decimal("19.8")}
    else:
        assert result["status"] == "COMPLETED"
        assert balances == {"TMN": Decimal(60), "USDT": Decimal("9.788"), "BTC": Decimal("0.099")}


@pytest.mark.parametrize("quantity,expected_status", [("0.1", "COMPLETED"), ("2", "STOPPED")])
def test_mixed_route_spot_fill_uses_settled_otc_proceeds(tmp_path, request_body, quantity, expected_status, capsys):
    def at(seconds):
        return (START + timedelta(seconds=seconds)).isoformat()

    market_db(tmp_path, [quote(START + timedelta(seconds=4), 99, 100)]).c.close()
    initial = {**request_body, "symbol": "USDTTMN", "base_quantity": "150", "decision_at": at(0),
               "quote": {**request_body["quote"], "symbol": "USDTTMN", "price": "2",
                         "received_at": at(0), "price_expires_at": at(5)},
               "market": {**request_body["market"], "symbol": "USDTTMN", "received_at": at(0), "maxNotional": "400"}}
    route = {"opening_balances": {"TMN": "300"}, "legs": [
        {"base": "USDT", "quote_asset": "TMN", "submit_at": at(1), "modeled_settle_at": at(2),
         "fee_rate": "0.01", "request": initial},
        {"spot": {"symbol": "BTCUSDT", "side": "BUY", "base_quantity": quantity,
                  "submit_at": at(3), "settle_by": at(5), "fee_rate": "0.01"}},
    ]}
    result = operator_action(tmp_path, "otc-route-replay", route)
    assert result["status"] == expected_status
    assert result["legs"][1]["receipt_at"] == at(4)
    balances = {key: Decimal(value) for key, value in result["closing_balances"].items()}
    expected = (Decimal("138.5"), Decimal("0.099")) if quantity == "0.1" else (Decimal("48.5"), Decimal("0.99"))
    assert (balances["USDT"], balances["BTC"]) == expected
    assert balances["TMN"] == 0
    reconstructed = {"TMN": Decimal(300)}
    for posting in result["postings"]:
        asset = posting["asset"]
        reconstructed[asset] = reconstructed.get(asset, Decimal(0)) + Decimal(posting["amount"])
    assert reconstructed == balances
    route["legs"][1]["spot"]["submit_at"] = at(1)
    with pytest.raises(ValueError, match="sequential"):
        operator_action(tmp_path, "otc-route-replay", route)
    route["legs"][1]["spot"]["submit_at"] = at(3)
    data = tmp_path / "live"
    data.mkdir()
    market_db(data, [quote(START + timedelta(seconds=4), 99, 100)]).c.close()
    request = tmp_path / "route.json"
    request.write_text(json.dumps(route), encoding="utf-8")
    assert main(["--data", str(tmp_path), "research", "otc-route-replay", str(request)]) == 0
    assert json.loads(capsys.readouterr().out) == result


def test_spot_conversion_waits_for_the_point_in_time_session_open(tmp_path):
    from dataclasses import replace

    opened = START.replace(hour=8, minute=0)
    closed = opened - timedelta(seconds=1)
    market_db(tmp_path, [
        replace(quote(closed, 90, 91), symbol="USDTTMN"),
        replace(quote(opened, 99, 100), symbol="USDTTMN"),
    ]).c.close()
    route = {"opening_balances": {"TMN": "500"}, "legs": [
        {"spot": {"symbol": "USDTTMN", "side": "BUY", "base_quantity": "1",
                  "submit_at": closed.isoformat(), "settle_by": opened.isoformat(), "fee_rate": "0"}},
    ]}
    result = operator_action(tmp_path, "otc-route-replay", route)
    assert result["status"] == "COMPLETED"
    assert result["legs"][0]["receipt_at"] == opened.isoformat()
    assert {asset: Decimal(amount) for asset, amount in result["closing_balances"].items()} == {
        "TMN": Decimal(400), "USDT": Decimal(1),
    }


def test_portfolio_otc_sell_reserves_cash_until_settlement():
    from gym.domain.sim import CashBook
    from gym.services.portfolio_otc import PortfolioOTC
    from tests.support import START, supplied_otc_quote

    quote = supplied_otc_quote(price="102")
    quote["quote"]["side"] = "SELL"
    book = CashBook({"USDT": Decimal(20), "TMN": Decimal(0)})
    events = []
    routing = PortfolioOTC([quote])
    decision = START + timedelta(seconds=60)
    terms = {"cash": book.get("USDT"), "spot_price": Decimal(101), "spot_fee": Decimal("0.001"),
             "latency": timedelta(seconds=1), "end": START + timedelta(minutes=5)}
    assert routing.select(decision, "SELL", Decimal(10), **terms)
    assert routing.reserved("USDT") == 10
    assert routing.reserved("TMN") == 0
    settle = decision + timedelta(seconds=6)
    routing.advance(settle, book, events)
    assert book.balances == {"USDT": 20, "TMN": 0} and not events
    routing.advance(settle + timedelta(microseconds=1), book, events)
    assert book.balances == {"USDT": 10, "TMN": Decimal("1018.98")}
    assert len(events) == 1 and routing.reserved("USDT") == 0
    assert not routing.select(settle + timedelta(seconds=1), "SELL", Decimal(10), **terms)


def test_two_leg_portfolio_otc_reserves_source_and_prevents_quote_reuse():
    from gym.domain.sim import CashBook
    from gym.services.portfolio_otc import PortfolioOTC

    route = supplied_otc_route()
    second_candidate = supplied_otc_route()
    second_candidate[1]["quote"]["price"] = "0.95"
    at = START + timedelta(seconds=60)
    routing = PortfolioOTC([], routes=[second_candidate, route])
    book = CashBook({"TMN": Decimal(100), "USDT": Decimal(0)})
    terms = {"cash": Decimal(100), "spot_price": Decimal(100), "spot_fee": Decimal(0),
             "latency": timedelta(seconds=1), "end": START + timedelta(minutes=5)}
    events = []
    assert not routing.select(at, "BUY", Decimal(10), **{**terms, "cash": Decimal(89)})
    assert routing.select(at, "BUY", Decimal(10), **terms)
    first_settle = at + timedelta(seconds=6)
    routing.advance(first_settle + timedelta(seconds=1), book, events)
    assert routing.reserved("TMN") == 90 and routing.reserved("USDT") == 0
    assert book.balances == {"TMN": 100, "USDT": 0} and not events
    assert not routing.select(first_settle + timedelta(seconds=1), "BUY", Decimal(10), **terms)
    finish = at + timedelta(seconds=12)
    routing.advance(finish + timedelta(microseconds=1), book, events)
    assert book.balances == {"TMN": 10, "USDT": Decimal("8.91"), "X": 0}
    assert routing.reserved("TMN") == 0 and len(events) == 1
    assert not routing.select(finish + timedelta(seconds=1), "BUY", Decimal(10), **terms)


def test_two_leg_portfolio_otc_requires_both_quotes_at_cutoff_and_no_residual():
    from gym.services.portfolio_otc import PortfolioOTC

    route = supplied_otc_route()
    at = START + timedelta(seconds=60)
    route[1]["quote"]["received_at"] = at.isoformat()
    routing = PortfolioOTC([], routes=[route])
    assert not routing.select(at, "BUY", Decimal(10), cash=Decimal(100), spot_price=Decimal(100),
                              spot_fee=Decimal(0), latency=timedelta(0), end=at + timedelta(minutes=1))
    route[1]["base_quantity"] = "8"
    with pytest.raises(ValueError, match="without intermediate residual"):
        PortfolioOTC([], routes=[route])
