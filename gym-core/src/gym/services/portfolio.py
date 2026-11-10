"""Shared-cash paper portfolio: one strategy over several markets of one quote currency.

Each market keeps its own session (bars, decisions, rules, quotas), but all of them post to one CashBook,
so an entry in one market leaves less cash for the others. The selected allocation policy sizes entries
against current portfolio equity. Quotes from all markets are fed in availability order.
"""
import heapq
from bisect import bisect_left, bisect_right
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from ..adapters.store import MarketDB
from ..domain.bars import qualified
from ..domain.execution_costs import modeled_execution_cost
from ..domain.model import InstrumentId, QualityLimits, iso, parse_ts
from ..domain.performance import performance, trade_ledger
from ..domain.portfolio_policy import PortfolioPolicy
from ..domain.registry import create_strategy
from ..domain.rules import is_closed
from ..domain.sim import CashBook, CostModel
from ..domain.strategy import digest
from .data_portal import DataPortal, curve_valuation
from .rules import RuleService
from .session import ENGINE_VERSION, LIMIT_ENGINE_VERSION, PaperSession

MAX_OBSERVATIONS = 200_000
MAX_MARKETS = 500


def portfolio(db: MarketDB, symbols: list[str], t0: datetime, t1: datetime, *, resolution: str = "15min",
              cash: Decimal = Decimal(1000), cost: CostModel = CostModel(), strategy_id: str = "ema-trend",
              params: dict | None = None, rules_mode: str = "point-in-time", store: str = "live", policy: dict | None = None,
              checkpoint: dict | None = None, universe_selection: dict | None = None) -> dict:
    """Replay one shared-cash portfolio using a read-isolated chronological snapshot."""
    if db.c.in_transaction:
        raise ValueError("portfolio requires its own read snapshot")
    db.c.execute("BEGIN")
    try:
        return _portfolio(db, symbols, t0, t1, resolution=resolution, cash=cash, cost=cost,
                          strategy_id=strategy_id, params=params, rules_mode=rules_mode, store=store,
                          policy=policy, checkpoint=checkpoint, universe_selection=universe_selection)
    finally:
        db.c.rollback()


def _portfolio(db, symbols, t0, t1, *, resolution, cash, cost, strategy_id, params, rules_mode, store, policy, checkpoint,
               universe_selection):
    """Replay strictly prior market observations against a shared simulated cash book."""
    _check_request(db, symbols, t0, t1, cost, rules_mode, universe_selection)
    return _Replay(db, symbols, t0, t1, resolution=resolution, cash=cash, cost=cost, strategy_id=strategy_id,
                   params=params, rules_mode=rules_mode, store=store, policy=policy, checkpoint=checkpoint,
                   universe_selection=universe_selection).run()


