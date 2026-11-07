"""Shared-cash paper portfolio: one strategy over several markets of one quote currency.

Each market keeps its own session (bars, decisions, rules, quotas), but all of them post to one CashBook,
so an entry in one market leaves less cash for the others. Every entry is sized to an equal target weight
of current portfolio equity. Quotes from all markets are fed in availability order.
"""
import heapq
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from ..adapters.store import MarketDB
from ..domain.bars import qualified
from ..domain.model import iso
from ..domain.performance import performance, trade_ledger
from ..domain.registry import create_strategy
from ..domain.sim import CashBook, CostModel
from ..domain.strategy import digest
from .data_portal import DataPortal
from .rules import RuleService
from .session import ENGINE_VERSION, PaperSession


def portfolio(db: MarketDB, symbols: list[str], t0: datetime, t1: datetime, *, resolution: str = "15min",
              cash: Decimal = Decimal(1000), cost: CostModel = CostModel(), strategy_id: str = "ema-trend",
              params: dict | None = None, rules_mode: str = "point-in-time", store: str = "live") -> dict:
    if not isinstance(symbols, list) or not 2 <= len(set(symbols)) == len(symbols) <= 8:
        raise ValueError("a portfolio needs 2..8 distinct markets")
    if rules_mode not in ("point-in-time", "today"):
        raise ValueError("rules_mode must be 'point-in-time' or 'today'")
    portal, svc = DataPortal(db), RuleService(db)
    today = svc.load()[1]
    rules_for = (lambda t: today) if rules_mode == "today" else (lambda t: svc.load(t)[1])
    instruments = {s: portal.instrument(s) for s in symbols}
    quotes = {inst.quote for inst in instruments.values()}
    if len(quotes) != 1:
        raise ValueError("portfolio markets must share one quote currency")
    quote = quotes.pop()
    book = CashBook({quote: cash})
    marks: dict[str, Decimal] = {}
    weight = Decimal(1) / len(symbols)

    def equity():
        return book.get(quote) + sum((book.get(instruments[s].base) * bid for s, bid in marks.items()), Decimal(0))

    def allocate(fraction):
        available = book.get(quote)
        if available <= 0:
            return Decimal(0)
        return min(Decimal(1), equity() * weight * fraction / available).quantize(Decimal("0.000001"), ROUND_DOWN)

    sessions, tops = {}, {}
    for s in symbols:
        strategy = create_strategy(strategy_id, params)
        session = PaperSession(portal, rules_for, strategy, s, t0, resolution, cash, cost)
        session.book, session.allocation = book, allocate
        sessions[s], tops[s] = session, portal.tops(s, t0, t1)
    curve, seen = [], {s: 0 for s in symbols}
    for _, _, symbol, top in heapq.merge(*([(x.ts_avail, i, s, x) for i, x in enumerate(tops[s])] for s in symbols)):
        if qualified(top):
            marks[symbol] = top.bid
        sessions[symbol].feed(top)
        if len(sessions[symbol].curve) > seen[symbol]:  # a decision bar closed: mark the whole portfolio
            seen[symbol] = len(sessions[symbol].curve)
            curve.append((sessions[symbol].curve[-1][0], str(equity())))
    for session in sessions.values():
        session.finish(t1)
    if not marks:
        raise ValueError("no qualified quotes for any portfolio market")
    end_equity = equity()
    inputs = {"engine": ENGINE_VERSION, "kind": "portfolio", "symbols": symbols, "from": iso(t0), "to": iso(t1),
              "resolution": resolution, "strategy": strategy_id, "params": sessions[symbols[0]].strategy.params,
              "config_hash": sessions[symbols[0]].strategy.config_hash, "cash": str(cash), "cost": cost.describe(),
              "rules_mode": rules_mode, "store": store,
              "data": digest([[(iso(x.ts_avail), x.bid, x.ask, x.bid_qty, x.ask_qty, sorted(x.flags)) for x in tops[s]] for s in symbols])}
    markets = {}
    for s, session in sessions.items():
        orders = session.orders
        ledger = trade_ledger(orders, instruments[s].base)
        markets[s] = {"fills": sum(o["status"] == "FILLED" for o in orders), "orders": orders,
                      "closed_trades": len(ledger["trades"]), "realized_pnl": str(sum((Decimal(t["pnl"]) for t in ledger["trades"]), Decimal(0))),
                      "holding": str(book.get(instruments[s].base)), "last_bid": str(marks.get(s)) if s in marks else None}
    result = {"quote": quote, "start_cash": str(cash), "curve": curve, "orders": [], "markets": markets,
              "balances": {k: str(v) for k, v in book.balances.items()},
              "end": {"mark_time": iso(t1), "equity": str(end_equity), "net": str(end_equity - cash)}}
    out = {"run_id": digest(inputs)[:16], "mode": "PORTFOLIO", "inputs": inputs, "result": result}
    from .reports import sampled_drawdown
    out["performance"] = {k: v for k, v in performance(out, sampled_drawdown(out)).items() if k not in ("ledger", "trades")}
    out["outputs_digest"] = digest(result)[:16]
    return out
