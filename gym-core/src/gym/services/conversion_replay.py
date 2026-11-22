"""Historical spot legs for the shared conversion replay ledger."""
from datetime import timedelta
from decimal import Decimal, localcontext

from ..domain.bars import qualified
from ..domain.market_models import decimal, fields, instant, rate
from ..domain.otc import replay_route
from ..domain.sim import CashBook, CostModel, market_order
from .data_portal import DataPortal
from .rules import RuleService


def replay_mixed_route(db, value, *, funding_cutoff=None):
    portal, rules = DataPortal(db), RuleService(db)
    return replay_route(value, spot=lambda leg: _plan(portal, rules, leg), funding_cutoff=funding_cutoff)


def _plan(portal, rules, leg):
    fields(leg, "symbol side base_quantity submit_at settle_by fee_rate")
    from ..domain.otc import _asset

    symbol, side = _asset(leg["symbol"]), leg["side"]
    if side not in ("BUY", "SELL"):
        raise ValueError("spot side must be BUY or SELL")
    inst = portal.instrument(symbol)
    submit, deadline = instant(leg["submit_at"]), instant(leg["settle_by"])
    if not submit <= deadline <= submit + timedelta(seconds=60):
        raise ValueError("spot settlement window must be within 60 seconds of submission")
    quantity = decimal(leg["base_quantity"], "base_quantity", positive=True)
    cost = CostModel(rate(leg["fee_rate"]), latency=timedelta(0), max_wait=deadline - submit,
                     max_participation=Decimal(1))

    def execute(balances, postings, quotas, index):
        top = next((q for q in portal.iter_tops(symbol, submit, deadline + timedelta(microseconds=1))
                    if qualified(q) and "CLOSED" not in q.flags), None)
        if top is None:
            return {"leg": index, "symbol": symbol, "status": "REFUSED", "reasons": ["NO_QUALIFIED_QUOTE"]}
        book = CashBook(balances)
        known_rules = rules.load(top.ts_avail)[1]
        with localcontext() as ctx:
            ctx.prec = 400
            fill = market_order(book, inst, side, Decimal(1), submit, top.ask if side == "BUY" else top.bid,
                                [top], 0, cost, portal.spec_at(symbol, top.ts_avail), known_rules,
                                quotas.setdefault(inst.base, {}), f"conversion#{index}", max_qty=quantity)
        for posting in book.postings:
            postings.append({"leg": index, "asset": posting["ccy"], "amount": posting["amount"],
                             "kind": posting["kind"], "at": posting["t"]})
        executed = Decimal(fill.get("qty", "0"))
        event = {"leg": index, "symbol": symbol, "filled_base_quantity": str(executed),
                 "receipt_at": top.ts_avail.isoformat(), "bid": str(top.bid), "ask": str(top.ask),
                 "bid_qty": str(top.bid_qty), "ask_qty": str(top.ask_qty)}
        if executed == quantity:
            return {**event, "status": "MODELED_SETTLEMENT"}
        return {**event, "status": "PARTIAL" if executed else "REFUSED",
                "reasons": [fill.get("reason", "UNFILLED_QUANTITY")]}

    debit, credit = (inst.quote, inst.base) if side == "BUY" else (inst.base, inst.quote)
    return {"debit": debit, "credit": credit, "send": submit, "settle": deadline, "spot": execute}
