"""Shared-cash replay reaches the private API and immutable, verified saved records."""
import asyncio
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.run_store import load_verified_run
from gym.adapters.store import SegmentWriter
from gym.api.server import make_app
from gym.domain.model import iso
from gym.services.collector import Collector
from gym.services.research_actions import research_action
from gym.services.research_process import calculate
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history, supplied_otc_quote


def request():
    return {"symbols": ["BTCUSDT", "ETHUSDT"], "from": iso(START),
            "to": iso(START + timedelta(minutes=30)), "resolution": "1min", "cash": "1000",
            "strategy": "ema-trend", "params": {"fast": 2, "slow": 3},
            "rules_mode": "point-in-time", "cost": {"fee_rate": "0.001", "latency_ms": 500,
                "max_wait_s": 60, "fee_assumption": "fee-in-received-asset"}}


def prepare(root):
    return market_db(root, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))


@pytest.mark.parametrize("alternate_routes", [False, True])
def test_multicurrency_reconciles_each_currency_and_rebuilds_checkpoint(tmp_path, alternate_routes):
    from dataclasses import replace

    fx = [replace(top, ts_avail=top.ts_avail - timedelta(seconds=10), bid=Decimal(99), ask=Decimal(101))
          for top in quote_history(n=181, sym="USDTTMN")]
    rows = quote_history(n=180) + quote_history(n=180, sym="ETHTMN") + fx
    symbols = ["BTCUSDT", "ETHTMN"]
    if alternate_routes:
        rows += quote_history(n=180, sym="BTCTMN")
        symbols += ["BTCTMN", "USDTTMN"]
    market_db(tmp_path, rows).c.close()
    value = {**request(), "symbols": symbols,
             "cash_by_currency": {"USDT": "1000", "TMN": "100000"}}
    out = research_action(tmp_path, "portfolio-replay", value)
    record = research_action(tmp_path, "portfolio-read", {"run_id": out["run_id"]})
    result = record["result"]
    assert Decimal(result["start_cash"]) == 2000
    assert record["inputs"]["portfolio_version"] == (15 if alternate_routes else 14)
    assert all(result["markets"][symbol]["fills"] for symbol in ("BTCUSDT", "ETHTMN"))
    if alternate_routes:
        alternate = result["markets"]["BTCTMN"]
        assert alternate["trade_route"] == "BTCUSDT" and alternate["holding"] == "0" and alternate["fills"] == 0
        assert result["markets"]["USDTTMN"]["reason"] == "QUOTE_CURRENCY_REFERENCE"
        assert research_action(tmp_path, "portfolio-replay", {**value, "symbols": symbols[::-1]})["run_id"] == out["run_id"]
    balances = {"USDT": Decimal(1000), "TMN": Decimal(100000)}
    for entry in result["postings"]:
        currency = entry["ccy"]
        balances[currency] = balances.get(currency, Decimal(0)) + Decimal(entry["amount"])
        assert balances[currency] >= 0
    assert balances == {currency: Decimal(amount) for currency, amount in result["balances"].items()}
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": out["run_id"], "quote_count": 55})["record"]
    resumed = research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})
    assert resumed["status"] == "EXACT_MATCH"


