"""Deterministic replays and paper-session lifecycle boundaries."""
import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from gym.adapters.run_store import run_path
from gym.domain.model import iso
from gym.domain.registry import create_strategy
from gym.domain.sim import CostModel
from gym.domain.strategy import EmaTrend
from gym.services.data_portal import DataPortal
from gym.services.paper import paper
from gym.services.session import PaperSession

from tests.support import START, market_db, quote, quote_history


def make_session(db, cost=None):
    return PaperSession(DataPortal(db), lambda t: [], EmaTrend(1, 2), "BTCUSDT", START, "1min", Decimal(1000), cost or CostModel())

def test_replay_is_deterministic_and_waterfall_reconciles(tmp_path):
    db = market_db(tmp_path, quote_history())
    a = paper(db, "BTCUSDT", START, START + timedelta(hours=6), resolution="1min", fast=3, slow=8)
    b = paper(db, "BTCUSDT", START, START + timedelta(hours=6), resolution="1min", fast=3, slow=8)
    assert a == b and a["result"]["fills"] >= 2
    w = {k: Decimal(v) for k, v in a["result"]["end"]["waterfall"].items()}
    assert w["directional"] + w["spread"] + w["fees"] + w["latency_drift"] == w["net"]
    assert w["fees"] < 0 and w["spread"] < 0
    first = a["result"]["decisions"][0]
    assert first["action"] == "ABSTAIN_WARMUP"  # warmup never fabricates a signal
    assert set(a["baselines"]) == {"hold USDT", "hold BTC"} and a["baselines"]["hold BTC"]["fills"] == 1
    assert [row["name"] for row in a["ranking"]["abstainers"]] == ["hold USDT"]
    active = a["ranking"]["active"]
    assert all(row["classification"] == "ACTIVE" and row["net_usdt_eq"] is not None for row in active)
    assert [Decimal(row["net_usdt_eq"]) for row in active] == sorted(
        (Decimal(row["net_usdt_eq"]) for row in active), reverse=True
    )
    c = paper(db, "BTCUSDT", START, START + timedelta(hours=6), resolution="1min", fast=3, slow=8, cost=CostModel(fee_rate=Decimal("0.004")))
    assert c["run_id"] != a["run_id"] and Decimal(c["result"]["end"]["net"]) < Decimal(a["result"]["end"]["net"])


def test_lifecycle_pending_and_abort(tmp_path):
    s = make_session(market_db(tmp_path, []))
    for sec, price in ((0, "100"), (60, "101"), (120, "102")):
        s.feed(quote(START + timedelta(seconds=sec), price, str(Decimal(price) + 1)))
    assert s.pending and s.book.get("BTC") == 0
    assert s.running_at == START + timedelta(minutes=2)
    s.feed(quote(START + timedelta(seconds=121), "102", "103"))
    assert not s.pending and s.book.get("BTC") > 0
    held = s.book.get("BTC")
    s.finish(START + timedelta(seconds=122), "operator stopped")
    assert s.state == "ABORTED" and s.book.get("BTC") == held  # no automatic liquidation
    assert s.events[-1]["reason"] == "operator stopped"
    with pytest.raises(ValueError):
        s.feed(quote(START + timedelta(seconds=123), "102", "103"))


def test_finish_pending_and_gaps(tmp_path):
    s = make_session(market_db(tmp_path, []))
    for sec in (0, 60, 120):
        s.feed(quote(START + timedelta(seconds=sec), str(100 + sec), str(101 + sec)))
    assert s.pending
    s.finish(START + timedelta(seconds=120))
    assert s.state == "ENDED" and not s.pending
    assert s.orders[-1]["reason"] == "SESSION_ENDED_BEFORE_SETTLEMENT"
    g = make_session(s.portal.db)
    g.feed(quote(START, "100", "101"))
    g.feed(quote(START + timedelta(hours=1), "102", "103"))
    assert g.skipped and len(g.decisions) == 1


def test_finishing_settles_without_new_intents(tmp_path):
    s = make_session(market_db(tmp_path, []))
    for sec in (0, 60, 120):
        s.feed(quote(START + timedelta(seconds=sec), str(100 + sec), str(101 + sec)))
    s.transition("FINISHING", START + timedelta(seconds=120))
    n = len(s.decisions)
    s.feed(quote(START + timedelta(seconds=121), "220", "221"))
    s.finish(START + timedelta(seconds=122))
    assert s.orders[0]["status"] == "FILLED" and len(s.decisions) == n
    assert s.state == "ENDED"


def test_live_watch_abort_preserves_record(tmp_path, monkeypatch):
    from gym.services import live_paper
    db = market_db(tmp_path, quote_history(n=30))
    times = iter([START, START + timedelta(seconds=130), START + timedelta(seconds=131)])
    monkeypatch.setattr(live_paper, "now_utc", lambda: next(times))
    async def interrupt(_):
        raise asyncio.CancelledError()
    monkeypatch.setattr(live_paper.asyncio, "sleep", interrupt)
    out = asyncio.run(live_paper.watch(db, tmp_path / "runs", "BTCUSDT", 1000, "1min", 1, 2, Decimal(1000)))
    assert out["result"]["session"]["state"] == "ABORTED"
    assert run_path(tmp_path / "runs", out["run_id"]).exists()


