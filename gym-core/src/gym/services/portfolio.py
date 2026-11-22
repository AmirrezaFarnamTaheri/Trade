"""Shared-cash paper portfolio: one strategy over several markets of one quote currency.

Each market keeps its own session (bars, decisions, rules, quotas), but all of them post to one CashBook,
so an entry in one market leaves less cash for the others. The selected allocation policy sizes entries
against current portfolio equity. Quotes from all markets are fed in availability order.
"""
import hashlib
import heapq
import json
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

from ..adapters.store import MarketDB
from ..domain.bars import BarSpec, qualified
from ..domain.execution_costs import modeled_execution_cost
from ..domain.model import InstrumentId, QualityLimits, iso, parse_ts
from ..domain.performance import performance, trade_ledger
from ..domain.portfolio_policy import PortfolioPolicy
from ..domain.registry import create_strategy
from ..domain.rules import closures, is_closed, tehran_day
from ..domain.sim import CashBook, CostModel, sellable_quantity
from ..domain.strategy import digest
from .data_portal import DataPortal, curve_valuation
from .portfolio_rank import PortfolioRank
from .rules import RuleService
from .session import ENGINE_VERSION, LIMIT_ENGINE_VERSION, PaperSession

MAX_OBSERVATIONS = 200_000
MAX_MULTICURRENCY_BOOK_OBSERVATIONS = 12_000_000
MAX_MARKETS = 500


class _ReconcilingCashBook(CashBook):
    """Record arithmetic rounding without changing strategy inventory or sizing."""

    def post(self, t, ccy, amount, kind, ref):
        previous = self.get(ccy)
        super().post(t, ccy, amount, kind, ref)
        with localcontext() as ctx:
            ctx.prec = 400
            adjustment = self.get(ccy) - previous - amount
        if adjustment:
            self.postings.append({**self.postings[-1], "amount": str(adjustment), "kind": "rounding"})


def fx_rebalance_limits(value):
    from ..domain.market_models import decimal, fields

    optional = [key for key in ("otc_quotes", "otc_routes", "mixed_routes", "residual_attempts") if isinstance(value, dict) and key in value]
    fields(value, " ".join(("target_usdt_cash_share band max_order_usdt", *optional)))
    if "residual_attempts" in value and ("mixed_routes" not in value or type(value["residual_attempts"]) is not int
                                         or not 1 <= value["residual_attempts"] <= 8):
        raise ValueError("residual_attempts requires mixed_routes and an integer from 1 to 8")
    target = decimal(value["target_usdt_cash_share"])
    band = decimal(value["band"], positive=True)
    cap = decimal(value["max_order_usdt"], positive=True)
    if target > 1 or band > 1:
        raise ValueError("FX target and band must be fractions")
    return target, band, cap


def portfolio(db: MarketDB, symbols: list[str], t0: datetime, t1: datetime, *, resolution: str = "15min",
              cash: Decimal = Decimal(1000), cost: CostModel = CostModel(), strategy_id: str = "ema-trend",
              params: dict | None = None, rules_mode: str = "point-in-time", store: str = "live", policy: dict | None = None,
              checkpoint: dict | None = None, universe_selection: dict | None = None, booked_accounting: bool = True,
              cash_by_currency: dict | None = None, dynamic_routes: bool = False,
              funding_legs: list | None = None, fx_rebalance: dict | None = None, margin_plans=None,
              venue: str = "wallex", rank_gate: dict | None = None) -> dict:
    """Replay one shared-cash portfolio using a read-isolated chronological snapshot."""
    if db.c.in_transaction:
        raise ValueError("portfolio requires its own read snapshot")
    db.c.execute("BEGIN")
    try:
        return _portfolio(DataPortal(db, venue=venue), symbols, t0, t1, resolution=resolution, cash=cash, cost=cost,
                          strategy_id=strategy_id, params=params, rules_mode=rules_mode, store=store,
                          policy=policy, checkpoint=checkpoint, universe_selection=universe_selection,
                          booked_accounting=booked_accounting, cash_by_currency=cash_by_currency, dynamic_routes=dynamic_routes,
                          funding_legs=funding_legs, fx_rebalance=fx_rebalance, margin_plans=margin_plans, rank_gate=rank_gate)
    finally:
        db.c.rollback()


