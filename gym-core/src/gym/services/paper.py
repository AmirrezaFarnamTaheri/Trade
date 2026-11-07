"""Paper replay orchestration, matched baselines and portfolio result aggregation."""
from datetime import datetime, timedelta
from decimal import Decimal

from ..adapters.store import MarketDB
from ..domain.bars import qualified
from ..domain.model import InstrumentId, QualityLimits, dec, iso
from ..domain.registry import create_strategy
from ..domain.rules import is_closed
from ..domain.sim import CostModel, Spec
from ..domain.strategy import BuyAndHold, digest
from .data_portal import DataPortal, rate_at
from .rules import RuleService
from .session import ENGINE_VERSION

CENT = Decimal("1e-8")


class PaperDataUnavailable(ValueError):
    """A paper replay has no qualified market observations."""


def run(portal: DataPortal, rules_for, strategy, symbol: str, t0: datetime, t1: datetime, resolution: str,
        cash: Decimal, cost: CostModel, subscriptions=(), reference_symbol=None) -> dict:
    from .session import PaperSession

    tops = portal.tops(symbol, t0, t1)
    session = PaperSession(portal, rules_for, strategy, symbol, t0, resolution, cash, cost, subscriptions, reference_symbol)
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
            "data_digest": digest([(iso(x.ts_avail), x.bid, x.ask, x.bid_qty, x.ask_qty, sorted(x.flags),
                                    *((x.depth,) if cost.walk_depth else ())) for x in tops]
                                  + ([("limit_trades", session.limit_trades)] if cost.order_type == "limit" else [])),
            "bars": len(decisions), "fills": len(fills), "nonfills": nonfills, "end": end,
            "balances": {k: str(v) for k, v in book.balances.items()}, "curve": curve,
            "decisions": decisions, "orders": orders, "postings": book.postings,
            "session": {"state": session.state, "events": session.events, "cursor": iso(session.cursor),
                        "running_at": session.running_at and iso(session.running_at), "skipped": session.skipped,
                        "subscriptions": list(session.closes.by_resolution), "bar_events": session.bar_events,
                        "reopenings": session.reopenings, "rule_snapshots": session.rule_snapshots}}


