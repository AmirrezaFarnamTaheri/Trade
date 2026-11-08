"""Registered configurations, matched paper accounts and availability-safe context signals."""
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.adapters.store import MarketDB
from gym.domain.registry import catalog, create_strategy
from gym.domain.sim import CostModel
from gym.services import research
from gym.services.diagnostics import diagnostics
from gym.services.paper import paper
from tests.support import START, market_db, quote, quote_history


def test_registry_normalizes_defaults_and_rejects_bad_parameters():
    assert len(catalog()) == 16
    assert create_strategy().config_hash == create_strategy("ema-trend", {"slow": 21, "fast": 8}).config_hash
    assert create_strategy("ema-trend", {"fast": 2}).config_hash != create_strategy().config_hash
    for name, params in (("unknown", {}), ("ema-trend", {"fast": True}), ("ema-trend", {"slow": 1}),
                         ("ema-trend", {"fast": 21}), ("sma-reversion", {"lookback": 0}),
                         ("relative-momentum", {"reference": "../secret"}), ("ema-trend", {"extra": 1})):
        with pytest.raises(ValueError):
            create_strategy(name, params)


def test_compound_revision_changes_identity_without_changing_legacy_configs():
    from gym.domain.strategy import digest
    for name in ("ema-trend","trend-pullback","adaptive-channel"):
        strategy = create_strategy(name)
        version = 1 if name=="ema-trend" else 3
        assert next(row for row in catalog() if row["id"]==name)["version"]==version
        assert strategy.version==version
        assert strategy.config_hash==digest({"strategy":name,"version":version,"params":strategy.params})


def test_compare_reuses_data_costs_snapshots_and_independent_cash(tmp_path):
    db = market_db(tmp_path, quote_history())
    candidates = [{"strategy": "ema-trend", "params": {"fast": 2, "slow": 3}},
                  {"strategy": "sma-reversion", "params": {"lookback": 4, "entry_bps": 1}}]
    args = (db, "BTCUSDT", START, START + timedelta(hours=5), candidates)
    result = research.compare(*args, resolution="1min", cost=CostModel(Decimal("0.0015")))
    assert result == research.compare(*args, resolution="1min", cost=CostModel(Decimal("0.0015")))
    assert result["mode"] == "COMPARE"
    first, second = result["runs"]
    assert first["inputs"]["data"] == second["inputs"]["data"]
    assert first["inputs"]["snapshots"] == second["inputs"]["snapshots"]
    assert first["inputs"]["cost"] == second["inputs"]["cost"]
    assert first["result"]["start_cash"] == second["result"]["start_cash"] == "1000"
    assert first["inputs"]["config_hash"] != second["inputs"]["config_hash"]
    assert "0.1500%" in first["warnings"][-1]
    assert all(check["status"] == "PASS" for check in diagnostics(db, second)["checks"].values())
    assert {row["name"] for row in result["ranking"]["all"]} >= {"A: ema-trend", "B: sma-reversion", "hold USDT"}


def test_compound_comparison_shares_market_snapshots_but_records_account_context(tmp_path):
    db = market_db(tmp_path,quote_history(n=480))
    try:
        out = research.compare(db,"BTCUSDT",START,START+timedelta(minutes=79),
            [{"strategy":"ema-trend"},{"strategy":"trend-pullback"},{"strategy":"adaptive-channel"}],resolution="1min")
        assert len({run["inputs"]["snapshots"] for run in out["runs"]}) == 1
        assert "execution_known" not in out["runs"][0]["result"]["decisions"][0]
        assert all("execution_snapshot" in run["result"]["decisions"][0] for run in out["runs"][1:])
    finally:
        db.c.close()


def test_comparison_freezes_database_between_candidates(tmp_path, monkeypatch):
    db = market_db(tmp_path, quote_history())
    original = research.paper
    calls = []
    def concurrent_collection(*args, **kwargs):
        result = original(*args, **kwargs)
        if not calls:
            writer = MarketDB(tmp_path / "market.db")
            try:
                writer.add_book_top(quote(START + timedelta(minutes=15, seconds=1), "999999", "1000000"), None)
            finally:
                writer.c.close()
        calls.append(result)
        return result
    monkeypatch.setattr(research, "paper", concurrent_collection)
    result = research.compare(db, "BTCUSDT", START, START + timedelta(hours=5),
                              [{"strategy": "ema-trend"}, {"strategy": "ema-trend"}], resolution="1min")
    assert result["runs"][0] == result["runs"][1]
    assert not db.c.in_transaction


def test_higher_timeframe_uses_only_closed_bars_and_is_prefix_stable(tmp_path):
    db = market_db(tmp_path, quote_history())
    out = paper(db, "BTCUSDT", START, START + timedelta(hours=5), resolution="1min",
                strategy_id="ema-confirmed", params={"fast": 2, "slow": 3, "confirmation": "15min"})
    decisions = out["result"]["decisions"]
    assert all(d["action"] == "ABSTAIN_WARMUP" for d in decisions[:14])
    assert decisions[14]["feature_values"]["confirmation_close"] is not None
    assert all(check["status"] == "PASS" for check in diagnostics(db, out)["checks"].values())
    with pytest.raises(ValueError, match="longer"):
        paper(db, "BTCUSDT", START, START + timedelta(hours=5), resolution="1h", strategy_id="ema-confirmed")


def test_reference_asset_changes_real_decisions_and_future_quotes_are_excluded(tmp_path):
    from gym.domain.model import BookTop
    rows = quote_history(n=1200)
    reference = [BookTop("ETHUSDT", q.ts_avail, Decimal(99), Decimal(101), Decimal(1), Decimal(1), frozenset()) for q in rows]
    db = market_db(tmp_path, sorted(rows + reference, key=lambda q: q.ts_avail))
    kwargs = {"resolution": "1min", "strategy_id": "relative-momentum", "params": {"lookback": 2, "reference": "ETHUSDT"}}
    out = paper(db, "BTCUSDT", START, START + timedelta(hours=3), **kwargs)
    assert out["result"]["fills"] >= 2
    assert all(check["status"] == "PASS" for check in diagnostics(db, out)["checks"].values())
    db.c.execute("delete from book_top where instrument_id='wallex:ETHUSDT'")
    future = BookTop("ETHUSDT", START + timedelta(hours=4), Decimal(99), Decimal(101), Decimal(1), Decimal(1), frozenset())
    db.add_book_top(future, None)
    missing = paper(db, "BTCUSDT", START, START + timedelta(hours=3), **kwargs)
    assert missing["result"]["fills"] == 0
    assert all(d["action"] == "ABSTAIN_NO_REFERENCE" for d in missing["result"]["decisions"])
    with pytest.raises(ValueError, match="differ"):
        paper(db, "BTCUSDT", START, START + timedelta(hours=3), strategy_id="relative-momentum", params={"reference": "BTCUSDT"})
