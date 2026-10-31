"""Paper replay orchestration, matched baselines and portfolio result aggregation."""
from datetime import datetime, timedelta
from decimal import Decimal

from ..adapters.store import MarketDB
from ..domain.bars import qualified
from ..domain.model import InstrumentId, dec, iso
from ..domain.rules import is_closed
from ..domain.sim import CostModel, Spec
from ..domain.strategy import BuyAndHold, EmaTrend, digest
from .data_portal import DataPortal, rate_at
from .rules import RuleService
from .session import ENGINE_VERSION

CENT = Decimal("1e-8")


def run(portal: DataPortal, rules_for, strategy, symbol: str, t0: datetime, t1: datetime, resolution: str,
        cash: Decimal, cost: CostModel) -> dict:
    from .session import PaperSession

    inst = portal.instrument(symbol)
    tops = portal.tops(symbol, t0, t1)
    session = PaperSession(portal, rules_for, strategy, symbol, t0, resolution, cash, cost)
    for top in tops:
        session.feed(top)
    session.finish(t1)
    return session_result(session, tops, cash)


def session_result(session, tops, cash):
    from .session import outcome_marks

    book, last_q, inst = session.book, session.last_quote, session.instrument
    strategy, symbol, cost = session.strategy, session.symbol, session.cost
    decisions, orders, curve = session.decisions, session.orders, session.curve
    outcome_marks(decisions, tops, session.cursor)

    fills = [o for o in orders if o["status"] == "FILLED"]
    # Reported to 1e-8 so the components add up to net exactly; directional is the remainder.
    costs = {k: sum((o["costs"][k] for o in fills), Decimal(0)).quantize(CENT) for k in ("spread", "fees", "latency_drift")}
    end = None
    if last_q:
        eq = book.equity(inst, last_q.bid)
        net = (eq - cash).quantize(CENT)
        end = {"mark_time": iso(last_q.ts_avail), "bid": str(last_q.bid), "equity": str(eq), "net": str(net),
               # Modeled, separately: what selling the holding at that bid would leave after the fee. Not done.
               "net_liquidation_estimate": str(book.get(inst.quote) + book.get(inst.base) * last_q.bid * (1 - cost.fee_rate)),
               "waterfall": {"directional": str(net + sum(costs.values())), **{k: str(-v) for k, v in costs.items()},
                             "net": str(net)}}
        for o in fills:
            o["costs"] = {k: str(v) for k, v in o["costs"].items()}
    nonfills: dict[str, int] = {}
    for o in orders:
        if o["status"] == "NONFILL":
            nonfills[o["reason"]] = nonfills.get(o["reason"], 0) + 1
    return {"strategy": strategy.name, "params": strategy.params, "symbol": symbol, "quote": inst.quote, "base": inst.base,
            "start_cash": str(cash), "observations": len(tops), "qualified": sum(map(qualified, tops)),
            "data_digest": digest([(iso(x.ts_avail), x.bid, x.ask, sorted(x.flags)) for x in tops]),
            "bars": len(decisions), "fills": len(fills), "nonfills": nonfills, "end": end,
            "balances": {k: str(v) for k, v in book.balances.items()}, "curve": curve,
            "decisions": decisions, "orders": orders, "postings": book.postings,
            "session": {"state": session.state, "events": session.events, "cursor": iso(session.cursor),
                        "running_at": session.running_at and iso(session.running_at), "skipped": session.skipped,
                        "reopenings": session.reopenings}}


