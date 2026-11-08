"""Wallex credit-ratio rules and observed-quote paper positions; no order authority."""
import itertools
import re
from collections import Counter
from datetime import timedelta
from decimal import Decimal, localcontext

from .bars import qualified
from .market_models import decimal, rate
from .model import iso

RULE_FIELDS = ["symbol", "base", "quote", "min_risk_coef", "max_risk_coef", "risk_coef_step", "liquidity_margin", "max_age"]
REQUEST_FIELDS = {"market", "side", "collateral", "risk_coef", "open_price"}
OPTIONAL_FIELDS = {"stop_loss", "take_profit"}


def seconds(value, name):
    if type(value) is not int or not 0 < value <= 366 * 86400:
        raise ValueError(f"{name} must be positive integer seconds, at most 366 days")
    return value


def market_rule(row):
    if type(row) is not dict or not set(RULE_FIELDS) <= row.keys():
        raise ValueError("incomplete margin market rules")
    for key in ("symbol", "base", "quote"):
        if type(row[key]) is not str or not re.fullmatch(r"[A-Z0-9]{1,24}", row[key]):
            raise ValueError("invalid margin market identity")
    if row["quote"] not in ("TMN", "USDT") or row["symbol"] != row["base"] + row["quote"]:
        raise ValueError("margin requires a supported base/quote identity")
    lo, hi, step = (decimal(row[key], key, positive=True) for key in ("min_risk_coef", "max_risk_coef", "risk_coef_step"))
    if lo > hi or (hi - lo) / step > 10000:
        raise ValueError("invalid or excessive credit-ratio grid")
    rate(row["liquidity_margin"], "liquidity_margin")
    seconds(row["max_age"], "max_age")
    return {key: row[key] for key in RULE_FIELDS}


def margin_request(value, rule):
    market_rule(rule)
    if type(value) is not dict or not REQUEST_FIELDS <= value.keys() or value.keys() - REQUEST_FIELDS - OPTIONAL_FIELDS:
        raise ValueError("margin preview requires market, side, collateral, risk_coef, open_price and optional protection prices only")
    if value["market"] != rule["symbol"] or value["side"] not in ("long", "short"):
        raise ValueError("unknown margin market or side; use long/short")
    for name in ("collateral", "risk_coef", "open_price", *(key for key in OPTIONAL_FIELDS if key in value)):
        decimal(value[name], name, positive=True)
    with localcontext() as context:
        context.prec = 160
        risk = decimal(value["risk_coef"])
        lo, hi, step = (decimal(rule[key]) for key in ("min_risk_coef", "max_risk_coef", "risk_coef_step"))
        if not lo <= risk <= hi or (risk - lo) % step:
            raise ValueError("credit ratio is outside this market's minimum, maximum or step")
    price = decimal(value["open_price"])
    for key in OPTIONAL_FIELDS & value.keys():
        below = (value["side"] == "long") == (key == "stop_loss")
        level = decimal(value[key])
        if not (level < price if below else level > price):
            raise ValueError("protection price is on the wrong side of entry")
    return dict(value)


