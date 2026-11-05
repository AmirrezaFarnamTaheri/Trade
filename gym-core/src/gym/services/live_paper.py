"""Poll the collector's local database; elapsed duration starts after strategy warmup."""
import asyncio
from datetime import timedelta

from ..adapters.run_store import save_run
from ..domain.model import iso
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .collector import now_utc
from .data_portal import DataPortal
from .paper import session_result
from .rules import RuleService
from .session import ENGINE_VERSION, PaperSession


async def watch(db, root, symbol, duration, resolution, fast, slow, cash, demo=False, subscriptions=(),
                cost=None, strategy_id="ema-trend", params=None):
    if duration <= 0:
        raise ValueError("duration must be positive")
    start, tops = now_utc(), []
    portal, svc, cost = DataPortal(db), RuleService(db), cost or CostModel()
    strategy = create_strategy(strategy_id, {"fast": fast, "slow": slow} if params is None and strategy_id == "ema-trend" else params)
    session = PaperSession(portal, lambda t: svc.load(t)[1], strategy, symbol, start, resolution, cash, cost,
                           subscriptions)
    reason, last_clock, regressed_at = None, start, None
    print("WARMING_UP: run the collector separately; duration begins at RUNNING.", flush=True)
    try:
        while True:
            now = now_utc()
            if now < last_clock:
                regressed_at = now
                raise ValueError("Clock regression during paper observation")
            last_clock = now
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
    except Exception as exc:  # noqa: BLE001 - every paper failure must retain an aborted run
        reason = f"Session error: {type(exc).__name__}: {exc}"
    finally:
        observed_finish = now_utc()
        last_processed = max(last_clock, session.cursor)
        if observed_finish < last_processed and regressed_at is None:
            regressed_at = observed_finish
        clock_regression = regressed_at is not None
        if clock_regression:
            reason = (reason + "; " if reason else "") + "Clock regression: session aborted; original wall-clock readings are retained."
        session.finish(max(last_processed, observed_finish), reason)
        result = session_result(session, tops, cash)
        inputs = {"engine": ENGINE_VERSION, "kind": "live-session", "symbol": symbol, "from": iso(start),
                  "to": iso(session.cursor), "resolution": resolution,
                  "subscriptions": list(session.closes.by_resolution),
                  "strategy": strategy.name, "strategy_version": 1, "config_hash": strategy.config_hash,
                  "params": strategy.params, "reference_symbol": session.reference_symbol,
                  "cash": str(cash), "cost": cost.describe(), "rules_mode": "point-in-time",
                  "store": "demo" if demo else "live", "data": result["data_digest"],
                  "snapshots": digest([(d["t"], d["snapshot"]) for d in session.decisions])}
        if clock_regression:
            inputs["clock_regression"] = {"observed_finish_at": iso(observed_finish),
                                          "last_processed_at": iso(last_processed),
                                          "first_regressed_at": iso(regressed_at)}
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
