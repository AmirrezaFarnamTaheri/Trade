"""Price pre-sized spot/OTC routes at the decision cutoff and replay later fills."""
from datetime import timedelta
from decimal import Decimal, localcontext

from ..domain.bars import qualified
from ..domain.market_models import decimal, fields, rate
from ..domain.model import iso
from ..domain.otc import _asset
from ..domain.rules import is_closed
from ..domain.sim import CashBook, CostModel, market_order
from ..domain.strategy import digest
from .portfolio_otc_route import _leg


def mixed_routes(value):
    if type(value) is not list or not 1 <= len(value) <= 32:
        raise ValueError("mixed_routes must contain 1..32 candidates")
    routes = [MixedRoute(row) for row in value]
    if len({route.key for route in routes}) != len(routes):
        raise ValueError("duplicate mixed conversion route")
    return routes


class MixedRoute:
    def __init__(self, row):
        fields(row, "otc spot first max_source")
        self.key = digest(row)
        self.otc = _leg(row["otc"])
        spot = row["spot"]
        fields(spot, "base quote_asset side base_quantity fee_rate wait_seconds")
        self.base = _asset(spot["base"])
        quote = _asset(spot["quote_asset"])
        self.symbol = self.base + quote
        self.spot = {**spot, "symbol": self.symbol}
        self.reserve = decimal(row["max_source"], positive=True)
        self.quantity = decimal(spot["base_quantity"], positive=True)
        self.fee = rate(spot["fee_rate"])
        seconds = spot["wait_seconds"]
        if type(seconds) is not int or not 1 <= seconds <= 60:
            raise ValueError("mixed spot wait_seconds must be 1..60")
        self.wait = timedelta(seconds=seconds)
        if self.base in ("TMN", "USDT") or self.otc["base"] != self.base:
            raise ValueError("mixed route requires one noncash intermediate asset")
        self.otc_first = row["first"] == "OTC"
        expected = ("SELL", "BUY") if self.otc_first else ("BUY", "SELL")
        if row["first"] not in ("SPOT", "OTC") or (spot["side"], self.otc["request"]["side"]) != expected:
            raise ValueError("mixed route must buy then sell the intermediate asset")
        if {quote, self.otc["quote_asset"]} != {"TMN", "USDT"}:
            raise ValueError("mixed route must exchange TMN and USDT")
        self.source, self.destination = (self.otc["quote_asset"], quote) if self.otc_first else (quote, self.otc["quote_asset"])
        self.side = "BUY" if self.source == "TMN" else "SELL"
        with localcontext() as ctx:
            ctx.prec = 400
            if self.otc_first:
                if self.reserve != self.otc["debit"] or self.quantity != self.otc["gross"] * (1 - self.otc["fee"]):
                    raise ValueError("mixed OTC-first amounts must use exact source and intermediate proceeds")
            elif self.otc["debit"] != self.quantity * (1 - self.fee):
                raise ValueError("mixed spot-first amounts must use exact net intermediate proceeds")

    def candidate(self, portal, rules_for, at, side, quantity, cash, used, latency, end, participation):
        if side != self.side or self.reserve > cash or self.otc["key"] in used or self.otc["received"] >= at:
            return None
        if side == "SELL" and self.reserve > quantity:
            return None
        first = at + latency
        otc_at = first if self.otc_first else first + self.wait + max(latency, timedelta(microseconds=1))
        spot_at = first + self.otc["delay"] + latency if self.otc_first else first
        settle = max(spot_at + self.wait, otc_at + self.otc["delay"])
        if otc_at >= self.otc["expiry"] or settle >= end:
            return None
        estimate = self._estimate(portal, rules_for, at, participation)
        if estimate is None:
            return None
        credit, gross, _ = estimate
        if side == "BUY" and gross > quantity:
            return None
        with localcontext() as ctx:
            ctx.prec = 400
            score = self.reserve / credit if side == "BUY" else -credit / self.reserve
        return score, self.key, (otc_at, spot_at, settle, estimate, quantity)

    def _estimate(self, portal, rules_for, at, participation):
        inst = portal.instrument(self.symbol)
        if (inst.base, inst.quote) != (self.base, self.spot["quote_asset"]):
            raise ValueError("mixed spot symbol does not match the recorded asset units")
        top = None
        for receipt in portal.iter_tops(self.symbol, at - timedelta(seconds=120), at):
            top = receipt
        rules = rules_for(at)
        if top is None or not qualified(top) or "CLOSED" in top.flags or is_closed(rules, inst, at):
            return None
        spot_side = self.spot["side"]
        source = self.base if self.otc_first else self.source
        available = self.quantity if self.otc_first else self.reserve
        cost = CostModel(fee_rate=self.fee, latency=timedelta(0), max_participation=participation)
        book = CashBook({source: available})
        with localcontext() as ctx:
            ctx.prec = 400
            fill = market_order(book, inst, spot_side, Decimal(1), top.ts_avail,
                                top.bid if self.otc_first else top.ask, [top], 0, cost,
                                portal.spec_at(self.symbol, at), rules, {}, "indicative", max_qty=self.quantity)
            if fill["status"] != "FILLED" or Decimal(fill["qty"]) != self.quantity:
                return None
            credit = book.get(self.destination) if self.otc_first else self.otc["gross"] * (1 - self.otc["fee"])
            gross = self.quantity * top.bid if self.otc_first else self.otc["gross"]
            evidence = {"at": iso(top.ts_avail), "bid": str(top.bid), "ask": str(top.ask),
                        "bid_qty": str(top.bid_qty), "ask_qty": str(top.ask_qty)}
            return (credit, gross, evidence) if credit > 0 else None

    def order(self, at, times):
        otc_at, spot_at, settle, (credit, gross, indicative_quote), cap = times
        leg = self.otc
        otc = {"base": self.base, "quote_asset": leg["quote_asset"], "fee_rate": str(leg["fee"]),
               "request": {**leg["request"], "decision_at": iso(at)}, "submit_at": iso(otc_at),
               "modeled_settle_at": iso(otc_at + leg["delay"])}
        spot = {"spot": {"symbol": self.symbol, "side": self.spot["side"], "base_quantity": self.spot["base_quantity"],
                         "fee_rate": str(self.fee), "submit_at": iso(spot_at), "settle_by": iso(spot_at + self.wait)}}
        legs = [otc, spot] if self.otc_first else [spot, otc]
        return {"route_id": self.key, "mixed": True, "decision": at, "settle": settle, "side": self.side,
                "qty": gross if self.side == "BUY" else self.reserve, "debit": self.reserve,
                "source": self.source, "destination": self.destination, "intermediate": self.base,
                "credit": credit, "indicative_quote": indicative_quote, "legs": legs,
                "spot_receive_limit": cap if self.side == "BUY" else None}
