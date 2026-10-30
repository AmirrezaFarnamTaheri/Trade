"""Workstream A1 checks: exact parsing, quality, rules (REG-01/02/05/07), store, API guard, layering."""
import ast
import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from gym.adapters.store import MarketDB, SegmentWriter, read_segment
from gym.domain.model import TEHRAN, UTC, BookSide, InstrumentId, book_top, levels, loads, dec
from gym.domain.rules import PRESETS, evaluate, next_change, parse_rule
from gym.services.collector import Collector
from gym.services.rules import RuleService

SRC = Path(__file__).resolve().parents[1] / "src" / "gym"
# Real frames captured from wss://api.wallex.ir/connection/websocket on 2026-10-30.
WS_DEPTH = ('{"push":{"channel":"orderbook:BTCTMN@buyDepth","pub":{"data":{"message":[{"price":21038000010,'
            '"quantity":0.05229445,"sum":1100170639.6229446},{"price":21038000000,"quantity":0.00001245,"sum":261923.1},'
            '{"price":21022500222,"quantity":0.004329,"sum":91006403.461038}]}}}}')
WS_ASK = ('{"push":{"channel":"orderbook:BTCTMN@sellDepth","pub":{"data":{"message":[{"price":21079999645,'
          '"quantity":0.000919,"sum":19372519.673755},{"price":21079999646,"quantity":0.00474383,"sum":99999934.72068419},'
          '{"price":21079999647,"quantity":0.004,"sum":84319998.588}]}}}}')
WS_TRADE = ('{"push":{"channel":"public:BTCTMN@trade","pub":{"data":{"isBuyOrder":true,"price":"21038000010",'
            '"quantity":"0.00001399","timestamp":"2026-10-30T20:53:00Z"}}}}')
USDT, BTCT, BTCU = (InstrumentId.wallex(s) for s in ("USDTTMN", "BTCTMN", "BTCUSDT"))


def teh(s):
    return datetime.fromisoformat(s).replace(tzinfo=TEHRAN).astimezone(UTC)


def rule(**kw):
    base = {"id": "r", "family": "PairSuspension", "class": "VENUE", "action": "BLOCK_ALL", "scope": {"symbols": ["BTCTMN"]},
            "effective_from": "2026-01-01T00:00:00Z", "source": "operator", "status": "VERIFIED"}
    return parse_rule({**base, **kw})


def test_exact_decimals_never_float():
    lv = levels(loads(WS_DEPTH)["push"]["pub"]["data"]["message"])
    assert lv[0] == (Decimal("21038000010"), Decimal("0.05229445"))
    assert str(loads('{"x":1100170639.6229446}')["x"]) == "1100170639.6229446"
    with pytest.raises(TypeError):
        dec(0.1)


def test_book_quality_flags():
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    side = lambda p: BookSide([(Decimal(p), Decimal(1))] * 3, now)  # noqa: E731
    assert book_top("X", side("101"), side("100"), now).flags == {"CROSSED"}
    assert book_top("X", side("100"), side("100"), now).flags == {"ZERO_SPREAD"}
    assert "WIDE_SPREAD" in book_top("X", side("100"), side("110"), now).flags
    ok = book_top("X", side("100"), side("100.5"), now)
    assert ok.flags == set() and ok.spread_bps == Decimal("49.88")
    assert "STALE" in book_top("X", side("100"), side("100.5"), now + timedelta(seconds=121)).flags
    assert "STALE" in book_top("X", None, side("100.5"), now).flags
    assert "NON_FINITE" in book_top("X", BookSide([(Decimal("NaN"), Decimal(1))], now), side("1"), now).flags


def test_reg07_usdt_closure_is_pair_scoped():
    rules = [parse_rule(d) for d in PRESETS["usdt-irt-october-2026"]]
    night = teh("2026-10-31T00:30")
    for intent, side in (("ENTRY", "BUY"), ("EXIT", "SELL")):
        v = evaluate(rules, USDT, side, intent, night)
        assert not v.allowed and v.blockers[0]["rule_id"] == "wallex-usdttmn-closure-2330-1130"
        assert v.blockers[0]["class"] == "VENUE" and v.blockers[0]["source"] == "announcement"
        assert evaluate(rules, BTCT, side, intent, night).allowed
        assert evaluate(rules, BTCU, side, intent, night).allowed
    assert evaluate(rules, USDT, "BUY", "ENTRY", teh("2026-10-31T12:00")).allowed
    assert next_change(rules, USDT, "BUY", "ENTRY", night) == teh("2026-10-31T11:30")
    # The earlier 21:00-09:00 vintage applies before 18 October.
    assert not evaluate(rules, USDT, "BUY", "ENTRY", teh("2026-10-10T21:30")).allowed
    assert evaluate(rules, USDT, "BUY", "ENTRY", teh("2026-10-10T09:30")).allowed


