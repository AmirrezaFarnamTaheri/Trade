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