def preview_terms(value, request, rule):
    margin_request(request, rule)
    required = REQUEST_FIELDS | {"loan", "trade_fee", "open_fee", "extend_fee", "extend_time", "max_age", "call_price", "liquidity_price"}
    if type(value) is not dict or not required <= value.keys():
        raise ValueError("incomplete margin preview")
    for name in ("market", "side"):
        if value[name] != request[name]:
            raise ValueError("margin preview does not match its request")
    for name in ("risk_coef", "open_price"):
        if decimal(value[name], name, positive=True) != decimal(request[name]):
            raise ValueError("margin preview does not match its request")
    for key in ("collateral", "loan", "trade_fee", "open_fee", "extend_fee"):
        money = value[key]
        if type(money) is not dict or set(money) != {"currency", "value"} or money["currency"] not in (rule["base"], rule["quote"]):
            raise ValueError("unknown margin fee or debt currency")
        decimal(money["value"], key, positive=key in ("collateral", "loan"))
    if value["collateral"]["currency"] != rule["quote"] or decimal(value["collateral"]["value"]) != decimal(request["collateral"]):
        raise ValueError("margin collateral echo or currency mismatch")
    if value["loan"]["currency"] != rule["quote" if request["side"] == "long" else "base"]:
        raise ValueError("margin loan currency disagrees with side")
    for key in OPTIONAL_FIELDS:
        if (key in request and decimal(value.get(key), key, positive=True) != decimal(request[key])
                or key not in request and value.get(key) not in (None, "")):
            raise ValueError("margin protection echo mismatch")
    seconds(value["extend_time"], "extend_time")
    if seconds(value["max_age"], "max_age") > rule["max_age"]:
        raise ValueError("preview duration exceeds market maximum")
    price = decimal(value["open_price"], positive=True)
    call, liquidation = (decimal(value[key], key, positive=True) for key in ("call_price", "liquidity_price"))
    if not (liquidation < call < price if request["side"] == "long" else price < call < liquidation):
        raise ValueError("margin warning/liquidation levels are inconsistent with side")
    return {key: value[key] for key in required | (OPTIONAL_FIELDS & request.keys())}


def _depth_liquidation_mark(top, quantity, long, cash, debt_quote, fee_rate):
    """Price the *whole* open base exposure through a contemporaneous book side.

    Depth can be absent or unfillable; never extend the last level or assume
    a midpoint fill. The modeled exit fee is hypothetical until a real close.
    """
    status = "DEPTH_UNAVAILABLE"
    report = {"status": status, "required_base": str(quantity),
              "liquidation_value_quote": None, "mid_value_quote": None,
              "gap_to_mid_quote": None, "walked_notional_quote": None,
              "modeled_exit_fee_quote": None}
    if top.depth is None:
        return report
    if type(top.depth) not in (tuple, list) or len(top.depth) != 2:
        return {**report, "status": "INVALID_DEPTH"}
    levels = top.depth[0 if long else 1]
    if type(levels) not in (list, tuple) or not 1 <= len(levels) <= 50:
        return {**report, "status": "INVALID_DEPTH"}
    best = top.bid if long else top.ask
    best_qty = top.bid_qty if long else top.ask_qty
    previous, remaining, notional = None, quantity, Decimal(0)
    for level in levels:
        if (type(level) not in (list, tuple) or len(level) != 2
                or any(type(v) is not Decimal or not v.is_finite() or v <= 0 for v in level)):
            return {**report, "status": "INVALID_DEPTH"}
        price, size = level
        if ((previous is None and (price != best or size != best_qty))
                or (previous is not None and (price >= previous if long else price <= previous))):
            return {**report, "status": "INVALID_DEPTH"}
        take = min(size, remaining)
        notional += price * take
        remaining -= take
        previous = price
        if remaining <= 0:
            break
    if remaining > 0:
        return {**report, "status": "INSUFFICIENT_DEPTH"}
    midpoint = (top.bid + top.ask) / 2
    full_mid = midpoint * quantity
    if long:
        liquidation = cash + notional * (1 - fee_rate) - debt_quote
        mid_equity = cash + full_mid * (1 - fee_rate) - debt_quote
    else:
        liquidation = cash - notional * (1 + fee_rate) - debt_quote
        mid_equity = cash - full_mid * (1 + fee_rate) - debt_quote
    return {"status": "AVAILABLE", "required_base": str(quantity),
            "liquidation_value_quote": str(+liquidation), "mid_value_quote": str(+mid_equity),
            "gap_to_mid_quote": str(+(mid_equity - liquidation)),
            "walked_notional_quote": str(+notional),
            "modeled_exit_fee_quote": str(+(notional * fee_rate))}


