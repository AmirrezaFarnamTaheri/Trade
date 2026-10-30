"""Workstream A2 checks: bars (DATA-01/05/06), determinism (DATA-03), simulator and CashBook (SIM-01/04, §5.3)."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from gym.adapters.store import MarketDB
from gym.domain.bars import BarSpec, Consolidator, quote_bars
from gym.domain.model import TEHRAN, UTC, BookTop, InstrumentId
from gym.domain.rules import PRESETS, parse_rule
from gym.domain.sim import CashBook, CostModel, Spec, market_order
from gym.services.paper import DataPortal, paper
from gym.services.rules import RuleService

T0 = datetime(2026, 10, 29, 9, tzinfo=UTC)  # 12:30 Tehran: USDTTMN open
D = Decimal


def top(t, bid, ask, flags=()):
    return BookTop("BTCUSDT", t, D(bid), D(ask), D(1), D(1), frozenset(flags))


def tops(n=2000, step=10, sym="BTCUSDT"):
    """Up for the first half, down for the second: EMA trades at least twice."""
    out, px = [], D(70000)
    for i in range(n):
        px += D(3) if i < n // 2 else D(-3)
        out.append(BookTop(sym, T0 + timedelta(seconds=step * i), px - 5, px + 5, D(1), D(1), frozenset()))
    return out


def db_with(tmp_path, rows, preset_at=T0 - timedelta(days=30)):
    db = MarketDB(tmp_path / "m.db")
    for x in rows:
        db.add_book_top(x, None)
    RuleService(db).preset("usdt-irt-october-2026", preset_at)
    return db


def test_data01_explicit_failures(tmp_path):
    with pytest.raises(ValueError, match="unsupported resolution"):
        BarSpec("5min")
    with pytest.raises(ValueError, match="inverted"):
        DataPortal(db_with(tmp_path, [])).tops("BTCUSDT", T0, T0 - timedelta(hours=1))
    with pytest.raises(ValueError, match="no qualified"):
        paper(db_with(tmp_path, []), "BTCUSDT", T0, T0 + timedelta(hours=1))


def test_data05_06_bars():
    rows = tops(400) + [top(T0 + timedelta(seconds=4005), "1", "2", ["STALE"])]
    spec = BarSpec("15min", "MID")
    c, live = Consolidator("BTCUSDT", spec), []
    for x in rows[:-1]:
        live += c.update(x.ts_avail, spec.price(x))
    assert live == quote_bars("BTCUSDT", spec, rows)  # streaming == batch, and STALE quotes never become bars
    assert all(b.avail == b.end and not b.forming for b in live)
    assert all(b.start.minute % 15 == 0 and b.end - b.start == spec.step for b in live)
    f = c.forming(T0 + timedelta(seconds=3995))
    assert f.forming and f not in live
    assert c.scan(f.end) and c.forming(f.end) is None  # quiet market: the clock closes the bar
    bid, ask = quote_bars("X", BarSpec("15min", "BID"), rows), quote_bars("X", BarSpec("15min", "ASK"), rows)
    assert all(a.close - b.close == 10 for a, b in zip(ask, bid))  # separate bid and ask series
    day = BarSpec("1day").bucket(datetime(2026, 10, 29, 22, tzinfo=UTC))
    assert day.astimezone(TEHRAN).hour == 0 and day.astimezone(TEHRAN).day == 30  # Tehran midnight


def test_sim01_fill_after_latency_on_correct_side():
    inst = InstrumentId.wallex("BTCUSDT")
    q = [top(T0, "100", "101"), top(T0 + timedelta(milliseconds=300), "100", "102"),
         top(T0 + timedelta(seconds=1), "100", "103", ["STALE"]), top(T0 + timedelta(seconds=2), "99", "104")]
    book = CashBook({"USDT": D(1000)})
    o = market_order(book, inst, "BUY", D(1), T0, D(101), q, 0, CostModel(), Spec(), [], {}, "o1")
    # Not the triggering quote, not inside the latency, not a STALE one: the first qualified quote after 500 ms.
    assert o["status"] == "FILLED" and o["price"] == "104" and o["fill_time"].startswith("2026-10-29T09:00:02")
    assert o["costs"]["latency_drift"] == D(3) * D(o["qty"])
    s = market_order(book, inst, "SELL", D(1), T0, D(100), q, 0, CostModel(), Spec(), [], {}, "o2")
    assert s["price"] == "99" and s["fee_ccy"] == "USDT"
    late = market_order(book, inst, "BUY", D(1), T0, D(101), q[:1], 0, CostModel(), Spec(), [], {}, "o3")
    assert late == {"ref": "o3", "side": "BUY", "decision_time": late["decision_time"], "status": "NONFILL",
                    "reason": "NO_QUALIFIED_QUOTE"}
    odd = CashBook({"TMN": D(300_000_000)})  # 28-digit division used to round up and overdraw
    o = market_order(odd, InstrumentId.wallex("BTCTMN"), "BUY", D(1), T0, D(1), [BookTop("BTCTMN", T0 + timedelta(seconds=1),
                     D(21016006081), D(21016006083), D(1), D(1), frozenset())], 0, CostModel(), Spec(), [], {}, "odd")
    assert o["status"] == "FILLED" and odd.get("TMN") >= 0
    tiny = market_order(CashBook({"USDT": D(5)}), inst, "BUY", D(1), T0, D(101), q, 0, CostModel(),
                        Spec(5, D("0.00001"), D(10)), [], {}, "o4")
    assert tiny["reason"] == "BELOW_MIN_NOTIONAL"  # never rounded up into exposure


def test_spec_audit_example():
    """§5.3: 1000 cash, buy 100 at ask 10, 0.1 base fee, mark at bid 9.9 -> equity 998.01; fee not subtracted twice."""
    inst, book = InstrumentId.wallex("BTCUSDT"), CashBook({"USDT": D(1000)})
    o = market_order(book, inst, "BUY", D("0.1"), T0, D(10), [top(T0 + timedelta(seconds=1), "9.9", "10")], 0,
                     CostModel(fee_rate=D("0.01")), Spec(), [], {}, "a")
    assert o["fee"] == "0.100" and book.get("USDT") == 900 and book.get("BTC") == D("9.9")
    assert book.equity(inst, D("9.9")) == D("998.01")


def test_sim04_rules_veto_and_quota_resize():
    rules = [parse_rule(d) for d in PRESETS["usdt-irt-october-2026"]]
    inst = InstrumentId.wallex("USDTTMN")
    night = datetime(2026, 10, 29, 20, tzinfo=UTC)  # 23:30 Tehran: closure starts
    q = [BookTop("USDTTMN", night + timedelta(seconds=1), D(273000), D(273500), D(1), D(1), frozenset())]
    o = market_order(CashBook({"TMN": D(10 ** 9)}), inst, "BUY", D(1), night - timedelta(seconds=1), D(273500), q, 0,
                     CostModel(), Spec(), rules, {}, "n")
    assert o["status"] == "NONFILL" and o["reason"] == "RULE:wallex-usdttmn-closure-2330-1130"
    noon = datetime(2026, 10, 29, 9, tzinfo=UTC)
    q = [BookTop("USDTTMN", noon + timedelta(seconds=1), D(273000), D(273500), D(1), D(1), frozenset())]
    used = {}
    o = market_order(CashBook({"TMN": D(10 ** 9)}), inst, "BUY", D(1), noon, D(273500), q, 0, CostModel(), Spec(2),
                     rules, used, "q")
    assert o["resized"] == "VenueQuota" and o["qty"] == "2000.00" and used[noon.date()] == D(2000)


def test_data03_paper_is_deterministic_and_waterfall_sums(tmp_path):
    db = db_with(tmp_path, tops())
    a = paper(db, "BTCUSDT", T0, T0 + timedelta(hours=6), resolution="1min", fast=3, slow=8)
    b = paper(db, "BTCUSDT", T0, T0 + timedelta(hours=6), resolution="1min", fast=3, slow=8)
    assert a == b and a["result"]["fills"] >= 2
    w = {k: D(v) for k, v in a["result"]["end"]["waterfall"].items()}
    assert w["directional"] + w["spread"] + w["fees"] + w["latency_drift"] == w["net"]
    assert w["fees"] < 0 and w["spread"] < 0
    first = a["result"]["decisions"][0]
    assert first["action"] == "ABSTAIN_WARMUP"  # warmup never fabricates a signal
    assert set(a["baselines"]) == {"hold USDT", "hold BTC"} and a["baselines"]["hold BTC"]["fills"] == 1
    c = paper(db, "BTCUSDT", T0, T0 + timedelta(hours=6), resolution="1min", fast=3, slow=8, cost=CostModel(fee_rate=D("0.004")))
    assert c["run_id"] != a["run_id"] and D(c["result"]["end"]["net"]) < D(a["result"]["end"]["net"])


def test_reg05_rules_point_in_time_vs_today(tmp_path):
    rows = tops(3000, sym="USDTTMN")
    rows = [BookTop("USDTTMN", x.ts_avail + timedelta(hours=10), x.bid / 250, x.ask / 250, D(1), D(1), x.flags) for x in rows]
    late = T0 + timedelta(days=1)  # rules recorded after the window
    db = db_with(tmp_path, rows, preset_at=late)
    t0, t1 = rows[0].ts_avail, rows[-1].ts_avail
    pit = paper(db, "USDTTMN", t0, t1, resolution="1min", fast=3, slow=8)
    now = paper(db, "USDTTMN", t0, t1, resolution="1min", fast=3, slow=8, rules_mode="today")
    assert not any("RULE:" in r for r in pit["result"]["nonfills"])
    assert any("RULE:" in r for r in now["result"]["nonfills"]) and any("TODAY" in w for w in now["warnings"])
