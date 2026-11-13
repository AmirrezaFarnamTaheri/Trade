"""Observation recovery never republishes retained metadata as a fresh REST receipt."""
import asyncio
import json
from datetime import timedelta

import pytest

from gym.adapters.store import SegmentWriter
from gym.domain.model import InstrumentId
from gym.services.capabilities import workspace_capabilities
from gym.services.collector import CATALOG_PATH, Collector
from tests.support import START, market_db


def catalogue():
    return [{"symbol": base + quote, "base_asset": base, "quote_asset": quote,
             "is_spot": True, "flags": [], "stats": {"24h": {"volume": "100"}}}
            for base, quote in (("BTC", "USDT"), ("ETH", "USDT"), ("USDT", "TMN"))]


def test_rest_outage_recovers_whole_retained_universe_without_rewriting_metadata(tmp_path, monkeypatch):
    db = market_db(tmp_path, [])
    for row in catalogue():
        db.upsert_instrument(InstrumentId.wallex(row["symbol"], row["base_asset"], row["quote_asset"]),
                             {}, row, "rest:" + CATALOG_PATH, START)
    before = db.c.execute("SELECT * FROM instrument_specs ORDER BY instrument_id").fetchall()
    seg = SegmentWriter(tmp_path / "raw", db)
    collector = Collector(db, seg, None)

    async def unavailable(*_):
        raise TimeoutError("public REST unavailable")

    monkeypatch.setattr(collector, "rest_text", unavailable)
    try:
        asyncio.run(collector.load_catalog(None))
        assert set(collector.insts) == {row["symbol"] for row in catalogue()}
        assert collector.catalog_received_at is None
        assert workspace_capabilities(collector)["catalog_source"] == "RETAINED_METADATA"
        assert before == db.c.execute("SELECT * FROM instrument_specs ORDER BY instrument_id").fetchall()
        assert any(flag == "CATALOG_RETAINED" for flag, in db.c.execute("SELECT flag FROM quality_events"))
    finally:
        seg.close()
        db.c.close()


def test_retained_catalogue_respects_selection_and_malformed_metadata_cannot_be_backfilled(tmp_path, monkeypatch):
    db = market_db(tmp_path, [])
    for row in catalogue():
        db.upsert_instrument(InstrumentId.wallex(row["symbol"], row["base_asset"], row["quote_asset"]),
                             {}, row, "rest:" + CATALOG_PATH, START)
    seg = SegmentWriter(tmp_path / "raw", db)
    collector = Collector(db, seg, None, remove_symbols=["ETHUSDT"])

    async def unavailable(*_):
        raise TimeoutError()

    monkeypatch.setattr(collector, "rest_text", unavailable)
    try:
        asyncio.run(collector.load_catalog(None))
        assert "ETHUSDT" not in collector.insts and len(collector.insts) == 2
        db.c.execute("UPDATE instrument_specs SET spec='{}' WHERE instrument_id='wallex:ETHUSDT'")
        rejected = Collector(db, seg, None)
        monkeypatch.setattr(rejected, "rest_text", unavailable)
        asyncio.run(rejected.load_catalog(None))
        assert not rejected.insts and not rejected.catalog
    finally:
        seg.close()
        db.c.close()


def test_current_rest_success_is_distinguished_from_retained_metadata(tmp_path, monkeypatch):
    from gym.services import collector as module

    db = market_db(tmp_path, [])
    seg = SegmentWriter(tmp_path / "raw", db)
    collector = Collector(db, seg, None)

    async def observed(*_):
        return json.dumps({"result": {"markets": catalogue()}})

    monkeypatch.setattr(collector, "rest_text", observed)
    monkeypatch.setattr(module, "now_utc", lambda: START + timedelta(days=1))
    try:
        asyncio.run(collector.load_catalog(None))
        assert len(collector.insts) == 3 and collector.catalog_received_at == START + timedelta(days=1)
        assert workspace_capabilities(collector)["catalog_source"] == "PUBLIC_REST"
    finally:
        seg.close()
        db.c.close()


@pytest.mark.parametrize("raw", [b"invalid", "x" * (4 * 1024 * 1024 + 1)])
def test_retained_catalogue_rejects_invalid_storage_types_and_oversized_rows(tmp_path, raw):
    db = market_db(tmp_path, [])
    row = catalogue()[0]
    db.upsert_instrument(InstrumentId.wallex(row["symbol"], row["base_asset"], row["quote_asset"]),
                         {}, row, "rest:" + CATALOG_PATH, START)
    db.c.execute("UPDATE instrument_specs SET spec=?", (raw,))
    seg = SegmentWriter(tmp_path / "raw", db)
    try:
        assert Collector(db, seg, None).retained_catalog(START) == []
    finally:
        seg.close()
        db.c.close()


def test_refresh_stores_a_changed_catalogue_without_changing_the_observed_markets(tmp_path, monkeypatch):
    from gym.services import collector as module
    from gym.services.data_portal import DataPortal

    db = market_db(tmp_path, [])
    seg = SegmentWriter(tmp_path / "raw", db)
    collector = Collector(db, seg, None)
    rows = catalogue()
    state = {"fail": False}

    async def observed(*_):
        if state["fail"]:
            raise TimeoutError
        return json.dumps({"result": {"markets": rows}})

    monkeypatch.setattr(collector, "rest_text", observed)
    monkeypatch.setattr(module, "now_utc", lambda: START)
    try:
        asyncio.run(collector.load_catalog(None))
        observed_markets = dict(collector.insts)
        symbol = rows[0]["symbol"]
        rows[0] = rows[0] | {"is_zero_fee": True}
        rows.append(rows[0] | {"symbol": "NEWUSDT", "base_asset": "NEW"})
        monkeypatch.setattr(module, "now_utc", lambda: START + timedelta(hours=6))
        asyncio.run(collector.refresh_catalog(None))
        assert DataPortal(db).metadata_at(symbol, START + timedelta(hours=7))["raw"]["is_zero_fee"] is True
        assert collector.catalog_received_at == START + timedelta(hours=6)
        assert collector.insts == observed_markets
        state["fail"] = True
        monkeypatch.setattr(module, "now_utc", lambda: START + timedelta(hours=12))
        asyncio.run(collector.refresh_catalog(None))
        assert collector.catalog_received_at == START + timedelta(hours=6)
        assert db.c.execute("SELECT count(*) FROM quality_events WHERE flag='SOURCE_ERROR' AND detail LIKE 'catalog refresh%'").fetchone()[0] == 1
    finally:
        seg.close()
        db.c.close()
