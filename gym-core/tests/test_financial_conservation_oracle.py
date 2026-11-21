"""Independent double-entry conservation oracle and financial accounting invariants (F001-F006, F008-F009, F012)."""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from gym.domain.model import InstrumentId, iso
from gym.domain.performance import booked_notionals, performance, trade_ledger
from gym.domain.sim import CostModel
from gym.services.paper import paper
from gym.services.portfolio import portfolio
from tests.support import START, market_db, quote_history


def _dec(rng: random.Random, low: float, high: float, places: int) -> Decimal:
    return Decimal(rng.randint(int(low * 10**places), int(high * 10**places))).scaleb(-places)


def _generate_case(rng: random.Random, *, allow_base_sell_fee: bool = True, allow_rebates: bool = True):
    """Build a valid sequence of fills, exact postings, and an independent double-entry balance oracle."""
    start_quote = Decimal("100000")
    quote_bal, base_bal = start_quote, Decimal(0)
    orders, postings = [], []
    total_quote_out = Decimal(0)  # net quote spent on acquisitions
    total_quote_in = Decimal(0)  # net quote received on dispositions

    steps = rng.randint(4, 18)
    for minute in range(1, steps + 1):
        at = iso(START + timedelta(minutes=minute))
        can_sell = base_bal > Decimal("0.0005")
        is_sell = can_sell and (minute == steps and rng.random() < 0.5 or rng.random() < 0.45)
        price = _dec(rng, 10, 500, 4)
        ref = f"ord-{minute}"

        if not is_sell:
            qty = _dec(rng, 0.01, 3.0, 5)
            # Round execution price slightly to prove booked_notionals overrides qty * rounded_price.
            gross = (qty * price).quantize(Decimal("0.00000001"))
            rounded_price = (gross / qty).quantize(Decimal("0.01"))
            fee_in_base = rng.random() < 0.5
            if fee_in_base:
                fee = (qty * _dec(rng, 0.0, 0.005, 5)).quantize(Decimal("0.00000001"))
                if fee >= qty:
                    fee = Decimal(0)
                fee_ccy = "BTC"
                quote_delta = -gross
                base_delta = qty - fee
                total_quote_out += gross
            else:
                rate = _dec(rng, -0.001, 0.005, 5) if allow_rebates else _dec(rng, 0.0, 0.005, 5)
                fee = (gross * rate).quantize(Decimal("0.00000001"))
                fee_ccy = "USDT"
                quote_delta = -gross - fee
                base_delta = qty
                total_quote_out += gross + fee
            if quote_bal + quote_delta < 0:
                continue
            quote_bal += quote_delta
            base_bal += base_delta
            orders.append({"ref": ref, "side": "BUY", "status": "FILLED", "qty": str(qty),
                           "price": str(rounded_price), "fee": str(fee), "fee_ccy": fee_ccy, "fill_time": at})
            postings.append({"ref": ref, "ccy": "USDT", "kind": "buy", "amount": str(-gross)})
            postings.append({"ref": ref, "ccy": "BTC", "kind": "buy", "amount": str(qty)})
            if fee:
                postings.append({"ref": ref, "ccy": fee_ccy, "kind": "fee", "amount": str(-fee)})
        else:
            fee_in_base = allow_base_sell_fee and (rng.random() < 0.35)
            close_all = rng.random() < 0.35
            if fee_in_base:
                if close_all:
                    fee = (base_bal * Decimal("0.001")).quantize(Decimal("0.00000001"))
                    qty = base_bal - fee
                    if qty <= 0:
                        continue
                else:
                    max_qty = base_bal * Decimal("0.9")
                    qty = min(max_qty, _dec(rng, 0.0001, float(max_qty), 5))
                    fee = (qty * Decimal("0.001")).quantize(Decimal("0.00000001"))
                    if qty <= 0 or qty + fee > base_bal:
                        continue
                gross = (qty * price).quantize(Decimal("0.00000001"))
                rounded_price = (gross / qty).quantize(Decimal("0.01"))
                fee_ccy = "BTC"
                base_bal -= qty + fee
                quote_bal += gross
                total_quote_in += gross
            else:
                qty = base_bal if close_all else min(base_bal, _dec(rng, 0.0001, float(base_bal), 5))
                if qty <= 0:
                    continue
                gross = (qty * price).quantize(Decimal("0.00000001"))
                rounded_price = (gross / qty).quantize(Decimal("0.01"))
                rate = _dec(rng, -0.001, 0.005, 5) if allow_rebates else _dec(rng, 0.0, 0.005, 5)
                fee = (gross * rate).quantize(Decimal("0.00000001"))
                fee_ccy = "USDT"
                base_bal -= qty
                quote_bal += gross - fee
                total_quote_in += gross - fee
            orders.append({"ref": ref, "side": "SELL", "status": "FILLED", "qty": str(qty),
                           "price": str(rounded_price), "fee": str(fee), "fee_ccy": fee_ccy, "fill_time": at})
            postings.append({"ref": ref, "ccy": "USDT", "kind": "sell", "amount": str(gross)})
            postings.append({"ref": ref, "ccy": "BTC", "kind": "sell", "amount": str(-qty)})
            if fee:
                postings.append({"ref": ref, "ccy": fee_ccy, "kind": "fee", "amount": str(-fee)})

    return {
        "start_quote": start_quote,
        "end_quote": quote_bal,
        "end_base": base_bal,
        "total_quote_out": total_quote_out,
        "total_quote_in": total_quote_in,
        "orders": orders,
        "postings": postings,
    }


