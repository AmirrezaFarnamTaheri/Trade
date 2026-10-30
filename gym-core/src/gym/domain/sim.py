"""Simulated market orders against observed quote sides, with a dual-asset CashBook (spec §5.3, §8.1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

from .bars import qualified
from .model import BookTop, InstrumentId, iso
from .rules import Rule, evaluate, tehran_day


@dataclass(frozen=True)
class CostModel:
    fee_rate: Decimal = Decimal("0.002")  # Wallex documentation example; the account's real rate is unconfirmed
    latency: timedelta = timedelta(milliseconds=500)
    max_wait: timedelta = timedelta(seconds=60)
    # Named assumption, not a venue fact: fees are charged in the asset received.
    fee_assumption: str = "fee-in-received-asset"

    def describe(self) -> dict:
        return {"fee_rate": str(self.fee_rate), "latency_ms": self.latency // timedelta(milliseconds=1),
                "max_wait_s": self.max_wait.total_seconds(), "fee_assumption": self.fee_assumption}


@dataclass(frozen=True)
class Spec:
    """Order constraints known at the decision; None means unknown and is not enforced."""
    qty_decimals: int | None = None
    min_qty: Decimal | None = None
    min_notional: Decimal | None = None


@dataclass
class CashBook:
    """Balances per actual currency. IRT and USDT are never netted; every change is a posting."""
    balances: dict[str, Decimal]
    postings: list[dict] = field(default_factory=list)

    def post(self, t: datetime, ccy: str, amount: Decimal, kind: str, ref: str):
        self.balances[ccy] = self.balances.get(ccy, Decimal(0)) + amount
        if self.balances[ccy] < 0:
            raise ArithmeticError(f"{ccy} balance would go negative ({kind} {ref})")
        self.postings.append({"t": iso(t), "ccy": ccy, "amount": str(amount), "kind": kind, "ref": ref})

    def get(self, ccy: str) -> Decimal:
        return self.balances.get(ccy, Decimal(0))

    def equity(self, inst: InstrumentId, bid: Decimal) -> Decimal:
        """Mark-to-venue-bid in the quote currency."""
        return self.get(inst.quote) + self.get(inst.base) * bid


def _floor(x: Decimal, decimals: int | None) -> Decimal:
    return x if decimals is None else x.quantize(Decimal(1).scaleb(-decimals), ROUND_DOWN)


def market_order(book: CashBook, inst: InstrumentId, side: str, fraction: Decimal, decision_time: datetime,
                 decision_quote: Decimal, tops: list[BookTop], start: int, cost: CostModel, spec: Spec,
                 rules: list[Rule], quota_used: dict, ref: str) -> dict:
    """Fill at the first qualified quote at or after decision + latency, or record a nonfill with its reason."""
    out = {"ref": ref, "side": side, "decision_time": iso(decision_time), "status": "NONFILL"}
    earliest, deadline = decision_time + cost.latency, decision_time + cost.max_wait
    top = next((x for x in tops[start:] if x.ts_avail >= earliest and qualified(x)), None)
    if top is None or top.ts_avail > deadline:
        return {**out, "reason": "NO_QUALIFIED_QUOTE"}
    t = top.ts_avail
    intent = "ENTRY" if side == "BUY" else "EXIT"
    day = tehran_day(t)
    v = evaluate(rules, inst, side, intent, t, live=False, used=quota_used.get(day, Decimal(0)))
    if not v.allowed:
        b = v.blockers[0]
        return {**out, "fill_time": iso(t), "reason": f"RULE:{b['rule_id']}", "rule": b}
    price = top.ask if side == "BUY" else top.bid
    mid = (top.bid + top.ask) / 2
    if side == "BUY":
        with localcontext() as ctx:
            ctx.rounding = ROUND_DOWN  # 28-digit division must never round the quantity up past the cash
            qty = _floor(book.get(inst.quote) * fraction / price, spec.qty_decimals)
        if v.quota_remaining is not None and qty > v.quota_remaining:
            qty = _floor(v.quota_remaining, spec.qty_decimals)  # resize the excess, never exceed the cap
            out["resized"] = "VenueQuota"
    else:
        qty = _floor(book.get(inst.base) * fraction, spec.qty_decimals)
    notional = qty * price
    if qty <= 0 or (spec.min_qty and qty < spec.min_qty) or (spec.min_notional and notional < spec.min_notional):
        return {**out, "fill_time": iso(t), "reason": "BELOW_MIN_NOTIONAL"}
    if side == "BUY":
        fee = qty * cost.fee_rate
        book.post(t, inst.quote, -notional, "buy", ref)
        book.post(t, inst.base, qty, "buy", ref)
        book.post(t, inst.base, -fee, "fee", ref)
        fee_value, spread, drift = fee * price, (price - mid) * qty, (price - decision_quote) * qty
        if inst.base in {r.params.get("asset") for r in rules if r.family == "VenueQuota"}:
            quota_used[day] = quota_used.get(day, Decimal(0)) + qty
    else:
        fee = notional * cost.fee_rate
        book.post(t, inst.base, -qty, "sell", ref)
        book.post(t, inst.quote, notional, "sell", ref)
        book.post(t, inst.quote, -fee, "fee", ref)
        fee_value, spread, drift = fee, (mid - price) * qty, (decision_quote - price) * qty
    return {**out, "status": "FILLED", "fill_time": iso(t), "qty": str(qty), "price": str(price), "fee": str(fee),
            "fee_ccy": inst.base if side == "BUY" else inst.quote,
            "costs": {"spread": spread, "fees": fee_value, "latency_drift": drift}}