@pytest.mark.parametrize("include_spot", [False, True])
def test_opening_conversion_flows_into_portfolio_and_checkpoint(tmp_path, include_spot):
    from dataclasses import replace

    fx = [replace(top, ts_avail=top.ts_avail - timedelta(seconds=30), bid=Decimal(99), ask=Decimal(101))
          for top in quote_history(n=181, sym="USDTTMN")]
    market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHTMN") + fx).c.close()
    decision = iso(START - timedelta(seconds=60))
    submit = iso(START - timedelta(seconds=50))
    settle = iso(START - timedelta(seconds=40))
    leg = {"base": "USDT", "quote_asset": "TMN", "submit_at": submit, "modeled_settle_at": settle,
           "fee_rate": "0.01", "request": {
               "symbol": "USDTTMN", "side": "BUY", "base_quantity": "1000", "decision_at": decision,
               "quote": {"symbol": "USDTTMN", "side": "BUY", "received_at": decision,
                         "price": "100", "price_expires_at": settle},
               "market": {"symbol": "USDTTMN", "received_at": decision, "buyStatus": "ENABLE",
                          "sellStatus": "ENABLE", "minQty": "1", "minNotional": "100", "maxNotional": "200000"},
           }}
    legs = [leg]
    if include_spot:
        legs.append({"spot": {"symbol": "USDTTMN", "side": "SELL", "base_quantity": "0.5",
                              "submit_at": iso(START - timedelta(seconds=35)),
                              "settle_by": iso(START - timedelta(seconds=25)), "fee_rate": "0"}})
    value = {**request(), "symbols": ["BTCUSDT", "ETHTMN"], "funding_legs": legs,
             "cash_by_currency": {"TMN": "100000", "USDT": "0"}}
    response = research_action(tmp_path, "portfolio-replay", value)
    record = research_action(tmp_path, "portfolio-read", {"run_id": response["run_id"]})
    result = record["result"]
    assert record["inputs"]["portfolio_version"] == 17
    assert Decimal(result["start_cash"]) == 1000
    assert Decimal(result["opening_funding"]["closing_balances"]["USDT"]) == Decimal("989.5" if include_spot else "990")
    assert result["opening_funding"]["status"] == "COMPLETED"
    assert result["markets"]["BTCUSDT"]["fills"] > 0
    balances = {"TMN": Decimal(100000), "USDT": Decimal(0)}
    for posting in result["postings"]:
        ccy = posting["ccy"]
        balances[ccy] = balances.get(ccy, Decimal(0)) + Decimal(posting["amount"])
    assert balances == {ccy: Decimal(amount) for ccy, amount in result["balances"].items()}
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": response["run_id"], "quote_count": 55})["record"]
    assert research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})["status"] == "EXACT_MATCH"
    leg["modeled_settle_at"] = value["from"]
    with pytest.raises(ValueError, match="settle before"):
        research_action(tmp_path, "portfolio-replay", value)


@pytest.mark.parametrize("otc", ["none", "better", "costlier", "expired"])
def test_in_window_fx_rebalances_on_later_receipts_and_recovers(tmp_path, otc):
    from dataclasses import replace

    fx = [replace(top, ts_avail=top.ts_avail - timedelta(seconds=7), bid=Decimal(99), ask=Decimal(101))
          for top in quote_history(n=181, sym="USDTTMN")]
    market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHTMN") + fx).c.close()
    value = {**request(), "symbols": ["BTCUSDT", "ETHTMN"],
             "cash_by_currency": {"USDT": "0", "TMN": "100000"},
             "cost": {**request()["cost"], "max_participation": "1"},
             "fx_rebalance": {"target_usdt_cash_share": "0.7", "band": "0.1", "max_order_usdt": "10"}}
    if otc != "none":
        value["fx_rebalance"]["otc_quotes"] = [supplied_otc_quote(
            price="102" if otc == "costlier" else "98",
            expiry_seconds=30 if otc == "expired" else 180)]
    response = research_action(tmp_path, "portfolio-replay", value)
    record = research_action(tmp_path, "portfolio-read", {"run_id": response["run_id"]})
    assert record["inputs"]["portfolio_version"] == (18 if otc == "none" else 19)
    result = record["result"]
    fills = [row for row in result["fx_orders"] if row["status"] == "FILLED"]
    otc_fills = [row for row in fills if row.get("venue_model") == "SUPPLIED_OTC_QUOTE"]
    assert len(otc_fills) == (1 if otc == "better" else 0)
    assert fills and all(row["fill_time"] > row["decision_time"] for row in fills)
    assert all(Decimal(row["qty"]) <= 1 for row in fills if row not in otc_fills)
    for fill in otc_fills:
        assert fill["submit_time"] < fill["fill_time"]
        assert Decimal(fill["qty"]) == 10 and Decimal(fill["price"]) == 98
        assert Decimal(fill["fee"]) == Decimal("0.01") and fill["fee_ccy"] == "USDT"
        postings = [entry for entry in result["postings"] if entry["ref"] == fill["ref"]]
        assert [(p["ccy"], Decimal(p["amount"])) for p in postings] == [
            ("TMN", Decimal(-980)), ("USDT", Decimal(10)), ("USDT", Decimal("-0.01"))]
    balances = {"USDT": Decimal(0), "TMN": Decimal(100000)}
    for posting in result["postings"]:
        ccy = posting["ccy"]
        balances[ccy] = balances.get(ccy, Decimal(0)) + Decimal(posting["amount"])
        assert balances[ccy] >= 0
    assert balances == {ccy: Decimal(amount) for ccy, amount in result["balances"].items()}
    for count in (13, 55):
        checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": response["run_id"], "quote_count": count})["record"]
        assert research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})["status"] == "EXACT_MATCH"


