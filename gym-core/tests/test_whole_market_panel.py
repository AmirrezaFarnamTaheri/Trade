"""Whole-market feature slices preserve the information available at each cutoff."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import InstrumentId, iso
from gym.services.historical_universe import whole_window_spot_selection
from gym.services.market_watchlists import save_watchlist
from scripts.whole_market_panel import market_panel
from tests.support import START, market_db, quote


def test_panel_distinguishes_missing_markets_and_strictly_prior_receipts(tmp_path):
    old = START - timedelta(seconds=70)
    recent = START - timedelta(seconds=10)
    future = START + timedelta(seconds=30)
    db = market_db(tmp_path, [quote(old, "99", "101"), quote(recent, "109", "111"), quote(START, "119", "121"),
                             replace(quote(future, "49", "51"), symbol="SOLUSDT"),
                             replace(quote(recent, "9", "11"), symbol="ADAUSDT", ask_qty=Decimal(0))])
    for symbol, listed, products in (
        ("BTCUSDT", old, {"is_spot": True}),
        ("ADAUSDT", old, {"is_spot": True, "is_margin": True}),
        ("XRPUSDT", old, {"is_spot": False, "is_otc": True}),
        ("SOLUSDT", future, {"is_spot": True}),
    ):
        db.upsert_instrument(InstrumentId.wallex(symbol), {}, products, "fixture", listed)
    try:
        begin = START - timedelta(minutes=2)
        config, _, _, first, second = market_panel(db, begin, START + timedelta(minutes=2), step_seconds=60, age_seconds=30)
        one = {r["symbol"]: r for r in first["rows"]}
        assert config["mode"] == "WHOLE"
        assert set(one) == {"BTCUSDT", "ADAUSDT", "XRPUSDT"}
        assert one["BTCUSDT"]["receipt"] == iso(recent)
        assert one["BTCUSDT"]["momentum_reference_receipt"] == iso(old)
        assert Decimal(one["BTCUSDT"]["features"]["momentum_bps"]) == 1_000
        assert one["ADAUSDT"]["products"]["margin"] is True
        assert one["ADAUSDT"]["features"]["ask_size"] is None
        assert one["XRPUSDT"]["products"]["otc"] is True
        assert one["XRPUSDT"]["eligibility"] == "SPOT_NOT_CONFIRMED"
        assert one["XRPUSDT"]["features"]["bid"] is None
        assert first["ranked_spot_symbols"] == ["BTCUSDT"]
        assert {r["symbol"] for r in second["rows"]} == {*one, "SOLUSDT"}
        assert second["ranked_spot_symbols"] == []
        _, *prefix = market_panel(db, begin, START + timedelta(seconds=1), step_seconds=60, age_seconds=30)
        sliced = prefix[-1]
        assert sliced == first
        _, curated = market_panel(db, START, START + timedelta(minutes=1), step_seconds=60,
                                  age_seconds=30, symbols=["XRPUSDT", "BTCUSDT"])
        assert [r["symbol"] for r in curated["rows"]] == ["BTCUSDT", "XRPUSDT"]
        with pytest.raises(ValueError, match="unknown markets at cutoff"):
            list(market_panel(db, START, START + timedelta(minutes=1), step_seconds=60,
                              age_seconds=30, symbols=["SOLUSDT"]))
    finally:
        db.c.close()


def test_watchlist_panel_cannot_warm_up_from_prelisting_or_another_venue(tmp_path):
    venue, symbol = "fixture", "EURCOIN"
    db = market_db(tmp_path, [replace(quote(START + timedelta(seconds=175), "900", "904"), symbol=symbol)])
    def when(seconds):
        return START + timedelta(seconds=seconds)

    try:
        inst = InstrumentId(venue, symbol, "COIN", "EUR")
        db.upsert_instrument(inst, {}, {"is_spot": True}, "fixture", when(60))
        db.upsert_instrument(inst, {}, {"is_spot": False}, "fixture", when(190))
        for seconds, bid, ask in ((-10, "10", "11"), (55, "20", "22"), (110, "30", "32"),
                                  (170, "40", "42"), (235, "50", "52")):
            db.add_book_top(replace(quote(when(seconds), bid, ask), symbol=symbol), None, venue=venue)
        watchlist = save_watchlist(tmp_path, {"name": "EUR", "effective_from": iso(START), "symbols": [symbol]})
        header, *slices = market_panel(db, START, when(300), step_seconds=60, age_seconds=15, venue=venue, watchlist=watchlist)
        assert header["universe_selection"] == whole_window_spot_selection(
            db, START, when(300), venue=venue, store="live", watchlist=watchlist)
        assert header["mode"] == "CURATED"
        rows = [item["rows"][0] for item in slices]
        assert rows[1]["eligibility"] == "QUOTE_PRECEDES_SPOT_WINDOW"
        assert rows[2]["eligibility"] == "READY" and rows[2]["momentum_reference_receipt"] is None
        assert rows[2]["validity"]["ask"] and not rows[2]["validity"]["momentum_bps"]
        assert rows[3]["momentum_reference_receipt"] == iso(when(110))
        assert rows[3]["receipt"] == iso(when(170)) and slices[3]["ranked_spot_symbols"] == [symbol]
        assert rows[4]["eligibility"] == "SPOT_NOT_CONFIRMED" and rows[4]["exit_quote_available"]
    finally:
        db.c.close()
