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
        assert path == "/v1/markets"
        return json.dumps({"result": {"symbols": {"BTCUSDT": next(snapshots)}}})

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
    assert original["source"] == stored[4] == "rest:/v1/markets"
    assert original["version"] == stored[0]
    assert original["raw_digest"] == hashlib.sha256(stored[3].encode()).hexdigest()
