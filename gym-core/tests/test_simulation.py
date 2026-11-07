"""Simulated order settlement, quota sizing and cash accounting."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from gym.domain.model import UTC, BookTop, InstrumentId
from gym.domain.rules import PRESETS, parse_rule
from gym.domain.sim import CashBook, CostModel, Spec, market_order
from tests.support import START, quote


def test_orders_fill_after_latency_on_the_correct_side():
    inst = InstrumentId.wallex("BTCUSDT")
    q = [quote(START, "100", "101"), quote(START + timedelta(milliseconds=300), "100", "102"),
         quote(START + timedelta(seconds=1), "100", "103", ["STALE"]), quote(START + timedelta(seconds=2), "99", "104")]
    book = CashBook({"USDT": Decimal(1000)})
    o = market_order(book, inst, "BUY", Decimal(1), START, Decimal(101), q, 0, CostModel(), Spec(), [], {}, "o1")
    # Not the triggering quote, not inside the latency, not a STALE one: the first qualified quote after 500 ms.
    assert o["status"] == "FILLED" and o["price"] == "104" and o["fill_time"].startswith("2026-10-29T09:00:02")
    assert o["costs"]["latency_drift"] == Decimal(3) * Decimal(o["qty"])
    s = market_order(book, inst, "SELL", Decimal(1), START, Decimal(100), q, 0, CostModel(), Spec(), [], {}, "o2")
    assert s["price"] == "99" and s["fee_ccy"] == "USDT"
    late = market_order(book, inst, "BUY", Decimal(1), START, Decimal(101), q[:1], 0, CostModel(), Spec(), [], {}, "o3")
    assert late == {"ref": "o3", "side": "BUY", "decision_time": late["decision_time"], "status": "NONFILL",
                    "reason": "NO_QUALIFIED_QUOTE"}
    odd = CashBook({"TMN": Decimal(300_000_000)})  # 28-digit division used to round up and overdraw
    o = market_order(odd, InstrumentId.wallex("BTCTMN"), "BUY", Decimal(1), START, Decimal(1), [BookTop("BTCTMN", START + timedelta(seconds=1),
                     Decimal(21016006081), Decimal(21016006083), Decimal(1), Decimal(1), frozenset())], 0, CostModel(), Spec(), [], {}, "odd")
    assert o["status"] == "FILLED" and odd.get("TMN") >= 0
    tiny = market_order(CashBook({"USDT": Decimal(5)}), inst, "BUY", Decimal(1), START, Decimal(101), q, 0, CostModel(),
                        Spec(5, Decimal("0.00001"), Decimal(10)), [], {}, "o4")
    assert tiny["reason"] == "BELOW_MIN_NOTIONAL"  # never rounded up into exposure


def test_cashbook_charges_received_asset_fees_once():
    """§5.3: 1000 cash, buy 100 at ask 10, 0.1 base fee, mark at bid 9.9 -> equity 998.01; fee not subtracted twice."""
    inst, book = InstrumentId.wallex("BTCUSDT"), CashBook({"USDT": Decimal(1000)})
    o = market_order(book, inst, "BUY", Decimal("0.1"), START, Decimal(10), [quote(START + timedelta(seconds=1), "9.9", "10")], 0,
                     CostModel(fee_rate=Decimal("0.01")), Spec(), [], {}, "a")
    assert o["fee"] == "0.100" and book.get("USDT") == 900 and book.get("BTC") == Decimal("9.9")
    assert book.equity(inst, Decimal("9.9")) == Decimal("998.01")


def test_rules_veto_orders_and_resize_quota_excess():
    rules = [parse_rule(d) for d in PRESETS["usdt-irt-october-2026"]]
    inst = InstrumentId.wallex("USDTTMN")
    night = datetime(2026, 10, 29, 20, tzinfo=UTC)  # 23:30 Tehran: closure starts
    q = [BookTop("USDTTMN", night + timedelta(seconds=1), Decimal(273000), Decimal(273500), Decimal(1), Decimal(1), frozenset())]
    o = market_order(CashBook({"TMN": Decimal(10 ** 9)}), inst, "BUY", Decimal(1), night - timedelta(seconds=1), Decimal(273500), q, 0,
                     CostModel(), Spec(), rules, {}, "n")
    assert o["status"] == "NONFILL" and o["reason"] == "RULE:wallex-usdttmn-closure-2330-1130"
    noon = datetime(2026, 10, 29, 9, tzinfo=UTC)
    q = [BookTop("USDTTMN", noon + timedelta(seconds=1), Decimal(273000), Decimal(273500), Decimal(1), Decimal(1), frozenset())]
    used = {}
    o = market_order(CashBook({"TMN": Decimal(10 ** 9)}), inst, "BUY", Decimal(1), noon, Decimal(273500), q, 0, CostModel(), Spec(2),
                     rules, used, "q")
    assert o["resized"] == "VenueQuota" and o["qty"] == "2000.00" and used[noon.date()] == Decimal(2000)


def test_cost_boundary():
    for fee in ("NaN", "Infinity", "-0.01", "1"):
        with pytest.raises(ValueError):
            CostModel(Decimal(fee))
    with pytest.raises(ValueError):
        CostModel(latency=timedelta(seconds=-1))


def test_optional_participation_cap_resizes_fills_to_displayed_size():
    inst = InstrumentId.wallex("BTCUSDT")
    top = [BookTop("BTCUSDT", START + timedelta(seconds=1), Decimal(100), Decimal(101), Decimal(3), Decimal("0.5"), frozenset())]
    capped = CostModel(max_participation=Decimal("0.2"))
    book = CashBook({"USDT": Decimal(1000)})
    o = market_order(book, inst, "BUY", Decimal(1), START, Decimal(101), top, 0, capped, Spec(), [], {}, "b")
    assert o["status"] == "FILLED" and Decimal(o["qty"]) == Decimal("0.1") and o["resized"] == "DisplayedCapacity"
    assert book.get("USDT") == Decimal("989.9")
    blind = [BookTop("BTCUSDT", START + timedelta(seconds=1), Decimal(100), Decimal(101), None, None, frozenset())]
    o = market_order(CashBook({"USDT": Decimal(1000)}), inst, "BUY", Decimal(1), START, Decimal(101), blind, 0, capped, Spec(), [], {}, "c")
    assert o["reason"] == "DISPLAYED_CAPACITY_UNAVAILABLE"
    # Default models keep their exact earlier description, so saved run identities do not change.
    assert "max_participation" not in CostModel().describe()
    assert CostModel.from_description(capped.describe()) == capped
    with pytest.raises(ValueError):
        CostModel(max_participation=Decimal("1.5"))


def test_depth_walk_fills_at_the_volume_weighted_price_within_the_budget():
    inst = InstrumentId.wallex("BTCUSDT")
    depth = (((Decimal(100), Decimal(1)), (Decimal(99), Decimal(5))),
             ((Decimal(101), Decimal("0.5")), (Decimal(102), Decimal(1)), (Decimal(110), Decimal(10))))
    top = [BookTop("BTCUSDT", START + timedelta(seconds=1), Decimal(100), Decimal(101), Decimal(1), Decimal("0.5"), frozenset(), depth)]
    walk = CostModel(fee_rate=Decimal(0), walk_depth=True)
    book = CashBook({"USDT": Decimal("152.5")})  # 0.5 @ 101 + 1 @ 102 = 152.5 exactly
    o = market_order(book, inst, "BUY", Decimal(1), START, Decimal(101), top, 0, walk, Spec(), [], {}, "b")
    assert Decimal(o["qty"]) == Decimal("1.5") and Decimal(o["price"]) * Decimal("1.5") == Decimal("152.5")
    assert book.get("USDT") == 0 and o["costs"]["latency_drift"] == 0  # the best level did not move
    o = market_order(book, inst, "SELL", Decimal(1), START, Decimal(100), top, 0, walk, Spec(), [], {}, "s")
    assert Decimal(o["price"]) == (Decimal(100) + Decimal("0.5") * 99) / Decimal("1.5")
    thin = CashBook({"BTC": Decimal(10)})
    o = market_order(thin, inst, "SELL", Decimal(1), START, Decimal(100), top, 0, walk, Spec(), [], {}, "t")
    assert Decimal(o["qty"]) == 6 and o["resized"] == "ObservedDepth" and o["requested_qty"] == "10"
    blind = [BookTop("BTCUSDT", START + timedelta(seconds=1), Decimal(100), Decimal(101), Decimal(1), Decimal(1), frozenset())]
    o = market_order(CashBook({"USDT": Decimal(10)}), inst, "BUY", Decimal(1), START, Decimal(101), blind, 0, walk, Spec(), [], {}, "u")
    assert o["reason"] == "DEPTH_UNAVAILABLE"
    assert "walk_depth" not in CostModel().describe() and CostModel.from_description(walk.describe()) == walk


def test_carried_remainder_fills_on_later_quotes_within_max_wait(tmp_path):
    from gym.services.paper import paper
    from tests.support import market_db, quote_history
    db = market_db(tmp_path, quote_history(n=500))
    cost = CostModel(max_participation=Decimal("0.01"), carry_remainder=True)
    out = paper(db, "BTCUSDT", START, START + timedelta(hours=1), resolution="1min", fast=2, slow=3, cost=cost)
    orders = out["result"]["orders"]
    children = [o for o in orders if "parent" in o]
    assert children and all(o["ref"].startswith(o["parent"] + ".") for o in children)
    parent = next(o for o in orders if o["ref"] == children[0]["parent"])
    filled = [o for o in [parent, *children] if o["ref"].startswith(parent["ref"]) and o["status"] == "FILLED"]
    total = sum(Decimal(o["qty"]) for o in filled)
    # Later fills add to the first; a rising ask can leave the cash short of the original target.
    assert Decimal(parent["qty"]) < total <= Decimal(parent["requested_qty"])
    assert out["inputs"]["cost"]["carry_remainder"] is True


def test_sizing_caps_entries_and_targets_volatility():
    closes = [Decimal(100 + (i % 2)) for i in range(21)]  # about 1% per bar
    assert CostModel(max_fraction=Decimal("0.25")).size(Decimal(1), closes) == Decimal("0.25")
    vol = CostModel(vol_target=Decimal("0.002"))
    assert Decimal("0.19") < vol.size(Decimal(1), closes) < Decimal("0.21")  # 0.2% / ~1% realized
    assert vol.size(Decimal(1), closes[:10]) == 0  # not enough history: no entry yet
    assert CostModel.from_description(vol.describe()) == vol and "vol_target" not in CostModel().describe()


def test_sized_paper_runs_record_the_fraction_used(tmp_path):
    from gym.services.paper import paper
    from tests.support import market_db, quote_history
    db = market_db(tmp_path, quote_history(n=500))
    out = paper(db, "BTCUSDT", START, START + timedelta(hours=1), resolution="1min", fast=2, slow=3,
                cost=CostModel(max_fraction=Decimal("0.3")))
    sized = [d for d in out["result"]["decisions"] if "sized_fraction" in d]
    assert sized and all(d["sized_fraction"] == "0.3" for d in sized)
    buy = next(o for o in out["result"]["orders"] if o["side"] == "BUY" and o["status"] == "FILLED")
    assert Decimal(buy["qty"]) * Decimal(buy["price"]) <= Decimal(300)


def _limit_session(tmp_path, prints, maker="0.0002"):
    from gym.domain.model import TradeTick
    from gym.services.data_portal import DataPortal
    from gym.services.rules import RuleService
    from gym.services.session import PaperSession, PendingOrder
    from tests.support import market_db
    tops = [BookTop("BTCUSDT", START + timedelta(seconds=s), Decimal(100), Decimal(101), Decimal(2), Decimal(2), frozenset())
            for s in (1, 5, 10, 20)]
    db = market_db(tmp_path, tops)
    for seconds, price, qty, aggressor in prints:
        t = START + timedelta(seconds=seconds)
        db.add_trade(TradeTick("BTCUSDT", t, t, Decimal(price), Decimal(qty), aggressor), "x")
    svc = RuleService(db)
    from gym.domain.strategy import BuyAndHold
    cost = CostModel(order_type="limit", maker_fee_rate=Decimal(maker))
    session = PaperSession(DataPortal(db), lambda t: svc.load(t)[1], BuyAndHold(), "BTCUSDT", START, "1min", Decimal(1000), cost)
    order = {"ref": "BTCUSDT#1", "side": "BUY", "decision_time": START.isoformat(), "status": "PENDING"}
    session.orders.append(order)
    session.pending = PendingOrder(order, Decimal(1), START, Decimal(101))
    for top in tops:
        session.settle(top, top.ts_avail)
    return order, session


def test_limit_order_fills_after_the_queue_ahead_trades_away_at_the_maker_fee(tmp_path):
    order, session = _limit_session(tmp_path, [(0.5, "100", "9", "SELL"), (3, "100", "1.5", "SELL"), (7, "100", "1", "SELL")])
    assert order["status"] == "FILLED" and order["price"] == "100" and order["maker"] is True
    assert order["limit_price"] == "100" and order["queue_ahead"] == "2"
    assert Decimal(order["fee"]) == Decimal(order["qty"]) * Decimal("0.0002")
    assert Decimal(order["costs"]["spread"]) < 0  # resting at the bid earns half the spread
    assert len(session.limit_trades) == 2  # the print before the order rested does not count


def test_limit_order_with_queue_left_expires_without_a_fill(tmp_path):
    order, _ = _limit_session(tmp_path, [(7, "100", "0.5", "SELL"), (8, "101", "5", "BUY")])
    assert order["status"] == "PENDING"  # still resting inside max_wait
    order, session = _limit_session(tmp_path, [(7, "100", "0.5", "SELL")])
    session.settle(None, START + timedelta(seconds=61))
    assert order["status"] == "NONFILL" and order["reason"] == "LIMIT_EXPIRED"