def replay_margin(terms, rule, points, end, exit_fee_rate, holding_seconds, *, depth_valuation=False):
    """Conservative limit entry, bid/ask exits and initial venue-preview trigger levels."""
    if type(depth_valuation) is not bool:
        raise ValueError("depth_valuation requires a boolean flag")
    request = {key: terms[key] for key in REQUEST_FIELDS - {"collateral"}}
    request["collateral"] = terms["collateral"]["value"]
    request.update({key: terms[key] for key in OPTIONAL_FIELDS & terms.keys()})
    terms = preview_terms(terms, request, rule)
    fee_rate = rate(exit_fee_rate, "exit_fee_rate")
    if holding_seconds is not None:
        seconds(holding_seconds, "holding_seconds")
        if holding_seconds > terms["max_age"]:
            raise ValueError("holding time exceeds preview lifetime")
    if len(points) > 10000 or any(b[0].ts_avail < a[0].ts_avail for a, b in itertools.pairwise(points)):
        raise ValueError("margin quotes must be bounded and availability-ordered")
    if any(top.ts_avail >= end or top.symbol != rule["symbol"] or type(closed) is not bool for top, closed in points):
        raise ValueError("invalid margin quote identity, cutoff or market state")
    with localcontext() as context:
        context.prec = 160
        return _replay(terms, rule, points, end, fee_rate, holding_seconds, depth_valuation)