@pytest.mark.parametrize("phase", ["shutdown", "poll", "recovered"])
def test_live_clock_regression_retains_an_explicit_aborted_receipt(tmp_path, monkeypatch, phase):
    from gym.services import live_paper

    db = market_db(tmp_path, quote_history(n=30))
    finish_second = {"shutdown": 110, "poll": 111, "recovered": 140}[phase]
    times = iter([START, START + timedelta(seconds=130), START + timedelta(seconds=110)]
                 + ([] if phase == "shutdown" else [START + timedelta(seconds=finish_second)]))
    monkeypatch.setattr(live_paper, "now_utc", lambda: next(times))

    async def interrupt(_):
        if phase == "shutdown":
            raise asyncio.CancelledError()

    monkeypatch.setattr(live_paper.asyncio, "sleep", interrupt)
    try:
        out = asyncio.run(live_paper.watch(db, tmp_path / "runs", "BTCUSDT", 1000, "1min", 1, 2, Decimal(1000)))
        assert out["result"]["session"]["state"] == "ABORTED"
        assert out["inputs"]["clock_regression"] == {
            "observed_finish_at": iso(START + timedelta(seconds=finish_second)),
            "last_processed_at": iso(START + timedelta(seconds=130)),
            "first_regressed_at": iso(START + timedelta(seconds=110)),
        }
        assert out["inputs"]["to"] == iso(START + timedelta(seconds=max(130, finish_second)))
        assert "Clock regression" in out["result"]["session"]["events"][-1]["reason"]
        assert run_path(tmp_path / "runs", out["run_id"]).exists()
    finally:
        db.c.close()


@pytest.mark.parametrize("repeat_start", [False, True])
def test_live_duration_stops_intents_at_deadline(tmp_path, monkeypatch, repeat_start):
    from gym.services import live_paper
    db = market_db(tmp_path, quote_history(n=30))
    times = iter([START] + ([START] if repeat_start else [])
                 + [START + timedelta(seconds=130), START + timedelta(seconds=190), START + timedelta(seconds=191)])
    monkeypatch.setattr(live_paper, "now_utc", lambda: next(times))
    async def no_wait(_):
        return None
    monkeypatch.setattr(live_paper.asyncio, "sleep", no_wait)
    out = asyncio.run(live_paper.watch(db, tmp_path / "runs", "BTCUSDT", 5, "1min", 1, 2, Decimal(1000)))
    r = out["result"]
    assert r["session"]["state"] == "ENDED"
    assert max(d["t"] for d in r["decisions"]) <= iso(START + timedelta(seconds=125))
    assert any(e["state"] == "FINISHING" and e["t"] == iso(START + timedelta(seconds=125)) for e in r["session"]["events"])
    from gym.adapters.run_store import load_verified_run
    from gym.services.replay_debugger import replay_decisions
    from gym.services.research_grounding import MetricUnavailable, resolve_run_metric
    import json
    assert load_verified_run(tmp_path / "runs", out["run_id"], store="live")["outputs_digest"] == out["outputs_digest"]
    assert replay_decisions(tmp_path / "runs", {"run_id": out["run_id"], "offset": 0, "limit": 10}, store="live")["decisions"]
    with pytest.raises(MetricUnavailable):
        resolve_run_metric(tmp_path / "runs", {"run_id": out["run_id"], "metric": "hold_cash_net_quote"}, store="live")
    path = run_path(tmp_path / "runs", out["run_id"])
    saved = json.loads(path.read_text())
    for change in ("result", "baselines", "fx", "ranking"):
        changed = json.loads(json.dumps(saved))
        if change == "result":
            changed["result"]["fills"] += 1
        else:
            changed[change] = {"invented": True}
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            load_verified_run(tmp_path / "runs", out["run_id"], store="live")
    path.write_text(json.dumps(saved))


@pytest.mark.parametrize("name,params", [
    ("ema-trend", {"fast": 1, "slow": 2}),
    ("sma-reversion", {"lookback": 2, "entry_bps": 1}),
    ("sma-cross", {"fast": 2, "slow": 3}),
    ("bollinger-reversion", {"lookback": 6, "deviations": 1}),
    ("ema-confirmed", {"fast": 1, "slow": 2, "confirmation": "15min"}),
    ("relative-momentum", {"lookback": 2, "reference": "ETHUSDT"}),
])
def test_live_watch_uses_registered_strategy_and_context(tmp_path, monkeypatch, name, params):
    from gym.services import live_paper

    db = market_db(tmp_path, quote_history(n=200) + quote_history(n=200, sym="ETHUSDT"))
    times = iter([START, START + timedelta(minutes=30), START + timedelta(minutes=30, seconds=1)])
    monkeypatch.setattr(live_paper, "now_utc", lambda: next(times))

    async def interrupt(_):
        raise asyncio.CancelledError()

    monkeypatch.setattr(live_paper.asyncio, "sleep", interrupt)
    try:
        out = asyncio.run(live_paper.watch(db, tmp_path / "runs", "BTCUSDT", 10000, "1min", 1, 2,
                                         Decimal(1000), strategy_id=name, params=params))
        strategy = create_strategy(name, params)
        assert out["inputs"]["strategy"] == out["result"]["strategy"] == name
        assert out["inputs"]["params"] == strategy.params
        assert out["inputs"]["config_hash"] == strategy.config_hash
        assert out["inputs"]["reference_symbol"] == getattr(strategy, "reference_symbol", None)
        assert set(getattr(strategy, "required_resolutions", ())) <= set(out["inputs"]["subscriptions"])
        assert any(d["action"] != "ABSTAIN_WARMUP" for d in out["result"]["decisions"])
        assert out["result"]["session"]["state"] == "ABORTED"
    finally:
        db.c.close()
