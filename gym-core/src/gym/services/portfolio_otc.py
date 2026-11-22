"""Select and settle supplied USDTTMN OTC quotes for portfolio cash rebalancing."""
from datetime import timedelta
from decimal import Decimal, localcontext

from ..domain.market_models import decimal, fields, instant, rate
from ..domain.model import iso
from ..domain.otc import quote_preview
from .portfolio_otc_route import OTCRoute, quote_key


class PortfolioOTC:
    @classmethod
    def from_policy(cls, value):
        if {"otc_quotes", "otc_routes"} & value.keys():
            return cls(value.get("otc_quotes", []), routes=value.get("otc_routes", []))
        return None

    def __init__(self, quotes, *, routes=()):
        if type(quotes) is not list or len(quotes) > 256 or not (quotes or routes):
            raise ValueError("otc_quotes must contain 1..256 supplied quotes")
        if type(routes) not in (list, tuple) or len(routes) > 32:
            raise ValueError("otc_routes accepts at most 32 two-leg routes")
        self.routes = [OTCRoute(legs) for legs in routes]
        if len({route.key for route in self.routes}) != len(self.routes):
            raise ValueError("duplicate OTC route")
        self.quotes = []
        self.used = set()
        self.pending = None
        for row in quotes:
            fields(row, "quote market fee_rate max_base_quantity settlement_seconds")
            quote = row["quote"]
            fields(quote, "symbol side received_at price price_expires_at")
            if quote["symbol"] != "USDTTMN":
                raise ValueError("portfolio OTC quotes must be for USDTTMN")
            seconds = row["settlement_seconds"]
            if type(seconds) is not int or not 0 <= seconds <= 60:
                raise ValueError("OTC settlement_seconds must be 0..60")
            available = instant(quote["received_at"])
            expires = instant(quote["price_expires_at"])
            if expires <= available:
                raise ValueError("OTC expiry must follow quote receipt")
            request = {"symbol": "USDTTMN", "side": quote["side"], "base_quantity": row["max_base_quantity"],
                       "decision_at": iso(available), "quote": quote, "market": row["market"]}
            quote_preview(request)
            price = decimal(quote["price"])
            key = quote_key(quote)
            if any(existing[0] == key for existing in self.quotes):
                raise ValueError("duplicate OTC quote")
            self.quotes.append((key, available, row, request, price, rate(row["fee_rate"])))

    def select(self, at, side, quantity, *, cash, spot_price, spot_fee, latency, end):
        if self.pending is not None:
            return False
        with localcontext() as ctx:
            ctx.prec = 400
            reference = spot_price / (1 - spot_fee) if side == "BUY" else -spot_price * (1 - spot_fee)
        direct = self._direct_candidate(at, side, quantity, cash, reference, latency, end)
        routed = [(candidate, route) for route in self.routes
                  if (candidate := route.candidate(at, side, quantity, cash, self.used, latency, end)) is not None
                  and candidate[0] < (direct[0] if direct is not None else reference)]
        if routed:
            (_, _, times), route = min(routed, key=lambda item: item[0])
            self.pending = route.order(at, times)
            self.used.update((route.first["key"], route.last["key"]))
            return True
        if direct is None:
            return False
        _, key, settle, debit, received, fee, price, submit = direct
        self.used.add(key)
        self.pending = {"quote_id": key, "settle": settle, "debit": debit, "received": received,
                        "fee": fee, "price": price, "decision": at, "submit": submit, "side": side,
                        "qty": quantity}
        return True

    def _direct_candidate(self, at, side, quantity, cash, reference, latency, end):
        candidates = []
        for key, available, row, request, price, fee in self.quotes:
            if key in self.used or available >= at or request["side"] != side:
                continue
            if instant(row["market"]["received_at"]) >= at or quantity > decimal(row["max_base_quantity"]):
                continue
            submit = at + latency
            settle = submit + timedelta(seconds=row["settlement_seconds"])
            if settle >= end:
                continue
            preview = quote_preview({**request, "decision_at": iso(submit), "base_quantity": format(quantity, "f")})
            if preview["status"] != "MODELED_QUOTE":
                continue
            gross = Decimal(preview["gross_quote_amount"])
            debit, received = (gross, quantity) if side == "BUY" else (quantity, gross)
            if debit > cash:
                continue
            with localcontext() as ctx:
                ctx.prec = 400
                score = price / (1 - fee) if side == "BUY" else -price * (1 - fee)
            if score < reference:
                candidates.append((score, key, settle, debit, received, fee, price, submit))
        return min(candidates, default=None)

    def reserved(self, currency):
        order = self.pending
        if order and currency == ("TMN" if order["side"] == "BUY" else "USDT"):
            return order["debit"]
        return Decimal(0)

    def advance(self, at, book, events):
        order = self.pending
        if order is None or order["settle"] >= at:
            return
        if "route_id" in order:
            self._release_route(book, events, order)
            self.pending = None
            return
        side, settle = order["side"], order["settle"]
        debit, credit = ("TMN", "USDT") if side == "BUY" else ("USDT", "TMN")
        ref = f"otc-fx-rebalance/{len(events) + 1}"
        with localcontext() as ctx:
            ctx.prec = 400
            fee = order["received"] * order["fee"]
            book.post(settle, debit, -order["debit"], side.lower(), ref)
            book.post(settle, credit, order["received"], side.lower(), ref)
            book.post(settle, credit, -fee, "fee", ref)
        events.append({"ref": ref, "venue_model": "SUPPLIED_OTC_QUOTE", "quote_id": order["quote_id"],
                       "status": "FILLED", "side": side, "decision_time": iso(order["decision"]),
                       "submit_time": iso(order["submit"]), "fill_time": iso(settle), "qty": str(order["qty"]),
                       "price": str(order["price"]), "fee": str(fee), "fee_ccy": credit})
        self.pending = None

    @staticmethod
    def _release_route(book, events, order):
        ref = f"otc-fx-route/{len(events) + 1}"
        settle = order["settle"]
        with localcontext() as ctx:
            ctx.prec = 400
            for posting in order["report"]["postings"]:
                # The route is reserved as one conversion until downstream settlement.
                book.post(settle, posting["asset"], Decimal(posting["amount"]), posting["kind"], ref)
        events.append({"ref": ref, "venue_model": "SUPPLIED_OTC_ROUTE", "route_id": order["route_id"],
                       "status": "FILLED", "side": order["side"], "decision_time": iso(order["decision"]),
                       "submit_time": order["legs"][0]["submit_at"], "fill_time": iso(settle),
                       "qty": str(order["qty"]), "source_debit": str(order["debit"]),
                       "destination_credit": str(order["credit"]),
                       "legs": order["legs"], "leg_postings": order["report"]["postings"]})
