"""Historical public Wallex metadata remains point-in-time and lossless (DATA-02)."""
import asyncio
import hashlib
import json
from datetime import timedelta

from gym.adapters.store import MarketDB
from gym.domain.model import iso
from gym.services import collector as collector_module
from gym.services.collector import Collector
from gym.services.data_portal import DataPortal

from .support import START


class _Segments:
    def write(self, *_args):
        return "segment"


def test_historical_public_metadata(monkeypatch, tmp_path):
    first = {
        "symbol": "BTCUSDT",
        "baseAsset": "BTC",
        "quoteAsset": "USDT",
        "enName": "Bitcoin",
        "faName": "بیت کوین",
        "stepSize": "6",
        "publicExtra": {"tier": "legacy"},
    }
    second = {
        "symbol": "BTCUSDT",
        "baseAsset": "BTC",
        "quoteAsset": "USDT",
        "enName": "Bitcoin",
        "faName": "بیت کوین",
        "stepSize": "5",
        "minNotional": "10",
    }
    snapshots = iter((first, second))

    async def get_text(_session, path):
        assert path == "/hector/web/v1/markets"
        return json.dumps({"result": {"markets": [next(snapshots)]}})

    later = START + timedelta(days=1)
    times = iter((START, later))
    monkeypatch.setattr(collector_module.wallex, "get_text", get_text)
    monkeypatch.setattr(collector_module, "now_utc", lambda: next(times))

    db = MarketDB(tmp_path / "market.db")
    collector = Collector(db, _Segments(), ["BTCUSDT"])
    asyncio.run(collector.load_catalog(None))
    portal = DataPortal(db)

    assert portal.metadata_at("BTCUSDT", START - timedelta(microseconds=1)) is None
    original = portal.metadata_at("BTCUSDT", START)
    assert original["raw"] == first
    assert "minNotional" not in original["raw"]

    asyncio.run(collector.load_catalog(None))
    assert portal.metadata_at("BTCUSDT", START) == {
        **original,
        "valid_to": later,
    }
    current = portal.metadata_at("BTCUSDT", later)
    assert current["raw"] == second
    assert "publicExtra" not in current["raw"]

    stored = db.c.execute(
        "select rowid, valid_from, valid_to, spec, source from instrument_specs where rowid=?",
        (original["version"],),
    ).fetchone()
    assert original["valid_from"] == START and stored[2] == iso(later)
    assert original["source"] == stored[4] == "rest:/hector/web/v1/markets"
    assert original["version"] == stored[0]
    assert original["raw_digest"] == hashlib.sha256(stored[3].encode()).hexdigest()


def test_custom_symbol_overlays_follow_catalog(monkeypatch, tmp_path):
    rows = [
        {"symbol": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT"},
        {"symbol": "ETHUSDT", "base_asset": "ETH", "quote_asset": "USDT", "flags": ["isRisky"]},
    ]

    async def rest_text(_session, _path, **_params):
        return json.dumps({"result": {"markets": rows}})

    db = MarketDB(tmp_path / "custom.db")
    collector = Collector(db, _Segments(), ["BTCUSDT"],
                          add_symbols=("ethusdt", "missingusdt"), remove_symbols=("btcusdt", "ghostusdt"))
    monkeypatch.setattr(collector, "rest_text", rest_text)
    asyncio.run(collector.load_catalog(None))

    assert list(collector.insts) == ["ETHUSDT"]
    assert collector.universe["observed_assets"] == ["ETH"]
    assert collector.universe["added_markets"] == ["ETHUSDT"]
    assert collector.universe["removed_markets"] == ["BTCUSDT"]
    assert collector.universe["remove_requests"] == ["BTCUSDT", "GHOSTUSDT"]
    assert collector.universe["custom_note"] == "custom additions are observed only and bypass ranking filters"
    assert set(db.c.execute("select instrument_id from quality_events where flag='SOURCE_ERROR'").fetchall()) == {
        ("wallex:MISSINGUSDT",), ("wallex:GHOSTUSDT",),
    }


def test_ranked_universe_is_balanced_and_shard_safe():
    markets = [{
        "symbol": "USDTTMN", "base_asset": "USDT", "quote_asset": "TMN", "is_spot": True,
        "price": "250000", "quote_volume_24h": "1000000000", "flags": [],
    }]
    for n in range(60):
        for quote in ("TMN", "USDT"):
            markets.append({
                "symbol": f"A{n}{quote}", "base_asset": f"A{n}", "quote_asset": quote, "is_spot": True,
                "quote_volume_24h": str((60 - n) * (250000 if quote == "TMN" else 1)), "flags": [],
            })
    markets += [
        {"symbol": "RISKUSDT", "base_asset": "RISK", "quote_asset": "USDT", "is_spot": True,
         "quote_volume_24h": "999999999", "flags": ["isRisky"]},
        {"symbol": "OFFUSDT", "base_asset": "OFF", "quote_asset": "USDT", "is_spot": False,
         "quote_volume_24h": "999999999", "flags": []},
    ]

    symbols, info = collector_module.select_universe(markets, 50)

    assert len(info["selected_assets"]) == 50
    assert info["selected_assets"][0] == "USDT"
    assert "RISKUSDT" not in symbols and "OFFUSDT" not in symbols
    assert len(symbols) == 99 and info["websocket_shards"] == 5


def test_ranking_does_not_compare_raw_tmn_volume_without_fx():
    markets = [{
        "symbol": f"A{n}USDT", "base_asset": f"A{n}", "quote_asset": "USDT", "is_spot": True,
        "quote_volume_24h": str(100 - n), "flags": [],
    } for n in range(25)]
    markets.append({
        "symbol": "WHALETMN", "base_asset": "WHALE", "quote_asset": "TMN", "is_spot": True,
        "quote_volume_24h": "999999999999", "flags": [],
    })

    symbols, _ = collector_module.select_universe(markets, 25)

    assert "WHALETMN" not in symbols
    assert (2 * collector_module.MAX_ASSETS + collector_module.CANDLE_BATCH - 1) // collector_module.CANDLE_BATCH <= 120


def test_asset_count_boundaries_and_429_backoff(monkeypatch, tmp_path):
    import aiohttp
    import pytest

    with pytest.raises(ValueError, match="25..500"):
        collector_module.select_universe([], 24)
    with pytest.raises(ValueError, match="25..500"):
        collector_module.select_universe([], 501)
    assert collector_module.select_universe([], 500)[0] == []

    class Gate:
        interval = 0.25
        async def wait(self):
            pass
        async def penalize(self):
            self.interval *= 2

    calls = 0
    async def get_text(_session, _path, **_params):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise aiohttp.ClientResponseError(None, (), status=429, headers={"Retry-After": "0"})
        return "ok"

    async def no_sleep(_delay):
        pass

    db = MarketDB(tmp_path / "rate.db")
    collector = Collector(db, _Segments(), ["BTCUSDT"])
    collector.rest_rate = Gate()
    monkeypatch.setattr(collector_module.wallex, "get_text", get_text)
    monkeypatch.setattr(collector_module.asyncio, "sleep", no_sleep)

    assert asyncio.run(collector.rest_text(None, "/v1/depth", symbol="BTCUSDT")) == "ok"
    assert calls == 2 and collector.rest_rate.interval == 0.5
    assert db.c.execute("select flag from quality_events").fetchall() == [("RATE_LIMIT",)]
