"""Simulated market orders against observed quote sides, with a dual-asset CashBook (spec §5.3, §8.1)."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

from .bars import qualified
from .market_models import decimal
from .model import BookTop, InstrumentId, iso
from .rules import Rule, evaluate, tehran_day


@dataclass(frozen=True)
class CostModel:
    fee_rate: Decimal = Decimal("0.001")  # operator account fee observed 2026-11-01 via /v1/account/fee (all 373 markets)
    latency: timedelta = timedelta(milliseconds=500)
    max_wait: timedelta = timedelta(seconds=60)
    # Named assumption, not a venue fact: fees are charged in the asset received.
    fee_assumption: str = "fee-in-received-asset"
    # Optional share of the displayed best-level size one fill may take; larger orders are resized down.
    max_participation: Decimal | None = None
    # Fill across the stored order-book levels at their volume-weighted price instead of only the best level.
    walk_depth: bool = False
    # Keep working a resized order on later quotes until it fills or max_wait passes.
    carry_remainder: bool = False
    # Sizing applied to every entry, whatever the strategy asked for: a hard cap on the cash fraction
    # (for example a fractional-Kelly figure), and volatility targeting from recent decision closes.
    max_fraction: Decimal | None = None
    vol_target: Decimal | None = None  # target standard deviation of per-bar returns of the position
    vol_lookback: int = 20
    # "limit": rest at the near touch after latency and fill when the queue ahead trades away or the
    # market trades through; unfilled at max_wait means no fill. Maker fee defaults to the taker fee.
    order_type: str = "market"
    maker_fee_rate: Decimal | None = None

    def __post_init__(self):
        if not self.fee_rate.is_finite() or not 0 <= self.fee_rate < 1:
            raise ValueError("fee must be finite and in [0,1)")
        if self.latency < timedelta(0) or self.max_wait < self.latency:
            raise ValueError("need 0 <= latency <= max_wait")
        if self.max_participation is not None and (not self.max_participation.is_finite() or not 0 < self.max_participation <= 1):
            raise ValueError("max participation must be in (0, 1]")
        for name in ("max_fraction", "vol_target"):
            value = getattr(self, name)
            if value is not None and (not value.is_finite() or not 0 < value <= 1):
                raise ValueError(f"{name.replace('_', ' ')} must be in (0, 1]")
        if type(self.vol_lookback) is not int or not 5 <= self.vol_lookback <= 500:
            raise ValueError("vol lookback must be 5..500 bars")
        if self.order_type not in ("market", "limit"):
            raise ValueError("order type must be market or limit")
        if self.maker_fee_rate is not None and (not self.maker_fee_rate.is_finite() or not 0 <= self.maker_fee_rate < 1):
            raise ValueError("maker fee must be finite and in [0,1)")

    def describe(self) -> dict:
        out = {"fee_rate": str(self.fee_rate), "latency_ms": self.latency // timedelta(milliseconds=1),
               "max_wait_s": self.max_wait.total_seconds(), "fee_assumption": self.fee_assumption}
        if self.max_participation is not None:  # absent by default so earlier run identities are unchanged
            out["max_participation"] = str(self.max_participation)
        if self.walk_depth:
            out["walk_depth"] = True
        if self.carry_remainder:
            out["carry_remainder"] = True
        if self.max_fraction is not None:
            out["max_fraction"] = str(self.max_fraction)
        if self.vol_target is not None:
            out["vol_target"], out["vol_lookback"] = str(self.vol_target), self.vol_lookback
        if self.order_type != "market":
            out["order_type"] = self.order_type
            out["maker_fee_rate"] = str(self.maker_fee)
            out["limit_fill_model"] = "queue-capacity/2"
        return out

    @property
    def maker_fee(self) -> Decimal:
        return self.fee_rate if self.maker_fee_rate is None else self.maker_fee_rate

    def size(self, fraction: Decimal, closes: list[Decimal]) -> Decimal:
        """Entry fraction after the sizing rules; until enough closes exist, volatility targeting buys nothing."""
        if self.vol_target is not None:
            recent = closes[-(self.vol_lookback + 1):]
            if len(recent) <= self.vol_lookback:
                return Decimal(0)
            returns = [b / a - 1 for a, b in itertools.pairwise(recent)]
            mean = sum(returns, Decimal(0)) / len(returns)
            vol = (sum(((r - mean) ** 2 for r in returns), Decimal(0)) / (len(returns) - 1)).sqrt()
            if vol > 0:
                fraction = min(fraction, (self.vol_target / vol).quantize(Decimal("0.000001"), ROUND_DOWN))
        return fraction if self.max_fraction is None else min(fraction, self.max_fraction)

    @classmethod
    def from_description(cls, d: dict) -> CostModel:
        if d.get("limit_fill_model", "queue-capacity/2") != "queue-capacity/2":
            raise ValueError("unsupported limit fill model")
        return cls(Decimal(d["fee_rate"]), timedelta(milliseconds=d["latency_ms"]), timedelta(seconds=d["max_wait_s"]),
                   max_participation=Decimal(d["max_participation"]) if "max_participation" in d else None,
                   walk_depth=d.get("walk_depth", False), carry_remainder=d.get("carry_remainder", False),
                   max_fraction=Decimal(d["max_fraction"]) if "max_fraction" in d else None,
                   vol_target=Decimal(d["vol_target"]) if "vol_target" in d else None, vol_lookback=d.get("vol_lookback", 20),
                   order_type=d.get("order_type", "market"),
                   maker_fee_rate=Decimal(d["maker_fee_rate"]) if "maker_fee_rate" in d else None)


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


def _walk(levels, qty: Decimal) -> Decimal:
    """Quote notional of taking `qty` best-first from observed levels; qty never exceeds their total."""
    notional, left = Decimal(0), qty
    for price, size in levels:
        take = min(size, left)
        notional += take * price
        left -= take
        if left <= 0:
            break
    return notional


def _budget_qty(levels, budget: Decimal) -> Decimal:
    """Base quantity whose walked notional is at most `budget` (rounded down)."""
    qty, left = Decimal(0), budget
    for price, size in levels:
        if left <= 0:
            break
        take = min(size, left / price)
        qty += take
        left -= take * price
    return qty


def sellable_quantity(quantity: Decimal, bid: Decimal, spec: Spec) -> Decimal:
    """Executable lot under known venue precision/minimums; never discards the actual balance."""
    quantity = _floor(quantity,spec.qty_decimals)
    return quantity if quantity>0 and (spec.min_qty is None or quantity>=spec.min_qty) and (spec.min_notional is None or quantity*bid>=spec.min_notional) else Decimal(0)


def market_order(book: CashBook, inst: InstrumentId, side: str, fraction: Decimal, decision_time: datetime,
                 decision_quote: Decimal, tops: list[BookTop], start: int, cost: CostModel, spec: Spec,
                 rules: list[Rule], quota_used: dict, ref: str, day_open: Decimal | None = None,
                 *, execution_limits=None, max_qty: Decimal | None = None, limit_price: Decimal | None = None) -> dict:
    """Fill at the first qualified quote at or after decision + latency, or record a nonfill with its reason."""
    out = {"ref": ref, "side": side, "decision_time": iso(decision_time), "status": "NONFILL"}
    if execution_limits is not None and (
            type(execution_limits) is not dict or set(execution_limits) != {"max_spread_bps", "participation_bps"}
            or type(execution_limits["max_spread_bps"]) is not int or not 1 <= execution_limits["max_spread_bps"] <= 1000
            or type(execution_limits["participation_bps"]) is not int or not 1 <= execution_limits["participation_bps"] <= 10000):
        raise ValueError("invalid paper execution limits")
    earliest, deadline = decision_time + cost.latency, decision_time + cost.max_wait
    top = next((x for x in tops[start:] if x.ts_avail >= earliest and qualified(x)), None)
    if top is None or top.ts_avail > deadline:
        return {**out, "reason": "NO_QUALIFIED_QUOTE"}
    t = top.ts_avail
    intent = "ENTRY" if side == "BUY" else "EXIT"
    day = tehran_day(t)
    mid = (top.bid + top.ask) / 2
    change = None if day_open is None else ((mid - day_open) / day_open * 100).quantize(Decimal("0.01"))
    v = evaluate(rules, inst, side, intent, t, live=False, used=quota_used.get(day, Decimal(0)),
                 day_change_pct=change)
    if not v.allowed:
        b = v.blockers[0]
        return {**out, "fill_time": iso(t), "reason": f"RULE:{b['rule_id']}", "rule": b}
    best = price = top.ask if side == "BUY" else top.bid
    if limit_price is not None:  # a resting order fills at its own price and pays the maker fee
        best = price = limit_price
    fee_rate = cost.maker_fee if limit_price is not None else cost.fee_rate
    levels = None
    if cost.walk_depth and limit_price is None:
        if top.depth is None:
            return {**out, "fill_time": iso(t), "reason": "DEPTH_UNAVAILABLE"}
        levels = top.depth[1] if side == "BUY" else top.depth[0]
    if execution_limits is not None and side == "BUY" and top.spread_bps > execution_limits["max_spread_bps"]:
        return {**out,"fill_time":iso(t),"reason":"ENTRY_SPREAD_LIMIT"}
    if side == "BUY":
        with localcontext() as ctx:
            ctx.rounding = ROUND_DOWN  # 28-digit division must never round the quantity up past the cash
            budget = book.get(inst.quote) * fraction
            qty = _floor(_budget_qty(levels, budget) if levels else budget / price, spec.qty_decimals)
        if v.quota_remaining is not None and qty > v.quota_remaining:
            qty = _floor(v.quota_remaining, spec.qty_decimals)  # resize the excess, never exceed the cap
            out["resized"] = "VenueQuota"
    else:
        qty = _floor(book.get(inst.base) * fraction, spec.qty_decimals)
    requested = qty
    if levels is not None:
        depth_total = sum((size for _, size in levels), Decimal(0))
        if qty > depth_total:
            qty, out["resized"] = _floor(depth_total, spec.qty_decimals), "ObservedDepth"
    if cost.max_participation is not None:
        shown = depth_total if levels is not None else top.ask_qty if side == "BUY" else top.bid_qty
        if shown is None or not shown.is_finite() or shown <= 0:
            return {**out, "fill_time": iso(t), "reason": "DISPLAYED_CAPACITY_UNAVAILABLE"}
        cap = _floor(shown * cost.max_participation, spec.qty_decimals)
        if qty > cap:
            qty, out["resized"] = cap, "DisplayedCapacity"
    if max_qty is not None and qty > max_qty:
        qty = _floor(max_qty, spec.qty_decimals)  # the unfilled rest of a resized order
    if qty < requested and out.get("resized") in ("ObservedDepth", "DisplayedCapacity"):
        out["requested_qty"] = str(requested if max_qty is None else min(requested, max_qty))
    notional = _walk(levels, qty) if levels and qty > 0 else qty * price
    if levels and qty > 0:
        price = notional / qty  # volume-weighted across the levels taken
    if qty <= 0 or (spec.min_qty and qty < spec.min_qty) or (spec.min_notional and notional < spec.min_notional):
        return {**out, "fill_time": iso(t), "reason": "BELOW_MIN_NOTIONAL"}
    if execution_limits is not None:
        available = top.ask_qty if side == "BUY" else top.bid_qty
        try:
            available = decimal(available,"displayed capacity",positive=True)
        except ValueError:
            return {**out,"fill_time":iso(t),"reason":"DISPLAYED_CAPACITY_UNAVAILABLE"}
        if qty > available * execution_limits["participation_bps"] / 10000:
            return {**out,"fill_time":iso(t),"reason":"DISPLAYED_CAPACITY_LIMIT"}
        if side == "BUY" and sellable_quantity(book.get(inst.base)+qty*(1-cost.fee_rate),top.bid,spec) == 0:
            return {**out,"fill_time":iso(t),"reason":"NET_HOLDING_BELOW_EXIT_MINIMUM"}
    if side == "BUY":
        fee = qty * fee_rate
        if (book.get(inst.base) + qty) - fee <= book.get(inst.base):
            return {**out, "fill_time": iso(t), "reason": "NET_BASE_ROUNDS_TO_ZERO"}
        book.post(t, inst.quote, -notional, "buy", ref)
        book.post(t, inst.base, qty, "buy", ref)
        book.post(t, inst.base, -fee, "fee", ref)
        # Spread is execution price against mid, so it includes walked depth; drift is the best-level move during latency.
        fee_value, spread, drift = fee * price, (price - mid) * qty, (best - decision_quote) * qty
        if inst.base in {r.params.get("asset") for r in rules if r.family == "VenueQuota"}:
            quota_used[day] = quota_used.get(day, Decimal(0)) + qty
    else:
        fee = notional * fee_rate
        book.post(t, inst.base, -qty, "sell", ref)
        book.post(t, inst.quote, notional, "sell", ref)
        book.post(t, inst.quote, -fee, "fee", ref)
        fee_value, spread, drift = fee, (mid - price) * qty, (decision_quote - best) * qty
    return {**out, "status": "FILLED", "fill_time": iso(t), "qty": str(qty), "price": str(price), "fee": str(fee),
            "fee_ccy": inst.base if side == "BUY" else inst.quote,
            "costs": {"spread": spread, "fees": fee_value, "latency_drift": drift}}
