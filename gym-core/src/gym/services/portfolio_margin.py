"""Reserved collateral and liabilities for an isolated paper margin overlay."""
from collections import deque
from datetime import timedelta
from decimal import Decimal, localcontext

from ..domain.bars import qualified
from ..domain.margin import protection_edits, replay_margin, seconds
from ..domain.market_models import decimal, fields, instant, rate
from ..domain.model import iso
from ..domain.rules import is_closed
from ..domain.strategy import digest
from .margin import load_receipt


def load_margin_plans(root, requests):
    if requests is None:
        return None
    if type(requests) is not list or not 1 <= len(requests) <= 8:
        raise ValueError("margin_positions requires 1..8 preview-backed positions")
    plans = []
    for request in requests:
        optional = [key for key in ("entry_breakout_ticks", "protection_edits") if isinstance(request, dict) and key in request]
        fields(request, " ".join(["preview_id exit_fee_rate holding_seconds", *optional]))
        if "protection_edits" in optional:
            protection_edits(request["protection_edits"])
        if "entry_breakout_ticks" in optional and (type(request["entry_breakout_ticks"]) is not int or not 2 <= request["entry_breakout_ticks"] <= 64):
            raise ValueError("entry_breakout_ticks must be an integer from 2 to 64")
        rate(request["exit_fee_rate"])
        if request["holding_seconds"] is not None:
            seconds(request["holding_seconds"], "holding_seconds")
        receipt = load_receipt(root, request["preview_id"], "PREVIEW")
        plans.append((request, receipt))
    if len({receipt["rule"]["symbol"] for _, receipt in plans}) != len(plans):
        raise ValueError("margin positions must use different market symbols")
    return sorted(plans, key=lambda pair: pair[0]["preview_id"])


def _breakout(points, length, side):
    history = deque(maxlen=length)
    for index, (top, closed) in enumerate(points):
        if closed or not qualified(top):
            history.clear()
            continue
        while history and top.ts_avail - history[0].ts_avail > timedelta(seconds=30):
            history.popleft()
        if history and history[-1].ts_avail == top.ts_avail:
            history[-1] = top
            continue
        if len(history) == length:
            crossed = (top.bid > max(q.ask for q in history) if side == "long" else
                       top.ask < min(q.bid for q in history))
            if crossed:
                return index, top.ts_avail
        history.append(top)
    return None


def _position(portal, rules_for, start, end, request, receipt, cost):
    rule, terms = receipt["rule"], receipt["terms"]
    symbol, currency = rule["symbol"], rule["quote"]
    if instant(receipt["received_at"]) > start:
        raise ValueError("margin terms must be known at the portfolio start")
    instrument = portal.instrument(symbol)
    if currency not in ("USDT", "TMN") or (instrument.base, instrument.quote) != (rule["base"], currency):
        raise ValueError("margin receipt instrument and currency must match the portfolio")
    if instrument.base in ("USDT", "TMN"):
        raise ValueError("margin positions cannot use the portfolio FX reference")
    points = []
    for top in portal.iter_tops(symbol, start, end):
        if len(points) >= 10000:
            raise ValueError("margin position exceeds 10000 recorded quotes")
        points.append((top, "CLOSED" in top.flags or is_closed(rules_for(top.ts_avail), instrument, top.ts_avail)))
    states = deque()

    def observe(at, state, cash, units, quote_debt, base_debt, mark):
        states.append((at, state, cash, units, quote_debt, base_debt, mark))

    active = points
    signal = entry_until = None
    if "entry_breakout_ticks" in request:
        active = []
        match = _breakout(points, request["entry_breakout_ticks"], terms["side"])
        if match:
            index, signal = match
            submit = signal + max(cost.latency, timedelta(microseconds=1))
            active = [(q, closed) for q, closed in points[index+1:] if q.ts_avail >= submit]
            entry_until = submit + cost.max_wait
    outcome = replay_margin(terms, rule, active, end, request["exit_fee_rate"], request["holding_seconds"],
                            observe=observe, entry_until=entry_until, edits=request.get("protection_edits"))
    if "entry_breakout_ticks" in request:
        outcome["entry_signal"] = {"model": "quote-breakout/1", "side": terms["side"],
                                   "at": iso(signal) if signal else None,
                                   "valid_until": iso(entry_until) if signal else None}
    collateral = decimal(terms["collateral"]["value"], positive=True)
    initial = (start, "ENTRY_PENDING", collateral, Decimal(0), Decimal(0), Decimal(0), collateral)
    # Bind all receipt content actually used by the margin model and the availability clock.
    evidence = digest([(iso(q.ts_avail), q.bid, q.ask, q.bid_qty, q.ask_qty, sorted(q.flags), closed)
                       for q, closed in points])
    return {"id": receipt["run_id"], "symbol": symbol, "currency": currency, "collateral": collateral,
            "states": states, "current": initial, "last_mark": collateral, "released": False, "release_at": None,
            "outcome": outcome, "data_digest": evidence}


class PortfolioMargin:
    def __init__(self, portal, rules_for, start, end, plans, book, cost):
        self.positions = [_position(portal, rules_for, start, end, request, receipt, cost) for request, receipt in plans]
        self.requests = [request for request, _ in plans]
        self.symbols = {position["symbol"] for position in self.positions}
        self.evidence = digest([position["data_digest"] for position in self.positions])
        with localcontext() as ctx:
            ctx.prec = 400
            for position in self.positions:
                currency, amount = position["currency"], position["collateral"]
                if amount > book.get(currency):
                    raise ValueError(f"insufficient {currency} cash for reserved margin collateral")
                book.post(start, currency, -amount, "margin_collateral", position["id"])

    def advance(self, at, book, *, terminal=False):
        for position in self.positions:
            states = position["states"]
            while states and (states[0][0] < at or terminal and states[0][0] == at):
                position["current"] = states.popleft()
                time, state, cash, _, _, _, mark = position["current"]
                if mark is not None:
                    position["last_mark"] = mark
                if position["released"]:
                    continue
                if state.startswith("CLOSED") or terminal and time == at and state == "ENTRY_PENDING":
                    with localcontext() as ctx:
                        ctx.prec = 400
                        book.post(at, position["currency"], cash, "margin_release", position["id"])
                    position["released"] = True
                    position["release_at"] = iso(at)

    def equity(self, currency):
        return sum((self._equity(p) for p in self.positions if p["currency"] == currency), Decimal(0))

    @staticmethod
    def _equity(position):
        quote_debt = position["current"][4]
        if position["released"]:
            return -quote_debt
        return position["last_mark"]

    def stale(self, at):
        return any(p["current"][1] in ("OPEN", "CLOSE_PENDING") and
                   (p["current"][6] is None or at - p["current"][0] > timedelta(seconds=30))
                   for p in self.positions)

    def deficit(self):
        return any(p["current"][1] == "CLOSED_WITH_DEBT" and p["current"][4] > 0 for p in self.positions)

    def checkpoint(self):
        return [(p["id"], p["current"], p["last_mark"], p["released"], p["release_at"]) for p in self.positions]

    def report(self):
        return [{key: position[key] for key in ("id", "symbol", "currency", "outcome", "data_digest", "release_at")}
                | {"reserved_collateral": str(position["collateral"])} for position in self.positions]
