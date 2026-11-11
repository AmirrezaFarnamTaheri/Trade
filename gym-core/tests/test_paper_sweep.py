"""The bulk sweep must give exactly what `paper()` gives, run by run, while sharing quotes, rules and baselines."""
import sqlite3
from datetime import timedelta
from decimal import Decimal

from gym.adapters.store import MarketDB
from gym.domain.performance import performance, sampled_drawdown
from gym.domain.sim import CostModel
from gym.services.data_portal import DataPortal
from gym.services.paper import paper
from gym.services.paper_sweep import CachedPortal, FrozenRules, sweep, sweep_market
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history

END = START + timedelta(hours=5)


def _db(tmp_path):
    db = market_db(tmp_path, quote_history(n=1800) + quote_history(n=1800, sym="ETHUSDT"))
    RuleService(db).preset("usdt-irt-october-2026", START + timedelta(hours=2))  # a mid-window rule vintage
    db.c.close()
    return tmp_path / "market.db"


def test_cached_quotes_and_frozen_rules_equal_the_database(tmp_path):
    db = MarketDB(_db(tmp_path), readonly=True)
    portal, plain, rules, svc = CachedPortal(db, START - timedelta(days=1), END), DataPortal(db), FrozenRules(db), RuleService(db)
    for a, b in [(START, END), (START + timedelta(minutes=7), START + timedelta(hours=1, seconds=3)), (START, START + timedelta(seconds=1))]:
        assert portal.tops("BTCUSDT", a, b) == plain.tops("BTCUSDT", a, b)
    for minutes in range(-60, 400, 7):
        at = START + timedelta(minutes=minutes)
        assert rules.version(at) == db.rules_version_as_of(at)
        assert rules(at) == svc.load(at)[1]


def test_sweep_rows_match_full_paper_runs(tmp_path):
    path = _db(tmp_path)
    rows = sweep_market(str(path), "ETHUSDT", START, END, ("1min", "15min"), ("ema-trend", "macd-cross", "rsi-rebound"),
                        Decimal(1000), Decimal(300_000_000), Decimal("0.001"))
    db = MarketDB(path, readonly=True)
    for row in rows:
        out = paper(db, "ETHUSDT", START, END, resolution=row["resolution"], strategy_id=row["strategy"],
                    cost=CostModel(Decimal("0.001")))
        perf = performance(out, sampled_drawdown(out))
        assert row["status"] == "OK"
        assert (row["net"], row["fills"], row["data_digest"]) == (out["result"]["end"]["net"], out["result"]["fills"],
                                                                 out["result"]["data_digest"])
        assert row["hold_net"] == out["baselines"]["hold ETH"]["end"]["net"]
        assert row["closed_trades"] == perf["trades"]["closed_trades"]


def test_sweep_resumes_records_trials_and_refuses_changed_settings(tmp_path):
    path = _db(tmp_path)
    out = tmp_path / "sweeps" / "s.sqlite3"
    first = sweep(tmp_path, out, START, END, resolutions=("15min",), strategies=("ema-trend", "lead-lag"), workers=2,
                  progress=lambda _: None)
    assert first["runs"] == 4 and first["markets"] == 2
    conn = sqlite3.connect(out)
    statuses = dict(conn.execute("SELECT strategy, count(*) FROM runs GROUP BY strategy, status").fetchall())
    assert statuses["ema-trend"] == 2
    conn.close()
    again = []
    sweep(tmp_path, out, START, END, resolutions=("15min",), strategies=("ema-trend", "lead-lag"), workers=2,
          progress=again.append)
    assert "0 to run" in again[0]
    ledger = sqlite3.connect(tmp_path / "trial_ledger.sqlite3")
    assert ledger.execute("SELECT count(*) FROM trial_attempts WHERE source='experiment'").fetchone()[0] >= 2
    try:
        sweep(tmp_path, out, START, END, resolutions=("1h",), strategies=("ema-trend",), workers=1, progress=lambda _: None)
        raise AssertionError("changed settings must be refused")
    except ValueError as error:
        assert "different settings" in str(error)
    assert path.exists()
