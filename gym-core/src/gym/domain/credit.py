"""Wallex trading-credit package terms and a causal paper replay of one package holding one asset.

Assumptions, not venue facts: the warning and liquidation limits apply to the whole sub-account value marked at the
bid; the daily fee is charged per completed day; a liquidation sells everything at the bid.
"""
import itertools
import re
from datetime import timedelta
from decimal import Decimal, localcontext

from .bars import qualified
from .market_models import decimal, rate
from .model import iso

MONEY = {"assurance": "assurance", "loan": "loan", "warning_limit": "warning_limit", "liquidity_limit": "liquidity_limit",
         "daily_fee": "daily_fee_after_discount", "final_fee": "final_fee_after_discount"}


def package_terms(row):
    """Validate one venue package row and keep only the fields the replay uses."""
    if type(row) is not dict or type(row.get("id")) is not int or type(row.get("expire_days")) is not int:
        raise ValueError("incomplete trading-credit package")
    if not 1 <= row["expire_days"] <= 366 or row.get("status") not in ("ACTIVE", "INACTIVE"):
        raise ValueError("invalid trading-credit package lifetime or status")
    if type(row.get("currency")) is not str or not re.fullmatch(r"[A-Z0-9]{2,12}", row["currency"]):
        raise ValueError("invalid trading-credit package currency")
    terms = {"id": row["id"], "currency": row["currency"], "status": row["status"], "expire_days": row["expire_days"]}
    for name, key in MONEY.items():
        if type(row.get(key)) is not str:
            raise ValueError(f"trading-credit {name} must be a decimal string")
        terms[name] = format(decimal(row[key], name, positive=name not in ("daily_fee", "final_fee")), "f")
    if not decimal(terms["liquidity_limit"]) < decimal(terms["warning_limit"]) < decimal(terms["assurance"]) + decimal(terms["loan"]):
        raise ValueError("trading-credit limits are not below the opening account value in order")
    return {key: terms[key] for key in ("id", "currency", "assurance", "loan", "warning_limit", "liquidity_limit",
                                        "status", "expire_days", "daily_fee", "final_fee")}


def replay_credit(terms, base, points, start, end, *, exposure, fee_rate):
    """Open the package at `start`, put `exposure` of the account into `base` at the first usable ask, and hold.

    `points` are (quote, market_closed) pairs in availability order inside [start, end).
    """
    if not isinstance(exposure, Decimal) or not exposure.is_finite() or not 0 < exposure <= 1:
        raise ValueError("exposure must be a share of the account above zero and at most one")
    fee_rate = rate(fee_rate, "fee_rate")
    if len(points) > 100000 or any(b[0].ts_avail < a[0].ts_avail for a, b in itertools.pairwise(points)):
        raise ValueError("credit quotes must be bounded and availability-ordered")
    if not start < end or any(not start <= top.ts_avail < end or type(closed) is not bool for top, closed in points):
        raise ValueError("invalid credit window, quote time or market state")
    with localcontext() as context:
        context.prec = 60
        return _replay(terms, base, points, start, end, exposure, fee_rate)


def _replay(terms, base, points, start, end, exposure, fee_rate):
    loan, collateral = decimal(terms["loan"]), decimal(terms["assurance"])
    warning, liquidation, daily = (decimal(terms[key]) for key in ("warning_limit", "liquidity_limit", "daily_fee"))
    expiry = start + timedelta(days=terms["expire_days"])
    cash, units, days = collateral + loan, Decimal(0), 0
    fees = {"package": Decimal(0), "trade_base": Decimal(0), "trade_quote": Decimal(0)}
    events, state, entered, warned, last, nonfills = [], "ENTRY_PENDING", False, False, None, {}

    def accrue(at):
        nonlocal cash, days
        elapsed = (min(at, expiry) - start) // timedelta(days=1)
        if elapsed > days:
            cash -= daily * (elapsed - days)
            fees["package"] += daily * (elapsed - days)
            days = elapsed

    def miss(reason):
        nonfills[reason] = nonfills.get(reason, 0) + 1

    for top, closed in points:
        accrue(top.ts_avail)
        if not qualified(top):
            miss("UNQUALIFIED_QUOTE")
            continue
        last = top
        if not entered:
            quantity = cash * exposure / top.ask
            if closed or top.ask_qty is None or top.ask_qty < quantity:
                miss("CLOSED_MARKET" if closed else "INSUFFICIENT_TOP_DEPTH")
                continue
            cash -= quantity * top.ask
            fees["trade_base"] += quantity * fee_rate
            units, entered, state = quantity * (1 - fee_rate), True, "OPEN"
            events.append({"at": iso(top.ts_avail), "action": "PAPER_OPEN", "price": str(top.ask), "base_quantity": str(units)})
        value = cash + units * top.bid
        reason = "LIQUIDATION" if value <= liquidation else "EXPIRY" if top.ts_avail >= expiry else None
        if reason is None:
            if value <= warning and not warned:
                warned = True
                events.append({"at": iso(top.ts_avail), "action": "WARNING_LEVEL", "account_value": str(value)})
            continue
        if closed or top.bid_qty is None or top.bid_qty < units:
            state = f"{reason}_UNSETTLED"
            action = "CLOSE_UNAVAILABLE" if closed else "CLOSE_DEPTH_UNAVAILABLE"
            if not events or events[-1]["action"] != action:
                events.append({"at": iso(top.ts_avail), "action": action, "reason": reason})
            continue
        notional = units * top.bid
        fees["trade_quote"] += notional * fee_rate
        cash, units, state = cash + notional * (1 - fee_rate), Decimal(0), f"CLOSED_{reason}"
        events.append({"at": iso(top.ts_avail), "action": f"PAPER_{reason}", "price": str(top.bid)})
        break
    if state == "OPEN":
        state = "OPEN_AT_WINDOW_END"
    value = cash + (units * last.bid if last is not None else 0)
    return {"state": state, "account_value": str(value), "trader_equity": str(value - loan),
            "trader_pnl": str(value - loan - collateral),
            "return_on_collateral_pct": str(((value - loan - collateral) / collateral * 100).quantize(Decimal("0.01"))),
            "base": base, "base_quantity": str(units), "last_bid": last and str(last.bid),
            "fee_days": days, "fees": {key: str(amount) for key, amount in fees.items()},
            "events": events, "nonfills": nonfills}
