"""One portfolio strategy consumes independent venue records and denominations."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import InstrumentId, iso
from gym.services.research_actions import research_action
from gym.services.research_process import calculate, work_estimate
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
