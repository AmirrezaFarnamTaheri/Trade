"""Exact sizing vectors shared by exec-core and the simulator's optional bridge."""
import json
import random
from datetime import timedelta
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
from pathlib import Path

import pytest

from gym.domain import sim
from gym.domain.model import BookTop, InstrumentId
from tests.support import START


@pytest.mark.parametrize("side,precision,balance,fraction,price,want", [
    ("SELL", 28, "1.99999999999999999999999999999", "0.5", "1", "1.00"),
    ("SELL", 6, "12345.6789", "0.123456", "1", "1524.15"),
    ("BUY", 6, "12345.6789", "0.123456", "0.5", "3048.28"),
])
def test_native_comparison_preserves_contextual_sizing(side, precision, balance, fraction, price, want):
    kernel = pytest.importorskip("exec_kernel")
    previous = sim._KERNEL
    outputs = []
    try:
        for module in (None, kernel):
            sim.use_kernel(module)
            with localcontext() as context:
                context.prec = precision
                book = sim.CashBook({"BTC": Decimal(balance), "USDT": Decimal(balance)})
                top = BookTop("BTCUSDT", START, Decimal(price), Decimal(price),
                              Decimal(10000), Decimal(10000), frozenset())
                outputs.append(sim._order_size(book, InstrumentId.wallex("BTCUSDT"), side,
                                                Decimal(fraction), Decimal(price), None, top,
                                                sim.CostModel(), sim.Spec(2), None, None, {}))
        assert str(outputs[0]) == want
        assert outputs[0].as_tuple() == outputs[1].as_tuple()
    finally:
        sim.use_kernel(previous)


def test_native_comparison_preserves_each_depth_walk_rounding_step():
    kernel = pytest.importorskip("exec_kernel")
    previous = sim._KERNEL
    outputs = []
    try:
        for module in (None, kernel):
            sim.use_kernel(module)
            with localcontext() as context:
                context.prec = 6
                book = sim.CashBook({"USDT": Decimal(100)})
                top = BookTop("BTCUSDT", START, Decimal(1), Decimal(1),
                              Decimal(1000), Decimal(1000), frozenset())
                outputs.append(sim._order_size(book, InstrumentId.wallex("BTCUSDT"), "BUY", Decimal(1),
                                                Decimal(1), [(Decimal(1), Decimal("0.02002")),
                                                             (Decimal(2), Decimal(1000))], top,
                                                sim.CostModel(), sim.Spec(2), None, None, {}))
        assert str(outputs[0]) == "50.00"
        assert outputs[0].as_tuple() == outputs[1].as_tuple()
    finally:
        sim.use_kernel(previous)


@pytest.mark.parametrize("native", [False, True])
def test_native_comparison_preserves_quantity_quantize_trap(native):
    kernel = pytest.importorskip("exec_kernel") if native else None
    previous = sim._KERNEL
    try:
        sim.use_kernel(kernel)
        with localcontext() as context:
            context.prec = 6
            book = sim.CashBook({"BTC": Decimal("12345.6789")})
            top = BookTop("BTCUSDT", START, Decimal(1), Decimal(1), Decimal(1000), Decimal(1000), frozenset())
            with pytest.raises(InvalidOperation):
                sim._order_size(book, InstrumentId.wallex("BTCUSDT"), "SELL", Decimal(1), Decimal(1),
                                None, top, sim.CostModel(), sim.Spec(2), None, None, {})
    finally:
        sim.use_kernel(previous)


@pytest.mark.parametrize("native", [False, True])
def test_cash_and_holdings_sizing_vectors(native):
    kernel = pytest.importorskip("exec_kernel") if native else None
    previous = sim._KERNEL
    fixture = json.loads((Path(__file__).resolve().parents[2] / "contracts/v1/fixtures/order-sizing.json").read_text())
    try:
        sim.use_kernel(kernel)
        for case in fixture["cases"]:
            cash, holdings, fraction, price = (Decimal(case[k]) for k in ("cash", "holdings", "fraction", "price"))
            levels = [(Decimal(p), Decimal(s)) for p, s in case["levels"]] or None
            book = sim.CashBook({"USDT": cash, "BTC": holdings})
            top = BookTop("BTCUSDT", START, price, price, Decimal(100), Decimal(100), frozenset())
            inst = InstrumentId.wallex("BTCUSDT", "BTC", "USDT")
            for side, key in (("BUY", "buy"), ("SELL", "sell")):
                quantity = sim._order_size(book, inst, side, fraction, price, levels, top,
                                           sim.CostModel(), sim.Spec(case["qty_decimals"]), None, None, {})
                assert format(quantity, "f") == case[key], case
            if native:
                assert kernel.cash_quantity(str(cash), str(fraction), str(price),
                                            [tuple(level) for level in case["levels"]], case["qty_decimals"]) == case["buy"]
                assert kernel.holdings_quantity(str(holdings), str(fraction), case["qty_decimals"]) == case["sell"]
    finally:
        sim.use_kernel(previous)