@pytest.mark.parametrize("seed", range(8))
def test_independent_oracle_conserves_base_quote_and_cost_across_fees_and_rebates(seed):
    """F001, F002, F003, F004, F008: exact conservation across 400 randomized sequences."""
    rng = random.Random(20261121 + seed)
    for _ in range(50):
        case = _generate_case(rng)
        ledger = trade_ledger(case["orders"], "BTC", quote="USDT", postings=case["postings"])
        open_qty = Decimal(ledger["open"]["quantity"])
        open_cost = Decimal(ledger["open"]["cost"])
        closed_cost = sum((Decimal(t["cost"]) for t in ledger["trades"]), Decimal(0))
        closed_proceeds = sum((Decimal(t["proceeds"]) for t in ledger["trades"]), Decimal(0))
        realized_fifo = sum((Decimal(t["pnl"]) for t in ledger["trades"]), Decimal(0))
        realized_avg = sum((Decimal(t["average_cost_pnl"]) for t in ledger["trades"]), Decimal(0))

        # Exact base balance conservation against double-entry postings oracle.
        posted_base = sum((Decimal(p["amount"]) for p in case["postings"] if p["ccy"] == "BTC"), Decimal(0))
        posted_quote = case["start_quote"] + sum(
            (Decimal(p["amount"]) for p in case["postings"] if p["ccy"] == "USDT"), Decimal(0)
        )
        assert open_qty == case["end_base"] == posted_base
        assert posted_quote == case["end_quote"]
        assert closed_proceeds == case["total_quote_in"]
        assert abs((closed_cost + open_cost) - case["total_quote_out"]) < Decimal("1e-20")

        # Cash-flow conservation identity: end_quote - start_quote == realized_pnl - open_cost.
        cash_delta = case["end_quote"] - case["start_quote"]
        assert abs(cash_delta - (realized_fifo - open_cost)) < Decimal("1e-20")

        # When completely flat, FIFO and average-cost realized P&L must match identically.
        if open_qty == 0:
            assert open_cost == 0
            assert abs(realized_fifo - realized_avg) < Decimal("1e-18")
            assert abs(cash_delta - realized_fifo) < Decimal("1e-18")


@pytest.mark.parametrize("caller_prec", [12, 28, 50])
def test_trade_ledger_is_invariant_to_caller_decimal_context(caller_prec):
    """F002/F008: caller Decimal precision cannot split dust or alter realized FIFO P&L."""
    rng = random.Random(999)
    case = _generate_case(rng)
    baseline = trade_ledger(case["orders"], "BTC", quote="USDT", postings=case["postings"])
    with localcontext() as ctx:
        ctx.prec = caller_prec
        observed = trade_ledger(case["orders"], "BTC", quote="USDT", postings=case["postings"])
    assert observed == baseline


def test_modern_postings_fail_closed_on_missing_duplicate_wrong_sign_or_nan():
    """F005: modern filled receipts cannot reconcile without unique, correctly signed gross quote postings."""
    order_buy = {"ref": "b1", "side": "BUY", "status": "FILLED", "qty": "1", "price": "100",
                 "fee": "0", "fee_ccy": "USDT", "fill_time": iso(START)}
    order_sell = {"ref": "s1", "side": "SELL", "status": "FILLED", "qty": "1", "price": "110",
                  "fee": "0", "fee_ccy": "USDT", "fill_time": iso(START + timedelta(minutes=5))}

    with pytest.raises(ValueError, match="missing its gross quote posting"):
        booked_notionals([order_buy], "USDT", [])

    with pytest.raises(ValueError, match="invalid or duplicate gross quote posting"):
        booked_notionals([order_buy], "USDT", [
            {"ref": "b1", "ccy": "USDT", "kind": "buy", "amount": "-100"},
            {"ref": "b1", "ccy": "USDT", "kind": "buy", "amount": "-100"},
        ])

    with pytest.raises(ValueError, match="invalid or duplicate gross quote posting"):
        booked_notionals([order_buy], "USDT", [{"ref": "b1", "ccy": "USDT", "kind": "buy", "amount": "100"}])

    with pytest.raises(ValueError, match="invalid or duplicate gross quote posting"):
        booked_notionals([order_sell], "USDT", [{"ref": "s1", "ccy": "USDT", "kind": "sell", "amount": "-110"}])

    with pytest.raises(ValueError, match="invalid or duplicate gross quote posting"):
        booked_notionals([order_buy], "USDT", [{"ref": "b1", "ccy": "USDT", "kind": "buy", "amount": "NaN"}])

    with pytest.raises(ValueError, match="exceeds the quantity bought earlier"):
        trade_ledger([order_buy, {**order_sell, "qty": "1", "fee": "0.1", "fee_ccy": "BTC"}], "BTC", quote="USDT",
                     postings=[{"ref": "b1", "ccy": "USDT", "kind": "buy", "amount": "-100"},
                               {"ref": "s1", "ccy": "USDT", "kind": "sell", "amount": "110"}])


