"""Select and settle supplied USDTTMN OTC quotes for portfolio cash rebalancing."""
from datetime import timedelta
from decimal import Decimal, localcontext

from ..domain.market_models import decimal, fields, instant, rate
from ..domain.model import iso
from ..domain.otc import quote_preview
from ..domain.strategy import digest


class PortfolioOTC:
    def __init__(self, quotes):
        if type(quotes) is not list or not 1 <= len(quotes) <= 256:
            raise ValueError("otc_quotes must contain 1..256 supplied quotes")
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
            with localcontext() as ctx:
                ctx.prec = 64
                key = digest(("USDTTMN", quote["side"], iso(available), iso(expires), str(price.normalize())))
            if any(existing[0] == key for existing in self.quotes):
                raise ValueError("duplicate OTC quote")
            self.quotes.append((key, available, row, request, price, rate(row["fee_rate"])))

    def select(self, at, side, quantity, *, cash, spot_price, spot_fee, latency, end):
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
                reference = spot_price / (1 - spot_fee) if side == "BUY" else -spot_price * (1 - spot_fee)
            if score < reference:
                candidates.append((score, key, settle, debit, received, fee, price, submit))
        if not candidates:
            return False
        _, key, settle, debit, received, fee, price, submit = min(candidates)
        self.used.add(key)
        self.pending = {"quote_id": key, "settle": settle, "debit": debit, "received": received,
                        "fee": fee, "price": price, "decision": at, "submit": submit, "side": side,
                        "qty": quantity}
        return True

    def reserved(self, currency):
        order = self.pending
        if order and currency == ("TMN" if order["side"] == "BUY" else "USDT"):
            return order["debit"]
        return Decimal(0)

    def advance(self, at, book, events):
        order = self.pending
        if order is None or order["settle"] >= at:
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