def test_dynamic_route_selects_lower_cost_pair_without_duplicating_inventory(tmp_path):
    from dataclasses import replace

    fx = [replace(top, ts_avail=top.ts_avail - timedelta(seconds=10), bid=Decimal(99), ask=Decimal(101))
          for top in quote_history(n=181, sym="USDTTMN")]
    market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="BTCTMN") + fx).c.close()
    value = {**request(), "symbols": ["BTCUSDT", "BTCTMN"], "dynamic_routes": True,
             "cash_by_currency": {"USDT": "100000", "TMN": "100000"},
             "cost": {**request()["cost"], "max_participation": "1"}}
    result = research_action(tmp_path, "portfolio-replay", value)
    saved = research_action(tmp_path, "portfolio-read", {"run_id": result["run_id"]})
    assert saved["inputs"]["portfolio_version"] == 16
    markets = saved["result"]["markets"]
    assert markets["BTCTMN"]["fills"] > 0
    assert markets["BTCUSDT"]["fills"] == 0 and markets["BTCUSDT"]["holding"] == "0"
    assert any(row["selected"] == "BTCTMN" for row in saved["result"]["route_changes"])
    assert research_action(tmp_path, "portfolio-replay", {**value, "symbols": value["symbols"][::-1]})["run_id"] == result["run_id"]
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": result["run_id"], "quote_count": 55})["record"]
    assert research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})["status"] == "EXACT_MATCH"


def test_dynamic_route_remains_pinned_while_inventory_is_open(tmp_path):
    from dataclasses import replace

    fx = [replace(top, ts_avail=top.ts_avail - timedelta(seconds=10), bid=Decimal(99), ask=Decimal(101))
          for top in quote_history(n=181, sym="USDTTMN")]
    # TMN starts cheaper and then becomes more expensive before the held position is sold.
    toman = [replace(top, bid=top.bid * 200, ask=top.ask * 200) if index >= 48 else top
             for index, top in enumerate(quote_history(n=180, sym="BTCTMN", turn=1))]
    market_db(tmp_path, quote_history(n=180, turn=1) + toman + fx).c.close()
    value = {**request(), "symbols": ["BTCUSDT", "BTCTMN"], "dynamic_routes": True,
             "cash_by_currency": {"USDT": "100000", "TMN": "100000"},
             "cost": {**request()["cost"], "max_participation": "1"}}
    result = research_action(tmp_path, "portfolio-replay", value)
    saved = research_action(tmp_path, "portfolio-read", {"run_id": result["run_id"]})
    markets = saved["result"]["markets"]
    assert Decimal(markets["BTCTMN"]["holding"]) > 0
    assert markets["BTCUSDT"]["fills"] == 0 and markets["BTCUSDT"]["holding"] == "0"
    assert not any(row["selected"] == "BTCUSDT" for row in saved["result"]["route_changes"])