def paper(db: MarketDB, symbol: str, t0: datetime, t1: datetime, *, resolution: str = "15min", fast: int = 8,
          slow: int = 21, cash: Decimal = Decimal(1000), cost: CostModel = CostModel(), rules_mode: str = "point-in-time",
          store: str = "live") -> dict:
    """A replayable paper run plus matched baselines. Same inputs give the same run_id and outputs."""
    if rules_mode not in ("point-in-time", "today"):
        raise ValueError("rules_mode must be 'point-in-time' or 'today'")
    portal, svc = DataPortal(db), RuleService(db)
    today = svc.load()[1]
    rules_for = (lambda t: today) if rules_mode == "today" else (lambda t: svc.load(t)[1])
    inst = portal.instrument(symbol)
    main = run(portal, rules_for, EmaTrend(fast, slow), symbol, t0, t1, resolution, cash, cost)
    if main["qualified"] == 0:
        raise ValueError(f"no qualified {symbol} quotes between {iso(t0)} and {iso(t1)}")
    base_syms = {f"hold {inst.base}": symbol}
    if inst.quote == "TMN":
        base_syms["hold USDT"] = "USDTTMN"
    if inst.base != "BTC":
        base_syms["hold BTC"] = "BTC" + inst.quote
    baselines = {f"hold {inst.quote}": {"end": {"equity": str(cash), "net": "0"}, "fills": 0}}
    for name, s in base_syms.items():
        b = run(portal, rules_for, BuyAndHold(), s, t0, t1, resolution, cash, cost)
        baselines[name] = {k: b[k] for k in ("symbol", "end", "fills", "nonfills")} if b["end"] else {"unavailable": f"no qualified {s} quotes"}

    # Headline numeraire: USDT-equivalent through a disclosed, non-executable valuation rate.
    fx = None
    if inst.quote == "TMN":
        u = portal.tops("USDTTMN", t0 - timedelta(days=1), t1)
        r0, r1 = rate_at(u, t0), rate_at(u, t1)
        if r0 and r1:
            fx = {"pair": "USDTTMN", "start": str(r0[0]), "start_time": iso(r0[1]), "end": str(r1[0]), "end_time": iso(r1[1]),
                  "basis": "MID of last qualified quote; derived valuation rate, not executable"}
            # While USDT/IRT is closed the factor is the last pre-closure mid: usable for valuation, labeled stale.
            usdt = InstrumentId.wallex("USDTTMN")
            for edge, at in (("start", t0), ("end", t1)):
                fx[f"{edge}_status"] = "STALE_CLOSED" if is_closed(rules_for(at), usdt, at) else "LIVE"
    for row in [main, *baselines.values()]:
        e = row.get("end")
        if not e:
            continue
        if inst.quote == "USDT":
            e["net_usdt_eq"] = e["net"]
        elif fx:
            e["net_usdt_eq"] = str((dec(e["equity"]) / dec(fx["end"]) - cash / dec(fx["start"])).quantize(Decimal("0.0001")))
    inputs = {"engine": ENGINE_VERSION, "symbol": symbol, "from": iso(t0), "to": iso(t1), "resolution": resolution, "params": main["params"],
              "cash": str(cash), "cost": cost.describe(), "rules_mode": rules_mode, "store": store,
              "data": main["data_digest"], "ruleset_version_now": svc.load()[0]}
    out = {"run_id": digest(inputs)[:16], "mode": "PAPER", "inputs": inputs, "numeraire": "USDT-equivalent" if fx or inst.quote == "USDT" else inst.quote,
           "fx": fx, "result": main, "baselines": baselines, "warnings": warnings(main, store, rules_mode, portal, symbol, t0)}
    if fx and "STALE_CLOSED" in (fx["start_status"], fx["end_status"]):
        out["warnings"].append("USDT/IRT was closed at a valuation boundary: the FX factor is STALE_CLOSED (last pre-closure mid).")
    if inst.quote == "TMN" and fx is None:
        out["warnings"].append("USDT-equivalent unavailable: no point-in-time FX valuation at the window start/end.")
    out["outputs_digest"] = digest({k: out[k] for k in ("result", "baselines", "fx")})[:16]
    return out


def warnings(main, store, rules_mode, portal, symbol, t0) -> list[str]:
    w = []
    if store == "demo":
        w.append("DEMO data: synthetic quotes. Not evidence; can never reach a gate report.")
    if rules_mode == "today":
        w.append("Re-run under TODAY's rules, not the rules known at each decision.")
    if portal.spec_at(symbol, t0) == Spec():
        w.append("Precision and minimums unknown at the start of the window; not enforced.")
    if main["fills"] < 30:
        w.append(f"Only {main['fills']} fills: far too few to claim anything about this strategy.")
    w.append("Fee rate 0.2% is the documentation example and fee currency is an assumption; confirm the account's real fees.")
    return w
