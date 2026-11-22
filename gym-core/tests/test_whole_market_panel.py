"""Whole-market feature slices preserve the information available at each cutoff."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import InstrumentId, iso
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
        config, first, second = market_panel(db, START, START + timedelta(minutes=2), step_seconds=60, age_seconds=30)
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
        _, sliced = market_panel(db, START, START + timedelta(seconds=1), step_seconds=60, age_seconds=30)
        assert sliced == first
        _, curated = market_panel(db, START, START + timedelta(minutes=1), step_seconds=60,
                                  age_seconds=30, symbols=["XRPUSDT", "BTCUSDT"])
        assert [r["symbol"] for r in curated["rows"]] == ["BTCUSDT", "XRPUSDT"]
        with pytest.raises(ValueError, match="unknown markets at cutoff"):
            list(market_panel(db, START, START + timedelta(minutes=1), step_seconds=60,
                              age_seconds=30, symbols=["SOLUSDT"]))
    finally:
        db.c.close()