def paper(db: MarketDB, symbol: str, t0: datetime, t1: datetime, *, resolution: str = "15min", fast: int = 8,
          slow: int = 21, cash: Decimal = Decimal(1000), cost: CostModel = CostModel(), rules_mode: str = "point-in-time",
          store: str = "live", subscriptions=(), strategy_id="ema-trend", params=None, reference_symbol=None, outages=()) -> dict:
    """A replayable paper run plus matched baselines. Same inputs give the same run_id and outputs."""
    if rules_mode not in ("point-in-time", "today"):
        raise ValueError("rules_mode must be 'point-in-time' or 'today'")
    if any(not t0 <= start < end <= t1 for start, end in outages):
        raise ValueError("outage intervals must be inside the replay window")
    portal, svc = DataPortal(db, excluded=outages), RuleService(db)
    today = svc.load()[1]
    rules_for = (lambda t: today) if rules_mode == "today" else (lambda t: svc.load(t)[1])
    inst = portal.instrument(symbol)
    strategy = create_strategy(strategy_id, {"fast": fast, "slow": slow} if params is None and strategy_id == "ema-trend" else params)
    subscriptions = tuple(dict.fromkeys((resolution, *subscriptions, *getattr(strategy, "required_resolutions", ()))))
    reference_symbol = reference_symbol or getattr(strategy, "reference_symbol", None)
    main = run(portal, rules_for, strategy, symbol, t0, t1, resolution, cash, cost, subscriptions, reference_symbol)
    if main["qualified"] == 0:
        raise PaperDataUnavailable(f"no qualified {symbol} quotes between {iso(t0)} and {iso(t1)}")
    base_syms = {f"hold {inst.base}": symbol}
    if inst.quote == "TMN":
        base_syms["hold USDT"] = "USDTTMN"
    if inst.base != "BTC":
        base_syms["hold BTC"] = "BTC" + inst.quote
    baselines = {f"hold {inst.quote}": {"end": {"equity": str(cash), "net": "0"}, "fills": 0}}
    baseline_evidence = {}
    for name, s in base_syms.items():
        b = run(portal, rules_for, BuyAndHold(), s, t0, t1, resolution, cash, cost, subscriptions)
        # Keep raw-data and rule/spec-dependent results before reducing the baseline display.
        baseline_evidence[s] = digest(b)
        baselines[name] = {k: b[k] for k in ("symbol", "end", "fills", "nonfills")} if b["end"] else {"unavailable": f"no qualified {s} quotes"}

    # Headline numeraire: USDT-equivalent through a disclosed, non-executable valuation rate.
    fx = None
    if inst.quote == "TMN":
        u = portal.tops("USDTTMN", t0 - timedelta(days=1), t1)
        r0, r1 = rate_at(u, t0), rate_at(u, t1)
        if r0 and r1:
            fx = {"pair": "USDTTMN", "start": str(r0[0]), "start_time": iso(r0[1]), "end": str(r1[0]), "end_time": iso(r1[1]),
                  "basis": "MID of last qualified quote; derived valuation rate, not executable"}
            usdt = InstrumentId.wallex("USDTTMN")
            for edge, at, rate in (("start", t0, r0), ("end", t1, r1)):
                age = (at - rate[1]).total_seconds()
                fx[f"{edge}_age_seconds"] = age
                if is_closed(rules_for(at), usdt, at):
                    fx[f"{edge}_status"] = "STALE_CLOSED"
                else:
                    fx[f"{edge}_status"] = "STALE" if age > QualityLimits().stale_s else "LIVE"
    for row in [main, *baselines.values()]:
        e = row.get("end")
        if not e:
            continue
        if inst.quote == "USDT":
            e["net_usdt_eq"] = e["net"]
        elif fx:
            e["net_usdt_eq"] = str((dec(e["equity"]) / dec(fx["end"]) - cash / dec(fx["start"])).quantize(Decimal("0.0001")))
    metadata = portal.metadata_at(symbol, t0)
    metadata_ref = None if metadata is None else {
        "version": metadata["version"], "valid_from": iso(metadata["valid_from"]),
        "valid_to": metadata["valid_to"] and iso(metadata["valid_to"]), "source": metadata["source"],
        "raw_digest": metadata["raw_digest"],
    }
    inputs = {"engine": ENGINE_VERSION, "symbol": symbol, "from": iso(t0), "to": iso(t1), "resolution": resolution,
              "subscriptions": list(subscriptions), "params": main["params"],
              "strategy": strategy.name, "strategy_version": strategy.version, "config_hash": strategy.config_hash,
              "reference_symbol": reference_symbol,
              "cash": str(cash), "cost": cost.describe(), "rules_mode": rules_mode, "store": store,
              "data": main["data_digest"],
              "auxiliary_evidence": {"baselines": baseline_evidence, "fx": fx},
              "snapshots": digest([(d["t"], d["snapshot"]) for d in main["decisions"]]),
              "metadata": metadata_ref, "ruleset_version_now": svc.load()[0],
              "modeled_feed_outages": [(iso(start), iso(end)) for start, end in outages]}
    rank = ranking(main, baselines)
    out = {"run_id": digest(inputs)[:16], "mode": "PAPER", "inputs": inputs, "numeraire": "USDT-equivalent" if fx or inst.quote == "USDT" else inst.quote,
           "fx": fx, "result": main, "baselines": baselines, "ranking": rank,
           "warnings": warnings(main, store, rules_mode, portal, symbol, t0, cost)}
    if fx and "STALE_CLOSED" in (fx["start_status"], fx["end_status"]):
        out["warnings"].append("USDT/IRT was closed at a valuation boundary: the FX factor is STALE_CLOSED (last pre-closure mid).")
    if fx and "STALE" in (fx["start_status"], fx["end_status"]):
        out["warnings"].append(
            "USDT/IRT FX factor is STALE at an open-market valuation boundary "
            f"(start age {fx['start_age_seconds']:g}s; end age {fx['end_age_seconds']:g}s). "
            "USDT-equivalent results and ranking use the last known MID, not a current price.")
    if inst.quote == "TMN" and fx is None:
        out["warnings"].append("USDT-equivalent unavailable: no point-in-time FX valuation at the window start/end.")
    out["outputs_digest"] = digest({k: out[k] for k in ("result", "baselines", "ranking", "fx")})[:16]
    return out


