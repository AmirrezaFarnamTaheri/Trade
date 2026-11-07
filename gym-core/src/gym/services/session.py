"""Incremental paper-session engine. No venue orders; replay and polling share this path."""
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

from ..domain.bars import BarSpec, CloseSubscriptions, qualified
from ..domain.market_models import decimal
from ..domain.model import iso, parse_ts
from ..domain.portfolio import portfolio_sizing
from ..domain.rules import closures, is_closed, session_period, tehran_day
from ..domain.sim import CashBook, market_order, sellable_quantity
from ..domain.strategy import Snapshot, digest

ENGINE_VERSION = "paper-session/8"


@dataclass
class PendingOrder:
    record: dict
    fraction: Decimal
    decision_time: datetime
    decision_price: Decimal
    stop_distance_bps: Decimal | None = None
    max_qty: Decimal | None = None  # set on the working remainder of a resized order
    limit: Decimal | None = None  # resting price of a limit order, once placed
    queue_ahead: Decimal | None = None
    checked: datetime | None = None


class PaperSession:
    def __init__(self, portal, rules_for, strategy, symbol, start, resolution, cash, cost, subscriptions=(), reference_symbol=None):
        if not cash.is_finite() or cash <= 0:
            raise ValueError("cash must be positive and finite")
        self.portal = portal
        self.rules_for = rules_for
        self.strategy = strategy
        self.symbol = symbol
        self.instrument = portal.instrument(symbol)
        self.cost = cost
        self.execution_limits = getattr(strategy,"execution_limits",None)
        self.track_positions = self.execution_limits is not None or getattr(strategy, "requires_position_context", False)
        if self.execution_limits is not None and cost.order_type == "limit":
            raise ValueError("compound strategies do not support limit orders; use market orders")
        if self.execution_limits is not None and cost.carry_remainder:
            raise ValueError("compound strategies do not support working order remainders")
        self.position_entry = self.position_stop = self.position_opened = self.position_id = None
        self.position_closed = True
        self.bar_spec = BarSpec(resolution, "MID")
        required = getattr(strategy, "required_resolutions", ())
        if any(BarSpec(r).step <= self.bar_spec.step for r in required):
            raise ValueError("confirmation resolution must be longer than the decision resolution")
        resolutions = tuple(dict.fromkeys((resolution, *subscriptions, *required)))
        self.reference_symbol = reference_symbol or getattr(strategy, "reference_symbol", None)
        if self.reference_symbol == symbol:
            raise ValueError("reference asset must differ from the traded asset")
        self.latest_bars = {}
        periods = {"session": self.session_of} if "session" in resolutions else {}
        self.closes = CloseSubscriptions(symbol, resolutions, periods)
        self.consolidator = self.closes.by_resolution[resolution]
        self.book = CashBook({self.instrument.quote: cash})
        self.allocation = None  # portfolio hook: rescales an entry fraction against shared cash
        self.decision_filter = None
        self.risk_budget = None
        self.limit_trades = []  # trade prints that decided limit fills; part of the data identity
        self.last_quote = None
        self.pending: PendingOrder | None = None
        self.cursor = start
        self.decisions = []
        self.rule_snapshots = {}
        self.orders = []
        self.curve = []
        self.quota = {}
        self.events = []
        self.bar_events = []
        self.skipped = []
        self.reopenings = []
        # ponytail: on-close subscriptions only; add event/schedule/regime clocks when a real strategy needs them.
        # ponytail: the band reference is the first observed mid of the Tehran day; switch to the venue's
        # published reference price once Wallex exposes one.
        self.day_open = {}
        self.state = "CONFIGURED"
        self.events.append({"state": self.state, "t": iso(start)})
        self.transition("WARMING_UP", start)
        self.running_at = None

    def session_of(self, t):
        return session_period(self.rules_for(t), self.instrument, t)

    def transition(self, state, at, reason=None):
        self.state = state
        self.events.append({"state": state, "t": iso(at), "reason": reason})

    def scan(self, at):
        closed_bars = self.closes.scan(at)
        for bar in closed_bars:
            self.bar_events.append({"t": iso(bar.avail), "resolution": bar.spec.resolution,
                                    "start": iso(bar.start), "close": str(bar.close)})
            if bar.spec != self.bar_spec:
                continue
            quote = self.last_quote if self.last_quote and bar.avail - self.last_quote.ts_avail <= timedelta(seconds=120) else None
            visible = {**self.latest_bars, **{b.spec.resolution: b for b in closed_bars if b.avail <= bar.avail}}
            context = tuple(b for r, b in sorted(visible.items()) if r != self.bar_spec.resolution)
            reference = None
            if self.reference_symbol:
                references = self.portal.tops(self.reference_symbol, bar.avail - timedelta(seconds=120),
                                              bar.avail + timedelta(microseconds=1))
                reference = next((q for q in reversed(references) if qualified(q)), None)
            execution = None
            if self.track_positions:
                quantity = self.book.get(self.instrument.base)
                tradable = sellable_quantity(quantity,quote.bid,self.portal.spec_at(self.symbol,bar.avail)) if quote else quantity
                holding = quantity>0 and (not self.position_closed or tradable>0)
                execution = {"equity":self.book.equity(self.instrument,quote.bid) if quote else None,
                    "position_qty":quantity,"tradable_qty":tradable,
                    "position_state":"OPEN" if holding else "DUST" if quantity>0 else "FLAT","fee_rate":self.cost.maker_fee if self.cost.order_type == "limit" else self.cost.fee_rate,
                    "bid_qty":quote.bid_qty if quote else None,
                    "ask_qty":quote.ask_qty if quote else None,
                    "entry_price":self.position_entry,
                    "stop_price":self.position_stop,
                    "entry_time":iso(self.position_opened),"position_id":self.position_id}
                for key,value in execution.items():
                    if isinstance(value,Decimal):
                        try:
                            execution[key] = format(decimal(value,key),"f")
                        except ValueError:
                            execution[key] = None
            snapshot = Snapshot(bar.avail, self.symbol, bar, quote and quote.bid, quote and quote.ask,
                                quote and quote.ts_avail, context, reference, execution)
            if execution is None:
                holding = bool(quote) and self.book.get(self.instrument.base)*quote.bid>self.book.equity(self.instrument,quote.bid)/100
            action, fraction, reasons, feature_hash = self.strategy.decide(snapshot, holding)
            if self.decision_filter is not None:
                action, fraction, reasons = self.decision_filter(action, fraction, reasons)
                if action in ("BUY_REQUEST", "SELL_REQUEST") and quote is None:
                    action, fraction, reasons = "ABSTAIN_NO_QUOTE", Decimal(0), (*reasons, "fresh quote required for portfolio order")
            if action == "BUY_REQUEST" and self.strategy.params.get("entry_risk_bps") and not self.pending:
                fraction, sizing = self.size_risk_entry(fraction, quote, bar.avail)
                self.strategy.feature_values["entry_sizing"] = sizing
                feature_hash = digest(self.strategy.feature_values)[:16]
                if fraction <= 0:
                    action, reasons = "ABSTAIN_RISK_SIZING", (sizing["status"],)
            if self.state == "WARMING_UP" and getattr(self.strategy,"ready",action not in ("ABSTAIN_WARMUP", "ABSTAIN_NO_REFERENCE")):
                self.running_at = bar.avail
                self.transition("RUNNING", bar.avail)
            decision = {"t": iso(bar.avail), "snapshot": snapshot.id, "close": str(bar.close), "action": action,
                   "reasons": list(reasons), "features": feature_hash, "bid": quote and str(quote.bid), "ask": quote and str(quote.ask),
                   "quote_time": quote and iso(quote.ts_avail)}
            decision["feature_values"] = self.strategy.feature_values
            if execution is not None:
                decision["execution_known"] = execution
                decision["execution_snapshot"] = digest([snapshot.id,execution])[:16]
            decision["balances_before"] = {k: str(v) for k, v in self.book.balances.items()}
            decision["bar_known"] = {"start": iso(bar.start), "end": iso(bar.end), "available_at": iso(bar.avail),
                                     "open": str(bar.open), "high": str(bar.high), "low": str(bar.low)}
            decision["context_known"] = [{"resolution": b.spec.resolution, "start": iso(b.start), "end": iso(b.end),
                "available_at": iso(b.avail), "open": str(b.open), "high": str(b.high), "low": str(b.low), "close": str(b.close)} for b in context]
            decision["reference_known"] = None if reference is None else {"symbol": reference.symbol,
                "available_at": iso(reference.ts_avail), "bid": str(reference.bid), "ask": str(reference.ask)}
            rules_known = [{"id": r.id, "family": r.family, "class": r.cls, "action": r.action,
                "scope": r.scope, "params": r.params, "effective_from": iso(r.effective_from),
                "effective_until": r.effective_until and iso(r.effective_until), "status": r.status,
                "disabled": r.disabled, "source": r.source, "last_confirmed_at": r.last_confirmed_at and iso(r.last_confirmed_at),
                "review_hours": r.review_hours, "exit_confirmed": r.exit_confirmed} for r in self.rules_for(bar.avail)]
            decision["rules_ref"] = digest(rules_known)
            self.rule_snapshots[decision["rules_ref"]] = rules_known
            if action in ("BUY_REQUEST", "SELL_REQUEST"):
                side = action.split("_")[0]
                if side == "SELL" and getattr(self.strategy, "requires_position_context", False) and self.pending and self.pending.record["side"] == "BUY":
                    self.pending.record.update(status="CANCELLED", reason="EXIT_CANCELS_WORKING_ENTRY")
                    self.pending = None
                if side == "BUY" and not self.pending and (self.cost.max_fraction is not None or self.cost.vol_target is not None):
                    fraction = self.cost.size(fraction, [Decimal(d["close"]) for d in self.decisions] + [bar.close])
                    decision["sized_fraction"] = str(fraction)
                if side == "BUY" and not self.pending and self.allocation is not None:
                    fraction = self.allocation(fraction)
                    decision["allocated_fraction"] = str(fraction)
                if self.pending:
                    decision["skipped"] = "PENDING_ORDER"
                elif ("sized_fraction" in decision or "allocated_fraction" in decision) and fraction <= 0:
                    decision["skipped"] = "SIZED_TO_ZERO"
                else:
                    ref = f"{self.symbol}#{len(self.orders) + 1}"
                    order = {"ref": ref, "side": side, "decision_time": iso(bar.avail), "status": "PENDING"}
                    self.orders.append(order)
                    stop_distance = None
                    if self.execution_limits is not None and side == "BUY":
                        stop_distance = Decimal(self.strategy.feature_values["stop_distance_bps"])
                        if not stop_distance.is_finite() or not 0<stop_distance<10000:
                            raise ValueError("invalid proposed paper stop distance")
                    self.pending = PendingOrder(order, fraction, bar.avail, quote.ask if side == "BUY" else quote.bid,stop_distance)
                    decision["order"] = ref
            self.decisions.append(decision)
            if quote:
                self.curve.append((iso(bar.avail), str(self.book.equity(self.instrument, quote.bid))))
            next_start = self.consolidator.period_of(at)[0]
            if next_start > bar.end:
                venue_closed = is_closed(self.rules_for(bar.end), self.instrument, bar.end)
                self.skipped.append({"from": iso(bar.end), "to": iso(next_start),
                                     "reason": "VENUE_CLOSED" if venue_closed else "NO_OBSERVATIONS"})

        self.latest_bars.update({b.spec.resolution: b for b in closed_bars})

    def settle(self, top, at, closing=False):
        if not self.pending:
            return
        if self.cost.order_type == "limit" and self.execution_limits is None:
            return self.settle_limit(top, at, closing)
        pending = self.pending
        order = pending.record
        eligible_quote = (top is not None and qualified(top)
                          and top.ts_avail >= pending.decision_time + self.cost.latency)
        timed_out = at > pending.decision_time + self.cost.max_wait
        if eligible_quote or timed_out:
            if eligible_quote and order["side"] == "BUY" and self.strategy.params.get("entry_risk_bps"):
                spec = self.portal.spec_at(self.symbol, at)
                if spec.qty_decimals is None or spec.min_notional is None:
                    order.update(status="NONFILL", reason="UNKNOWN_RISK_SIZING_RULES", fill_time=iso(at))
                    self.pending = None
                    return
                _, capacity = self.risk_cash(top)
                pending.fraction = min(pending.fraction, (capacity / self.book.get(self.instrument.quote)).quantize(Decimal("0.000000000001"), ROUND_DOWN)) if self.book.get(self.instrument.quote) else Decimal(0)
            previous_base,previous_cash = self.book.get(self.instrument.base),self.book.get(self.instrument.quote)
            result = market_order(
                self.book, self.instrument, order["side"], pending.fraction,
                pending.decision_time, pending.decision_price, [top] if top is not None else [], 0,
                self.cost, self.portal.spec_at(self.symbol, at), self.rules_for(at), self.quota, order["ref"],
                self.day_open.get(tehran_day(top.ts_avail)) if top is not None else None,
                execution_limits=self.execution_limits, max_qty=pending.max_qty,
            )
            order.update(result)
            if self.execution_limits is not None and result["status"] == "FILLED":
                if order["side"] == "BUY":
                    cost_basis = previous_base*(self.position_entry or Decimal(0))+previous_cash-self.book.get(self.instrument.quote)
                    self.position_entry = cost_basis/self.book.get(self.instrument.base)
                    self.position_stop = self.position_entry*(1-pending.stop_distance_bps/10000)
                    self.position_opened,self.position_id = parse_ts(result["fill_time"]),order["ref"]
                    self.position_closed = False
                else:
                    remaining = self.book.get(self.instrument.base)
                    self.position_closed = sellable_quantity(remaining,top.bid,self.portal.spec_at(self.symbol,at)) == 0
                    order["residual_base"] = str(remaining)
                    if remaining == 0:
                        self.position_entry = self.position_stop = self.position_opened = self.position_id = None
            elif self.track_positions and result["status"] == "FILLED":
                self.record_position_fill(order, previous_base, previous_cash, top, at)
            self.pending = None
            if (self.cost.carry_remainder and self.execution_limits is None and result["status"] == "FILLED"
                    and "requested_qty" in result and not closing):
                # Keep working the rest on later quotes; the original decision time bounds it by max_wait.
                child = {"ref": f"{order.get('parent', order['ref'])}.{sum(o.get('parent') == order.get('parent', order['ref']) for o in self.orders) + 1}",
                         "parent": order.get("parent", order["ref"]), "side": order["side"],
                         "decision_time": order["decision_time"], "status": "PENDING"}
                self.orders.append(child)
                self.pending = PendingOrder(child, Decimal(1), pending.decision_time, pending.decision_price,
                                            max_qty=Decimal(result["requested_qty"]) - Decimal(result["qty"]))
        elif closing:
            order.update(status="NONFILL", reason="SESSION_ENDED_BEFORE_SETTLEMENT")
            self.pending = None

    def settle_limit(self, top, at, closing):
        """Rest at the near touch; each fill is bounded by observed trades or crossing quote capacity."""
        pending, order = self.pending, self.pending.record
        buy = order["side"] == "BUY"
        if closing or at > pending.decision_time + self.cost.max_wait:
            order.update(status="NONFILL", reason="SESSION_ENDED_BEFORE_SETTLEMENT" if closing else "LIMIT_EXPIRED")
            self.pending = None
            return
        if top is None or not qualified(top) or top.ts_avail < pending.decision_time + self.cost.latency:
            return
        if pending.limit is None:
            shown = top.bid_qty if buy else top.ask_qty
            try:
                shown = decimal(shown, "displayed queue")
            except ValueError:
                order.update(status="NONFILL", reason="QUEUE_UNKNOWN", fill_time=iso(top.ts_avail))
                self.pending = None
                return
            pending.limit, pending.queue_ahead, pending.checked = (top.bid if buy else top.ask), shown, top.ts_avail
            spec = self.portal.spec_at(self.symbol, at)
            with localcontext() as ctx:
                ctx.rounding = ROUND_DOWN
                quantity = self.book.get(self.instrument.quote) * pending.fraction / pending.limit if buy else self.book.get(self.instrument.base) * pending.fraction
                if spec.qty_decimals is not None:
                    quantity = quantity.quantize(Decimal(1).scaleb(-spec.qty_decimals), ROUND_DOWN)
            pending.max_qty = quantity if pending.max_qty is None else min(quantity, pending.max_qty)
            order.update(limit_price=str(pending.limit), placed_at=iso(top.ts_avail), queue_ahead=str(shown))
            order["remaining_qty"] = str(pending.max_qty)
            return
        if top.ts_avail <= pending.checked:
            return
        through = top.ask <= pending.limit if buy else top.bid >= pending.limit
        placed = parse_ts(order["placed_at"])
        prints = [x for x in self.portal.trades_by_event(self.symbol, placed, top.ts_avail + timedelta(microseconds=1))
                  if pending.checked < x.ts_avail <= top.ts_avail]
        capacity = Decimal(0)
        for trade in prints:
            against = trade.aggressor == ("SELL" if buy else "BUY")  # takers hitting our side
            if not against:
                continue
            try:
                decimal(trade.price, "trade price", positive=True)
                decimal(trade.qty, "trade quantity", positive=True)
            except ValueError:
                continue
            self.limit_trades.append((iso(trade.ts_event), iso(trade.ts_avail), str(trade.price), str(trade.qty), trade.aggressor))
            if trade.price < pending.limit if buy else trade.price > pending.limit:
                pending.queue_ahead = Decimal(0)
                capacity += trade.qty
            elif trade.price == pending.limit:
                ahead = min(pending.queue_ahead, trade.qty)
                pending.queue_ahead -= ahead
                capacity += trade.qty - ahead
        pending.checked = top.ts_avail
        if through:
            shown = top.ask_qty if buy else top.bid_qty
            try:
                shown = decimal(shown, "crossing quantity")
            except ValueError:
                shown = Decimal(0)
            # The quote and its preceding prints may describe the same liquidity.
            capacity = max(capacity, shown or Decimal(0))
            pending.queue_ahead = Decimal(0)
        if capacity <= 0:
            return
        previous_base, previous_cash = self.book.get(self.instrument.base), self.book.get(self.instrument.quote)
        if buy and self.allocation is not None:
            capacity = min(capacity, previous_cash * pending.fraction / pending.limit)
            if capacity <= 0:
                return
        if buy and self.strategy.params.get("entry_risk_bps"):
            spec = self.portal.spec_at(self.symbol, at)
            if spec.qty_decimals is None or spec.min_notional is None:
                order.update(status="NONFILL", reason="UNKNOWN_RISK_SIZING_RULES", fill_time=iso(at))
                self.pending = None
                return
            _, budget = self.risk_cash(top)
            capacity = min(capacity, budget / pending.limit)
            if capacity <= 0:
                return
        result = market_order(self.book, self.instrument, order["side"], Decimal(1), pending.decision_time,
                              pending.decision_price, [top], 0, self.cost, self.portal.spec_at(self.symbol, at),
                              self.rules_for(at), self.quota, order["ref"],
                              self.day_open.get(tehran_day(top.ts_avail)), max_qty=min(pending.max_qty, capacity), limit_price=pending.limit)
        if result["status"] != "FILLED" and result.get("reason") == "BELOW_MIN_NOTIONAL":
            order["last_nonfill_reason"] = result["reason"]
            return
        order.update({k: v for k, v in result.items() if k not in ("ref", "side", "decision_time")})
        order["maker"] = True
        self.pending = None
        if result["status"] == "FILLED":
            if self.track_positions:
                self.record_position_fill(order, previous_base, previous_cash, top, at)
            remaining = pending.max_qty - Decimal(result["qty"])
            order["requested_qty"], order["remaining_qty"] = str(pending.max_qty), str(remaining)
            if remaining > 0:
                parent = order.get("parent", order["ref"])
                child = {"ref": f"{parent}.{sum(o.get('parent') == parent for o in self.orders) + 1}",
                         "parent": parent, "side": order["side"], "decision_time": order["decision_time"],
                         "status": "PENDING", "limit_price": str(pending.limit), "placed_at": order["placed_at"],
                         "queue_ahead": str(pending.queue_ahead), "remaining_qty": str(remaining)}
                self.orders.append(child)
                self.pending = PendingOrder(child, Decimal(1), pending.decision_time, pending.decision_price,
                                            max_qty=remaining, limit=pending.limit,
                                            queue_ahead=pending.queue_ahead, checked=pending.checked)

    def record_position_fill(self, order, previous_base, previous_cash, top, at):
        quantity = self.book.get(self.instrument.base)
        if order["side"] == "BUY":
            self.position_entry = (previous_base * (self.position_entry or Decimal(0)) + previous_cash - self.book.get(self.instrument.quote)) / quantity
            if self.position_closed:
                self.position_opened, self.position_id = parse_ts(order["fill_time"]), order.get("parent", order["ref"])
            self.position_closed = False
        else:
            self.position_closed = sellable_quantity(quantity, top.bid, self.portal.spec_at(self.symbol, at)) == 0
            order["residual_base"] = str(quantity)
            if quantity == 0:
                self.position_entry = self.position_stop = self.position_opened = self.position_id = None

    def risk_cash(self, quote):
        if self.risk_budget is not None:
            return self.risk_budget()
        equity = self.book.equity(self.instrument, quote.bid)
        held_cost = self.book.get(self.instrument.base) * (self.position_entry or Decimal(0))
        rate = Decimal(self.strategy.params["entry_risk_bps"]) / 10000
        stop = Decimal(self.strategy.params["exit_stop_bps"]) / 10000
        return equity, max(Decimal(0), equity * rate / stop - held_cost)

    def size_risk_entry(self, fraction, quote, at):
        spec = self.portal.spec_at(self.symbol, at)
        if spec.qty_decimals is None or spec.min_notional is None:
            return Decimal(0), {"status": "UNKNOWN_VENUE_MINIMUM_OR_PRECISION"}
        equity, capacity = self.risk_cash(quote)
        cash = min(self.book.get(self.instrument.quote) * fraction, capacity)
        fee = self.cost.maker_fee if self.cost.order_type == "limit" else self.cost.fee_rate
        stop = quote.ask * (1 - Decimal(self.strategy.params["exit_stop_bps"]) / 10000) / (1 - fee)**2
        if equity <= 0 or cash <= 0 or stop >= quote.ask:
            return Decimal(0), {"status": "NO_RISK_CAPACITY_OR_INVALID_FEE_ADJUSTED_STOP"}
        with localcontext() as context:
            context.prec = 160
            report = portfolio_sizing(self.instrument.quote, format(equity, "f"), format(cash, "f"),
                format(Decimal(self.strategy.params["entry_risk_bps"]) / 10000, "f"), "0", "1", format(fee, "f"), "0", [{
                    "symbol": self.symbol, "entry_price": format(quote.ask, "f"), "stop_price": format(stop, "f"),
                    "risk_fraction": format(Decimal(self.strategy.params["entry_risk_bps"]) / 10000, "f"),
                    "max_position_fraction": "1", "quantity_step": format(Decimal(1).scaleb(-spec.qty_decimals), "f")}])
        row = report["allocations"][0]
        if row["entry_cash_quote"] < spec.min_notional or spec.min_qty is not None and row["gross_base_quantity"] < spec.min_qty:
            return Decimal(0), {"status": "BELOW_VENUE_MINIMUM"}
        fraction = (row["entry_cash_quote"] / self.book.get(self.instrument.quote)).quantize(Decimal("0.000000000001"), ROUND_DOWN)
        return fraction, {"status": row["status"], "quantity": str(row["gross_base_quantity"]),
            "entry_cash_quote": str(row["entry_cash_quote"]), "modeled_loss_quote": str(row["modeled_loss_quote"]),
            "remaining_capacity_quote": str(capacity), "stop_execution_verified": False}

    def feed(self, top):
        if self.state in ("ENDED", "ABORTED") or top.ts_avail < self.cursor:
            raise ValueError("session closed or observation out of order")
        if self.state != "FINISHING":
            self.scan(top.ts_avail)
        if qualified(top):
            self.day_open.setdefault(tehran_day(top.ts_avail), (top.bid + top.ask) / 2)
            self.mark_reopening(top)
        self.settle(top, top.ts_avail)
        if qualified(top):
            self.closes.update(top.ts_avail, self.bar_spec.price(top))
            self.last_quote = top
        self.cursor = top.ts_avail

    def mark_reopening(self, top):
        """Mark the gap once, on the first qualified quote after a venue closure the position was held across."""
        last = self.last_quote
        if last is None:
            return
        spans = closures(self.rules_for(top.ts_avail), self.instrument, top.ts_avail)
        crossed = [(s, e) for s, e in spans if last.ts_avail < e <= top.ts_avail]
        if not crossed:
            return
        held = self.book.get(self.instrument.base)
        self.reopenings.append({
            "closed_from": iso(crossed[0][0]), "reopened_at": iso(crossed[-1][1]), "first_quote": iso(top.ts_avail),
            "pre_close_bid": str(last.bid), "reopen_bid": str(top.bid), "base_held": str(held),
            "gap_value": str(held * (top.bid - last.bid)),
        })
        self.curve.append((iso(top.ts_avail), str(self.book.equity(self.instrument, top.bid))))

    def finish(self, at, reason=None):
        if self.state in ("ENDED", "ABORTED") or at < self.cursor:
            raise ValueError("session closed or finish before cursor")
        if self.state != "FINISHING" and not reason:
            self.scan(at)
        if self.state != "FINISHING":
            self.transition("FINISHING", at)
        self.settle(None, at, closing=True)
        self.cursor = at
        self.transition("ABORTED" if reason else "ENDED", at, reason)


def outcome_marks(decisions, tops, end):
    """First qualified mark on/after each horizon; never read beyond the session cut."""
    quotes = [quote for quote in tops if qualified(quote) and quote.ts_avail <= end]
    times = [quote.ts_avail for quote in quotes]
    for decision in decisions:
        decision["marks"] = {}
        for minutes in (15, 60, 240):
            due = parse_ts(decision["t"]) + timedelta(minutes=minutes)
            index = bisect_left(times, due)
            mark = {"due": iso(due), "status": "PENDING" if due > end else "MISSING"}
            if due <= end and index < len(quotes):
                quote = quotes[index]
                delay = (quote.ts_avail - due).total_seconds()
                mark.update(
                    status="OBSERVED_AFTER_GAP" if delay > 120 else "MATURE",
                    at=iso(quote.ts_avail), bid=str(quote.bid), ask=str(quote.ask), delay_s=delay,
                )
            decision["marks"][str(minutes)] = mark