def _replay(terms, rule, points, end, fee_rate, holding_seconds, depth_valuation):
    long = terms["side"] == "long"
    price = decimal(terms["open_price"])
    loan = decimal(terms["loan"]["value"])
    quantity = loan / price if long else loan
    cash, units, debt_quote, debt_base = decimal(terms["collateral"]["value"]), Decimal(0), Decimal(0), Decimal(0)
    fees, events, entry, last, state, periods, close_reason = {}, [], None, None, "ENTRY_PENDING", 0, None
    nonfills, last_seen, last_closed = Counter(), None, False

    def charge(money, count=1):
        nonlocal cash, units, debt_base
        value, currency = decimal(money["value"]) * count, money["currency"]
        fees[currency] = fees.get(currency, Decimal(0)) + value
        if currency == rule["quote"]:
            cash -= value
        elif long:
            units -= value
            if units < 0:
                raise ValueError("base-denominated fees exceed modeled long holdings")
        else:
            debt_base += value

    def accrue(at):
        nonlocal periods
        elapsed = (at - entry["clock"]) // timedelta(seconds=terms["extend_time"])
        if elapsed > periods:
            charge(terms["extend_fee"], elapsed - periods)
            periods = elapsed

    for top, closed in points:
        if state.startswith("CLOSED"):
            break
        last_seen, last_closed = top, closed
        if entry is not None:
            accrue(top.ts_avail)
        if not qualified(top):
            nonfills["UNQUALIFIED_QUOTE"] += 1
            continue
        last = top
        if entry is None:
            available = top.ask_qty if long else top.bid_qty
            if closed or available is None or available < quantity or (top.ask > price if long else top.bid < price):
                reason = "CLOSED_MARKET" if closed else "INSUFFICIENT_TOP_DEPTH" if available is None or available < quantity else "LIMIT_NOT_REACHED"
                nonfills[reason] += 1
                continue
            units, debt_quote, debt_base = (quantity, loan, Decimal(0)) if long else (Decimal(0), Decimal(0), loan)
            if not long:
                cash += quantity * price
            charge(terms["trade_fee"])
            charge(terms["open_fee"])
            if cash < 0 or units < 0:
                raise ValueError("preview fees cannot be funded by modeled collateral")
            entry = {"at": iso(top.ts_avail), "clock": top.ts_avail, "price": str(price), "gross_base_quantity": str(quantity)}
            events.append({"at": iso(top.ts_avail), "action": "PAPER_OPEN", "price": str(price)})
            state = "OPEN"
        mark = top.bid if long else top.ask
        def crossed(level, below, mark=mark):
            return mark <= decimal(level) if below else mark >= decimal(level)
        liquidation = crossed(terms["liquidity_price"], long)
        warning = crossed(terms["call_price"], long)
        age = (top.ts_avail - entry["clock"]).total_seconds()
        reason = ("PAPER_LIQUIDATION" if liquidation else
                  "PAPER_STOP" if "stop_loss" in terms and crossed(terms["stop_loss"], long) else
                  "PAPER_TARGET" if "take_profit" in terms and crossed(terms["take_profit"], not long) else
                  "PAPER_EXPIRY" if age >= terms["max_age"] else
                  "PAPER_TIME_EXIT" if holding_seconds is not None and age >= holding_seconds else close_reason)
        if reason:
            close_reason, state = reason, "CLOSE_PENDING"
            if closed:
                action = "CLOSURE_LIQUIDATION_UNKNOWN" if liquidation else "CLOSE_UNAVAILABLE"
            elif (top.bid_qty if long else top.ask_qty) is None or (top.bid_qty if long else top.ask_qty) < (units if long else debt_base):
                action = "CLOSE_DEPTH_UNAVAILABLE"
            else:
                notional = units * top.bid if long else debt_base * top.ask
                exit_fee = notional * fee_rate
                fees[rule["quote"]] = fees.get(rule["quote"], Decimal(0)) + exit_fee
                cash += notional - exit_fee if long else -notional - exit_fee
                units, debt_base = Decimal(0), Decimal(0)
                if cash < 0:
                    debt_quote -= cash
                    cash = Decimal(0)
                repaid = min(cash, debt_quote)
                cash, debt_quote = cash - repaid, debt_quote - repaid
                state, action = ("CLOSED_WITH_DEBT" if debt_quote else "CLOSED"), reason
            events.append({"at": iso(top.ts_avail), "action": action, "price": str(mark)})
        elif warning:
            events.append({"at": iso(top.ts_avail), "action": "MARGIN_CALL_WARNING", "price": str(mark)})
    if entry and not state.startswith("CLOSED"):
        accrue(end)
        age = (end - entry["clock"]).total_seconds()
        if age >= terms["max_age"] or holding_seconds is not None and age >= holding_seconds:
            state = "CLOSE_PENDING"
    fresh = last is not None and last is last_seen and not last_closed and 0 <= (end - last.ts_avail).total_seconds() <= 30
    equity = cash - debt_quote if state.startswith("CLOSED") else cash + units * last.bid - debt_quote - debt_base * last.ask if fresh and entry else None
    liquidation = None
    if depth_valuation:
        if state.startswith("CLOSED"):
            liquidation = {"status": "SETTLED", "liquidation_value_quote": str(cash - debt_quote),
                           "mid_value_quote": None, "gap_to_mid_quote": None}
        elif not fresh or entry is None:
            liquidation = {"status": "UNAVAILABLE_FRESH_BOOK",
                           "liquidation_value_quote": None, "mid_value_quote": None,
                           "gap_to_mid_quote": None}
        else:
            liquidation = _depth_liquidation_mark(last, units if long else debt_base,
                                                  long, cash, debt_quote, fee_rate)
            equity = (Decimal(liquidation["liquidation_value_quote"])
                      if liquidation["status"] == "AVAILABLE" else None)
    return {"state": state, "entry": {key: value for key, value in entry.items() if key != "clock"} if entry else None,
            "cash_quote": str(cash), "base_units": str(units), "debt_quote": str(debt_quote), "debt_base": str(debt_base),
            "equity_quote": str(equity) if equity is not None else None,
            "extension_periods": periods, "fees_by_currency": {key: str(value) for key, value in fees.items()},
            "mark": {"at": iso(last.ts_avail) if last else None,
                     "status": "FRESH" if fresh else "STALE" if last else "UNAVAILABLE",
                     **({"liquidation": liquidation, "valuation_model": "depth-walk-liquidation/1"}
                        if depth_valuation else {})},
            "events": events, "nonfills": dict(nonfills)}
