"""Rule scopes, precedence, quarantining and historical versions."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from gym.adapters.store import MarketDB
from gym.domain.model import TEHRAN, UTC, BookTop, InstrumentId
from gym.domain.rules import PRESETS, evaluate, next_change, parse_rule
from gym.services.rules import RuleService
from gym.services.paper import paper
from tests.support import START, market_db, quote_history


USDT, BTCT, BTCU = (InstrumentId.wallex(s) for s in ("USDTTMN", "BTCTMN", "BTCUSDT"))


def tehran_time(s):
    return datetime.fromisoformat(s).replace(tzinfo=TEHRAN).astimezone(UTC)


def restriction(**kw):
    base = {"id": "r", "family": "PairSuspension", "class": "VENUE", "action": "BLOCK_ALL", "scope": {"symbols": ["BTCTMN"]},
            "effective_from": "2026-01-01T00:00:00Z", "source": "operator", "status": "VERIFIED"}
    return parse_rule({**base, **kw})




def test_usdt_closure_is_pair_scoped():
    rules = [parse_rule(d) for d in PRESETS["usdt-irt-october-2026"]]
    night = tehran_time("2026-10-31T00:30")
    for intent, side in (("ENTRY", "BUY"), ("EXIT", "SELL")):
        v = evaluate(rules, USDT, side, intent, night)
        assert not v.allowed and v.blockers[0]["rule_id"] == "wallex-usdttmn-closure-2330-1130"
        assert v.blockers[0]["class"] == "VENUE" and v.blockers[0]["source"] == "announcement"
        assert evaluate(rules, BTCT, side, intent, night).allowed
        assert evaluate(rules, BTCU, side, intent, night).allowed
    assert evaluate(rules, USDT, "BUY", "ENTRY", tehran_time("2026-10-31T12:00")).allowed
    assert next_change(rules, USDT, "BUY", "ENTRY", night) == tehran_time("2026-10-31T11:30")
    # The earlier 21:00-09:00 vintage applies before 18 October.
    assert not evaluate(rules, USDT, "BUY", "ENTRY", tehran_time("2026-10-10T21:30")).allowed
    assert evaluate(rules, USDT, "BUY", "ENTRY", tehran_time("2026-10-10T09:30")).allowed


def test_quota_counts_and_resets():
    rules = [parse_rule(d) for d in PRESETS["usdt-irt-october-2026"]]
    noon = tehran_time("2026-10-31T12:00")
    assert evaluate(rules, USDT, "BUY", "ENTRY", noon, used=Decimal(1500)).quota_remaining == Decimal(500)
    full = evaluate(rules, USDT, "BUY", "ENTRY", noon, used=Decimal(2000))
    assert not full.allowed and full.blockers[0]["family"] == "VenueQuota"
    assert evaluate(rules, USDT, "SELL", "EXIT", noon, used=Decimal(2000)).allowed
    assert evaluate(rules, BTCU, "BUY", "ENTRY", noon, used=Decimal(2000)).allowed  # spending USDT is not buying it
    # Exhausted quota at noon: closure starts 23:30, and the cap resets at Tehran midnight, still inside the closure.
    assert next_change(rules, USDT, "BUY", "ENTRY", noon, used=Decimal(2000)) == tehran_time("2026-11-01T11:30")


def test_rule_precedence_preserves_exit_permissions():
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    assert evaluate([restriction(**{"class": "SCENARIO"})], BTCT, "SELL", "ENTRY", now).allowed
    assert not evaluate([restriction(**{"class": "SCENARIO"})], BTCT, "SELL", "ENTRY", now, live=False).allowed
    pol = restriction(**{"class": "POLICY", "status": "VERIFIED"})
    assert not evaluate([pol], BTCT, "BUY", "ENTRY", now).allowed
    v = evaluate([pol], BTCT, "SELL", "EXIT", now)
    assert v.allowed and v.warnings  # ordinary POLICY never blocks an exit, but says it would
    assert not evaluate([restriction(**{"class": "POLICY", "exit_confirmed": True})], BTCT, "SELL", "EXIT", now).allowed
    inf = restriction(status="INFERRED", last_confirmed_at="2026-10-28T00:00:00Z")
    assert evaluate([inf], BTCT, "SELL", "EXIT", now).allowed
    e = evaluate([inf], BTCT, "BUY", "ENTRY", now)
    assert not e.allowed and e.blockers[0]["status"] == "STALE"  # stale, not void
    assert evaluate([restriction(action="WARN")], BTCT, "BUY", "ENTRY", now).warnings


def test_malformed_rules_quarantined(tmp_path):
    svc = RuleService(MarketDB(tmp_path / "m.db"))
    now = datetime(2026, 10, 30, tzinfo=UTC)
    res = svc.import_([{"id": "bad", "family": "Nope"}, {"id": "tw", "family": "TradingWindow", "class": "VENUE",
                       "action": "BLOCK_ALL", "params": {}, "effective_from": "2026-01-01T00:00:00Z",
                       "source": "operator", "status": "VERIFIED"}], now)
    assert {q["id"] for q in res["quarantined"]} == {"bad", "tw"}
    _, rules, q = svc.load()
    assert rules == [] and len(q) == 2
    with pytest.raises(ValueError):
        svc.put({"id": "x", "effective_from": "2026-01-01T00:00:00"}, now)  # unzoned date is rejected outright


def test_rule_ledger_versions_and_rollback(tmp_path):
    db = MarketDB(tmp_path / "m.db")
    svc = RuleService(db)
    t0 = datetime(2026, 10, 30, 10, tzinfo=UTC)
    d = {"id": "s", "family": "PairSuspension", "class": "VENUE", "action": "BLOCK_ENTRY", "scope": {"symbols": ["BTCTMN"]},
         "effective_from": "2026-01-01T00:00:00Z", "source": "operator", "status": "VERIFIED"}
    s1 = svc.put(d, t0)
    assert not svc.check(BTCT, "BUY", "ENTRY", t0)["allowed"]
    svc.disable("s", t0 + timedelta(hours=1))
    assert svc.check(BTCT, "BUY", "ENTRY", t0 + timedelta(hours=2))["allowed"]  # next evaluation, no restart
    # Point-in-time vintage: as recorded before the disable, the suspension still applied.
    assert not svc.check(BTCT, "BUY", "ENTRY", t0, at_rules=t0 + timedelta(minutes=30))["allowed"]
    v = svc.rollback("s", s1, t0 + timedelta(hours=3))
    r = svc.check(BTCT, "BUY", "ENTRY", t0 + timedelta(hours=4))
    assert not r["allowed"] and r["ruleset_version"] == v
    assert [e["op"] for e in db.rule_events("s")] == ["add", "disable", "rollback"]


def test_replay_respects_rule_vintages(tmp_path):
    rows = quote_history(3000, sym="USDTTMN")
    rows = [BookTop("USDTTMN", x.ts_avail + timedelta(hours=10), x.bid / 250, x.ask / 250, Decimal(1), Decimal(1), x.flags) for x in rows]
    late = START + timedelta(days=1)  # rules recorded after the window
    db = market_db(tmp_path, rows, preset_at=late)
    t0, t1 = rows[0].ts_avail, rows[-1].ts_avail
    pit = paper(db, "USDTTMN", t0, t1, resolution="1min", fast=3, slow=8)
    now = paper(db, "USDTTMN", t0, t1, resolution="1min", fast=3, slow=8, rules_mode="today")
    assert not any("RULE:" in r for r in pit["result"]["nonfills"])
    assert any("RULE:" in r for r in now["result"]["nonfills"]) and any("TODAY" in w for w in now["warnings"])
