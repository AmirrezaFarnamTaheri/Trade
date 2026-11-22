"""Causal mixed spot and OTC routing through one paper portfolio account."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from itertools import islice

import pytest

from gym.domain.model import iso
from gym.services.data_portal import DataPortal
from gym.services.research_actions import research_action
from gym.services.research_ledger import ResearchLedger
from gym.services.research_process import calculate
from tests.support import START, market_db, quote, quote_history, supplied_otc_quote
from tests.test_portfolio_workflow import request
from tests.test_research_ledger import schedule


def route_input(first):
    buy = first == "OTC"
    otc_symbol = "ADATMN" if buy else "ADAUSDT"
    otc = supplied_otc_quote(price="50" if buy else "5")
    otc["quote"].update(symbol=otc_symbol, side="BUY" if buy else "SELL")
    otc["market"]["symbol"] = otc_symbol
    otc.pop("max_base_quantity")
    otc.update(base="ADA", quote_asset="TMN" if buy else "USDT", fee_rate="0", base_quantity="1")
    return {"first": first, "max_source": "50", "otc": otc,
            "spot": {"base": "ADA", "quote_asset": "USDT" if buy else "TMN",
                     "side": "SELL" if buy else "BUY", "base_quantity": "1", "fee_rate": "0",
                     "wait_seconds": 20}}


def setup(root, first, detail, recovery_quotes=()):
    route = route_input(first)
    spot = route["spot"]
    symbol = spot["base"] + spot["quote_asset"]
    bid, ask = ("5", "6") if first == "OTC" else ("39", "40")
    after = {"complete": ("4", "4.1") if first == "OTC" else ("44", "45"),
             "over_cap": ("11", "12")}.get(detail, (bid, ask))
    rows = [replace(quote(START + timedelta(seconds=55), bid, ask), symbol=symbol),
            replace(quote(START + timedelta(seconds=70), *after), symbol=symbol,
                    bid_qty=Decimal("0.5") if detail == "partial" else Decimal(1),
                    ask_qty=Decimal("0.5") if detail == "partial" else Decimal(1))]
    rows += [replace(quote(START + timedelta(seconds=offset), bid, ask), symbol=symbol,
                     bid_qty=Decimal("0.25")) for offset in recovery_quotes]
    rows += quote_history(n=360, sym="ETHUSDT") + quote_history(n=360, sym="SOLTMN")
    rows += [replace(top, ts_avail=top.ts_avail - timedelta(seconds=7), bid=Decimal(99), ask=Decimal(101))
             for top in quote_history(n=361, sym="USDTTMN")]
    market_db(root, rows).c.close()
    value = {**request(), "symbols": ["ETHUSDT", "SOLTMN", symbol],
             "cash_by_currency": {"USDT": "0", "TMN": "100000"},
             "cost": {**request()["cost"], "max_participation": "1"},
             "fx_rebalance": {"target_usdt_cash_share": "0.7", "band": "0.1", "max_order_usdt": "10",
                              "mixed_routes": [route]}}
    return value


@pytest.mark.parametrize("first,detail,status,credit,residual", [
    ("OTC", "complete", "FILLED", "4", "0"),
    ("SPOT", "complete", "FILLED", "5", "0"),
    ("OTC", "partial", "PARTIAL", "2.5", "0.5"),
    ("SPOT", "partial", "PARTIAL", "0", "0.5"),
    ("OTC", "over_cap", "PARTIAL", "0", "1"),
])
def test_mixed_route_books_actual_quotes_and_stops_with_residual(tmp_path, first, detail, status, credit, residual):
    value = setup(tmp_path, first, detail)
    response = research_action(tmp_path, "portfolio-replay", value)
    record = research_action(tmp_path, "portfolio-read", {"run_id": response["run_id"]})
    assert record["inputs"]["portfolio_version"] == 22
    result = record["result"]
    fill, = [row for row in result["fx_orders"] if row.get("venue_model") == "SPOT_OTC_ROUTE"]
    assert fill["status"] == status
    assert Decimal(fill["destination_credit"]) == Decimal(credit)
    assert Decimal(fill["intermediate_residual"]) == Decimal(residual)
    assert Decimal(result["balances"]["ADA"]) == Decimal(residual)
    assert fill["indicative_spot_quote"]["at"] < fill["decision_time"] < iso(START + timedelta(seconds=70))
    settle_postings = [p for p in result["postings"] if p["ref"] == fill["ref"]]
    assert all(p["t"] == fill["released_at"] for p in settle_postings)
    if status == "PARTIAL":
        assert result["mixed_route_residuals"] == {"ADA": fill["intermediate_residual"]}
        assert result["end"]["valuation_status"] == "STALE_VALUATION"
        assert len(result["fx_orders"]) == 1
    with localcontext() as ctx:
        ctx.prec = 400
        balances = {asset: Decimal(amount) for asset, amount in value["cash_by_currency"].items()}
        for posting in result["postings"]:
            asset = posting["ccy"]
            balances[asset] = balances.get(asset, Decimal(0)) + Decimal(posting["amount"])
        assert balances == {asset: Decimal(amount) for asset, amount in result["balances"].items()}
    for count in (15, 50):
        checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": response["run_id"], "quote_count": count})["record"]
        assert research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})["status"] == "EXACT_MATCH"


def test_supervised_scheduler_selects_mixed_route_and_publishes_once(tmp_path):
    value = setup(tmp_path, "SPOT", "complete")
    due = iso(START + timedelta(hours=1))
    with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        options = {key: value[key] for key in ("cash_by_currency", "fx_rebalance")}
        schedule(ledger, max_participation="1", portfolio_symbols=value["symbols"], **options)
    tick = asyncio.run(calculate(tmp_path, "tick", at=due))
    item, = tick["completed"]
    reply = research_action(tmp_path, "portfolio-read", {"run_id": item["run_id"]})
    assert any(o.get("venue_model") == "SPOT_OTC_ROUTE" and o["status"] == "FILLED"
               for o in reply["result"]["fx_orders"])
    assert not asyncio.run(calculate(tmp_path, "tick", at=due))["completed"]


@pytest.mark.parametrize("first,attempts,remaining", [("OTC", 2, "0"), ("SPOT", 1, "0.25")])
def test_partial_inventory_recovery_uses_disjoint_windows(tmp_path, first, attempts, remaining):
    value = setup(tmp_path, first, "partial", range(95, 350, 5))
    value["fx_rebalance"]["residual_attempts"] = attempts
    response = research_action(tmp_path, "portfolio-replay", value)
    record = research_action(tmp_path, "portfolio-read", {"run_id": response["run_id"]})
    result = record["result"]
    assert record["inputs"]["portfolio_version"] == 23
    recovery = [o for o in result["fx_orders"] if o.get("venue_model") == "SPOT_RESIDUAL_RECOVERY"]
    assert len(recovery) == attempts
    previous = result["fx_orders"][0]["released_at"]
    for order in recovery:
        assert previous < order["decision_time"] < iso(datetime.fromisoformat(order["outcome"]["receipt_at"])) <= order["released_at"]
        assert Decimal(order["outcome"]["filled_base_quantity"]) == Decimal("0.25")
        previous = order["released_at"]
    assert Decimal(result["balances"]["ADA"]) == Decimal(remaining)
    assert Decimal(result["mixed_route_residuals"].get("ADA", "0")) == Decimal(remaining)
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": response["run_id"], "quote_count": 36})["record"]
    assert research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})["status"] == "EXACT_MATCH"


def test_recovery_digest_independent_of_read_chunk_and_market_order(tmp_path, monkeypatch):
    value = setup(tmp_path, "OTC", "partial", range(95, 350, 5))
    value["fx_rebalance"]["residual_attempts"] = 2
    expected = research_action(tmp_path, "portfolio-replay", value)
    original = DataPortal.iter_tops
    for chunk_size in (3, 37):
        def chunked(portal, *args, chunk_size=chunk_size):
            source = original(portal, *args)
            while batch := list(islice(source, chunk_size)):
                yield from batch
        monkeypatch.setattr(DataPortal, "iter_tops", chunked)
        replay = research_action(tmp_path, "portfolio-replay", {**value, "symbols": value["symbols"][::-1]})
        assert replay["run_id"] == expected["run_id"]
        assert replay["outputs_digest"] == expected["outputs_digest"]
