"""Deterministic replays and paper-session lifecycle boundaries."""
import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest
from gym.adapters.run_store import run_path
from gym.domain.model import iso
from gym.domain.sim import CostModel
from gym.domain.strategy import EmaTrend
from gym.services.data_portal import DataPortal
from gym.services.paper import paper
from gym.services.session import PaperSession
from tests.support import START, market_db, quote, quote_history


def make_session(db, cost=CostModel()):
    return PaperSession(DataPortal(db), lambda t: [], EmaTrend(1, 2), "BTCUSDT", START, "1min", Decimal(1000), cost)

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


def test_live_duration_stops_intents_at_deadline(tmp_path, monkeypatch):
    from gym.services import live_paper
    db = market_db(tmp_path, quote_history(n=30))
    times = iter([START, START + timedelta(seconds=130), START + timedelta(seconds=190), START + timedelta(seconds=191)])
    monkeypatch.setattr(live_paper, "now_utc", lambda: next(times))
    async def no_wait(_):
        return None
    monkeypatch.setattr(live_paper.asyncio, "sleep", no_wait)
    out = asyncio.run(live_paper.watch(db, tmp_path / "runs", "BTCUSDT", 5, "1min", 1, 2, Decimal(1000)))
    r = out["result"]
    assert r["session"]["state"] == "ENDED"
    assert max(d["t"] for d in r["decisions"]) <= iso(START + timedelta(seconds=125))
    assert any(e["state"] == "FINISHING" and e["t"] == iso(START + timedelta(seconds=125)) for e in r["session"]["events"])
