"""Seeded randomized property checks (no extra dependency): invariants over many generated cases."""
import random
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import BookTop, InstrumentId, iso
from gym.domain.performance import trade_ledger
from gym.domain.sim import CashBook, CostModel, Spec, market_order
from tests.support import START

CASES = 300


def dec(rng, low, high, places):
    return Decimal(rng.randint(int(low * 10**places), int(high * 10**places))).scaleb(-places)


@pytest.mark.parametrize("seed", range(4))
def test_fifo_ledger_conserves_quantity_and_cost(seed):
    rng = random.Random(seed)
    for _ in range(CASES // 4):
        orders, held, bought_cost = [], Decimal(0), Decimal(0)
        for minute in range(1, rng.randint(2, 13)):
            if held > 0 and rng.random() < 0.45:
                qty = min(held, dec(rng, 0.001, float(held) + 0.001, 3))
                orders.append({"ref": f"s{minute}", "side": "SELL", "status": "FILLED", "qty": str(qty), "price": str(dec(rng, 50, 150, 2)),
                               "fee": "0", "fee_ccy": "USDT", "fill_time": iso(START + timedelta(minutes=minute))})
                held -= qty
            else:
                qty, price = dec(rng, 0.001, 2, 3), dec(rng, 50, 150, 2)
                orders.append({"ref": f"b{minute}", "side": "BUY", "status": "FILLED", "qty": str(qty), "price": str(price),
                               "fee": "0", "fee_ccy": "BTC", "fill_time": iso(START + timedelta(minutes=minute))})
                held, bought_cost = held + qty, bought_cost + qty * price
        ledger = trade_ledger(orders, "BTC")
        closed_cost = sum((Decimal(t["cost"]) for t in ledger["trades"]), Decimal(0))
        assert Decimal(ledger["open"]["quantity"]) == held
        assert abs(closed_cost + Decimal(ledger["open"]["cost"]) - bought_cost) < Decimal("1e-20")
        if held == 0:  # flat: both cost methods realize the same total
            fifo = sum((Decimal(t["pnl"]) for t in ledger["trades"]), Decimal(0))
            average = sum((Decimal(t["average_cost_pnl"]) for t in ledger["trades"]), Decimal(0))
            assert abs(fifo - average) < Decimal("1e-18")


@pytest.mark.parametrize("seed", range(4))
def test_market_orders_never_overdraw_and_postings_balance(seed):
    rng = random.Random(100 + seed)
    inst = InstrumentId.wallex("BTCUSDT")
    for _ in range(CASES // 4):
        bid = dec(rng, 1, 100000, 2)
        ask = bid + dec(rng, 0.01, 50, 2)
        levels = ((tuple((bid - i, dec(rng, 0.001, 3, 3)) for i in range(3))), tuple((ask + i, dec(rng, 0.001, 3, 3)) for i in range(3)))
        top = BookTop("BTCUSDT", START + timedelta(seconds=1), bid, ask, levels[0][0][1], levels[1][0][1], frozenset(), levels)
        cost = CostModel(fee_rate=dec(rng, 0, 0.01, 4), walk_depth=rng.random() < 0.5,
                         max_participation=dec(rng, 0.01, 1, 2) if rng.random() < 0.5 else None)
        spec = Spec(qty_decimals=rng.choice([None, 3, 6, 8]))
        cash, base = dec(rng, 0, 10**7, 2), dec(rng, 0, 5, 6)
        book = CashBook({"USDT": cash, "BTC": base})
        side = rng.choice(["BUY", "SELL"])
        out = market_order(book, inst, side, dec(rng, 0.01, 1, 2), START, ask if side == "BUY" else bid, [top], 0, cost, spec, [], {}, "x")
        assert book.get("USDT") >= 0 and book.get("BTC") >= 0
        if out["status"] == "FILLED":
            qty, price = Decimal(out["qty"]), Decimal(out["price"])
            total_depth = sum((size for _, size in levels[1 if side == "BUY" else 0]), Decimal(0))
            assert qty > 0 and (not cost.walk_depth or qty <= total_depth)
            if side == "BUY":
                assert abs(cash - book.get("USDT") - qty * price) < Decimal("1e-12") * max(Decimal(1), cash)
            else:
                assert base - book.get("BTC") == qty


def test_cost_model_descriptions_round_trip():
    rng = random.Random(7)
    for _ in range(CASES):
        model = CostModel(fee_rate=dec(rng, 0, 0.01, 4), latency=timedelta(milliseconds=rng.randint(0, 5000)),
                          max_participation=rng.choice([None, dec(rng, 0.01, 1, 2)]), walk_depth=rng.random() < 0.5,
                          carry_remainder=rng.random() < 0.5, max_fraction=rng.choice([None, dec(rng, 0.01, 1, 2)]),
                          vol_target=rng.choice([None, dec(rng, 0.0001, 0.05, 4)]), order_type=rng.choice(["market", "limit"]),
                          maker_fee_rate=rng.choice([None, dec(rng, 0, 0.002, 4)]))
        again = CostModel.from_description(model.describe())
        assert again.describe() == model.describe()
