"""Incremental paper-session engine. No venue orders; replay and polling share this path."""
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from ..domain.bars import BarSpec, CloseSubscriptions, qualified
from ..domain.model import iso, parse_ts
from ..domain.rules import closures, is_closed, session_period, tehran_day
from ..domain.sim import CashBook, market_order
from ..domain.strategy import Snapshot

ENGINE_VERSION = "paper-session/5"


@dataclass
class PendingOrder:
    record: dict
    fraction: Decimal
    decision_time: datetime
    decision_price: Decimal


class PaperSession:
    def __init__(self, portal, rules_for, strategy, symbol, start, resolution, cash, cost, subscriptions=()):
        if not cash.is_finite() or cash <= 0:
            raise ValueError("cash must be positive and finite")
        self.portal = portal
        self.rules_for = rules_for
        self.strategy = strategy
        self.symbol = symbol
        self.instrument = portal.instrument(symbol)
        self.cost = cost
        self.bar_spec = BarSpec(resolution, "MID")
        resolutions = tuple(dict.fromkeys((resolution, *subscriptions)))
        periods = {"session": self.session_of} if "session" in resolutions else {}
        self.closes = CloseSubscriptions(symbol, resolutions, periods)
        self.consolidator = self.closes.by_resolution[resolution]
        self.book = CashBook({self.instrument.quote: cash})
        self.last_quote = None
        self.pending: PendingOrder | None = None
        self.cursor = start
        self.decisions = []
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
        for bar in self.closes.scan(at):
            self.bar_events.append({"t": iso(bar.avail), "resolution": bar.spec.resolution,
                                    "start": iso(bar.start), "close": str(bar.close)})
            if bar.spec != self.bar_spec:
                continue
            quote = self.last_quote if self.last_quote and bar.avail - self.last_quote.ts_avail <= timedelta(seconds=120) else None
            snapshot = Snapshot(bar.avail, self.symbol, bar, quote and quote.bid, quote and quote.ask, quote and quote.ts_avail)
            holding = bool(quote) and self.book.get(self.instrument.base) * quote.bid > self.book.equity(self.instrument, quote.bid) / 100
            action, fraction, reasons, feature_hash = self.strategy.decide(snapshot, holding)
            if self.state == "WARMING_UP" and action != "ABSTAIN_WARMUP":
                self.running_at = bar.avail
                self.transition("RUNNING", bar.avail)
            decision = {"t": iso(bar.avail), "snapshot": snapshot.id, "close": str(bar.close), "action": action,
                   "reasons": list(reasons), "features": feature_hash, "bid": quote and str(quote.bid), "ask": quote and str(quote.ask),
                   "quote_time": quote and iso(quote.ts_avail)}
            decision["feature_values"] = self.strategy.feature_values
            if action in ("BUY_REQUEST", "SELL_REQUEST"):
                if self.pending:
                    decision["skipped"] = "PENDING_ORDER"
                else:
                    ref = f"{self.symbol}#{len(self.orders) + 1}"
                    side = action.split("_")[0]
                    order = {"ref": ref, "side": side, "decision_time": iso(bar.avail), "status": "PENDING"}
                    self.orders.append(order)
                    self.pending = PendingOrder(order, fraction, bar.avail, quote.ask if side == "BUY" else quote.bid)
                    decision["order"] = ref
            self.decisions.append(decision)
            if quote:
                self.curve.append((iso(bar.avail), str(self.book.equity(self.instrument, quote.bid))))
            next_start = self.consolidator.period_of(at)[0]
            if next_start > bar.end:
                closed = is_closed(self.rules_for(bar.end), self.instrument, bar.end)
                self.skipped.append({"from": iso(bar.end), "to": iso(next_start),
                                     "reason": "VENUE_CLOSED" if closed else "NO_OBSERVATIONS"})

    def settle(self, top, at, closing=False):
        if not self.pending:
            return
        pending = self.pending
        order = pending.record
        eligible_quote = (top is not None and qualified(top)
                          and top.ts_avail >= pending.decision_time + self.cost.latency)
        timed_out = at > pending.decision_time + self.cost.max_wait
        if eligible_quote or timed_out:
            result = market_order(
                self.book, self.instrument, order["side"], pending.fraction,
                pending.decision_time, pending.decision_price, [top] if top is not None else [], 0,
                self.cost, self.portal.spec_at(self.symbol, at), self.rules_for(at), self.quota, order["ref"],
                self.day_open.get(tehran_day(top.ts_avail)) if top is not None else None,
            )
            order.update(result)
            self.pending = None
        elif closing:
            order.update(status="NONFILL", reason="SESSION_ENDED_BEFORE_SETTLEMENT")
            self.pending = None

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