def _portfolio(portal, symbols, t0, t1, *, resolution, cash, cost, strategy_id, params, rules_mode, store, policy, checkpoint,
               universe_selection, booked_accounting, cash_by_currency, dynamic_routes, funding_legs, fx_rebalance,
               margin_plans, rank_gate):
    """Replay strictly prior market observations against a shared simulated cash book."""
    if portal.venue != "wallex" and cash_by_currency is not None:
        raise ValueError("alternate venue replay requires a single quote currency")
    _check_request(portal, symbols, t0, t1, cost, rules_mode, universe_selection,
                   multicurrency=cash_by_currency is not None)
    if rank_gate is not None:
        step = BarSpec(resolution).step
        if resolution == "session" or ((t1 - t0) // step + 2) * len(symbols) > 100_000:
            raise ValueError("rank replay requires fixed bars and at most 100000 instrument cutoffs")
        rank_gate = PortfolioRank(rank_gate, step)
    if cash_by_currency is not None or rank_gate is not None:
        symbols = sorted(symbols)
    return _Replay(portal, symbols, t0, t1, resolution=resolution, cash=cash, cost=cost, strategy_id=strategy_id,
                   params=params, rules_mode=rules_mode, store=store, policy=policy, checkpoint=checkpoint,
                   universe_selection=universe_selection, booked_accounting=booked_accounting,
                   cash_by_currency=cash_by_currency, dynamic_routes=dynamic_routes, funding_legs=funding_legs,
                   fx_rebalance=fx_rebalance, margin_plans=margin_plans, rank_gate=rank_gate).run()


class _Replay:
    """One portfolio replay: shared cash book, per-market paper sessions and the portfolio policy.

    The former closure state lives on the instance; each stage is a method small enough to review on its own.
    """

    def __init__(self, portal, symbols, t0, t1, *, resolution, cash, cost, strategy_id, params, rules_mode, store, policy,
                 checkpoint, universe_selection, booked_accounting, cash_by_currency, dynamic_routes, funding_legs,
                 fx_rebalance, margin_plans, rank_gate):
        self.db, self.symbols, self.t0, self.t1 = portal.db, symbols, t0, t1
        self.resolution, self.cash, self.cost, self.strategy_id = resolution, cash, cost, strategy_id
        self.rules_mode, self.store, self.policy, self.checkpoint = rules_mode, store, policy, checkpoint
        self.universe_selection = universe_selection
        self.booked_accounting = booked_accounting
        self.portal = portal
        self.rank_gate = rank_gate
        self.rules_for, self.rule_evidence = _rule_timeline(self.db, rules_mode)
        self.instruments = {s: self.portal.instrument(s) for s in symbols}
        if any(inst.kind != "SPOT" for inst in self.instruments.values()):
            raise ValueError("portfolio spot sessions require spot instruments")
        self.reference_routes = {}
        quotes = {inst.quote for inst in self.instruments.values()}
        self.multicurrency = cash_by_currency is not None
        self.margin = None
        self.margin_plans = margin_plans
        if margin_plans is not None and (not self.multicurrency or not booked_accounting or rules_mode != "point-in-time"):
            raise ValueError("margin positions require point-in-time mixed-currency booked accounting")
        if funding_legs is not None and (not self.multicurrency or not booked_accounting or rules_mode != "point-in-time"):
            raise ValueError("opening funding legs require point-in-time mixed-currency booked accounting")
        self.funding_legs, self.funding_result = funding_legs, None
        self.fx_rebalance = fx_rebalance
        self.otc_fx = None
        self.fx_pending, self.fx_orders, self.fx_quotas = None, [], {}
        if fx_rebalance is not None:
            self.fx_target, self.fx_band, self.fx_cap = fx_rebalance_limits(fx_rebalance)
            if (not self.multicurrency or not booked_accounting or rules_mode != "point-in-time"
                    or cost.order_type != "market"
                    or cost.walk_depth or cost.max_participation is None or cost.impact_models
                    or cost.hourly_costs or cost.postfill_costs):
                raise ValueError("invalid in-window FX rebalance settings")
            from .portfolio_otc import PortfolioOTC

            self.otc_fx = PortfolioOTC.from_policy(fx_rebalance)
        if type(dynamic_routes) is not bool or (dynamic_routes and (
                not self.multicurrency or strategy_id != "ema-trend" or cost.order_type != "market"
                or cost.walk_depth or cost.max_participation is None or cost.market_fees
                or cost.impact_models or cost.hourly_costs or cost.postfill_costs
                or (params or {}).get("exit_venue_stop", 0) not in (0, 3))):
            raise ValueError("dynamic routes require mixed-currency EMA and capped best-level spot execution")
        self.dynamic_routes = dynamic_routes
        self.entry_windows = (universe_selection or {}).get("entry_windows", {})
        self.variable_routes = dynamic_routes or (self.multicurrency and bool(self.entry_windows))
        self.listed = {s: t0 for s in symbols if s not in self.entry_windows}
        self.listing_events = iter(sorted(
            (parse_ts(stamp), symbol, entering)
            for symbol, intervals in self.entry_windows.items() for begin, end in intervals
            for stamp, entering in ((begin, True), (end, False)) if parse_ts(stamp) < t1))
        self.next_listing = next(self.listing_events, None)
        self.route_changes = []
        if self.multicurrency:
            self._configure_currencies(quotes, cash_by_currency)
        elif len(quotes) != 1:
            raise ValueError("portfolio markets must share one quote currency")
        if not self.multicurrency and len({inst.base for inst in self.instruments.values()}) != len(symbols):
            raise ValueError("portfolio markets must have distinct base assets")
        if not self.multicurrency:
            self.quote = quotes.pop()
            self.book = CashBook({self.quote: cash})
        self.marks: dict[str, Decimal] = {}
        self.mark_times, self.mark_order = {}, {}
        self.held, self.held_order = set(), []
        traded_symbols = [s for s in symbols if s not in self.reference_routes]
        self.controller = PortfolioPolicy({} if policy is None else policy, traded_symbols)
        if self.controller.usdt_fx_risk and (self.quote != "TMN" or portal.venue != "wallex"):
            raise ValueError("usdt_fx_risk is only applicable to TMN-quoted portfolios")
        self.fx_risk_tops = _fx_tops(self.db, self.portal, t0, t1, "portfolio FX risk") if self.controller.usdt_fx_risk else []
        self.fx_risk_times = [top.ts_avail for top in self.fx_risk_tops]
        self.weights = self.controller.weights({})
        self.reserved, self.histories, self.policy_events = {}, {s: [] for s in symbols}, []
        self.rebalance_pending = set()
        self.next_rebalance, self.risk_state, self.next_close = t0, None, None
        self.sessions = {}
        self.quote_counts = {s: [0, 0] for s in symbols}
        for s in traded_symbols:
            strategy = create_strategy(strategy_id, params)
            starting_cash = self.book.get(self.instruments[s].quote) if self.multicurrency else cash
            session = PaperSession(self.portal, self.rules_for, strategy, s, t0, resolution, starting_cash, cost,
                                   shared_book=self.book)
            session.allocation = lambda fraction, symbol=s: self.allocate(symbol, fraction)
            session.decision_filter = (lambda action, fraction, reasons, symbol=s:
                                       self.filter_decision(symbol, action, fraction, reasons))
            self.sessions[s] = session
            if strategy.params.get("entry_risk_bps"):
                if self.multicurrency:
                    raise ValueError("entry risk sizing requires a single quote currency")
                session.risk_budget = lambda symbol=s: self.risk_budget(symbol)
        if self.entry_windows:
            self._advance_listings(t0)
            if self.multicurrency:
                self._count_listed_routes()
        if checkpoint is not None and (type(checkpoint.get("quote_count")) is not int or
                checkpoint["quote_count"] < 1):
            raise ValueError("portfolio checkpoint cursor exceeds observed quotes")
        self.curve = []
        self.prefix = hashlib.sha256(b"[") if checkpoint is not None else None

    def _configure_currencies(self, quotes, opening):
        from ..domain.market_models import decimal

        if quotes != {"TMN", "USDT"} or type(opening) is not dict or opening.keys() != quotes:
            raise ValueError("multi-currency replay requires explicit TMN and USDT opening cash")
        if self.policy is not None:
            raise ValueError("multi-currency replay currently uses default allocation")
        self.opening_cash = {currency: decimal(amount, currency) for currency, amount in opening.items()}
        if not any(self.opening_cash.values()):
            raise ValueError("multi-currency replay requires positive opening capital")
        reconciles = self.margin_plans or {"otc_routes", "mixed_routes"} & (self.fx_rebalance or {}).keys()
        book_type = _ReconcilingCashBook if reconciles else CashBook
        self.book = book_type(dict(self.opening_cash))
        if self.funding_legs is not None:
            self._fund_opening_account()
        if self.margin_plans:
            from .portfolio_margin import PortfolioMargin

            self.margin = PortfolioMargin(self.portal, self.rules_for, self.t0, self.t1, self.margin_plans, self.book, self.cost)
        self._configure_routes(quotes)
        self.quote = "USDT"
        self.fx_stream = iter(self.portal.iter_tops("USDTTMN", self.t0 - timedelta(days=1), self.t1))
        self.fx_next = next(self.fx_stream, None)
        self.fx_mark = None
        self.fx_evidence = hashlib.sha256()
        self._fx_valuation_calendar = (None, None, ())
        self._advance_fx(self.t0)
        if self.fx_mark is None:
            raise ValueError("multi-currency replay requires an opening USDTTMN valuation observation")
        self.opening_fx = self.fx_mark
        self.cash = self._combined_equity(self.opening_cash)
        if self.fx_rebalance is not None:
            self.fx_instrument = self.portal.instrument("USDTTMN")
            metadata = self.portal.metadata_at("USDTTMN", self.t0)
            terms = metadata["raw"] if metadata else {}
            self.fx_cost = self.cost.for_market("USDTTMN", zero_fee=terms.get("isZeroFee", terms.get("is_zero_fee")) is True)

    def _fund_opening_account(self):
        from .conversion_replay import replay_mixed_route

        self.funding_result = replay_mixed_route(
            self.db, {"opening_balances": self.opening_cash, "legs": self.funding_legs},
            funding_cutoff=self.t0)
        balances = self.funding_result["closing_balances"]
        if any(Decimal(amount) for currency, amount in balances.items() if currency not in self.opening_cash):
            raise ValueError("opening funding route left inventory outside the portfolio cash currencies")
        self.book = type(self.book)(
            {currency: Decimal(amount) for currency, amount in balances.items()},
            [{"t": posting["at"], "ccy": posting["asset"], "amount": posting["amount"],
              "kind": posting["kind"], "ref": f"opening-funding/{posting['leg']}"}
             for posting in self.funding_result["postings"]],
        )

    def _configure_routes(self, quotes):
        owners = {}
        self.route_candidates = defaultdict(list)
        margin_symbols = self.margin.symbols if self.margin else set()
        mixed = self.otc_fx.mixed if self.otc_fx else ()
        mixed_bases = {route.base for route in mixed}
        mixed_symbols = {route.symbol for route in mixed}
        if (margin_symbols | mixed_symbols) - self.instruments.keys():
            raise ValueError("margin and mixed spot execution require a selected portfolio symbol")
        if margin_symbols & mixed_symbols:
            raise ValueError("a mixed spot route cannot share its symbol with margin")
        # Allocate one venue route per asset using opening balances and a stable currency/symbol preference.
        for symbol in sorted(self.symbols, key=lambda s: (
                not self.book.get(self.instruments[s].quote), self.instruments[s].quote != "USDT", s)):
            inst = self.instruments[symbol]
            if symbol in margin_symbols:
                self.reference_routes[symbol] = {"reason": "MARGIN_POSITION", "trade_route": None}
            elif inst.base in mixed_bases:
                self.reference_routes[symbol] = {"reason": "MIXED_ROUTE_INTERMEDIATE", "trade_route": None}
            elif inst.base in quotes:
                self.reference_routes[symbol] = {"reason": "QUOTE_CURRENCY_REFERENCE", "trade_route": None}
            elif inst.base in owners and not self.variable_routes:
                self.reference_routes[symbol] = {"reason": "ALTERNATE_ROUTE", "trade_route": owners[inst.base]}
            else:
                owners[inst.base] = symbol
                self.route_candidates[inst.base].append(symbol)
        self.trade_routes = {} if self.variable_routes else owners
        if not self.route_candidates:
            raise ValueError("multi-currency replay requires at least one traded underlying")
        self.quote_market_counts = {quote: sum(self.instruments[s].quote == quote
                                              for choices in self.route_candidates.values() for s in choices)
                                    for quote in quotes}

    def _choose_routes(self, at):
        """Choose a freshly observed, funded route before scanning any symbol at this close."""
        for base, symbols in self.route_candidates.items():
            if self.book.get(base) > 0 or any(self.sessions[s].pending for s in symbols):
                continue
            if self.entry_windows:
                symbols = [s for s in symbols if s in self.listed]
            if not self.dynamic_routes:
                previous = self.trade_routes.get(base)
                if previous not in symbols:
                    choice = min(symbols, key=lambda s: (not self.book.get(self.instruments[s].quote),
                                 self.instruments[s].quote != "USDT", s), default=None)
                    self._set_route(base, choice, at)
                continue
            candidates = []
            for symbol in symbols:
                session, instrument = self.sessions[symbol], self.instruments[symbol]
                top = session.last_quote
                if (top is None or not qualified(top) or top.ts_avail >= at or "CLOSED" in top.flags
                        or self.entry_windows and top.ts_avail < self.listed[symbol]
                        or at - top.ts_avail > timedelta(seconds=120)
                        or is_closed(self.rules_for(at), instrument, at)
                        or top.ask_qty is None or top.ask_qty <= 0):
                    continue
                free = self.book.get(instrument.quote) - self.reserved_in(instrument.quote)
                target = self.equity_in(instrument.quote) / self.quote_market_counts[instrument.quote]
                clip = min(top.ask_qty * session.cost.max_participation, min(free, target) / top.ask)
                if not sellable_quantity(clip, top.ask, self.portal.spec_at(symbol, at)):
                    continue
                fx = self.fx_mark.bid if instrument.quote == "TMN" else Decimal(1)
                unit_cost = top.ask / fx / (1 - session.cost.fee_rate)
                candidates.append((unit_cost, symbol))
            choice = min(candidates)[1] if candidates else None
            self._set_route(base, choice, at)

    def _set_route(self, base, choice, at):
        previous = self.trade_routes.pop(base, None)
        if choice is not None:
            self.trade_routes[base] = choice
        if choice != previous:
            self.route_changes.append({"at": iso(at), "asset": base, "previous": previous, "selected": choice})

    def _count_listed_routes(self):
        counts = defaultdict(int)
        symbols = (s for routes in self.route_candidates.values() for s in routes) if self.dynamic_routes else self.trade_routes.values()
        for symbol in symbols:
            if symbol in self.listed:
                counts[self.instruments[symbol].quote] += 1
        self.quote_market_counts = counts

    def _advance_listings(self, at):
        if self.next_listing is None or self.next_listing[0] > at:
            return
        while self.next_listing is not None and self.next_listing[0] <= at:
            stamp, symbol, entering = self.next_listing
            if entering:
                self.listed[symbol] = stamp
            else:
                self.listed.pop(symbol, None)
                self.histories[symbol].clear()
                if self.rank_gate:
                    self.rank_gate.tops.pop(symbol, None)
                    self.rank_gate.previous.pop(symbol, None)
                session = self.sessions.get(symbol)
                if session and session.pending and session.pending.record["side"] == "BUY":
                    session.pending.record.update(status="CANCELLED", reason="SPOT_MEMBERSHIP_ENDED", cancelled_at=iso(stamp))
                    session.pending = None
                    self.reserved.pop(symbol, None)
            self.next_listing = next(self.listing_events, None)
        if self.multicurrency:
            self._count_listed_routes()

    def _advance_fx(self, at):
        while self.fx_next is not None and self.fx_next.ts_avail < at:
            top = self.fx_next
            if self.fx_pending is not None:
                self._fill_fx_rebalance(top)
            if qualified(top):
                self.fx_mark = top
                book_size = (top.bid_qty, top.ask_qty) if self.fx_rebalance is not None else ()
                self.fx_evidence.update(digest((iso(top.ts_avail), top.bid, top.ask, sorted(top.flags), *book_size)).encode())
            self.fx_next = next(self.fx_stream, None)

    def _request_fx_rebalance(self, close):
        if self.fx_pending is not None or (self.otc_fx and self.otc_fx.pending) or self.risk_state:
            return
        free_usdt = max(Decimal(0), self.book.get("USDT") - self.reserved_in("USDT"))
        free_tmn = max(Decimal(0), self.book.get("TMN") - self.reserved_in("TMN"))
        cash = self._combined_equity({"USDT": free_usdt, "TMN": free_tmn})
        gap = cash * self.fx_target - free_usdt
        if abs(gap) <= cash * self.fx_band:
            return
        side = "BUY" if gap > 0 else "SELL"
        price = self.fx_mark.ask if side == "BUY" else self.fx_mark.bid
        quantity = min(abs(gap), self.fx_cap)
        if self.otc_fx and self.otc_fx.select(close, side, quantity, cash=free_tmn if side == "BUY" else free_usdt,
                                             spot_price=price, spot_fee=self.fx_cost.fee_rate,
                                             latency=self.fx_cost.latency, end=self.t1,
                                             mixed_context=(self.portal, self.rules_for, self.fx_cost.max_participation)):
            return
        self.fx_pending = (close, side, quantity, price)

    def _fill_fx_rebalance(self, top):
        from ..domain.sim import market_order

        submitted, side, amount, price = self.fx_pending
        at = top.ts_avail
        if at > submitted + self.cost.max_wait:
            self._expire_fx_rebalance()
            return
        inst = self.fx_instrument
        rules = self.rules_for(at)
        if (at <= submitted or at < submitted + self.cost.latency or not qualified(top)
                or "CLOSED" in top.flags or is_closed(rules, inst, at)):
            return
        currency = "TMN" if side == "BUY" else "USDT"
        free = max(Decimal(0), self.book.get(currency) - self.reserved_in(currency))
        debit = min(free, amount * top.ask if side == "BUY" else amount)
        with localcontext() as ctx:
            ctx.rounding = ROUND_DOWN
            fraction = debit / self.book.get(currency) if debit else Decimal(0)
            spec = self.portal.spec_at(inst.symbol, at)
            result = market_order(self.book, inst, side, fraction, submitted, price, [top], 0, self.fx_cost,
                                  spec, rules, self.fx_quotas,
                                  f"fx-rebalance/{len(self.fx_orders) + 1}", max_qty=amount)
        result["terms_digest"] = digest({"spec": asdict(spec), "rules": rules, "cost": self.fx_cost.describe()})
        if "costs" in result:
            result["costs"] = {key: str(value) for key, value in result["costs"].items()}
        self.fx_orders.append(result)
        self.fx_pending = None

    def _expire_fx_rebalance(self):
        submitted, side, _, _ = self.fx_pending
        self.fx_orders.append({"decision_time": iso(submitted), "side": side,
                               "status": "NONFILL", "reason": "NO_QUALIFIED_QUOTE"})
        self.fx_pending = None

    def _combined_equity(self, amounts):
        fx = self.fx_mark
        return amounts["USDT"] + amounts["TMN"] / ((fx.bid + fx.ask) / 2)

    def fx_at_close(self, close):
        """Select only the most recent fresh, open, strictly earlier FX quote."""
        idx = bisect_left(self.fx_risk_times, close) - 1
        if idx < 0:
            return None
        top = self.fx_risk_tops[idx]
        if (not qualified(top) or "CLOSED" in top.flags
                or is_closed(self.rules_for(close), InstrumentId.wallex("USDTTMN"), close)
                or close - top.ts_avail > timedelta(seconds=QualityLimits().stale_s)):
            return None
        return (top.bid + top.ask) / 2

    def equity(self):
        """Value all paper holdings at currently known, currency-consistent marks."""
        if self.multicurrency:
            return self._combined_equity({quote: self.equity_in(quote) for quote in self.opening_cash})
        return self.equity_in(self.quote)

    def equity_in(self, quote):
        book, instruments, marks = self.book, self.instruments, self.marks
        equity = book.get(quote) + sum((book.get(instruments[s].base) * marks[s] for s in self.held_order
                                        if instruments[s].quote == quote), Decimal(0))
        return equity + self.margin.equity(quote) if self.margin else equity

    def reserved_in(self, quote, *, exclude=None):
        otc = self.otc_fx.reserved(quote) if self.otc_fx else Decimal(0)
        return sum((value for s, value in self.reserved.items()
                    if s != exclude and self.instruments[s].quote == quote), otc)

    def _fx_valuation_closed(self, at):
        # Timeline lookups reuse the same rules list for each recorded revision.
        rules, day = self.rules_for(at), tehran_day(at)
        cached_rules, cached_day, spans = self._fx_valuation_calendar
        if rules is not cached_rules or day != cached_day:
            spans = closures(rules, InstrumentId.wallex("USDTTMN"), at)
            self._fx_valuation_calendar = (rules, day, spans)
        return any(start <= at < end for start, end in spans)

    def valuation_state(self, at):
        """Fail portfolio valuation when a held market lacks a fresh mark."""
        stale_fx = self.multicurrency and ("CLOSED" in self.fx_mark.flags
                                           or at - self.fx_mark.ts_avail > timedelta(seconds=120)
                                           or self._fx_valuation_closed(at))
        return ("STALE_VALUATION" if stale_fx or (self.margin and self.margin.stale(at))
                or (self.otc_fx and self.otc_fx.residuals)
                or any(at - self.mark_times[s] > timedelta(seconds=120) for s in self.held_order)
                else "CURRENT")

    def allocate(self, symbol, fraction):
        """Reserve only funded shared paper cash below the target risk budget."""
        book, quote, reserved = self.book, self.instruments[symbol].quote, self.reserved
        equity = self.equity_in(quote)
        available = max(Decimal(0), book.get(quote) - self.reserved_in(quote)
                        - equity * self.controller.rates["cash_buffer"])
        if available <= 0 or self.risk_state or self.weights["status"] != "READY":
            return Decimal(0)
        held = book.get(self.instruments[symbol].base) * self.marks.get(symbol, Decimal(0))
        target = (equity / self.quote_market_counts[quote] if self.multicurrency
                  else equity * Decimal(self.weights["weights"][symbol]))
        target = max(Decimal(0), target - held)
        budget = (min(available, target, book.get(quote) * fraction)
                  if self.sessions[symbol].strategy.params.get("entry_risk_bps") else min(available, target * fraction))
        fraction = min(Decimal(1), budget / book.get(quote)).quantize(Decimal("0.000001"), ROUND_DOWN)
        reserved[symbol] = book.get(quote) * fraction
        if self.policy is not None:
            self.policy_events.append({"at": iso(self.controller.previous_at), "kind": "RESERVE", "symbol": symbol,
                                       "budget_quote": str(reserved[symbol]), "cash_quote": str(book.get(quote)),
                                       "reserved_quote": str(sum(reserved.values(), Decimal(0)))})
        return fraction

    def risk_budget(self, symbol):
        """Return entry stop-loss capacity net of filled and reserved exposure."""
        strategy = self.sessions[symbol].strategy
        stop = Decimal(strategy.params["exit_stop_bps"]) / 10000
        exposure_cost = sum((self.book.get(self.instruments[s].base) * (self.sessions[s].position_entry or Decimal(0))
                             for s in self.held_order), Decimal(0))
        other_orders = sum((amount for s, amount in self.reserved.items() if s != symbol), Decimal(0))
        capacity = max(Decimal(0), self.equity() * Decimal(strategy.params["entry_risk_bps"]) / 10000 / stop
                       - exposure_cost - other_orders)
        return self.equity(), capacity

    def risk(self, at):
        """Update portfolio loss latches and cancel unfilled entries when tripped."""
        if self.entry_windows:
            self._advance_listings(at)
        if self.otc_fx:
            self.otc_fx.advance(at, self.book, self.fx_orders, db=self.db, participation=self.fx_cost.max_participation,
                                latency=self.fx_cost.latency, end=self.t1)
        if self.multicurrency:
            self._advance_fx(at)
        if self.margin:
            self.margin.advance(at, self.book, terminal=at == self.t1)
        controller = self.controller
        if self.margin and self.margin.deficit():
            state = "MARGIN_DEFICIT"
        elif self.valuation_state(at) != "CURRENT":
            state = ("DRAWDOWN" if controller.drawdown_latched else "DAILY_LOSS" if controller.daily_latched
                     else "STALE_VALUATION")
        else:
            state = controller.observe(at, self.equity())
        if state != self.risk_state:
            self.risk_state = state
            self.policy_events.append({"at": iso(at), "kind": "RISK", "state": state, "equity": str(self.equity()),
                                       **({"reserved_by_currency": {q: str(self.reserved_in(q)) for q in sorted(self.opening_cash)}}
                                          if self.multicurrency else {"reserved_quote": str(self.reserved_in(self.quote))})})
        if state:
            for s in tuple(self.reserved):
                session = self.sessions[s]
                if session.pending and session.pending.record["side"] == "BUY":
                    session.pending.record.update(status="CANCELLED", reason="PORTFOLIO_" + state)
                    session.pending = None
                    self.reserved.pop(s, None)

    def filter_decision(self, symbol, action, fraction, reasons):
        """Apply portfolio risk, allowed rebalance and modeled transaction costs."""
        if self.variable_routes and self.trade_routes.get(self.instruments[symbol].base) != symbol:
            return "HOLD", Decimal(0), ("INACTIVE_ROUTE",)
        risk_state = self.risk_state
        if risk_state in ("DRAWDOWN", "DAILY_LOSS"):
            if self.book.get(self.instruments[symbol].base) > 0:
                return "SELL_REQUEST", Decimal(1), ("PORTFOLIO_" + risk_state,)
            return "ABSTAIN_PORTFOLIO_RISK", Decimal(0), ("PORTFOLIO_" + risk_state,)
        if risk_state and action == "BUY_REQUEST":
            return "ABSTAIN_PORTFOLIO_RISK", Decimal(0), (risk_state,)
        if action == "SELL_REQUEST":
            return action, fraction, reasons
        if (self.controller.description["rebalance"] and self.weights["status"] == "READY"
                and symbol in self.rebalance_pending and not risk_state
                and action in ("HOLD", "BUY_REQUEST", "SELL_REQUEST")):
            action, fraction, reasons = self._rebalance(symbol, action, fraction, reasons)
        if self.entry_windows and action == "BUY_REQUEST":
            listed_at, top = self.listed.get(symbol), self.sessions[symbol].last_quote
            if listed_at is None or top is None or top.ts_avail < listed_at:
                return "ABSTAIN_SPOT_MEMBERSHIP", Decimal(0), ("SPOT_ENTRY_UNAVAILABLE",)
        if self.rank_gate:
            return self.rank_gate.filter_entry(symbol, action, fraction, reasons)
        return action, fraction, reasons

    def _rebalance(self, symbol, action, fraction, reasons):
        controller = self.controller
        self.rebalance_pending.discard(symbol)
        held = self.book.get(self.instruments[symbol].base) * self.marks.get(symbol, Decimal(0))
        target = self.equity() * Decimal(self.weights["weights"][symbol])
        delta = target - held
        band = controller.rates["rebalance_threshold"]
        if controller.cost_aware_rebalance and self.equity() > 0:
            band = _cost_band(controller, self.sessions[symbol].cost, symbol, self.sessions[symbol].last_quote, delta, self.equity(), band,
                              self.policy_events)
            if band is None:
                return self._skip(symbol, "NO_FRESH_QUOTE_TO_PRICE_COST", delta, action, fraction, reasons)
        if self.equity() > 0 and abs(delta) > self.equity() * band:
            if delta > 0 and action != "BUY_REQUEST":
                strategy = self.sessions[symbol].strategy
                if (held <= 0 or not getattr(strategy, "entry_allowed", True)
                        or getattr(strategy, "execution_limits", None) is not None):
                    why = "STRATEGY_NOT_HOLDING" if held <= 0 else "STRATEGY_BLOCKS_ENTRY"
                    return self._skip(symbol, why, delta, action, fraction, reasons)
            if delta > 0:
                return "BUY_REQUEST", Decimal(1), ("PORTFOLIO_REBALANCE",)
            return "SELL_REQUEST", min(Decimal(1), -delta / held), ("PORTFOLIO_REBALANCE",)
        return self._skip(symbol, "WITHIN_BAND", delta, action, fraction, reasons)

    def _skip(self, symbol, why, delta, action, fraction, reasons):
        """Record why a due rebalance did not trade, so a report can answer 'why no rebalance?'."""
        self.policy_events.append({"at": iso(self.controller.previous_at), "kind": "REBALANCE_SKIPPED", "symbol": symbol,
                                   "reason": why, "target_gap_quote": str(delta)})
        return action, fraction, reasons

    def _needs_history(self):
        controller = self.controller
        return (controller.description["method"] != "equal" or controller.description["correlation_limit"] is not None
                or controller.portfolio_volatility_target is not None or controller.usdt_fx_risk
                or controller.expected_shortfall_limit is not None)

    def _record_close(self, s, session, close, risk_fx):
        """Append this market's closed bar to its return history (or reset it on a gap)."""
        controller, histories = self.controller, self.histories
        if histories[s] and close - histories[s][-1][0] != session.bar_spec.step:
            histories[s].clear()
            if self._needs_history():
                self.weights = {"status": "WARMING_UP", "weights": {symbol: "0" for symbol in self.symbols},
                                "risk_contribution_error": None}
                self.next_rebalance = close
                self.rebalance_pending.clear()
        decision = session.decisions[-1]
        if not controller.usdt_fx_risk or risk_fx is not None:
            scale = risk_fx if controller.usdt_fx_risk else Decimal(1)
            if controller.volatility_model == "parkinson-ewma":
                known = decision["bar_known"]
                histories[s].append((close, Decimal(decision["close"]) / scale,
                                     Decimal(known["high"]) / scale, Decimal(known["low"]) / scale))
            else:
                histories[s].append((close, Decimal(decision["close"]) / scale))
        histories[s] = histories[s][-(controller.description["lookback"] + 1):]

    def _close_bar(self, close):
        controller = self.controller
        self.risk(close)
        risk_fx = self.fx_at_close(close) if controller.usdt_fx_risk else None
        if controller.usdt_fx_risk and risk_fx is None:
            # A missing FX observation breaks the return chain for all
            # TMN assets. Never recycle target weights from stale risk data.
            for history in self.histories.values():
                history.clear()
            self.weights = controller.weights({})
            self.next_rebalance = close
            self.rebalance_pending.clear()
        if self.variable_routes:
            self._choose_routes(close)
            if self.entry_windows and not self.dynamic_routes:
                self._count_listed_routes()
        if self.rank_gate:
            active = set(self.trade_routes.values()) if self.variable_routes else self.sessions
            if self.entry_windows:
                active = self.listed.keys() & active
            self.rank_gate.advance(close, self.instruments, self.rules_for(close), active)
        for session in self.sessions.values():
            session.scan(close)
        if self.fx_rebalance is not None:
            self._request_fx_rebalance(close)
        stamp = iso(close)
        for s, session in self.sessions.items():
            if session.decisions and session.decisions[-1]["t"] == stamp and (not self.entry_windows or s in self.listed):
                self._record_close(s, session, close, risk_fx)
            if session.pending is None or session.pending.record["side"] != "BUY":
                self.reserved.pop(s, None)
        if close >= self.next_rebalance:
            self.weights = controller.weights(self.histories)
            if self.weights["status"] == "READY" and controller.description["rebalance"]:
                self.rebalance_pending.update(self.symbols)
            else:
                self.rebalance_pending.clear()
            self.next_rebalance = close + timedelta(seconds=controller.description["rebalance_seconds"])
            if self.policy is not None:
                self.policy_events.append({"at": iso(close), "kind": "TARGETS", **self.weights,
                                           "reserved_quote": str(sum(self.reserved.values(), Decimal(0)))})
        self.curve.append((iso(close), str(self.equity())))
        self.next_close = min((s.consolidator.cur["end"] for s in self.sessions.values() if s.consolidator.cur),
                              default=None)

    def close_through(self, at):
        """Advance every market to a common closed bar before any new quote."""
        # Close every market before revealing any later quote or settling its fills.
        while self.next_close is not None and self.next_close <= at:
            self._close_bar(self.next_close)

    def _feed(self, symbol, top):
        """One quote: marks, risk, the pending entry's funded share, the session itself and holdings bookkeeping."""
        book, quote, reserved = self.book, self.instruments[symbol].quote, self.reserved
        self.close_through(top.ts_avail)
        if self.entry_windows:
            self._advance_listings(top.ts_avail)
            if symbol not in self.listed and symbol not in self.held:
                return
        if self.rank_gate and (not self.entry_windows or symbol in self.listed):
            self.rank_gate.tops[symbol] = top
        if qualified(top):
            self.mark_order.setdefault(symbol, len(self.mark_order))
            self.marks[symbol] = top.bid
            self.mark_times[symbol] = top.ts_avail
        self.risk(top.ts_avail)
        session = self.sessions[symbol]
        if session.pending and session.pending.record["side"] == "BUY" and symbol in reserved:
            other_reserved = self.reserved_in(quote, exclude=symbol)
            capacity = max(Decimal(0), book.get(quote) - other_reserved - self.equity_in(quote) * self.controller.rates["cash_buffer"])
            session.pending.fraction = (min(Decimal(1), min(reserved[symbol], capacity) / book.get(quote))
                                        if book.get(quote) > 0 else Decimal(0))
        previous_cash = book.get(quote)
        reopenings = len(session.reopenings)
        session.feed(top)
        self._track_holding(symbol)
        current = session.consolidator.cur
        if current is not None:
            self.next_close = min(self.next_close, current["end"]) if self.next_close is not None else current["end"]
        if symbol in reserved:
            reserved[symbol] = max(Decimal(0), reserved[symbol] - max(Decimal(0), previous_cash - book.get(quote)))
            if session.pending is None:
                reserved.pop(symbol, None)
        if len(session.reopenings) > reopenings:
            self.curve.append((iso(top.ts_avail), str(self.equity())))

    def _track_holding(self, symbol):
        if self.variable_routes and self.trade_routes.get(self.instruments[symbol].base) != symbol:
            return
        if self.book.get(self.instruments[symbol].base) > 0:
            if symbol not in self.held:
                self.held.add(symbol)
                self.held_order[:] = sorted(self.held, key=self.mark_order.__getitem__)
        elif symbol in self.held:
            self.held.remove(symbol)
            self.held_order.remove(symbol)

    def _checkpoint(self, index, symbol, top):
        checkpoint = self.checkpoint
        record = (symbol, iso(top.ts_avail), top.bid, top.ask, top.bid_qty, top.ask_qty, sorted(top.flags), top.depth)
        if index > 1:
            self.prefix.update(b", ")
        self.prefix.update(json.dumps(record, sort_keys=True, default=str).encode())
        if index != checkpoint["quote_count"]:
            return
        sessions = self.sessions
        self.prefix.update(b"]")
        checkpoint.update(cursor=iso(top.ts_avail), prefix_digest=self.prefix.hexdigest(),
            pending_orders={s: session.pending.record["ref"] for s, session in sessions.items() if session.pending},
            state_digest=digest({"book": self.book, "reserved": self.reserved, "histories": self.histories,
                "weights": self.weights, "risk": self.risk_state, "policy": vars(self.controller),
                "rebalance_pending": sorted(self.rebalance_pending), "next_rebalance": self.next_rebalance,
                "marks": self.marks, "mark_times": self.mark_times, "curve": self.curve,
                **({"fx_data": self.fx_evidence.hexdigest()} if self.multicurrency else {}),
                **({"trade_routes": self.trade_routes} if self.variable_routes else {}),
                **({"listed": self.listed, "next_listing": self.next_listing} if self.entry_windows else {}),
                **({"fx_pending": self.fx_pending, "fx_orders": self.fx_orders,
                    "fx_quotas": {str(day): value for day, value in self.fx_quotas.items()}}
                   if self.fx_rebalance is not None else {}),
                **({"otc_pending": self.otc_fx.pending, "otc_used": sorted(self.otc_fx.used)} if self.otc_fx else {}),
                **({"mixed_residuals": self.otc_fx.residuals} if self.otc_fx and self.otc_fx.mixed else {}),
                **({"residual_recovery": self.otc_fx.unwind} if self.otc_fx and self.otc_fx.residual_attempts else {}),
                **({"margin": self.margin.checkpoint()} if self.margin else {}),
                **({"rank_gate": self.rank_gate.checkpoint()} if self.rank_gate else {}),
                "sessions": {s: {"cursor": session.cursor, "state": session.state, "decisions": session.decisions,
                    "orders": session.orders, "pending": asdict(session.pending) if session.pending else None,
                    "bar_events": session.bar_events, "rules": session.rule_snapshots,
                    "limit_trades": session.limit_trades,
                    **({"venue_stop": session.venue_stop, "stop_trades": session.venue_stop_trades}
                       if session.strategy.params.get("exit_venue_stop") else {})} for s, session in sessions.items()}}))

    def _quote_stream(self, symbol):
        for index, top in enumerate(self.portal.iter_tops(symbol, self.t0, self.t1)):
            yield top.ts_avail, index, symbol, top

    def run(self):
        checkpoint = self.checkpoint
        merged = heapq.merge(*(self._quote_stream(symbol) for symbol in self.symbols))
        index = 0
        for index, (_, _, symbol, top) in enumerate(merged, 1):
            counts = self.quote_counts[symbol]
            counts[0] += 1
            counts[1] += qualified(top)
            if symbol not in self.reference_routes:
                self._feed(symbol, top)
            if checkpoint is not None and index <= checkpoint["quote_count"]:
                self._checkpoint(index, symbol, top)
        if checkpoint is not None and index < checkpoint["quote_count"]:
            raise ValueError("portfolio checkpoint cursor exceeds observed quotes")
        self.close_through(self.t1)
        self.risk(self.t1)
        if self.fx_pending is not None:
            self._expire_fx_rebalance()
        for session in self.sessions.values():
            session.finish(self.t1)
        if not self.marks:
            raise ValueError("no qualified quotes for any portfolio market")
        return self._output()

    def _data_digest(self):
        """Hash the legacy canonical JSON shape without retaining its quote arrays."""
        hasher = hashlib.sha256(b"{")
        encode = json.JSONEncoder(default=str, sort_keys=True).encode
        for position, symbol in enumerate(sorted(self.symbols)):
            trades = self.sessions[symbol].limit_trades if self.cost.order_type == "limit" and symbol in self.sessions else []
            header = (", " if position else "") + encode(symbol) + ': {"limit_trades": ' + encode(trades) + ', "quotes": ['
            hasher.update(header.encode())
            for index, top in enumerate(self.portal.iter_tops(symbol, self.t0, self.t1)):
                record = (iso(top.ts_avail), top.bid, top.ask, top.bid_qty, top.ask_qty, sorted(top.flags),
                          *((top.depth,) if self.cost.walk_depth else ()))
                if index:
                    hasher.update(b", ")
                hasher.update(encode(record).encode())
            hasher.update(b"]}")
        hasher.update(b"}")
        return hasher.hexdigest()

    def _inputs(self, metadata, valuation):
        cost, sessions, symbols, controller = self.cost, self.sessions, self.symbols, self.controller
        first = next(iter(sessions.values())).strategy
        inputs = {"engine": LIMIT_ENGINE_VERSION if cost.order_type == "limit" else ENGINE_VERSION,
                  "kind": "portfolio", "portfolio_version": 5,
                  "symbols": symbols, "from": iso(self.t0), "to": iso(self.t1),
                  "resolution": self.resolution, "strategy": self.strategy_id, "params": first.params,
                  "strategy_version": first.version,
                  "config_hash": first.config_hash, "cash": str(self.cash), "cost": cost.describe(),
                  "rules_mode": self.rules_mode, "store": self.store,
                  "instruments": {s: asdict(inst) for s, inst in self.instruments.items()},
                  "snapshots": digest({s: [(d["t"], d["snapshot"]) for d in session.decisions]
                                       for s, session in sessions.items()}),
                  "rules": digest(self.rule_evidence), "metadata": digest(metadata), "valuation": digest(valuation),
                  "data": self._data_digest()}
        if self.policy is not None:
            inputs["policy"] = controller.description
        if self.portal.venue != "wallex":
            inputs["venue"] = self.portal.venue
        if self.universe_selection is not None:
            inputs["universe_selection"] = self.universe_selection
        if controller.usdt_fx_risk:
            inputs["fx_risk_data"] = digest([(iso(top.ts_avail), top.bid, top.ask, sorted(top.flags))
                                             for top in self.fx_risk_tops])
        inputs["portfolio_version"] = _portfolio_version(controller, cost, self.policy, self.universe_selection)
        if first.params.get("exit_venue_stop"):
            inputs["stop_trades"] = digest({s: session.venue_stop_trades for s, session in sessions.items()})
        if self.booked_accounting:
            inputs["trade_accounting"] = "booked-notional/1"
        if self.multicurrency:
            inputs["portfolio_version"] = 14
            inputs["cash_by_currency"] = {q: str(v) for q, v in sorted(self.opening_cash.items())}
            inputs["fx_data"] = self.fx_evidence.hexdigest()
        if self.reference_routes:
            inputs["portfolio_version"] = 15
            inputs["reference_routes"] = self.reference_routes
        if self.dynamic_routes:
            inputs.update(portfolio_version=16, dynamic_routes=True)
        if self.funding_result is not None:
            inputs.update(portfolio_version=17, funding_legs=self.funding_legs,
                          funding_evidence=digest(self.funding_result))
        if self.fx_rebalance is not None:
            version = 20 if "otc_routes" in self.fx_rebalance else 19 if self.otc_fx else 18
            inputs.update(portfolio_version=version, fx_rebalance=self.fx_rebalance, fx_execution_evidence=digest(self.fx_orders))
        if self.margin:
            inputs.update(portfolio_version=21, margin_positions=self.margin.requests, margin_data=self.margin.evidence)
        if self.otc_fx and self.otc_fx.mixed:
            inputs["portfolio_version"] = 23 if self.otc_fx.residual_attempts else 22
        if self.margin and any("entry_breakout_ticks" in request for request in self.margin.requests):
            inputs["portfolio_version"] = 24
        if self.margin and any("protection_edits" in request for request in self.margin.requests):
            inputs["portfolio_version"] = 25
        if self.rank_gate:
            inputs.update(portfolio_version=26, rank_gate=self.rank_gate.config, rank_evidence=digest(self.rank_gate.events))
        return inputs

    def _output(self):
        db, t0, t1, cash, quote = self.db, self.t0, self.t1, self.cash, self.quote
        end_equity = self.equity()
        metadata = {s: db.c.execute("SELECT valid_from, valid_to, spec, source FROM instrument_specs "
                                   "WHERE instrument_id=? AND valid_from<? AND (valid_to IS NULL OR valid_to>?) "
                                   "ORDER BY valid_from, rowid", (self.portal.instrument_key(s), iso(t1), iso(t0))).fetchall()
                    for s in self.symbols}
        fx_tops = _fx_tops(db, self.portal, t0, t1, "portfolio FX") if quote == "TMN" and self.portal.venue == "wallex" else []
        valuation = curve_valuation(quote, self.curve, t0, t1, fx_tops, self.rules_for)
        if self.multicurrency:
            valuation["conversion"] = {
                "pair": "USDTTMN", "basis": "observed mid", "start_at": iso(self.opening_fx.ts_avail),
                "end_at": iso(self.fx_mark.ts_avail), "end_status": self.valuation_state(t1),
            }
        first_fx, last_fx = valuation["start"], valuation["end"]
        inputs = self._inputs(metadata, valuation)
        markets = _market_summaries(self.sessions, self.instruments, None, self.book, self.marks, self.mark_times, t1,
                                    booked_accounting=self.booked_accounting, quote_counts=self.quote_counts,
                                    trade_routes=self.trade_routes if self.variable_routes else None)
        if inputs["params"].get("exit_venue_stop") == 3:
            for symbol, session in self.sessions.items():
                markets[symbol]["venue_stop"] = session.venue_stop_state()
        for symbol, route in self.reference_routes.items():
            count, usable = self.quote_counts[symbol]
            markets[symbol] = {"observations": count, "qualified": usable, "orders": [], "fills": 0,
                               "holding": "0", "mark_status": "REFERENCE_ONLY", **route}
        result = {"quote": quote, "start_cash": str(cash), "curve": self.curve, "orders": [], "markets": markets,
                  "valuation": valuation,
                  "balances": {k: str(v) for k, v in self.book.balances.items()},
                  "end": {"mark_time": iso(t1), "equity": str(end_equity), "net": str(end_equity - cash),
                          "valuation_status": self.valuation_state(t1)}}
        if self.booked_accounting:
            result["postings"] = self.book.postings
        if self.variable_routes:
            result["route_changes"] = self.route_changes
        if self.funding_result is not None:
            result["opening_funding"] = self.funding_result
        if self.fx_rebalance is not None:
            result["fx_orders"] = self.fx_orders
        if self.otc_fx and self.otc_fx.mixed:
            result["mixed_route_residuals"] = {asset: str(amount) for asset, amount in self.otc_fx.residuals.items()}
        if self.margin:
            result["margin_positions"] = self.margin.report()
            result["margin_risk_state"] = self.risk_state
        if self.rank_gate:
            result["rank_gate"] = self.rank_gate.events
        if self.policy is not None:
            result["policy_events"] = self.policy_events
            result["policy_state"] = {"risk": self.risk_state, "weights": self.weights, "clock": "Asia/Tehran",
                                      "scope": "Targets use prior closed returns. Optional rebalancing adjusts at subsequent decisions through normal fill/rule/cost checks; it does not assume unsettled sale proceeds. Risk exits use the next decision and executable quote. Limits can overshoot across gaps, fees or closures."}
        if quote == "USDT":
            result["end"]["net_usdt_eq"] = str(end_equity - cash)
        elif first_fx["rate"] and last_fx["rate"]:
            result["end"]["net_usdt_eq"] = str((end_equity / Decimal(last_fx["rate"])
                                                - cash / Decimal(first_fx["rate"])).quantize(Decimal("0.0001")))
        else:
            result["end"]["net_usdt_eq"] = None
        out = {"run_id": digest(inputs)[:16], "mode": "PORTFOLIO", "inputs": inputs, "result": result}
        from .reports import sampled_drawdown
        out["performance"] = {k: v for k, v in performance(out, sampled_drawdown(out)).items()
                              if k not in ("ledger", "trades")}
        out["outputs_digest"] = digest(result)[:16]
        return out


def _check_request(portal, symbols, t0, t1, cost, rules_mode, universe_selection, *, multicurrency=False):
    """Refuse malformed or over-budget portfolio requests before any replay state exists."""
    db = portal.db
    if not isinstance(symbols, list) or not 2 <= len(set(symbols)) == len(symbols) <= MAX_MARKETS:
        raise ValueError(f"a portfolio needs 2..{MAX_MARKETS} distinct markets")
    cost.assert_causal(t0)
    if rules_mode not in ("point-in-time", "today"):
        raise ValueError("rules_mode must be 'point-in-time' or 'today'")
    if universe_selection is not None:
        from .historical_universe import (
            select_universe,
            whole_spot_selection,
            whole_window_spot_selection,
        )

        schema = universe_selection.get("schema")
        if schema == "whole-spot-universe/1":
            actual = whole_spot_selection(db, t0, store=universe_selection["store"], venue=portal.venue)
        elif schema in ("whole-spot-universe/2", "watchlist-spot-universe/1"):
            actual = whole_window_spot_selection(db, t0, t1, store=universe_selection["store"],
                                                 watchlist=universe_selection.get("watchlist"), venue=portal.venue)
        elif portal.venue == "wallex":
            actual = select_universe(db, t0, quote_currency=universe_selection["quote_currency"],
                                     top_n=universe_selection["requested_top_n"],
                                     lookback_hours=universe_selection["lookback_hours"])
        else:
            raise ValueError("unsupported historical universe selection for this venue")
        if actual != universe_selection or actual.get("status", "AVAILABLE") != "AVAILABLE" or actual["symbols"] != symbols:
            raise ValueError("historical universe selection evidence changed")
    placeholders = ",".join("?" for _ in symbols)
    tables = [("book_top", "ts_avail")]
    if cost.order_type == "limit":
        tables.append(("trades", "ts_event"))
    for table, clock in tables:
        budget = (MAX_MULTICURRENCY_BOOK_OBSERVATIONS
                  if multicurrency and table == "book_top" and cost.order_type == "market" and not cost.walk_depth
                  else MAX_OBSERVATIONS)
        count = db.c.execute(f"SELECT count(*) FROM (SELECT 1 FROM {table} WHERE instrument_id IN ({placeholders}) "
                             f"AND {clock}>=? AND {clock}<? LIMIT ?)",
                             (*(portal.instrument_key(s) for s in symbols), iso(t0), iso(t1), budget + 1)).fetchone()[0]
        if count > budget:
            raise ValueError("portfolio observation budget exceeded; narrow the window")


def _rule_timeline(db, rules_mode):
    """Rules known at each historical decision time, plus the evidence of which versions were used."""
    svc = RuleService(db)
    today = svc.load()[1]
    rule_evidence, rule_cache, rule_times = {}, {}, []
    for (stamp,) in db.c.execute("SELECT ts FROM regime_events ORDER BY seq"):
        at = parse_ts(stamp)
        # Match the ledger's prefix fold even if a later event was backdated.
        rule_times.append(max(at, rule_times[-1]) if rule_times else at)

    def rules_for(at):
        """Load the market rules known at the supplied historical decision time."""
        version = "today" if rules_mode == "today" else bisect_right(rule_times, at)
        if version not in rule_cache:
            rules = today if rules_mode == "today" else svc.load(at)[1]
            rule_cache[version] = rules
            rule_evidence[str(version)] = {"known_from": None if version == "today" or not version else iso(rule_times[version - 1]),
                                           "fingerprint": digest([asdict(rule) for rule in rules])}
        return rule_cache[version]

    return rules_for, rule_evidence


def _fx_tops(db, portal, t0, t1, label):
    """USDTTMN quotes from a day before the window, within the observation budget."""
    count = db.c.execute("SELECT count(*) FROM (SELECT 1 FROM book_top WHERE instrument_id='wallex:USDTTMN' "
                         "AND ts_avail>=? AND ts_avail<? LIMIT ?)",
                         (iso(t0 - timedelta(days=1)), iso(t1), MAX_OBSERVATIONS + 1)).fetchone()[0]
    if count > MAX_OBSERVATIONS:
        raise ValueError(f"{label} observation budget exceeded; narrow the window")
    return portal.tops("USDTTMN", t0 - timedelta(days=1), t1)


def _cost_band(controller, cost, symbol, latest, delta, equity_now, band, policy_events):
    """Widen the rebalance band to the modeled round-trip cost; None when no fresh quote can price it."""
    if (latest is None or not qualified(latest)
            or latest.ts_avail > controller.previous_at
            or controller.previous_at - latest.ts_avail > timedelta(seconds=120)):
        policy_events.append({"at": iso(controller.previous_at), "kind": "REBALANCE_BAND",
                              "symbol": symbol, "status": "COST_UNAVAILABLE",
                              "requested": False})
        return None
    maker = cost.order_type == "limit"
    size = abs(delta) / (latest.bid if delta < 0 else latest.ask)
    measured = modeled_execution_cost(cost, symbol, controller.previous_at, size,
                                      latest.bid, latest.ask, maker=maker)
    fee_rate = Decimal(0) if cost.zero_fee else measured["fee_rate"] if measured is not None else (
        cost.maker_fee if maker else cost.fee_rate)
    uplift = measured["uplift_bps"] / 10000 if measured is not None else Decimal(0)
    modeled = 2 * fee_rate + (latest.ask - latest.bid) / latest.bid + uplift
    band = max(band, modeled)
    drift = abs(delta) / equity_now
    policy_events.append({
        "at": iso(controller.previous_at), "kind": "REBALANCE_BAND", "symbol": symbol,
        "status": "READY", "source_quote_time": iso(latest.ts_avail),
        "tracking_error_fraction": str(drift),
        "modeled_cost_fraction": str(modeled), "band_fraction": str(band),
        "estimated_turnover_quote": str(abs(delta)),
        "estimated_roundtrip_cost_quote": str(abs(delta) * modeled),
        "requested": drift > band, "cost_basis": "two fees, observed spread, optional dated uplift",
        "model": "causal-cost-aware-band/1"})
    return band


def _portfolio_version(controller, cost, policy, universe_selection):
    """Identity version: the newest input that changes how a portfolio replays (later versions win)."""
    version = 5
    if universe_selection is not None:
        version = 6
    if policy is not None and "portfolio_volatility_target" in controller.description:
        # New explicit portfolio risk input changes how targets are scaled.
        version = 7
    if controller.usdt_fx_risk:
        version = 9 if controller.portfolio_volatility_target is not None else 8
    if controller.expected_shortfall_limit is not None:
        version = 10
    if controller.cost_aware_rebalance:
        version = 11
    if cost.calibration is not None and "fractional_sizing_report_id" in cost.calibration:
        version = 12
    if controller.description["method"] == "hierarchical-risk-parity":
        version = 13
    return version


def _market_summaries(sessions, instruments, tops, book, marks, mark_times, t1, *, booked_accounting, quote_counts=None,
                      trade_routes=None):
    """Per-market fills, trades, holdings and mark freshness at the end of the window."""
    markets = {}
    postings = defaultdict(list)
    if booked_accounting:
        for posting in book.postings:
            postings[posting["ref"].partition("#")[0]].append(posting)
    for s, session in sessions.items():
        orders = session.orders
        ledger = trade_ledger(orders, instruments[s].base, quote=instruments[s].quote,
                              postings=postings[s] if booked_accounting else None)
        quantity = book.get(instruments[s].base)
        if trade_routes is not None and trade_routes.get(instruments[s].base) != s:
            quantity = Decimal(0)
        age = t1 - mark_times[s] if s in mark_times else None
        freshness = "UNAVAILABLE" if age is None else "STALE" if age > timedelta(seconds=120) else "CURRENT"
        count, usable = quote_counts[s] if quote_counts is not None else (len(tops[s]), sum(map(qualified, tops[s])))
        markets[s] = {"fills": sum(o["status"] == "FILLED" for o in orders), "orders": orders,
                      "observations": count, "qualified": usable,
                      "running_at": iso(session.running_at), "session_state": session.state,
                      "closed_trades": len(ledger["trades"]), "realized_pnl": str(sum((Decimal(t["pnl"]) for t in ledger["trades"]), Decimal(0))),
                      "holding": str(quantity), "last_bid": str(marks.get(s)) if s in marks else None,
                      "mark_time": iso(mark_times.get(s)), "mark_age_seconds": age.total_seconds() if age is not None else None,
                      "mark_status": freshness, **session.inventory_at(quantity, session.last_quote if freshness == "CURRENT" else None, t1)}
    return markets