def test_native_sizing_refuses_invalid_and_overflowing_inputs():
    kernel = pytest.importorskip("exec_kernel")
    for cash, fraction, price, decimals in (("1", "1", "0", 8), ("1", "1.1", "1", 8),
                                              ("1", "1", "1", 39), ("9" * 38, "1", "0.0001", 8)):
        with pytest.raises(ValueError):
            kernel.cash_quantity(cash, fraction, price, [], decimals)


def test_native_settlement_exposes_exact_shared_deltas():
    kernel = pytest.importorskip("exec_kernel")
    fixture = json.loads((Path(__file__).resolve().parents[2] / "contracts/v1/fixtures/fills.json").read_text())
    for case in fixture["cases"]:
        fee, base, quote = kernel.settle(case["side"] == "BUY", case["quantity"], case["notional"], case["fee_rate"])
        assert tuple(map(Decimal, (fee, base, quote))) == tuple(Decimal(case[k]) for k in ("fee", "base_delta", "quote_delta"))
    with pytest.raises(ValueError):
        kernel.settle(True, "1", "1", "1.1")


def test_native_sizing_matches_independent_rational_budget_walk():
    kernel = pytest.importorskip("exec_kernel")
    rng = random.Random(501)
    for _ in range(2000):
        cash = Decimal(rng.randrange(100000)).scaleb(-2)
        fraction = Decimal(rng.randrange(101)).scaleb(-2)
        levels = [(Decimal(rng.randrange(1, 10000)).scaleb(-2),
                   Decimal(rng.randrange(1, 10000)).scaleb(-4)) for _ in range(4)]
        decimals = rng.randrange(9)
        left, quantity = Fraction(cash) * Fraction(fraction), Fraction(0)
        for price, size in levels:
            take = min(Fraction(size), left / Fraction(price))
            quantity += take
            left -= take * Fraction(price)
        units = quantity * 10 ** decimals
        want = Fraction(units.numerator // units.denominator, 10 ** decimals)
        got = kernel.cash_quantity(str(cash), str(fraction), str(levels[0][0]),
                                   [(format(p, "f"), format(s, "f")) for p, s in levels], decimals)
        assert Fraction(got) == want


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("maker", [False, True])
@pytest.mark.parametrize("modeled", [False, True])
def test_native_fill_matches_dated_cost_fee_and_postings(side, maker, modeled):
    from tests.test_impact_cost_models import hourly_profile, impact_profile

    kernel = pytest.importorskip("exec_kernel")
    hourly = hourly_profile()
    from gym.domain.model import TEHRAN
    hourly["hours"] = {str(START.astimezone(TEHRAN).hour): hourly["hours"]["12"]}
    cost = sim.CostModel(hourly_costs={"BTCUSDT": hourly} if modeled else None,
                         impact_models={"BTCUSDT": impact_profile()} if modeled else None,
                         maker_fee_rate=Decimal("0.0005"))
    top = BookTop("BTCUSDT", START + timedelta(seconds=1), Decimal(100), Decimal("100.2"),
                  Decimal(1000), Decimal(1000), frozenset())
    inst = InstrumentId.wallex("BTCUSDT")
    outputs = []
    previous = sim._KERNEL
    try:
        for module in (None, kernel):
            sim.use_kernel(module)
            book = sim.CashBook({"BTC": Decimal(10), "USDT": Decimal(1000)})
            fill = sim.market_order(book, inst, side, Decimal("0.5"), START, top.ask,
                                     [top], 0, cost, sim.Spec(8), [], {}, "o",
                                     limit_price=Decimal("100.1") if maker else None)
            assert fill["status"] == "FILLED"
            outputs.append((repr(fill), book.balances, book.postings))
        assert outputs[0] == outputs[1]
    finally:
        sim.use_kernel(previous)
