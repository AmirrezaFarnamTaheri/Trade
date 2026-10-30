"""Paper replay (A2): Data Portal over market.db, one strategy, simulator, baselines, gross-to-net waterfall."""
from __future__ import annotations

import json
from bisect import bisect_right
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ..adapters.store import MarketDB
from ..domain.bars import BarSpec, Consolidator, qualified
from ..domain.model import BookTop, InstrumentId, dec, iso, parse_ts
from ..domain.sim import CashBook, CostModel, Spec, market_order
from ..domain.strategy import BuyAndHold, EmaTrend, Proposal, Snapshot, digest
from .rules import RuleService

QUOTE_MAX_AGE = timedelta(seconds=120)
CENT = Decimal("1e-8")


class DataPortal:
    """Point-in-time reads: quotes in availability order; specs and rules as they were known at a time."""

    def __init__(self, db: MarketDB):
        self.db = db

    def tops(self, symbol: str, t0: datetime, t1: datetime) -> list[BookTop]:
        if not t0 < t1:
            raise ValueError(f"inverted or empty range {iso(t0)} .. {iso(t1)}")
        rows = self.db.c.execute("select ts_avail, bid, ask, bid_qty, ask_qty, flags from book_top where instrument_id=? "
                                 "and ts_avail>=? and ts_avail<? order by ts_avail, rowid", (f"wallex:{symbol}", iso(t0), iso(t1)))
        d = lambda x: None if x is None else dec(x)  # noqa: E731
        return [BookTop(symbol, parse_ts(r[0]), d(r[1]), d(r[2]), d(r[3]), d(r[4]), frozenset(filter(None, r[5].split(","))))
                for r in rows]

    def instrument(self, symbol: str) -> InstrumentId:
        r = self.db.c.execute("select base, quote from instruments where symbol=?", (symbol,)).fetchone()
        return InstrumentId.wallex(symbol, *r) if r else InstrumentId.wallex(symbol)

    def spec_at(self, symbol: str, t: datetime) -> Spec:
        r = self.db.c.execute("select spec from instrument_specs where instrument_id=? and valid_from<=? and "
                              "(valid_to is null or valid_to>?) order by valid_from desc limit 1",
                              (f"wallex:{symbol}", iso(t), iso(t))).fetchone()
        if not r:
            return Spec()  # unknown at that time: not enforced, and the report says so
        s = json.loads(r[0])
        opt = lambda k: None if s.get(k) in (None, "") else dec(s[k])  # noqa: E731
        return Spec(None if s.get("stepSize") is None else int(s["stepSize"]), opt("minQty"), opt("minNotional"))


def rate_at(tops: list[BookTop], t: datetime) -> tuple[Decimal, datetime] | None:
    """Derived valuation rate: MID of the last qualified quote at or before t. Not an executable price."""
    q = [x for x in tops[: bisect_right([x.ts_avail for x in tops], t)] if qualified(x)]
    return ((q[-1].bid + q[-1].ask) / 2, q[-1].ts_avail) if q else None