def test_native_portfolio_saved_read_and_integrity(tmp_path):
    prepare(tmp_path).c.close()
    out = research_action(tmp_path, "portfolio-replay", request())
    reference = {"run_id": out["run_id"]}
    loaded = research_action(tmp_path, "portfolio-read", reference)
    assert loaded["mode"] == "PORTFOLIO" and loaded["outputs_digest"] == out["outputs_digest"]
    assert loaded["result"]["markets"]["BTCUSDT"]["fills"] > 0
    assert research_action(tmp_path, "portfolio-list")["runs"][0]["run_id"] == out["run_id"]
    assert research_action(tmp_path, "portfolio-replay", request())["run_id"] == out["run_id"]
    with pytest.raises(ValueError, match="store mismatch"):
        research_action(tmp_path, "portfolio-read", reference, store="demo")
    path = tmp_path / "runs" / "portfolios" / (out["run_id"] + ".json")
    changed = json.loads(path.read_text("utf-8"))
    changed["performance"] = {"total_return_pct": "99999999"}
    path.write_text(json.dumps(changed), "utf-8")
    assert research_action(tmp_path, "portfolio-read", reference)["performance"] == loaded["performance"]
    assert load_verified_run(path.parent, out["run_id"], store="live")["performance"] == loaded["performance"]
    changed["result"]["end"]["equity"] = "999999"
    path.write_text(json.dumps(changed), "utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_verified_run(path.parent, out["run_id"], store="live")


def test_stale_held_mark_keeps_accounting_but_makes_performance_provisional(tmp_path):
    market_db(tmp_path, quote_history(n=120, turn=1) + quote_history(n=180, sym="ETHUSDT", turn=1)).c.close()
    receipt = research_action(tmp_path, "portfolio-replay", request())
    path = tmp_path / "runs" / "portfolios" / (receipt["run_id"] + ".json")
    out = json.loads(path.read_text("utf-8"))
    result = out["result"]
    assert Decimal(result["markets"]["BTCUSDT"]["holding"]) > 0
    assert result["markets"]["BTCUSDT"]["mark_status"] == "STALE"
    assert result["markets"]["ETHUSDT"]["mark_status"] == "CURRENT"
    assert result["end"]["valuation_status"] == "STALE_VALUATION"
    assert Decimal(result["end"]["equity"]) > 0 and result["markets"]["BTCUSDT"]["orders"]
    assert out["performance"]["status"] == "PROVISIONAL"
    assert out["performance"]["total_return_pct"] is not None
    loaded = research_action(tmp_path, "portfolio-read", {"run_id": out["run_id"]})
    assert loaded["performance"] == out["performance"]
    assert loaded["outputs_digest"] == out["outputs_digest"]


@pytest.mark.parametrize("change", [
    {"symbols": ["BTCUSDT"]}, {"symbols": ["BTCUSDT", "BTCUSDT"]},
    {"symbols": ["BTCUSDT", "../escape"]}, {"symbols": ["BTCUSDT", "UNKNOWN"]},
    {"to": iso(START + timedelta(days=32))}, {"from": iso(START + timedelta(days=1))},
    {"cash": "NaN"}, {"cash": "0"}, {"cost": {"fee_rate": "0.001", "ignored": True}},
    {"rules_mode": "invented"}, {"resolution": "invalid"}, {"params": {"fast": True}}, {"resolution": []},
    *[{"policy": value} for value in (False, 0, "", [])],
    {"cost": {"fee_rate": "0.001", "latency_ms": 500, "max_wait_s": 10**1000, "fee_assumption": "fee-in-received-asset"}},
])
def test_invalid_portfolio_requests_leave_no_records(tmp_path, change):
    prepare(tmp_path).c.close()
    with pytest.raises(ValueError):
        research_action(tmp_path, "portfolio-replay", {**request(), **change})
    assert not list((tmp_path / "runs").rglob("*.json"))


def test_portfolio_private_api_uses_real_supervised_worker(tmp_path):
    db = prepare(tmp_path)
    col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["BTCUSDT", "ETHUSDT"])
    app = make_app(col, RuleService(db), "tok", tmp_path / "runs")

    async def check():
        async with TestClient(TestServer(app)) as client:
            assert (await (await client.get("/api/research")).json())["portfolio_replay"] is True
            value = {**request(), "policy": {"method": "inverse-volatility", "lookback": 3, "daily_loss_limit": "0.05"}}
            body = {"action": "portfolio-replay", "value": value}
            assert (await client.post("/api/research/action", json=body)).status == 403
            response = await client.post("/api/research/action", json=body, headers={"X-Gym-Token": "tok"})
            assert response.status == 200, await response.text()
            saved = await response.json()
            assert saved["authority"] == "PAPER_ONLY"
            loaded = await calculate(tmp_path, "portfolio-replay", value)
            assert loaded["run_id"] == saved["run_id"]
            response = await client.post("/api/research/action", json={"action": "portfolio-read", "value": {"run_id": saved["run_id"]}},
                                         headers={"X-Gym-Token": "tok"})
            assert response.status == 200
            assert (await response.json())["result"]["balances"]
    try:
        asyncio.run(check())
    finally:
        db.c.close()


def test_portfolio_observation_budget_is_checked_inside_snapshot(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("gym.services.portfolio")
    prepare(tmp_path).c.close()
    monkeypatch.setattr(module, "MAX_OBSERVATIONS", 10)
    with pytest.raises(ValueError, match="observation budget"):
        research_action(tmp_path, "portfolio-replay", request())
    assert not (tmp_path / "runs").exists()
