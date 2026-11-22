"""Historical universes are selected before evaluation without looking at future trades."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import InstrumentId, TradeTick, iso
from gym.services.historical_universe import select_universe
from gym.services.research_actions import research_action
from gym.services.research_ledger import ResearchLedger
from gym.services.research_market import screen_markets
from gym.services.research_process import calculate
from tests.support import START, market_db, quote_history


def _receipt(db, symbol, amount, at):
    db.add_trade(TradeTick(symbol, at, at, Decimal(100), Decimal(amount), "BUY"), "fixture")


def test_universe_manifest_preserves_catalogue_only_markets_and_rejects_unknown_symbols(tmp_path):
    db = market_db(tmp_path, quote_history(n=10))
    try:
        db.c.execute("INSERT INTO instrument_specs(instrument_id,valid_from,spec,source) VALUES(?,?,?,?)",
                     ("wallex:OTCUSDT", iso(START), '{"is_otc":true,"is_spot":false}', "fixture"))
        db.c.commit()
    finally:
        db.c.close()
    request = {"as_of": iso(START + timedelta(minutes=1)), "lookback_seconds": 60}
    whole = research_action(tmp_path, "universe-manifest", request)
    assert whole["mode"] == "WHOLE"
    assert whole["coverage"] == {"resolved": 2, "with_effective_spec": 1, "observed": 1,
                                 "catalogue_completeness": "UNKNOWN"}
    otc = next(row for row in whole["markets"] if row["symbol"] == "OTCUSDT")
    assert otc["products"] == {"spot": False, "margin": None, "otc": True}
    assert otc["status"] == "NO_RECENT_QUOTE"
    curated = research_action(tmp_path, "universe-manifest", {**request, "symbols": ["BTCUSDT"]})
    assert curated["mode"] == "CURATED" and len(curated["markets"]) == 1
    assert curated["manifest_id"] != whole["manifest_id"]
    earlier = research_action(tmp_path, "universe-manifest", {**request, "as_of": iso(START - timedelta(seconds=1))})
    assert earlier["markets"] == []
    with pytest.raises(ValueError, match="unknown markets"):
        research_action(tmp_path, "universe-manifest", {**request, "symbols": ["UNKNOWN"]})


def test_receipt_search_includes_aligned_bounds_and_excludes_other_venues(tmp_path):
    from tests.support import quote

    start, end = START, START + timedelta(minutes=1)
    before, after = start - timedelta(microseconds=1), end + timedelta(microseconds=1)
    db = market_db(tmp_path, [])
    try:
        for symbol, stamp in (("BTCUSDT", before), ("BTCUSDT", start), ("BTCUSDT", end), ("BTCUSDT", after),
                              ("ETHUSDT", start), ("SOLUSDT", before), ("XRPUSDT", after)):
            db.add_book_top(replace(quote(stamp, "99", "100"), symbol=symbol), None)
        db.add_book_top(replace(quote(end, "99", "100"), symbol="OTHERUSDT"), None, venue="lab")
    finally:
        db.c.close()
    manifest = research_action(tmp_path, "universe-manifest", {"as_of": iso(end), "lookback_seconds": 60})
    assert {row["symbol"]: row["last_quote_receipt"] for row in manifest["markets"]} == {
        "BTCUSDT": iso(end), "ETHUSDT": iso(start),
    }


def test_trade_volume_selection_uses_only_pre_start_receipts(tmp_path):
    """Later publication cannot turn a historically obscure market into a winner."""
    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        old = START - timedelta(minutes=2)
        _receipt(db, "BTCUSDT", "1", old)
        _receipt(db, "ETHUSDT", "10", old)
        selected = select_universe(db, START, quote_currency="USDT", top_n=2, lookback_hours=1)
        assert selected["symbols"] == ["ETHUSDT", "BTCUSDT"]
        assert selected["as_of_exclusive"] == iso(START)
        _receipt(db, "BTCUSDT", "100000", START + timedelta(minutes=1))
        assert select_universe(db, START, quote_currency="USDT", top_n=2, lookback_hours=1) == selected
        _receipt(db, "BTCUSDT", "100000", START - timedelta(seconds=1))
        assert select_universe(db, START, quote_currency="USDT", top_n=2, lookback_hours=1)["symbols"][0] == "BTCUSDT"
    finally:
        db.c.close()


def test_market_screen_can_rank_as_of_top_n_and_flag_collection_gap(tmp_path):
    """As-of screening retains a market that later stopped publishing rather than survivorship-filtering it."""
    data = quote_history(n=180) + quote_history(n=30, sym="ETHUSDT")
    db = market_db(tmp_path, data)
    try:
        for symbol, quantity in (("BTCUSDT", "2"), ("ETHUSDT", "3")):
            _receipt(db, symbol, quantity, START - timedelta(minutes=5))
        request = {"symbols": [], "reference": "BTCUSDT", "quote_currency": "USDT",
                   "from": iso(START), "to": iso(START + timedelta(minutes=30)),
                   "resolution": "1min", "metric": "momentum_percent", "top_n": 2,
                   "lookback_hours": 1}
        report = screen_markets(db, request, store="live")
        assert report["universe_selection"]["symbols"] == ["ETHUSDT", "BTCUSDT"]
        row = next(r for r in report["excluded"] if r["symbol"] == "ETHUSDT")
        assert row["collection_status"]["status"] == "COLLECTION_GAP_OR_STOPPED"
        assert row["collection_status"]["delisted"] is None
    finally:
        db.c.close()


def test_portfolio_opt_in_top_n_saved_identity_contains_selection_vintage(tmp_path):
    """Opt-in historical selection is in the verified portfolio run identity."""
    from tests.test_portfolio_workflow import request

    db = market_db(tmp_path, quote_history(n=180) + quote_history(n=180, sym="ETHUSDT"))
    try:
        for symbol, qty in (("BTCUSDT", "1"), ("ETHUSDT", "2")):
            _receipt(db, symbol, qty, START - timedelta(minutes=10))
    finally:
        db.c.close()
    value = {**request(), "symbols": [], "top_n": 2,
             "quote_currency": "USDT", "lookback_hours": 1}
    record = research_action(tmp_path, "portfolio-replay", value)
    loaded = research_action(tmp_path, "portfolio-read", {"run_id": record["run_id"]})
    assert loaded["inputs"]["portfolio_version"] == 6
    assert loaded["inputs"]["universe_selection"]["symbols"] == ["ETHUSDT", "BTCUSDT"]
    assert record["universe_selection"] == loaded["inputs"]["universe_selection"]
    assert loaded["inputs"]["store"] == "live"


@pytest.mark.parametrize("dynamic_routes", [False, True])
def test_whole_portfolio_changes_entry_universe_without_discarding_held_positions(tmp_path, dynamic_routes):
    from tests.test_portfolio_workflow import request

    def at(seconds):
        return START + timedelta(seconds=seconds)

    symbols = ("BTCTMN", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPTMN")
    quotes = [top for symbol in symbols for top in quote_history(n=66, sym=symbol, turn=0.55 if symbol == "SOLUSDT" else 1)]
    quotes += [replace(top, ts_avail=top.ts_avail - timedelta(seconds=1), bid=Decimal(99), ask=Decimal(101))
               for top in quote_history(n=67, sym="USDTTMN")]
    db = market_db(tmp_path, quotes)
    try:
        for symbol in symbols:
            db.upsert_instrument(InstrumentId.wallex(symbol), {}, {"is_spot": True}, "fixture",
                                 at({"BTCTMN": 240, "ETHUSDT": 320}.get(symbol, 0)))
        for symbol, seconds in (("BTCUSDT", 181), ("SOLUSDT", 250)):
            db.upsert_instrument(InstrumentId.wallex(symbol), {}, {"is_spot": False}, "fixture", at(seconds))
    finally:
        db.c.close()
    value = {**request(), "to": iso(at(660)), "cash_by_currency": {"USDT": "1000", "TMN": "100000"},
             "dynamic_routes": dynamic_routes}
    value["cost"] = {**value["cost"], "max_participation": "1"}
    value.pop("symbols")
    response = research_action(tmp_path, "portfolio-replay", value)
    saved = research_action(tmp_path, "portfolio-read", {"run_id": response["run_id"]})
    selection = saved["inputs"]["universe_selection"]
    assert selection["schema"] == "whole-spot-universe/2" and selection["symbols"] == list(symbols)
    assert selection["start_symbols"] == ["BTCUSDT", "SOLUSDT", "XRPTMN"]
    assert selection["entry_windows"]["ETHUSDT"] == [[iso(at(320)), iso(at(660))]]
    markets = saved["result"]["markets"]
    canceled, = markets["BTCUSDT"]["orders"]
    assert canceled["status"] == "CANCELLED" and canceled["reason"] == "SPOT_MEMBERSHIP_ENDED"
    assert canceled["cancelled_at"] == iso(at(181))
    assert markets["BTCTMN"]["orders"][0]["decision_time"] >= iso(at(420))
    assert markets["ETHUSDT"]["orders"][0]["decision_time"] >= iso(at(480))
    sold, = [o for o in markets["SOLUSDT"]["orders"] if o["side"] == "SELL" and o["status"] == "FILLED"]
    assert sold["fill_time"] > iso(at(250)) and Decimal(markets["SOLUSDT"]["holding"]) == 0
    short = research_action(tmp_path, "portfolio-replay", {**value, "to": iso(at(221))})
    prefix = research_action(tmp_path, "portfolio-read", {"run_id": short["run_id"]})
    assert "ETHUSDT" not in prefix["inputs"]["symbols"]
    early_fill, = [o for o in prefix["result"]["markets"]["SOLUSDT"]["orders"] if o["status"] == "FILLED"]
    assert early_fill == markets["SOLUSDT"]["orders"][0]
    with ResearchLedger(tmp_path / "research.sqlite3") as ledger:
        hypothesis = ledger.register({"symbol": "BTCUSDT", "strategy": value["strategy"], "params": value["params"]})
        ledger.schedule({"hypothesis_id": hypothesis["hypothesis_id"], "first_at": value["to"], "every_seconds": 3600,
                         "lookback_seconds": 660, "resolution": value["resolution"], "cash": value["cash"],
                         "fee_rate": value["cost"]["fee_rate"], "max_participation": "1", "dynamic_routes": dynamic_routes,
                         "cash_by_currency": value["cash_by_currency"]})
    completed, = asyncio.run(calculate(tmp_path, "tick", at=value["to"]))["completed"]
    assert completed["run_id"] == saved["run_id"]
    checkpoint = research_action(tmp_path, "replay-checkpoint", {"run_id": saved["run_id"], "quote_count": 80})["record"]
    assert research_action(tmp_path, "replay-resume", {"checkpoint_id": checkpoint["id"]})["result_digest"] == saved["outputs_digest"]


def test_membership_ends_after_partial_entry_keeps_fill_and_cancels_remainder(tmp_path):
    from tests.test_portfolio_workflow import request

    btc = quote_history(n=30, turn=1)
    btc[19] = replace(btc[19], ask_qty=Decimal("0.01"))
    fx = [replace(top, ts_avail=top.ts_avail - timedelta(seconds=1), bid=Decimal(99), ask=Decimal(101))
          for top in quote_history(n=31, sym="USDTTMN")]
    db = market_db(tmp_path, btc + quote_history(n=30, sym="ETHTMN", turn=1) + fx)
    loss = START + timedelta(seconds=195)
    try:
        for symbol in ("BTCUSDT", "ETHTMN"):
            db.upsert_instrument(InstrumentId.wallex(symbol), {}, {"is_spot": True}, "fixture", START)
        db.upsert_instrument(InstrumentId.wallex("BTCUSDT"), {}, {"is_spot": False}, "fixture", loss)
    finally:
        db.c.close()
    value = {**request(), "to": iso(START + timedelta(seconds=300)),
             "cash_by_currency": {"USDT": "1000", "TMN": "100000"}}
    value["cost"] = {**value["cost"], "max_participation": "0.25", "carry_remainder": True}
    del value["symbols"]
    replay = research_action(tmp_path, "portfolio-replay", value)
    saved = research_action(tmp_path, "portfolio-read", {"run_id": replay["run_id"]})
    market = saved["result"]["markets"]["BTCUSDT"]
    filled, remainder = market["orders"]
    assert filled["status"] == "FILLED" and Decimal(filled["qty"]) == Decimal("0.0025")
    assert remainder["status"] == "CANCELLED" and remainder["parent"] == filled["ref"]
    assert remainder["cancelled_at"] == iso(loss)
    assert Decimal(market["holding"]) == Decimal(filled["qty"]) - Decimal(filled["fee"])
