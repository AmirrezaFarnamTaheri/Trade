"""Causality checks must detect a deliberately future-dependent decision path."""
from datetime import timedelta

import pytest

from gym.domain.model import iso
from gym.services.research_actions import research_action
from gym.services.strategy_audit import audit_strategy
from tests.support import START, market_db, quote_history


def request():
    return {"symbol": "BTCUSDT", "strategy": "ema-trend", "params": {"fast": 2, "slow": 3},
            "from": iso(START), "to": iso(START + timedelta(minutes=39)), "resolution": "1min",
            "cash": "1000", "fee_rate": "0.001", "latency_ms": 500,
            "checkpoints": [iso(START + timedelta(minutes=20)), iso(START + timedelta(minutes=30))],
            "history_starts": [iso(START + timedelta(minutes=5))]}


def test_native_prefixes_and_read_snapshot_do_not_change_market_store(tmp_path):
    db = market_db(tmp_path, quote_history(n=240))
    try:
        count = db.c.execute("select count(*) from book_top").fetchone()[0]
        result = audit_strategy(db, request(), store="live")
        assert all(row["status"] == "MATCH" and row["compared_decisions"] > 0 for row in result["prefix_checks"])
        assert result["status"] == "CHECKED_PREFIXES_MATCH"
        assert not result["funded_authority"] and not result["proves_absence_of_bias"]
        assert result["history_checks"][0]["at"] == result["last_decision_at"]
        assert not db.c.in_transaction
        assert db.c.execute("select count(*) from book_top").fetchone()[0] == count
        assert research_action(tmp_path, "strategy-audit", request(), store="live")["report_id"] == result["report_id"]
    finally:
        db.c.close()


def test_future_reads_cannot_hide_behind_a_prefix_comparison(tmp_path, monkeypatch):
    from gym.services import strategy_audit as module
    original = module.run

    def future_dependent(portal, rules, strategy, symbol, start, end, *args):
        result = original(portal, rules, strategy, symbol, start, end, *args)
        future = portal.tops(symbol, START + timedelta(minutes=35), START + timedelta(minutes=38))
        for decision in result["decisions"]:
            decision["features"] = "future-present" if future else "future-absent"
        return result

    monkeypatch.setattr(module, "run", future_dependent)
    db = market_db(tmp_path, quote_history(n=240))
    try:
        result = audit_strategy(db, request(), store="demo")
        assert result["status"] == "PREFIX_DIFFERENCE"
        assert all(row["status"] == "DIFFERENT" for row in result["prefix_checks"])
        assert all(row["differences"] for row in result["prefix_checks"])
    finally:
        db.c.close()


@pytest.mark.parametrize("change", [
    {"checkpoints": []}, {"checkpoints": [iso(START)]}, {"latency_ms": True},
    {"history_starts": [iso(START - timedelta(minutes=1))]}, {"fee_rate": "1"},
    {"cash": "NaN"}, {"symbol": "../../secret"}, {"resolution": "session"},
    {"to": iso(START + timedelta(days=32))},
])
def test_rejects_invalid_or_unbounded_work_before_replay(tmp_path, change):
    db = market_db(tmp_path, quote_history(n=10))
    try:
        with pytest.raises(ValueError):
            audit_strategy(db, {**request(), **change}, store="live")
        assert not db.c.in_transaction
    finally:
        db.c.close()


def test_no_decisions_are_unverified_not_a_pass(tmp_path):
    db = market_db(tmp_path, quote_history(n=0))
    try:
        result = audit_strategy(db, request(), store="live")
        assert result["status"] == "NO_COMPARABLE_DECISIONS"
        assert all(row["status"] == "NO_COMPARABLE_DECISIONS" for row in result["prefix_checks"])
    finally:
        db.c.close()


def test_missing_feature_trace_cannot_certify_history_convergence(tmp_path, monkeypatch):
    from gym.services import strategy_audit as module
    original = module.run
    def untraced(*args):
        result = original(*args)
        for row in result["decisions"]:
            row.pop("feature_values", None)
        return result
    monkeypatch.setattr(module, "run", untraced)
    db = market_db(tmp_path, quote_history(n=240))
    try:
        assert audit_strategy(db, request(), store="live")["history_checks"][0]["status"] == "NOT_COMPARABLE"
    finally:
        db.c.close()
