"""Offline valuation of a supplied side-specific Wallex instant-trade quote."""
import re
from decimal import Decimal, localcontext

from .market_models import decimal, fields, instant, rate
from .strategy import digest


def quote_preview(value):
    fields(value, "symbol side base_quantity decision_at quote market")
    quote, market = value["quote"], value["market"]
    fields(quote, "symbol side received_at price price_expires_at")
    fields(market, "symbol received_at buyStatus sellStatus minQty minNotional maxNotional")
    symbol, side = value["symbol"], value["side"]
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9]{2,32}", symbol):
        raise ValueError("invalid OTC symbol")
    if symbol != market["symbol"] or symbol != quote["symbol"] or side not in ("BUY", "SELL") or side != quote["side"]:
        raise ValueError("market, quote and requested symbol and side must match")
    decision, received, expires = (instant(v) for v in (value["decision_at"], quote["received_at"], quote["price_expires_at"]))
    quantity = decimal(value["base_quantity"], "base_quantity", positive=True)
    price = decimal(quote["price"], "price", positive=True)
    minimum_qty = decimal(market["minQty"], "minQty")
    minimum, maximum = (decimal(market[k], k) for k in ("minNotional", "maxNotional"))
    if maximum < minimum:
        raise ValueError("inverted OTC notional limits")
    with localcontext() as ctx:
        ctx.prec = 132
        gross = quantity * price
    reasons = []
    if received > decision or instant(market["received_at"]) > decision:
        reasons.append("OBSERVATION_UNAVAILABLE")
    if decision >= expires:
        reasons.append("QUOTE_EXPIRED")
    if market["buyStatus" if side == "BUY" else "sellStatus"] != "ENABLE":
        reasons.append("SIDE_UNAVAILABLE")
    if quantity < minimum_qty or not minimum <= gross <= maximum:
        reasons.append("OUTSIDE_QUANTITY_OR_NOTIONAL_LIMITS")
    return {"symbol": symbol, "side": side, "status": "UNAVAILABLE" if reasons else "MODELED_QUOTE",
            "reasons": reasons, "gross_quote_amount": None if reasons else format(gross, "f"),
            "funded_authority": False, "settled": False}


def replay_route(value, *, spot=None, funding_cutoff=None):
    """Replay sequential conversions against one settled balance map."""
    fields(value, "opening_balances legs")
    opening, legs = value["opening_balances"], value["legs"]
    if (type(opening) is not dict or not 1 <= len(opening) <= 16
            or type(legs) is not list or not 1 <= len(legs) <= 8):
        raise ValueError("expected 1..16 balances and 1..8 OTC legs")
    balances = {_asset(code): decimal(amount, code) for code, amount in opening.items()}
    plans = [_route_leg(raw) if type(raw) is not dict or "spot" not in raw else _spot_plan(raw, spot) for raw in legs]
    if funding_cutoff is not None and any(plan["settle"] >= funding_cutoff for plan in plans):
        raise ValueError("funding legs must settle before the portfolio window")
    for previous, current in zip(plans, plans[1:]):
        if (previous["settle"] > current["send"] or previous["credit"] != current["debit"]
                or ("spot" in previous and previous["settle"] == current["send"])):
            raise ValueError("OTC legs must form a sequential currency route")
    events, postings = [], []
    quotas = {}
    for index, plan in enumerate(plans, 1):
        if "spot" in plan:
            event = plan["spot"](balances, postings, quotas, index)
            events.append(event)
            if event["status"] != "MODELED_SETTLEMENT":
                break
            continue
        preview = plan["preview"]
        reasons = list(preview["reasons"])
        debit, credit = plan["debit"], plan["credit"]
        balance = balances.get(debit, 0)
        with localcontext() as ctx:
            ctx.prec = 400
            quantity, consideration = plan["quantity"], plan["value"]
            spent, received = (consideration, quantity) if preview["side"] == "BUY" else (quantity, consideration)
            if not reasons and spent > balance:
                reasons.append("INSUFFICIENT_BALANCE")
            if reasons:
                events.append({"leg": index, "symbol": preview["symbol"], "status": "REFUSED", "reasons": reasons})
                break
            fee = received * plan["fee"]
            balances[debit] = balance - spent
            balances[credit] = balances.get(credit, 0) + received - fee
            for asset, delta, kind in ((debit, -spent, "trade"), (credit, received, "trade"), (credit, -fee, "fee")):
                postings.append({"leg": index, "asset": asset, "amount": format(delta, "f"), "kind": kind,
                                 "at": plan["settle"].isoformat()})
            events.append({"leg": index, "symbol": preview["symbol"], "status": "MODELED_SETTLEMENT"})
    completed = len(events) == len(plans) and events[-1]["status"] == "MODELED_SETTLEMENT"
    return {"schema": "otc-route-replay/1", "input_digest": digest(value), "status": "COMPLETED" if completed else "STOPPED",
            "legs": events, "postings": postings,
            "closing_balances": {code: format(amount, "f") for code, amount in sorted(balances.items())},
            "venue_settlement_verified": False, "funded_authority": False}


def _asset(code):
    if type(code) is not str or not re.fullmatch(r"[A-Z0-9]{1,16}", code):
        raise ValueError("invalid OTC asset code")
    return code


def _spot_plan(raw, spot):
    fields(raw, "spot")
    if spot is None:
        raise ValueError("spot execution requires a historical market store")
    return spot(raw["spot"])


def _route_leg(raw):
    fields(raw, "base quote_asset submit_at modeled_settle_at fee_rate request")
    base, quote_asset = raw["base"], raw["quote_asset"]
    _asset(base)
    _asset(quote_asset)
    request = raw["request"]
    original = quote_preview(request)
    if base == quote_asset or original["symbol"] != base + quote_asset:
        raise ValueError("OTC assets must match the instrument")
    send, settle = instant(raw["submit_at"]), instant(raw["modeled_settle_at"])
    if not instant(request["decision_at"]) <= send <= settle:
        raise ValueError("invalid OTC lifecycle times")
    preview = quote_preview({**request, "decision_at": raw["submit_at"]})
    preview["reasons"] = list(dict.fromkeys(original["reasons"] + preview["reasons"]))
    debit, credit = (quote_asset, base) if preview["side"] == "BUY" else (base, quote_asset)
    return {"debit": debit, "credit": credit, "send": send, "settle": settle, "preview": preview,
            "quantity": decimal(request["base_quantity"]), "value": Decimal(preview["gross_quote_amount"] or "0"),
            "fee": rate(raw["fee_rate"], "fee_rate")}
