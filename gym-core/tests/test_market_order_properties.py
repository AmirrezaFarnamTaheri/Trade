"""Seeded property tests for the simulator's money core: thousands of random orders, invariants on every one.

Each case draws a book, quotes (optionally with depth), a cost model and a venue precision, then checks:
a fill conserves cash exactly (quote moves by the notional, base by the quantity, the fee in the received asset),
never spends more than the fraction of cash it was given, respects the quantity precision, never trades at a
better price than the touch, and never fills before decision + latency; a non-fill leaves the book untouched.
"""
import random
from datetime import timedelta
from decimal import Decimal

import pytest

from gym.domain.model import BookTop, InstrumentId
from gym.domain.sim import CashBook, CostModel, Spec, market_order
from tests.support import START

INST = InstrumentId.wallex("BTCUSDT", "BTC", "USDT")


def close(actual: Decimal, expected: Decimal) -> bool:
    """Equal up to the default 28-significant-digit Decimal context that CashBook sums in.

    With a known venue precision every amount is exact; with unknown precision (qty_decimals None) quantities
    carry 28 significant digits and a balance sum can round in its last digit, about 1e-28 relative.
    """
    return abs(actual - expected) <= max(abs(expected), Decimal(1)) * Decimal("1e-26")


def d(rng, lo, hi, places):
    return Decimal(rng.randint(int(lo * 10**places), int(hi * 10**places))).scaleb(-places)


def case(seed):
    rng = random.Random(seed)
    walk = rng.random() < 0.4
    mid = d(rng, 100, 90000, 2)
    tops = []
    for i in range(rng.randint(1, 4)):
        half = d(rng, 0.01, 50, 2)
        bid, ask = mid - half, mid + half
        depth = None
        if walk or rng.random() < 0.3:
            levels = rng.randint(1, 4)
            asks = [(ask + Decimal(k) * d(rng, 0.01, 5, 2), d(rng, 0.0001, 3, 4)) for k in range(levels)]
            bids = [(bid - Decimal(k) * d(rng, 0.01, 5, 2), d(rng, 0.0001, 3, 4)) for k in range(levels)]
            depth = (tuple(bids), tuple(asks))
        tops.append(BookTop("BTCUSDT", START + timedelta(milliseconds=rng.randint(0, 3000) + 1000 * i), bid, ask,
                            d(rng, 0.0001, 5, 4), d(rng, 0.0001, 5, 4), frozenset(), depth))
        mid += d(rng, -20, 20, 2)
    tops.sort(key=lambda top: top.ts_avail)
    cost = CostModel(fee_rate=d(rng, 0, 0.005, 4), latency=timedelta(milliseconds=rng.randint(0, 2000)),
                     walk_depth=walk, max_participation=rng.choice([None, Decimal("0.5"), Decimal("0.1")]))
    spec = Spec(qty_decimals=rng.choice([None, 2, 4, 6, 8]), min_notional=rng.choice([None, Decimal(5)]))
    book = CashBook({"USDT": d(rng, 0, 50000, 2), "BTC": d(rng, 0, 2, 8)})
    side = rng.choice(["BUY", "SELL"])
    fraction = rng.choice([Decimal(1), Decimal("0.5"), d(rng, 0.01, 1, 2)])
    return book, side, fraction, tops, cost, spec


@pytest.mark.parametrize("block", range(8))
def test_market_order_invariants_hold_on_random_orders(block):
    filled = 0
    for seed in range(block * 500, block * 500 + 500):
        book, side, fraction, tops, cost, spec = case(seed)
        before = dict(book.balances)
        quote = tops[0].ask if side == "BUY" else tops[0].bid
        try:
            out = market_order(book, INST, side, fraction, START, quote, tops, 0, cost, spec, [], {}, f"o{seed}")
        except ArithmeticError as error:  # CashBook refuses a negative balance: that is itself a violation
            pytest.fail(f"seed {seed}: {error}")
        if out["status"] != "FILLED":
            assert book.balances == before and not book.postings, f"seed {seed}: a non-fill moved money"
            continue
        filled += 1
        qty, price, fee = Decimal(out["qty"]), Decimal(out["price"]), Decimal(out["fee"])
        assert qty > 0 and price > 0 and fee >= 0, seed
        if spec.qty_decimals is not None:
            assert qty == qty.quantize(Decimal(1).scaleb(-spec.qty_decimals)), f"seed {seed}: precision"
        assert out["fill_time"] >= (START + cost.latency).isoformat()[:19], f"seed {seed}: filled before latency"
        # Known venue precision: every amount is exact and so is every invariant. Unknown precision (None) puts
        # quantities at the 28-digit context limit, so there the invariants hold within that context. A walked
        # price is a volume-weighted quotient, so quote conservation against qty * price is approximate there too.
        exact = spec.qty_decimals is not None
        same = (lambda a, b: a == b) if exact else close
        first = next(t for t in tops if t.ts_avail >= START + cost.latency)
        if side == "BUY":
            budget = before["USDT"] * fraction
            spent = before["USDT"] - book.get("USDT")
            assert spent <= budget if exact else spent <= budget or close(spent, budget), f"seed {seed}: overspent"
            assert same(book.get("BTC"), before["BTC"] + qty - fee), f"seed {seed}: base not conserved"
            assert (same if not cost.walk_depth else close)(spent, qty * price), f"seed {seed}: quote not conserved"
            assert fee == qty * cost.fee_rate, f"seed {seed}: fee"
            assert price >= first.ask or (not exact and close(price, first.ask)), f"seed {seed}: bought below the ask"
        else:
            assert qty <= before["BTC"] * fraction and same(book.get("BTC"), before["BTC"] - qty), f"seed {seed}: sold too much"
            received = book.get("USDT") - before["USDT"]
            assert (same if not cost.walk_depth else close)(received, qty * price - fee), f"seed {seed}: quote not conserved"
            assert price <= first.bid or (not exact and close(price, first.bid)), f"seed {seed}: sold above the bid"
        assert out["costs"]["spread"] >= 0, f"seed {seed}: negative spread cost"
    assert filled >= 100, f"only {filled} fills in this block; the generator no longer exercises fills"