def test_quota_counts_and_resets():
    rules = [parse_rule(d) for d in PRESETS["usdt-irt-october-2026"]]
    noon = teh("2026-10-31T12:00")
    assert evaluate(rules, USDT, "BUY", "ENTRY", noon, used=Decimal(1500)).quota_remaining == Decimal(500)
    full = evaluate(rules, USDT, "BUY", "ENTRY", noon, used=Decimal(2000))
    assert not full.allowed and full.blockers[0]["family"] == "VenueQuota"
    assert evaluate(rules, USDT, "SELL", "EXIT", noon, used=Decimal(2000)).allowed
    assert evaluate(rules, BTCU, "BUY", "ENTRY", noon, used=Decimal(2000)).allowed  # spending USDT is not buying it
    # Exhausted quota at noon: closure starts 23:30, and the cap resets at Tehran midnight, still inside the closure.
    assert next_change(rules, USDT, "BUY", "ENTRY", noon, used=Decimal(2000)) == teh("2026-11-01T11:30")


def test_reg02_precedence():
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)
    assert evaluate([rule(**{"class": "SCENARIO"})], BTCT, "SELL", "ENTRY", now).allowed
    assert not evaluate([rule(**{"class": "SCENARIO"})], BTCT, "SELL", "ENTRY", now, live=False).allowed
    pol = rule(**{"class": "POLICY", "status": "VERIFIED"})
    assert not evaluate([pol], BTCT, "BUY", "ENTRY", now).allowed
    v = evaluate([pol], BTCT, "SELL", "EXIT", now)
    assert v.allowed and v.warnings  # ordinary POLICY never blocks an exit, but says it would
    assert not evaluate([rule(**{"class": "POLICY", "exit_confirmed": True})], BTCT, "SELL", "EXIT", now).allowed
    inf = rule(status="INFERRED", last_confirmed_at="2026-10-28T00:00:00Z")
    assert evaluate([inf], BTCT, "SELL", "EXIT", now).allowed
    e = evaluate([inf], BTCT, "BUY", "ENTRY", now)
    assert not e.allowed and e.blockers[0]["status"] == "STALE"  # stale, not void
    assert evaluate([rule(action="WARN")], BTCT, "BUY", "ENTRY", now).warnings


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


def test_reg01_reg05_ledger_versions_and_rollback(tmp_path):
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


def test_collector_segments_and_change_only_tops(tmp_path):
    db = MarketDB(tmp_path / "m.db")
    seg = SegmentWriter(tmp_path / "raw", db)
    col = Collector(db, seg, ["BTCTMN"])
    now = datetime(2026, 10, 30, 20, 53, 1, tzinfo=UTC)
    for f in (WS_DEPTH, WS_ASK, WS_TRADE, "{}", "not json"):
        col.handle_frame(f, now)
    col.tick(now)
    col.tick(now + timedelta(seconds=2))  # unchanged top: not written again
    assert db.c.execute("select count(*) from book_top").fetchone()[0] == 1
    assert db.c.execute("select bid, ask from book_top").fetchone() == ("21038000010", "21079999645")
    assert db.c.execute("select price, aggressor from trades").fetchall() == [("21038000010", "SELL")]
    assert db.c.execute("select count(*) from quality_events where flag='SOURCE_ERROR'").fetchone()[0] == 1
    seg.close()
    sid, path, a, b, sha, n = db.c.execute("select seg_id, path, seq_from, seq_to, sha256, bytes from segments").fetchone()
    lines = read_segment(Path(path))
    assert (a, b) == (1, 4) and [x["raw"] for x in lines] == [WS_DEPTH, WS_ASK, WS_TRADE, "not json"]
    import hashlib
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha


def test_api_loopback_and_token(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    from gym.api.server import make_app

    async def go():
        db = MarketDB(tmp_path / "m.db")
        col = Collector(db, SegmentWriter(tmp_path / "raw", db), ["USDTTMN"])
        svc = RuleService(db)
        svc.preset("usdt-irt-october-2026", datetime(2026, 10, 1, tzinfo=UTC))
        async with TestClient(TestServer(make_app(col, svc, "tok"), host="127.0.0.1")) as c:
            assert (await c.post("/api/presets/usdt-irt-october-2026")).status == 403
            assert (await c.get("/api/markets", headers={"Host": "evil.example"})).status == 403
            m = await (await c.get("/api/markets")).json()
            assert set(m["markets"][0]["act"]) == {"entry", "exit"}
            r = await c.post("/api/rules/import", data="[1]", headers={"X-Gym-Token": "tok"})
            assert r.status == 400
            assert "__GYM_TOKEN__" not in await (await c.get("/")).text()
    asyncio.run(go())


def test_layering_domain_is_pure():
    banned = {"gym.adapters", "gym.services", "gym.api", "aiohttp", "sqlite3", "zstandard", "socket", "asyncio"}
    for f in (SRC / "domain").glob("*.py"):
        for n in ast.walk(ast.parse(f.read_text("utf-8"))):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else \
                   [("gym." if n.level else "") + (n.module or "")] if isinstance(n, ast.ImportFrom) else []
            for m in mods:
                assert not any(m == b or m.startswith(b + ".") for b in banned), f"{f.name} imports {m}"
