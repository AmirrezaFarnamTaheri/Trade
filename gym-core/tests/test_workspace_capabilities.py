import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gym.adapters.store import MarketDB, SegmentWriter
from gym.api.server import make_app
from gym.domain.bars import FIXED_RESOLUTIONS, BarSpec, Consolidator
from gym.domain.model import iso
from gym.domain.registry import create_strategy
from gym.services.capabilities import workspace_capabilities
from gym.services.collector import Collector, parse_asset_count, select_universe
from gym.services.paper import paper
from gym.services.rules import RuleService
from gym.services.technical_analysis import technical_report

from .support import START, market_db, quote_history


def markets():
    return [
        {"symbol": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT", "is_spot": True},
        {"symbol": "RISKUSDT", "base_asset": "RISK", "quote_asset": "USDT", "is_spot": True, "flags": ["isRisky"]},
        {"symbol": "OFFUSDT", "base_asset": "OFF", "quote_asset": "USDT", "is_spot": False},
        {"symbol": "BTCEUR", "base_asset": "BTC", "quote_asset": "EUR", "is_spot": True},
    ]


def test_all_observes_flagged_spot_but_never_nonspot_and_keeps_ranked_policy():
    all_symbols, info = select_universe(markets(), None)
    assert set(all_symbols) == {"BTCUSDT", "RISKUSDT"}
    assert info["mode"] == "all-spot" and info["requested_assets"] is None
    assert info["available_safe_assets"] == 1
    assert select_universe(markets(), 1)[0] == ["BTCUSDT"]
    for value in (0, 501, True, "all"):
        with pytest.raises(ValueError):
            select_universe(markets(), value)
    too_many = [{"symbol": f"A{i}USDT", "base_asset": f"A{i}", "quote_asset": "USDT", "is_spot": True} for i in range(501)]
    with pytest.raises(ValueError, match="capacity"):
        select_universe(too_many, None)
    assert parse_asset_count("all") is None and parse_asset_count("1") == 1 and parse_asset_count("500") == 500
    for value in ("0", "501", "-1", "abc"):
        with pytest.raises(ValueError):
            parse_asset_count(value)


@pytest.mark.parametrize("resolution", ["3min", "5min", "30min", "2h", "4h", "6h", "12h"])
def test_new_timeframes_use_exact_shared_boundaries_and_strategy_schema(resolution):
    spec = BarSpec(resolution)
    at = START + timedelta(minutes=37, seconds=11)
    begin = spec.bucket(at)
    assert begin <= at < begin + spec.step
    assert spec.bucket(begin + spec.step) == begin + spec.step
    assert resolution in FIXED_RESOLUTIONS
    strategy = create_strategy("ema-confirmed", {"confirmation": resolution})
    assert strategy.required_resolutions == (resolution,)
    consolidator = Consolidator("BTCUSDT", spec, publication_lag=timedelta(seconds=2))
    assert consolidator.update(begin + timedelta(seconds=1), Decimal(100)) == []
    assert consolidator.scan(begin + spec.step) == []
    bars = consolidator.scan(begin + spec.step + timedelta(seconds=2))
    assert len(bars) == 1 and bars[0].close == 100 and not bars[0].forming


@pytest.mark.parametrize("resolution", ["5min", "4h", "12h"])
def test_new_timeframes_flow_through_paper_and_closed_bar_diagnostics(tmp_path, resolution):
    spec = BarSpec(resolution)
    start = spec.bucket(START)
    rows = quote_history(n=120, step=int(spec.step.total_seconds() // 20))
    # Move the same received-price path to an exact boundary for each timeframe.
    rows = [replace(row, ts_avail=start + (row.ts_avail - START)) for row in rows]
    end = start + spec.step * 6
    db = market_db(tmp_path, rows)
    try:
        result = paper(db, "BTCUSDT", start, end, resolution=resolution, fast=2, slow=3)
        assert result["inputs"]["resolution"] == resolution
        diagnostic = technical_report(db, "BTCUSDT", start, end, resolution=resolution)
        assert diagnostic["closed_bars"] == 6 and diagnostic["funded_authority"] is False
        assert diagnostic["last_closed_bar"]["to"] == iso(end)
    finally:
        db.c.close()


def test_catalog_capability_api_and_page_share_runtime_configuration(monkeypatch, tmp_path):
    async def run():
        db = MarketDB(tmp_path / "market.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), None)
        async def catalog(_session, _path, **_params):
            return json.dumps({"result": {"markets": markets()}})
        monkeypatch.setattr(col, "rest_text", catalog)
        await col.load_catalog(None)
        caps = workspace_capabilities(col)
        assert caps["collection"]["mode"] == "all-spot"
        assert caps["sides"]["SELL"] == "OWNED_ASSET_ONLY"
        assert caps["sides"]["SHORT"] == "PAPER_MARGIN"
        assert caps["funded_authority"] is False
        async with TestClient(TestServer(make_app(col, RuleService(db), "secret"))) as client:
            payload = await (await client.get("/api/markets")).json()
            assert len(payload["catalog"]) == 4 and len(payload["markets"]) == 2
            listed = {row["symbol"]: row for row in payload["catalog"]}
            assert listed["OFFUSDT"]["reason"] == "NOT_SPOT"
            assert listed["BTCEUR"]["reason"] == "UNSUPPORTED_QUOTE"
            assert listed["RISKUSDT"]["risk_flagged"] is True
            assert await (await client.get("/api/capabilities")).json() == caps
            setup = await (await client.get("/api/research")).json()
            assert setup["resolutions"] == list(FIXED_RESOLUTIONS)
            text = await (await client.get("/")).text()
            config = json.loads(text.split('id="gym-config" type="application/json">')[1].split('</script>')[0])
            assert config["resolutions"] == list(FIXED_RESOLUTIONS)
        db.c.close()
    asyncio.run(run())


def test_catalog_failure_keeps_server_available_then_recovers(monkeypatch, tmp_path):
    async def run():
        db = MarketDB(tmp_path / "market.db")
        seg = SegmentWriter(tmp_path / "raw", db)
        col = Collector(db, seg, None)
        failed, release, streaming = asyncio.Event(), asyncio.Event(), asyncio.Event()
        attempts = 0

        async def catalog(_session):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                failed.set()
                await release.wait()
            else:
                col.configure(["BTCUSDT"])

        async def stream(*_args):
            streaming.set()
            await asyncio.Event().wait()

        async def idle(*_args):
            await asyncio.Event().wait()

        monkeypatch.setattr(col, "load_catalog", catalog)
        monkeypatch.setattr(col, "_ws_loop", stream)
        monkeypatch.setattr(col, "_housekeeping", idle)
        monkeypatch.setattr(col, "_refresh_rest", idle)
        task = asyncio.create_task(col.run())
        try:
            await asyncio.wait_for(failed.wait(), 1)
            async with TestClient(TestServer(make_app(col, RuleService(db), "secret"))) as client:
                payload = await (await client.get("/api/markets")).json()
                assert payload["markets"] == [] and payload["capabilities"]["catalog_received_at"] is None
                release.set()
                await asyncio.wait_for(streaming.wait(), 4)
                assert not task.done() and attempts == 2
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            seg.close()
            db.c.close()
    asyncio.run(run())
