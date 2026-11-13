"""Paper replay of one venue stop order: activation on the last trade, then a market or limit fill."""
from datetime import timedelta
from decimal import Decimal

from ..domain.bars import qualified
from ..domain.market_models import rate
from ..domain.model import iso
from ..domain.sim import CashBook, CostModel, market_order

TYPES = ("STOP_MARKET", "STOP_LIMIT")
MAX_ROWS = 100000


def simulate_stop(instrument, reference_price, trades, quotes, spec, created, end, *, side, quantity, stop_price,
                  order_type, limit_price, fee_rate, store):
    """`reference_price` is the last trade before `created`; `trades` and `quotes` cover `[created, end)`.

    The venue activates the order itself, so no client latency applies after the activating trade.
    """
    if store not in ("live", "demo") or side not in ("BUY", "SELL") or order_type not in TYPES:
        raise ValueError("unsupported paper stop order")
    if (limit_price is None) != (order_type == "STOP_MARKET"):
        raise ValueError("a limit price belongs to STOP_LIMIT only")
    for name, value in (("quantity", quantity), ("stop_price", stop_price), ("reference_price", reference_price),
                        ("limit_price", limit_price)):
        if value is not None and (not isinstance(value, Decimal) or not value.is_finite() or value <= 0):
            raise ValueError("invalid exact " + name)
    if stop_price == reference_price:
        raise ValueError("the venue does not define a stop equal to the last trade")
    if not created < end or end - created > timedelta(days=1) or len(trades) > MAX_ROWS or len(quotes) > MAX_ROWS:
        raise ValueError("a stop replay needs a positive window of at most one day")
    falls = stop_price < reference_price
    out = {"schema": "paper-stop/1", "store": store, "symbol": instrument.symbol, "side": side, "type": order_type,
           "quantity": str(quantity), "stop_price": str(stop_price), "limit_price": limit_price and str(limit_price),
           "created": iso(created), "reference_trade_price": str(reference_price),
           "activates": "AT_OR_BELOW" if falls else "AT_OR_ABOVE", "status": "NOT_ACTIVATED", "activation": None,
           "fill": None, "unfilled_quantity": str(quantity), "slippage_from_stop_bps": None,
           "order_submitted": False, "funded_authority": False,
           "scope": "Recorded trades and quotes only. A fill takes at most the displayed touch size, or walks stored "
                    "depth when the quote has it. Venue trading rules and the queue for a resting limit are not modeled."}
    hit = next((x for x in trades if created <= x.ts_event < end
                and (x.price <= stop_price if falls else x.price >= stop_price)), None)
    if hit is None:
        return out
    out.update(status="ACTIVATED_UNFILLED", activation={"time": iso(hit.ts_event), "price": str(hit.price)})

    def reachable(top):
        if not qualified(top) or top.ts_avail < hit.ts_event:
            return False
        return limit_price is None or (top.ask <= limit_price if side == "BUY" else top.bid >= limit_price)

    top = next((x for x in quotes if reachable(x)), None)
    if top is None:
        return out
    walk = limit_price is None and top.depth is not None
    cost = CostModel(fee_rate=rate(str(fee_rate)), latency=timedelta(0), max_wait=end - hit.ts_event,
                     walk_depth=walk, max_participation=None if walk else Decimal(1))
    touch = top.ask if side == "BUY" else top.bid
    # Twice the touch notional: the quantity cap binds, not a rounding of cash divided by price.
    book = CashBook({instrument.quote: quantity * touch * 2} if side == "BUY" else {instrument.base: quantity})
    fill = market_order(book, instrument, side, Decimal(1), hit.ts_event, touch, [top], 0, cost, spec, [], {},
                        "paper-stop", max_qty=quantity)
    out["fill"] = {key: fill[key] for key in ("status", "reason", "fill_time", "qty", "price", "fee", "fee_ccy") if key in fill}
    if fill["status"] != "FILLED":
        return out
    filled, price = Decimal(fill["qty"]), Decimal(fill["price"])
    worse = stop_price - price if side == "SELL" else price - stop_price
    return dict(out, status="FILLED" if filled == quantity else "PARTIAL", unfilled_quantity=str(quantity - filled),
                slippage_from_stop_bps=str((worse / stop_price * 10000).quantize(Decimal("0.01"))))