class _Replay:
    """One portfolio replay: shared cash book, per-market paper sessions and the portfolio policy (finding E-1).

    The former closure state lives on the instance; each stage is a method small enough to review on its own.
    """

    def __init__(self, db, symbols, t0, t1, *, resolution, cash, cost, strategy_id, params, rules_mode, store, policy,
                 checkpoint, universe_selection):
        self.db, self.symbols, self.t0, self.t1 = db, symbols, t0, t1
        self.resolution, self.cash, self.cost, self.strategy_id = resolution, cash, cost, strategy_id
        self.rules_mode, self.store, self.policy, self.checkpoint = rules_mode, store, policy, checkpoint
        self.universe_selection = universe_selection
        self.portal = DataPortal(db)
        self.rules_for, self.rule_evidence = _rule_timeline(db, rules_mode)
        self.instruments = {s: self.portal.instrument(s) for s in symbols}
        quotes = {inst.quote for inst in self.instruments.values()}
        if len(quotes) != 1:
            raise ValueError("portfolio markets must share one quote currency")
        if len({inst.base for inst in self.instruments.values()}) != len(symbols):
            raise ValueError("portfolio markets must have distinct base assets")
        self.quote = quotes.pop()
        self.book = CashBook({self.quote: cash})
        self.marks: dict[str, Decimal] = {}
        self.mark_times, self.mark_order = {}, {}
        self.held, self.held_order = set(), []
        self.controller = PortfolioPolicy({} if policy is None else policy, symbols)
        if self.controller.usdt_fx_risk and self.quote != "TMN":
            raise ValueError("usdt_fx_risk is only applicable to TMN-quoted portfolios")
        self.fx_risk_tops = _fx_tops(db, self.portal, t0, t1, "portfolio FX risk") if self.controller.usdt_fx_risk else []
        self.fx_risk_times = [top.ts_avail for top in self.fx_risk_tops]
        self.weights = self.controller.weights({})
        self.reserved, self.histories, self.policy_events = {}, {s: [] for s in symbols}, []
        self.rebalance_pending = set()
        self.next_rebalance, self.risk_state, self.next_close = t0, None, None
        self.sessions, self.tops = {}, {}
        for s in symbols:
            strategy = create_strategy(strategy_id, params)
            session = PaperSession(self.portal, self.rules_for, strategy, s, t0, resolution, cash, cost)
            session.book = self.book
            session.allocation = lambda fraction, symbol=s: self.allocate(symbol, fraction)
            session.decision_filter = (lambda action, fraction, reasons, symbol=s:
                                       self.filter_decision(symbol, action, fraction, reasons))
            self.sessions[s], self.tops[s] = session, self.portal.tops(s, t0, t1)
            if strategy.params.get("entry_risk_bps"):
                session.risk_budget = lambda symbol=s: self.risk_budget(symbol)
        if checkpoint is not None and (type(checkpoint.get("quote_count")) is not int or
                not 1 <= checkpoint["quote_count"] <= sum(len(rows) for rows in self.tops.values())):
            raise ValueError("portfolio checkpoint cursor exceeds observed quotes")
        self.curve = []
        self.prefix = [] if checkpoint is not None else None

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
        book, instruments, marks = self.book, self.instruments, self.marks
        return book.get(self.quote) + sum((book.get(instruments[s].base) * marks[s] for s in self.held_order), Decimal(0))

    def valuation_state(self, at):
        """Fail portfolio valuation when a held market lacks a fresh mark."""
        return ("STALE_VALUATION" if any(at - self.mark_times[s] > timedelta(seconds=120) for s in self.held_order)
                else "CURRENT")

    def allocate(self, symbol, fraction):
        """Reserve only funded shared paper cash below the target risk budget."""
        book, quote, reserved = self.book, self.quote, self.reserved
        available = max(Decimal(0), book.get(quote) - sum(reserved.values(), Decimal(0))
                        - self.equity() * self.controller.rates["cash_buffer"])
        if available <= 0 or self.risk_state or self.weights["status"] != "READY":
            return Decimal(0)
        held = book.get(self.instruments[symbol].base) * self.marks.get(symbol, Decimal(0))
        target = max(Decimal(0), self.equity() * Decimal(self.weights["weights"][symbol]) - held)
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
        controller = self.controller
        if self.valuation_state(at) != "CURRENT":
            state = ("DRAWDOWN" if controller.drawdown_latched else "DAILY_LOSS" if controller.daily_latched
                     else "STALE_VALUATION")
        else:
            state = controller.observe(at, self.equity())
        if state != self.risk_state:
            self.risk_state = state
            self.policy_events.append({"at": iso(at), "kind": "RISK", "state": state, "equity": str(self.equity()),
                                       "reserved_quote": str(sum(self.reserved.values(), Decimal(0)))})
        if state:
            for s in tuple(self.reserved):
                session = self.sessions[s]
                if session.pending and session.pending.record["side"] == "BUY":
                    session.pending.record.update(status="CANCELLED", reason="PORTFOLIO_" + state)
                    session.pending = None
                    self.reserved.pop(s, None)

    def filter_decision(self, symbol, action, fraction, reasons):
        """Apply portfolio risk, allowed rebalance and modeled transaction costs."""
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
            return self._rebalance(symbol, action, fraction, reasons)
        return action, fraction, reasons

    def _rebalance(self, symbol, action, fraction, reasons):
        controller = self.controller
        self.rebalance_pending.discard(symbol)
        held = self.book.get(self.instruments[symbol].base) * self.marks.get(symbol, Decimal(0))
        target = self.equity() * Decimal(self.weights["weights"][symbol])
        delta = target - held
        band = controller.rates["rebalance_threshold"]
        if controller.cost_aware_rebalance and self.equity() > 0:
            band = _cost_band(controller, self.cost, symbol, self.sessions[symbol].last_quote, delta, self.equity(), band,
                              self.policy_events)
            if band is None:
                return action, fraction, reasons
        if self.equity() > 0 and abs(delta) > self.equity() * band:
            if delta > 0 and action != "BUY_REQUEST":
                strategy = self.sessions[symbol].strategy
                if (held <= 0 or not getattr(strategy, "entry_allowed", True)
                        or getattr(strategy, "execution_limits", None) is not None):
                    return action, fraction, reasons
            if delta > 0:
                return "BUY_REQUEST", Decimal(1), ("PORTFOLIO_REBALANCE",)
            return "SELL_REQUEST", min(Decimal(1), -delta / held), ("PORTFOLIO_REBALANCE",)
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
        for session in self.sessions.values():
            session.scan(close)
        stamp = iso(close)
        for s, session in self.sessions.items():
            if session.decisions and session.decisions[-1]["t"] == stamp:
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
        book, quote, reserved = self.book, self.quote, self.reserved
        self.close_through(top.ts_avail)
        if qualified(top):
            self.mark_order.setdefault(symbol, len(self.mark_order))
            self.marks[symbol] = top.bid
            self.mark_times[symbol] = top.ts_avail
        self.risk(top.ts_avail)
        session = self.sessions[symbol]
        if session.pending and session.pending.record["side"] == "BUY" and symbol in reserved:
            other_reserved = sum((value for s, value in reserved.items() if s != symbol), Decimal(0))
            capacity = max(Decimal(0), book.get(quote) - other_reserved - self.equity() * self.controller.rates["cash_buffer"])
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
        if self.book.get(self.instruments[symbol].base) > 0:
            if symbol not in self.held:
                self.held.add(symbol)
                self.held_order[:] = sorted(self.held, key=self.mark_order.__getitem__)
        elif symbol in self.held:
            self.held.remove(symbol)
            self.held_order.remove(symbol)

    def _checkpoint(self, index, symbol, top):
        checkpoint = self.checkpoint
        self.prefix.append((symbol, iso(top.ts_avail), top.bid, top.ask, top.bid_qty, top.ask_qty, sorted(top.flags),
                            top.depth))
        if index != checkpoint["quote_count"]:
            return
        sessions = self.sessions
        checkpoint.update(cursor=iso(top.ts_avail), prefix_digest=digest(self.prefix),
            pending_orders={s: session.pending.record["ref"] for s, session in sessions.items() if session.pending},
            state_digest=digest({"book": self.book, "reserved": self.reserved, "histories": self.histories,
                "weights": self.weights, "risk": self.risk_state, "policy": vars(self.controller),
                "rebalance_pending": sorted(self.rebalance_pending), "next_rebalance": self.next_rebalance,
                "marks": self.marks, "mark_times": self.mark_times, "curve": self.curve,
                "sessions": {s: {"cursor": session.cursor, "state": session.state, "decisions": session.decisions,
                    "orders": session.orders, "pending": asdict(session.pending) if session.pending else None,
                    "bar_events": session.bar_events, "rules": session.rule_snapshots,
                    "limit_trades": session.limit_trades} for s, session in sessions.items()}}))

    def run(self):
        checkpoint, tops = self.checkpoint, self.tops
        merged = heapq.merge(*([(x.ts_avail, i, s, x) for i, x in enumerate(tops[s])] for s in self.symbols))
        for index, (_, _, symbol, top) in enumerate(merged, 1):
            self._feed(symbol, top)
            if checkpoint is not None and index <= checkpoint["quote_count"]:
                self._checkpoint(index, symbol, top)
        self.close_through(self.t1)
        self.risk(self.t1)
        for session in self.sessions.values():
            session.finish(self.t1)
        if not self.marks:
            raise ValueError("no qualified quotes for any portfolio market")
        return self._output()

    def _inputs(self, metadata, valuation):
        cost, sessions, symbols, controller = self.cost, self.sessions, self.symbols, self.controller
        first = sessions[symbols[0]].strategy
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
                  "data": digest({s: {"quotes": [(iso(x.ts_avail), x.bid, x.ask, x.bid_qty, x.ask_qty, sorted(x.flags),
                                                   *((x.depth,) if cost.walk_depth else ())) for x in self.tops[s]],
                                      "limit_trades": sessions[s].limit_trades if cost.order_type == "limit" else []}
                                  for s in symbols})}
        if self.policy is not None:
            inputs["policy"] = controller.description
        if self.universe_selection is not None:
            inputs["universe_selection"] = self.universe_selection
        if controller.usdt_fx_risk:
            inputs["fx_risk_data"] = digest([(iso(top.ts_avail), top.bid, top.ask, sorted(top.flags))
                                             for top in self.fx_risk_tops])
        inputs["portfolio_version"] = _portfolio_version(controller, cost, self.policy, self.universe_selection)
        return inputs

    def _output(self):
        db, t0, t1, cash, quote = self.db, self.t0, self.t1, self.cash, self.quote
        end_equity = self.equity()
        metadata = {s: db.c.execute("SELECT valid_from, valid_to, spec, source FROM instrument_specs "
                                   "WHERE instrument_id=? AND valid_from<? AND (valid_to IS NULL OR valid_to>?) "
                                   "ORDER BY valid_from, rowid", ("wallex:" + s, iso(t1), iso(t0))).fetchall()
                    for s in self.symbols}
        fx_tops = _fx_tops(db, self.portal, t0, t1, "portfolio FX") if quote == "TMN" else []
        valuation = curve_valuation(quote, self.curve, t0, t1, fx_tops, self.rules_for)
        first_fx, last_fx = valuation["start"], valuation["end"]
        inputs = self._inputs(metadata, valuation)
        markets = _market_summaries(self.sessions, self.instruments, self.tops, self.book, self.marks, self.mark_times, t1)
        result = {"quote": quote, "start_cash": str(cash), "curve": self.curve, "orders": [], "markets": markets,
                  "valuation": valuation,
                  "balances": {k: str(v) for k, v in self.book.balances.items()},
                  "end": {"mark_time": iso(t1), "equity": str(end_equity), "net": str(end_equity - cash),
                          "valuation_status": self.valuation_state(t1)}}
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


