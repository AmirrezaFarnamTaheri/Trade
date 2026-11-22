"""Compare pre-sized two-leg OTC paper routes using cutoff-known receipts."""
from datetime import timedelta
from decimal import Decimal, localcontext

from ..domain.market_models import decimal, fields, instant, rate
from ..domain.model import iso
from ..domain.otc import _asset, quote_preview, replay_route
from ..domain.strategy import digest


def quote_key(quote):
    with localcontext() as ctx:
        ctx.prec = 64
        return digest((quote["symbol"], quote["side"], iso(instant(quote["received_at"])),
                       iso(instant(quote["price_expires_at"])), str(decimal(quote["price"]).normalize())))


def _leg(row):
    fields(row, "base quote_asset base_quantity quote market fee_rate settlement_seconds")
    base, quote_asset = _asset(row["base"]), _asset(row["quote_asset"])
    quote = row["quote"]
    fields(quote, "symbol side received_at price price_expires_at")
    fields(row["market"], "symbol received_at buyStatus sellStatus minQty minNotional maxNotional")
    if base == quote_asset or quote["symbol"] != base + quote_asset:
        raise ValueError("OTC assets must match the instrument")
    received = max(instant(quote["received_at"]), instant(row["market"]["received_at"]))
    expiry = instant(quote["price_expires_at"])
    if expiry <= received:
        raise ValueError("OTC route expiry must follow receipt of quote and terms")
    seconds = row["settlement_seconds"]
    if type(seconds) is not int or not 0 <= seconds <= 60:
        raise ValueError("OTC settlement_seconds must be 0..60")
    request = {"symbol": quote["symbol"], "side": quote["side"], "base_quantity": row["base_quantity"],
               "decision_at": iso(received), "quote": quote, "market": row["market"]}
    preview = quote_preview(request)
    if preview["status"] != "MODELED_QUOTE":
        raise ValueError("OTC route presizing violates the supplied market terms")
    quantity = decimal(row["base_quantity"])
    gross = Decimal(preview["gross_quote_amount"])
    fee = rate(row["fee_rate"])
    buy = quote["side"] == "BUY"
    return {"source": quote_asset if buy else base, "destination": base if buy else quote_asset,
            "debit": gross if buy else quantity, "gross": quantity if buy else gross, "fee": fee,
            "received": received, "expiry": expiry, "delay": timedelta(seconds=seconds),
            "key": quote_key(quote), "request": request, "base": base, "quote_asset": quote_asset}


class OTCRoute:
    def __init__(self, rows):
        if type(rows) is not list or len(rows) != 2:
            raise ValueError("each OTC route must contain exactly two legs")
        first, last = map(_leg, rows)
        self.first, self.last = first, last
        decimal(first["debit"], "route opening debit", positive=True)
        self.key = digest(rows)
        with localcontext() as ctx:
            ctx.prec = 400
            if (first["destination"] != last["source"] or first["destination"] in {"TMN", "USDT"}
                    or {first["source"], last["destination"]} != {"TMN", "USDT"}
                    or first["gross"] * (1 - first["fee"]) != last["debit"]):
                raise ValueError("OTC route must exchange TMN and USDT without intermediate residual")
            self.credit = last["gross"] * (1 - last["fee"])
            self.side = "BUY" if first["source"] == "TMN" else "SELL"
            self.size = last["gross"] if self.side == "BUY" else first["debit"]
            self.score = first["debit"] / self.credit if self.side == "BUY" else -self.credit / first["debit"]

    def candidate(self, at, side, quantity, cash, used, latency, end):
        first, last = self.first, self.last
        if (side != self.side or self.size > quantity or first["debit"] > cash
                or any(leg["key"] in used or leg["received"] >= at for leg in (first, last))):
            return None
        submit = at + latency
        first_settle = submit + first["delay"]
        # A later leg can send only after settlement plus its own submission latency.
        last_submit = first_settle + latency
        finish = last_submit + last["delay"]
        if submit >= first["expiry"] or last_submit >= last["expiry"] or finish >= end:
            return None
        return self.score, self.key, (submit, first_settle, last_submit, finish)

    def order(self, at, times):
        submit, first_settle, last_submit, finish = times
        first, last = self.first, self.last
        legs = [{"base": leg["base"], "quote_asset": leg["quote_asset"], "fee_rate": str(leg["fee"]),
                 "request": {**leg["request"], "decision_at": iso(at)}, "submit_at": iso(send),
                 "modeled_settle_at": iso(settle)}
                for leg, send, settle in ((first, submit, first_settle), (last, last_submit, finish))]
        report = replay_route({"opening_balances": {first["source"]: first["debit"]}, "legs": legs})
        if report["status"] != "COMPLETED":
            raise ArithmeticError("qualified OTC route failed to settle in replay")
        return {"route_id": self.key, "decision": at, "settle": finish, "side": self.side, "qty": self.size,
                "debit": first["debit"], "source": first["source"], "destination": last["destination"],
                "credit": self.credit, "legs": legs, "report": report}
