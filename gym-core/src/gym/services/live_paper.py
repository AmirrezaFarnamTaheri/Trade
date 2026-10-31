"""Poll the collector's local database; elapsed duration starts after strategy warmup."""
import asyncio
from datetime import timedelta
from decimal import Decimal

from ..domain.model import iso
from ..domain.sim import CostModel
from ..domain.strategy import EmaTrend, digest
from .collector import now_utc
from ..adapters.run_store import save_run
from .data_portal import DataPortal
from .paper import session_result
from .rules import RuleService
from .session import ENGINE_VERSION, PaperSession


async def watch(db, root, symbol, duration, resolution, fast, slow, cash, demo=False, subscriptions=()):
    if duration <= 0:
        raise ValueError("duration must be positive")
    start, tops = now_utc(), []
    portal, svc, cost = DataPortal(db), RuleService(db), CostModel()
    session = PaperSession(portal, lambda t: svc.load(t)[1], EmaTrend(fast, slow), symbol, start, resolution, cash, cost,
                           subscriptions)
    reason = None
    print("WARMING_UP: run the collector separately; duration begins at RUNNING.", flush=True)
    try:
        while True:
            now = now_utc()
            for top in portal.tops(symbol, session.cursor, now):
                if top.ts_avail > session.cursor:
                    if session.running_at and top.ts_avail >= session.running_at + timedelta(seconds=duration) and session.state != "FINISHING":
                        session.transition("FINISHING", session.running_at + timedelta(seconds=duration))
                    session.feed(top)
                    tops.append(top)
            if session.running_at and now >= session.running_at + timedelta(seconds=duration) and session.state != "FINISHING":
                session.transition("FINISHING", session.running_at + timedelta(seconds=duration))
            if session.state != "FINISHING":
                session.scan(now)
            if session.running_at and now >= session.running_at + timedelta(seconds=duration):
                if session.state != "FINISHING":
                    session.transition("FINISHING", now)
                session.settle(None, now)
                if not session.pending:
                    break
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        reason = "Operator interrupted (Ctrl+C)"
    except Exception as exc:
        reason = f"Session error: {type(exc).__name__}: {exc}"
    finally:
        session.finish(now_utc(), reason)
        result = session_result(session, tops, cash)
        inputs = {"engine": ENGINE_VERSION, "kind": "live-session", "symbol": symbol, "from": iso(start),
                  "to": iso(session.cursor), "resolution": resolution,
                  "subscriptions": list(dict.fromkeys((resolution, *subscriptions))),
                  "params": {"fast": fast, "slow": slow},
                  "cash": str(cash), "cost": cost.describe(), "rules_mode": "point-in-time",
                  "store": "demo" if demo else "live", "data": result["data_digest"]}
        out = {"run_id": digest(inputs)[:16], "mode": "PAPER", "inputs": inputs, "result": result,
               "baselines": {}, "fx": None, "numeraire": result["quote"],
               "outputs_digest": digest(result)[:16],
               "warnings": ["Live paper session: baselines/USDT attribution require a separate matched replay.",
                            "Assumed example fees; no depth/queue-position model; no capital authorization."]}
        if demo:
            out["warnings"].append("DEMO: never gate evidence.")
        path = save_run(out, root)
        print(f"{session.state}: {path}", flush=True)
    return out
