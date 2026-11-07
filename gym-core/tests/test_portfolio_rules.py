"""The snapshot rule cache changes only at recorded knowledge boundaries."""
from datetime import timedelta

from gym.domain.model import iso
from gym.services.portfolio import portfolio
from gym.services.rules import RuleService
from tests.support import START, market_db, quote_history


def test_rule_loading_is_bounded_by_vintages_and_future_rules_do_not_leak(tmp_path, monkeypatch):
    rows = quote_history(n=300) + quote_history(n=300, sym="ETHUSDT")
    db = market_db(tmp_path, rows)
    calls, load = [], RuleService.load
    def counted(self, at=None):
        calls.append(at)
        return load(self, at)
    monkeypatch.setattr(RuleService, "load", counted)
    options = {"resolution": "1min", "params": {"fast": 2, "slow": 3}}
    try:
        before = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=49), **options)
        assert len(calls) <= 3
        calls.clear()
        cutoff = START + timedelta(minutes=10)
        RuleService(db).put({"id": "pause", "family": "PairSuspension", "class": "VENUE", "action": "BLOCK_ALL",
            "scope": {"symbols": ["BTCUSDT"]}, "effective_from": iso(START), "source": "operator",
            "status": "VERIFIED"}, cutoff)
        after = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=49), **options)
        assert len(calls) <= 4
        assert before["inputs"]["rules"] != after["inputs"]["rules"] and after["inputs"]["portfolio_version"] == 5
        prefix = lambda out: [p for p in out["result"]["curve"] if p[0] < iso(cutoff)]
        assert prefix(before) == prefix(after)
        assert any(o["status"] == "NONFILL" for o in after["result"]["markets"]["BTCUSDT"]["orders"])
    finally:
        db.c.close()


def test_backdated_later_event_keeps_the_native_ledger_prefix_boundary(tmp_path):
    db = market_db(tmp_path, quote_history(n=300) + quote_history(n=300, sym="ETHUSDT"))
    options = {"resolution": "1min", "params": {"fast": 2, "slow": 8}}
    try:
        before = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=49), **options)
        rule = {"id": "future", "family": "PairSuspension", "class": "VENUE", "action": "BLOCK_ALL",
                "scope": {"symbols": ["OTHERUSDT"]}, "effective_from": iso(START), "source": "operator", "status": "VERIFIED"}
        RuleService(db).put(rule, START + timedelta(minutes=10))
        RuleService(db).put({**rule, "id": "backdated", "scope": {"symbols": ["BTCUSDT"]}}, START + timedelta(minutes=5))
        after = portfolio(db, ["BTCUSDT", "ETHUSDT"], START, START + timedelta(minutes=49), **options)
        cutoff = iso(START + timedelta(minutes=10))
        prefix = lambda out: [p for p in out["result"]["curve"] if p[0] < cutoff]
        assert prefix(before) == prefix(after)
        orders = after["result"]["markets"]["BTCUSDT"]["orders"]
        assert any(o["side"] == "BUY" and o["status"] == "FILLED" and o["fill_time"] < cutoff for o in orders)
        assert any(o["status"] == "NONFILL" for o in orders)
    finally:
        db.c.close()