def test_legacy_receipts_without_postings_keep_fallback_while_corrupt_modern_fails():
    """F006: genuine pre-posting archived receipts remain readable; mutated modern receipts fail closed."""
    orders = [
        {"ref": "b1", "side": "BUY", "status": "FILLED", "qty": "2", "price": "50",
         "fee": "0", "fee_ccy": "BTC", "fill_time": iso(START)},
        {"ref": "s1", "side": "SELL", "status": "FILLED", "qty": "2", "price": "60",
         "fee": "0", "fee_ccy": "USDT", "fill_time": iso(START + timedelta(minutes=10))},
    ]
    legacy = trade_ledger(orders, "BTC", quote="USDT", postings=None)
    assert Decimal(legacy["trades"][0]["pnl"]) == Decimal("20")
    assert Decimal(legacy["open"]["quantity"]) == 0

    with pytest.raises(ValueError, match="missing its gross quote posting"):
        trade_ledger(orders, "BTC", quote="USDT", postings=[{"ref": "b1", "ccy": "USDT", "kind": "buy", "amount": "-100"}])


def test_standalone_and_single_market_portfolio_reconcile_on_identical_fixture(tmp_path):
    """F012 & F009: one-active-market portfolio and standalone paper conserve exact cash, inventory, and postings."""
    symbol = "BTCUSDT"
    idle = "ETHUSDT"
    db = market_db(tmp_path, quote_history(n=120, turn=1, sym=symbol))
    spec = {"stepSize": 8, "minQty": "0.00000001", "minNotional": "1"}
    db.upsert_instrument(InstrumentId.wallex(symbol), {}, spec, "test", START)
    db.upsert_instrument(InstrumentId.wallex(idle, "ETH", "USDT"), {}, spec, "test", START)
    end = START + timedelta(minutes=30)
    cost = CostModel(fee_rate=Decimal("0.001"), max_fraction=Decimal("0.25"))
    params = {"fast": 2, "slow": 3, "position_model": "inventory/1"}
    try:
        solo = paper(db, symbol, START, end, resolution="1min", cash=Decimal(1000), cost=cost, params=params)
        multi = portfolio(db, [symbol, idle], START, end, resolution="1min", cash=Decimal(1000), cost=cost, params=params)
        solo_res = solo["result"]
        multi_res = multi["result"]
        btc_mkt = multi_res["markets"][symbol]
        eth_mkt = multi_res["markets"][idle]

        # Idle market never fills; active market fills identically to standalone on the same quote stream.
        assert eth_mkt["fills"] == 0 and Decimal(eth_mkt["holding"]) == 0
        assert solo_res["fills"] == btc_mkt["fills"] > 0

        # Exact double-entry conservation holds on both standalone and shared-cash portfolio postings.
        for res in (solo_res, multi_res):
            posted_usdt = Decimal(res["start_cash"]) + sum(
                (Decimal(p["amount"]) for p in res["postings"] if p["ccy"] == "USDT"), Decimal(0)
            )
            posted_btc = sum((Decimal(p["amount"]) for p in res["postings"] if p["ccy"] == "BTC"), Decimal(0))
            assert posted_usdt == Decimal(res["balances"]["USDT"])
            assert posted_btc == Decimal(res["balances"]["BTC"])

        # Recomputing trade_ledger from portfolio postings reproduces the portfolio summary's realized P&L exactly.
        btc_postings = [p for p in multi_res["postings"] if p["ref"].startswith(f"{symbol}#")]
        rebuilt = trade_ledger(btc_mkt["orders"], "BTC", quote="USDT", postings=btc_postings)
        rebuilt_pnl = sum((Decimal(t["pnl"]) for t in rebuilt["trades"]), Decimal(0))
        assert rebuilt_pnl == Decimal(btc_mkt["realized_pnl"])
        assert Decimal(rebuilt["open"]["quantity"]) == Decimal(btc_mkt["holding"])
        solo_perf = performance(solo)
        assert Decimal(solo_perf["trades"]["open_position"]["quantity"]) == Decimal(solo_res["balances"]["BTC"])
    finally:
        db.c.close()