def ranking(main, baselines, main_name="strategy"):
    """Matched ranking view; zero-trade results remain visible but are not active strategies."""
    rows = []
    for name, record in {main_name: main, **baselines}.items():
        end = record.get("end")
        if not end:
            rows.append({"name": name, "status": "UNAVAILABLE", "reason": record.get("unavailable")})
            continue
        fills = record.get("fills", 0)
        rows.append({"name": name, "status": "AVAILABLE", "fills": fills,
                     "classification": "ACTIVE" if fills else "ABSTAINER",
                     "net_quote": end["net"], "quote": main["quote"],
                     "net_usdt_eq": end.get("net_usdt_eq")})
    active = [row.copy() for row in rows
              if row.get("classification") == "ACTIVE" and row.get("net_usdt_eq") is not None]
    active.sort(key=lambda row: (Decimal(row["net_usdt_eq"]), row["name"]), reverse=True)
    for i, row in enumerate(active, 1):
        row["rank"] = i
    return {"headline": "USDT-equivalent", "active": active,
            "abstainers": [row for row in rows if row.get("classification") == "ABSTAINER"], "all": rows,
            "note": "Zero-trade runs are retained as abstainers and excluded from active-trading rank."}


def warnings(main, store, rules_mode, portal, symbol, t0, cost) -> list[str]:
    w = []
    if store == "demo":
        w.append("DEMO data: synthetic quotes. Not evidence; can never reach a gate report.")
    if rules_mode == "today":
        w.append("Re-run under TODAY's rules, not the rules known at each decision.")
    metadata = portal.metadata_at(symbol, t0)
    if metadata is None:
        w.append("Public instrument metadata was unavailable at the window start; fees, flags and capacity remain UNKNOWN.")
    else:
        missing = [name for name in ("isZeroFee", "isMarketTypeEnable") if name not in metadata["raw"]]
        if missing:
            w.append("Historical public metadata leaves " + ", ".join(missing) + " UNKNOWN; current values were not backfilled.")
    if portal.spec_at(symbol, t0) == Spec():
        w.append("Precision and minimums unknown at the start of the window; not enforced.")
    compacted = portal.db.c.execute("SELECT detail FROM quality_events WHERE flag='COMPACTED' AND instrument_id IS NULL "
                                    "AND substr(detail, 8, 27) > ? ORDER BY rowid DESC LIMIT 1", (iso(t0),)).fetchone()
    if compacted:
        w.append(f"Quotes in this window were compacted ({compacted[0]}); intra-bucket quote changes are gone. Raw archive keeps them.")
    if main["fills"] < 30:
        w.append(f"Only {main['fills']} fills: far too few to claim anything about this strategy.")
    w.append(f"Modeled fee rate {cost.fee_rate * 100}% per side; fee currency is an assumption. Confirm the account and pair fee.")
    if main["strategy"] in ("trend-pullback","adaptive-channel"):
        w.append("Compound paper policy: entry spread and displayed top-depth participation are checked at decision and fill; no queue or full-depth fill model. Baselines retain their original unconstrained execution model.")
        w.append("Stops and the session drawdown lock are evaluated at closed-bar decisions; gaps, minimums or insufficient displayed depth can prevent an exit or exceed the risk budget. No venue stop order or funded authority.")
    return w