def run(portal: DataPortal, rules_for, strategy, symbol: str, t0: datetime, t1: datetime, resolution: str,
        cash: Decimal, cost: CostModel) -> dict:
    inst, spec = portal.instrument(symbol), BarSpec(resolution, "MID")
    tops = portal.tops(symbol, t0, t1)
    con, book = Consolidator(symbol, spec), CashBook({inst.quote: cash})
    last_q, decisions, orders, curve, quota = None, [], [], [], {}

    def on_bar(bar, i):
        q = last_q if last_q and bar.avail - last_q.ts_avail <= QUOTE_MAX_AGE else None
        snap = Snapshot(bar.avail, symbol, bar, q and q.bid, q and q.ask, q and q.ts_avail)
        holding = bool(q) and book.get(inst.base) * q.bid > book.equity(inst, q.bid) / 100
        action, fraction, reasons, fh = strategy.decide(snap, holding)
        p = Proposal(snap.id, bar.avail, bar.end + spec.step, symbol, action, fraction, reasons, fh)
        rec = {"t": iso(p.decision_time), "snapshot": p.snapshot_id, "close": str(bar.close), "action": p.action,
               "reasons": list(p.reasons), "features": p.feature_hash}
        if action in ("BUY_REQUEST", "SELL_REQUEST"):
            side = action.split("_")[0]
            o = market_order(book, inst, side, fraction, p.decision_time, q.ask if side == "BUY" else q.bid, tops, i,
                             cost, portal.spec_at(symbol, p.decision_time), rules_for(p.decision_time), quota,
                             f"{symbol}#{len(orders) + 1}")
            orders.append(o)
            rec["order"] = o["ref"]
        decisions.append(rec)
        if q:
            curve.append((iso(bar.avail), str(book.equity(inst, q.bid))))

    for i, top in enumerate(tops):
        for bar in con.scan(top.ts_avail):
            on_bar(bar, i)
        if qualified(top):
            con.update(top.ts_avail, spec.price(top))
            last_q = top
    for bar in con.scan(t1):
        on_bar(bar, len(tops))

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
            "decisions": decisions, "orders": orders, "postings": book.postings}


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
        first = next((x for x in u if qualified(x) and x.ts_avail >= t0), None)
        r0, r1 = rate_at(u, t0) or (first and ((first.bid + first.ask) / 2, first.ts_avail)), rate_at(u, t1)
        if r0 and r1:
            fx = {"pair": "USDTTMN", "start": str(r0[0]), "start_time": iso(r0[1]), "end": str(r1[0]), "end_time": iso(r1[1]),
                  "basis": "MID of last qualified quote; derived valuation rate, not executable"}
    for row in [main, *baselines.values()]:
        e = row.get("end")
        if not e:
            continue
        if inst.quote == "USDT":
            e["net_usdt_eq"] = e["net"]
        elif fx:
            e["net_usdt_eq"] = str((dec(e["equity"]) / dec(fx["end"]) - cash / dec(fx["start"])).quantize(Decimal("0.0001")))
    inputs = {"symbol": symbol, "from": iso(t0), "to": iso(t1), "resolution": resolution, "params": main["params"],
              "cash": str(cash), "cost": cost.describe(), "rules_mode": rules_mode, "store": store,
              "data": main["data_digest"], "ruleset_version_now": svc.load()[0]}
    out = {"run_id": digest(inputs)[:16], "mode": "PAPER", "inputs": inputs, "numeraire": "USDT-equivalent" if fx or inst.quote == "USDT" else inst.quote,
           "fx": fx, "result": main, "baselines": baselines, "warnings": warnings(main, store, rules_mode, portal, symbol, t0)}
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


def save(out: dict, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    p = root / f"{out['run_id']}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), "utf-8")
    return p


def text_report(out: dict) -> str:
    r, e = out["result"], out["result"]["end"] or {}
    q = r["quote"]
    f = lambda x: f"{Decimal(x):>16,.2f}"  # noqa: E731
    lines = [f"PAPER run {out['run_id']}  {r['strategy']} {r['params']} on {r['symbol']} {out['inputs']['resolution']}",
             f"window {out['inputs']['from']} .. {out['inputs']['to']}   rules: {out['inputs']['rules_mode']}   "
             f"outputs {out['outputs_digest']}",
             f"bars {r['bars']}  fills {r['fills']}  nonfills {r['nonfills'] or 0}  observations {r['observations']} "
             f"(qualified {r['qualified']})", ""]
    if e:
        lines.append(f"Gross-to-net waterfall ({q}, mark-to-bid at {e['mark_time']}):")
        for k, v in e["waterfall"].items():
            lines.append(f"  {k:<16}{f(v)}")
        lines.append(f"  {'equity':<16}{f(e['equity'])}   net liquidation estimate (modeled) {f(e['net_liquidation_estimate']).strip()}")
    lines += ["", f"vs baselines (same window, cash, costs; net in {q}" + (", and USDT-equivalent)" if out["fx"] or q == "USDT" else ")")]
    for name, b in {"strategy": r, **out["baselines"]}.items():
        if "unavailable" in b:
            lines.append(f"  {name:<12} unavailable: {b['unavailable']}")
        else:
            be = b["end"]
            lines.append(f"  {name:<12}{f(be['net'])} {q}" + (f"   {f(be['net_usdt_eq'])} USDT-eq" if "net_usdt_eq" in be else ""))
    if out["fx"]:
        lines.append(f"  USDT-eq via {out['fx']['pair']} {out['fx']['start']} -> {out['fx']['end']} ({out['fx']['basis']})")
    lines += ["", *("! " + w for w in out["warnings"])]
    return "\n".join(lines)
