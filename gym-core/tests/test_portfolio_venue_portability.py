"""One portfolio strategy consumes independent venue records and denominations."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.store import MarketDB
from gym.domain.model import InstrumentId, iso
from gym.services.data_portal import DataPortal
from gym.services.research_actions import research_action
from gym.services.research_process import calculate, work_estimate
from scripts.audit_shared_portfolio import audit
from tests.support import START, market_db, quote_history
from tests.test_portfolio_workflow import request


def test_fixed_universe_replay_uses_second_venue_terms_and_preserves_scaled_returns(tmp_path):
    common = request()
    originals = ("BTCUSDT", "ETHUSDT")
    alternates = ("ALPHA", "BETA")
    scale = Decimal(100)
    db = market_db(tmp_path, [])
    try:
        for symbol, alternative in zip(originals, alternates):
            instrument = InstrumentId.wallex(symbol)
            db.upsert_instrument(instrument, {}, {"stepSize": 6, "minNotional": "1"}, "reference", START)
            db.upsert_instrument(InstrumentId("fixture", alternative, instrument.base + "X", "EUR"),
                                 {}, {"stepSize": 6, "minNotional": "100"}, "fixture", START)
            for top in quote_history(n=180, sym=symbol):
                db.add_book_top(top, None)
                db.add_book_top(replace(top, symbol=alternative, bid=top.bid * scale, ask=top.ask * scale),
                                None, venue="fixture")
        # A different venue's book for the same symbol must not win the lookup.
        db.add_book_top(replace(quote_history(n=1)[0], symbol="ALPHA"), None)
    finally:
        db.c.close()

    def replay(value):
        result = research_action(tmp_path, "portfolio-replay", value)
        return research_action(tmp_path, "portfolio-read", {"run_id": result["run_id"]})

    a = replay({**common, "symbols": list(originals)})
    alternate_request = {**common, "symbols": list(alternates), "venue": "fixture",
                         "cash": str(Decimal(common["cash"]) * scale)}
    assert work_estimate(tmp_path, alternate_request) == 360
    b = replay(alternate_request)
    assert b["inputs"]["venue"] == "fixture"
    assert b["result"]["quote"] == "EUR"
    assert b["result"]["valuation"]["basis"] == "USDT conversion unavailable"
    assert b["result"]["end"]["net_usdt_eq"] is None
    assert b["performance"]["total_return_pct"] == a["performance"]["total_return_pct"]
    assert Decimal(b["result"]["end"]["equity"]) == Decimal(a["result"]["end"]["equity"]) * scale
    for reference, alternative in zip(originals, alternates):
        aa, bb = a["result"]["markets"][reference], b["result"]["markets"][alternative]
        assert aa["observations"] == bb["observations"] == 180
        assert aa["fills"] == bb["fills"] and aa["fills"] > 0
        assert Decimal(bb["realized_pnl"]) == Decimal(aa["realized_pnl"]) * scale
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": b["run_id"], "quote_count": 100})
    resumed = research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["record"]["id"]})
    assert resumed["result_digest"] == b["outputs_digest"]


def test_alternate_venue_catalogue_replays_and_schedules_point_in_time(tmp_path):
    ending = START + timedelta(minutes=30)
    listed = START + timedelta(minutes=8)
    removed = START + timedelta(minutes=5)
    venue = "second-venue"
    db = market_db(tmp_path, quote_history(n=180, sym="ALPHA"))
    try:
        for symbol, at, spot in (("ALPHA", START, True), ("BETA", START, True),
                                 ("GAMMA", listed, True), ("DELTA", START, False)):
            db.upsert_instrument(InstrumentId(venue, symbol, symbol, "EUR"), {},
                                 {"is_spot": spot, "is_otc": not spot, "stepSize": 4, "minNotional": "5"}, "fixture", at)
            if spot:
                for top in quote_history(n=180, sym=symbol):
                    db.add_book_top(top, None, venue=venue)
        db.upsert_instrument(InstrumentId(venue, "ALPHA", "ALPHA", "EUR"), {}, {"is_spot": False}, "fixture", removed)
        db.upsert_instrument(InstrumentId("other", "REMOTE", "REMOTE", "EUR"), {},
                             {"is_spot": True}, "fixture", START)
        db.add_book_top(quote_history(n=1, sym="REMOTE")[0], None, venue="other")
    finally:
        db.c.close()
    report = {"as_of": iso(START), "lookback_seconds": 86400, "venue": venue}
    manifest = research_action(tmp_path, "universe-manifest", report)
    assert manifest["venue"] == venue
    assert manifest["coverage"]["observed"] == 3  # Early GAMMA quote is visible without spot terms.
    gamma = next(row for row in manifest["markets"] if row["symbol"] == "GAMMA")
    assert gamma["products"]["spot"] is None and gamma["spec_effective_from"] is None
    assert {row["symbol"] for row in manifest["markets"]} == {"ALPHA", "BETA", "DELTA", "GAMMA"}
    value = {**request(), "venue": venue}
    del value["symbols"]
    response = research_action(tmp_path, "portfolio-replay", value)
    run = research_action(tmp_path, "portfolio-read", {"run_id": response["run_id"]})
    selection = run["inputs"]["universe_selection"]
    assert selection["manifest_id"] == manifest["manifest_id"]
    assert selection["start_symbols"] == ["ALPHA", "BETA"]
    assert selection["symbols"] == ["ALPHA", "BETA", "GAMMA"]
    assert selection["entry_windows"] == {"ALPHA": [[iso(START), iso(removed)]], "GAMMA": [[iso(listed), iso(ending)]]}
    assert selection["excluded"] == {"DELTA": "SPOT_NOT_CONFIRMED"}
    assert run["result"]["quote"] == "EUR"
    gamma_orders = run["result"]["markets"]["GAMMA"]["orders"]
    assert gamma_orders and all(order["decision_time"] >= iso(listed) for order in gamma_orders)
    assert any(order["side"] == "SELL" and order["status"] == "FILLED" and order["fill_time"] > iso(removed)
               for order in run["result"]["markets"]["ALPHA"]["orders"])
    registered = research_action(tmp_path, "register", {"symbol": "ALPHA", "strategy": value["strategy"], "params": value["params"]})
    job = {"hypothesis_id": registered["hypothesis_id"], "first_at": iso(ending), "every_seconds": 3600,
           "lookback_seconds": 1800, "resolution": "1min", "cash": value["cash"],
           "fee_rate": value["cost"]["fee_rate"], "venue": venue}
    research_action(tmp_path, "schedule", job)
    completed, = asyncio.run(calculate(tmp_path, "tick", at=job["first_at"]))["completed"]
    assert completed["run_id"] == run["run_id"]
    frozen = research_action(tmp_path, "watchlist-save", {
        "name": "EUR curated", "effective_from": iso(START), "symbols": ["BETA", "GAMMA"]})["watchlist"]
    curated = research_action(tmp_path, "portfolio-replay", {**value, "watchlist_id": frozen["watchlist_id"]})
    assert curated["universe_selection"]["symbols"] == ["BETA", "GAMMA"]
    assert curated["universe_selection"]["venue"] == venue
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": run["run_id"], "quote_count": 100})["record"]
    assert research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})["result_digest"] == run["outputs_digest"]
    with pytest.raises(ValueError, match="invalid market venue"):
        research_action(tmp_path, "universe-manifest", {**report, "venue": "second-*"})


@pytest.mark.parametrize(("target", "side", "price", "fee_currency"), [
    ("0.5", "BUY", "0.81", "EUR"), ("0", "SELL", "0.79", "GBP"),
])
def test_alternate_archive_spot_fx_uses_pair_terms_and_reconciles_both_currencies(
        tmp_path, target, side, price, fee_currency):
    from collections import defaultdict
    from decimal import localcontext

    venue, pair = "second-venue", "EURGBP"
    db = market_db(tmp_path, [replace(quote_history(n=1)[0], symbol=pair)])
    try:
        for symbol, base, quote_asset in (("ALPHA", "A", "EUR"), ("BETA", "B", "GBP"), (pair, "EUR", "GBP")):
            db.upsert_instrument(InstrumentId(venue, symbol, base, quote_asset), {},
                                 {"is_spot": True, "stepSize": 4, "minNotional": "1"}, "fixture", START - timedelta(minutes=1))
            for index, top in enumerate(quote_history(n=60, sym=symbol)):
                if symbol == pair:
                    top = replace(top, ts_avail=top.ts_avail - timedelta(seconds=1),
                                  bid=Decimal("0.79") if index < 30 else Decimal("0.99"),
                                  ask=Decimal("0.81") if index < 30 else Decimal("1.01"),
                                  bid_qty=Decimal("8"), ask_qty=Decimal("8"))
                db.add_book_top(top, None, venue=venue)
        db.upsert_instrument(InstrumentId(venue, pair, "EUR", "GBP"), {},
                             {"is_spot": True, "stepSize": 4, "minNotional": "1", "is_zero_fee": True},
                             "fixture", START + timedelta(minutes=5))
    finally:
        db.c.close()

    value = {**request(), "to": iso(START + timedelta(minutes=10)), "venue": venue, "valuation_symbol": pair,
             "cash_by_currency": {"EUR": "100", "GBP": "800"},
             "fx_rebalance": {"target_base_cash_share": target, "band": "0.02", "max_order_base": "10"}}
    del value["symbols"]
    value["cost"] = {**value["cost"], "max_participation": "0.5"}
    replay = research_action(tmp_path, "portfolio-replay", value)
    run = research_action(tmp_path, "portfolio-read", {"run_id": replay["run_id"]})
    assert run["inputs"]["valuation_symbol"] == pair and run["inputs"]["portfolio_version"] == 27
    result = run["result"]
    assert result["quote"] == "EUR" and Decimal(result["start_cash"]) == Decimal("1100")
    assert result["end"]["net_usdt_eq"] is None
    assert result["valuation"]["conversion"]["secondary_currency"] == "GBP"
    assert result["valuation"]["conversion"]["start_at"] == iso(START - timedelta(seconds=1))
    assert Decimal(result["valuation"]["conversion"]["opening_rate"]) == Decimal("0.8")
    assert Decimal(result["valuation"]["conversion"]["closing_rate"]) == Decimal("1")
    assert result["markets"][pair]["reason"] == "QUOTE_CURRENCY_REFERENCE"
    fills = [order for order in result["fx_orders"] if order["status"] == "FILLED"]
    first = fills[0]
    assert first["side"] == side and Decimal(first["qty"]) == Decimal(4)
    assert Decimal(first["price"]) == Decimal(price) and first["fill_time"] > first["decision_time"]
    assert first["fee_ccy"] == fee_currency
    assert Decimal(first["fee"]) > 0 and Decimal(fills[-1]["fee"]) == 0
    with localcontext() as context:
        context.prec = 80
        opening = {asset: Decimal(amount) for asset, amount in value["cash_by_currency"].items()}
        balances = defaultdict(Decimal, opening)
        for posting in result["postings"]:
            balances[posting["ccy"]] += Decimal(posting["amount"])
        assert dict(balances) == {asset: Decimal(amount) for asset, amount in result["balances"].items()}
    db = MarketDB(tmp_path / "market.db", readonly=True)
    try:
        report = audit(run, DataPortal(db, venue=venue))
        assert report["currency"] == "EUR" and report["secondary_currency"] == "GBP"
        assert Decimal(report["components"]["passive_cash_fx"]) == Decimal("-200")
        assert Decimal(report["raw_reconciliation_residual_reporting_currency"]) == 0
    finally:
        db.c.close()
    registered = research_action(tmp_path, "register", {"symbol": "ALPHA", "strategy": value["strategy"], "params": value["params"]})
    job = {"hypothesis_id": registered["hypothesis_id"], "first_at": value["to"], "every_seconds": 3600,
           "lookback_seconds": 600, "resolution": value["resolution"], "cash": value["cash"],
           "fee_rate": value["cost"]["fee_rate"], "max_participation": value["cost"]["max_participation"],
           **{key: value[key] for key in ("venue", "valuation_symbol", "cash_by_currency", "fx_rebalance")}}
    research_action(tmp_path, "schedule", job)
    completed, = asyncio.run(calculate(tmp_path, "tick", at=job["first_at"]))["completed"]
    assert completed["run_id"] == run["run_id"]
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": run["run_id"], "quote_count": 80})["record"]
    assert research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})["result_digest"] == run["outputs_digest"]
    with pytest.raises(ValueError, match="needs valuation_symbol"):
        research_action(tmp_path, "portfolio-replay", {**value, "valuation_symbol": None})
    with pytest.raises(ValueError, match="matching the valuation pair"):
        research_action(tmp_path, "portfolio-replay", {**value, "valuation_symbol": "BETA"})
    stop_at = START + timedelta(minutes=5, seconds=20)
    db = MarketDB(tmp_path / "market.db")
    try:
        db.upsert_instrument(InstrumentId(venue, pair, "EUR", "GBP"), {},
                             {"is_spot": False}, "fixture", stop_at)
    finally:
        db.c.close()
    disabled = research_action(tmp_path, "portfolio-replay", value)
    disabled_run = research_action(tmp_path, "portfolio-read", {"run_id": disabled["run_id"]})
    disabled_orders = disabled_run["result"]["fx_orders"]
    assert any(order["status"] == "NONFILL" and order["decision_time"] >= iso(stop_at) for order in disabled_orders)
    assert all(order["fill_time"] < iso(stop_at) for order in disabled_orders if order["status"] == "FILLED")
    assert disabled_run["result"]["end"]["valuation_status"] == "STALE_VALUATION"