def _check_request(db, symbols, t0, t1, cost, rules_mode, universe_selection):
    """Refuse malformed or over-budget portfolio requests before any replay state exists."""
    if not isinstance(symbols, list) or not 2 <= len(set(symbols)) == len(symbols) <= MAX_MARKETS:
        raise ValueError(f"a portfolio needs 2..{MAX_MARKETS} distinct markets")
    cost.assert_causal(t0)
    if rules_mode not in ("point-in-time", "today"):
        raise ValueError("rules_mode must be 'point-in-time' or 'today'")
    if universe_selection is not None:
        from .historical_universe import select_universe

        actual = select_universe(db, t0, quote_currency=universe_selection["quote_currency"],
                                 top_n=universe_selection["requested_top_n"],
                                 lookback_hours=universe_selection["lookback_hours"])
        if actual != universe_selection or actual["status"] != "AVAILABLE" or actual["symbols"] != symbols:
            raise ValueError("historical universe selection evidence changed")
    placeholders = ",".join("?" for _ in symbols)
    tables = [("book_top", "ts_avail")]
    if cost.order_type == "limit":
        tables.append(("trades", "ts_event"))
    for table, clock in tables:
        count = db.c.execute(f"SELECT count(*) FROM (SELECT 1 FROM {table} WHERE instrument_id IN ({placeholders}) "
                             f"AND {clock}>=? AND {clock}<? LIMIT ?)",
                             (*("wallex:" + s for s in symbols), iso(t0), iso(t1), MAX_OBSERVATIONS + 1)).fetchone()[0]
        if count > MAX_OBSERVATIONS:
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
    fee_rate = measured["fee_rate"] if measured is not None else (
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


def _market_summaries(sessions, instruments, tops, book, marks, mark_times, t1):
    """Per-market fills, trades, holdings and mark freshness at the end of the window."""
    markets = {}
    for s, session in sessions.items():
        orders = session.orders
        ledger = trade_ledger(orders, instruments[s].base)
        markets[s] = {"fills": sum(o["status"] == "FILLED" for o in orders), "orders": orders,
                      "observations": len(tops[s]), "qualified": sum(qualified(top) for top in tops[s]),
                      "running_at": iso(session.running_at), "session_state": session.state,
                      "closed_trades": len(ledger["trades"]), "realized_pnl": str(sum((Decimal(t["pnl"]) for t in ledger["trades"]), Decimal(0))),
                      "holding": str(book.get(instruments[s].base)), "last_bid": str(marks.get(s)) if s in marks else None,
                      "mark_time": iso(mark_times.get(s)), "mark_age_seconds": (t1 - mark_times[s]).total_seconds() if s in mark_times else None,
                      "mark_status": "UNAVAILABLE" if s not in mark_times else "STALE" if t1 - mark_times[s] > timedelta(seconds=120) else "CURRENT"}
    return markets
