"""Frozen expanding-window paper selection using the existing append-only registry."""
import re
from datetime import timedelta

from ..adapters.run_store import save_run
from ..domain.bars import BarSpec
from ..domain.market_models import decimal, fields, instant, rate
from ..domain.model import iso
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from .collector import now_utc
from .data_portal import DataPortal
from .paper import PaperDataUnavailable, paper
from .reports import economic_report
from .research_protocol import _engine_digest


def walk_forward(registry, db, request):
    fields(request, "hypothesis symbol candidates windows final_from resolution cash fee_rate latency_ms purge_bars")
    if type(request["hypothesis"]) is not str or not 1 <= len(request["hypothesis"].strip()) <= 500:
        raise ValueError("need a bounded walk-forward hypothesis")
    symbol = request["symbol"]
    if type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol):
        raise ValueError("invalid walk-forward symbol")
    candidates, windows = request["candidates"], request["windows"]
    if (type(candidates) is not list or not 2 <= len(candidates) <= 8 or type(windows) is not list
            or not 1 <= len(windows) <= 5 or (len(candidates) + 1) * len(windows) > 32):
        raise ValueError("need 2..8 candidates, 1..5 windows and at most 32 replay slots")
    strategies = []
    for candidate in candidates:
        fields(candidate, "strategy params")
        strategies.append(create_strategy(candidate["strategy"], candidate["params"]))
    if len({s.config_hash for s in strategies}) != len(strategies):
        raise ValueError("walk-forward candidates must have distinct configurations")
    if type(request["resolution"]) is not str or request["resolution"] == "session":
        raise ValueError("walk-forward requires fixed-duration bars")
    spec = BarSpec(request["resolution"])
    if type(request["purge_bars"]) is not int or not 1 <= request["purge_bars"] <= 100:
        raise ValueError("purge_bars must be 1..100")
    if type(request["latency_ms"]) is not int or not 0 <= request["latency_ms"] <= 60000:
        raise ValueError("latency_ms must be 0..60000")
    cash = decimal(request["cash"], "cash", positive=True)
    cost = CostModel(fee_rate=rate(request["fee_rate"]), latency=timedelta(milliseconds=request["latency_ms"]))
    final_from, clock, periods = instant(request["final_from"]), now_utc(), []
    for window in windows:
        fields(window, "train_from train_to test_from test_to")
        a, b, c, d = (instant(window[name]) for name in ("train_from", "train_to", "test_from", "test_to"))
        if (not a < b < c < d <= clock or c - b < spec.step * request["purge_bars"]
                or b - a < 3 * spec.step or d - c < 3 * spec.step or d > final_from
                or (d - a) // spec.step > 5000 or d - a > timedelta(days=31)
                or any(spec.bucket(t) != t for t in (a, b, c, d))):
            raise ValueError("need closed-bar historical train/test windows, a purge and an unread final cutoff")
        if periods and (a != periods[0][0] or b <= periods[-1][1] or b < periods[-1][3] or c < periods[-1][3]):
            raise ValueError("training must expand from one origin; test windows must be disjoint")
        periods.append((a, b, c, d))
    if db.c.in_transaction:
        raise ValueError("walk-forward requires its own market snapshot")

    definition = registry.append("EXPERIMENT", None, {"workflow": "walk-forward/1", "definition": request,
        "engine_digest": _engine_digest(), "selection_is_exploratory": True,
        "final_data_read": False, "independent_final_evidence": False})
    key, slots = definition["id"], []
    # All slots precede market reads; interruption leaves a durable pending attempt.
    for fold in range(len(periods)):
        slots.append([registry.append("ATTEMPT", key, {"fold": fold, "candidate": i if i < len(strategies) else None,
            "phase": "TRAIN" if i < len(strategies) else "TEST", "state": "RESULT_PENDING"})
            for i in range(len(strategies) + 1)])
    db.c.execute("BEGIN")
    try:
        instrument = DataPortal(db).instrument(symbol)
        sources = {symbol, *[s.reference_symbol for s in strategies if hasattr(s, "reference_symbol")]}
        if instrument.base != "BTC":
            sources.add("BTC" + instrument.quote)
        if instrument.quote == "TMN":
            sources.add("USDTTMN")
        count = 0
        for source in sorted(sources):
            begin = periods[0][0] - (timedelta(days=1) if source == "USDTTMN" else timedelta(seconds=120))
            count += db.c.execute("SELECT count(*) FROM (SELECT 1 FROM book_top WHERE instrument_id=? "
                "AND ts_avail>=? AND ts_avail<? LIMIT ?)",
                ("wallex:" + source, iso(begin), iso(periods[-1][3]), 100001 - count)).fetchone()[0]
            if count > 100000:
                raise ValueError("walk-forward observation budget exceeded; narrow the window")

        def replay(slot, strategy, first, last):
            try:
                out = paper(db, symbol, first, last, resolution=spec.resolution, cash=cash,
                            cost=cost, store=registry.store, strategy_id=strategy.name, params=strategy.params)
                save_run(out, registry.root / "runs")
                result = {"state": "COMPLETED", "run_id": out["run_id"], "outputs_digest": out["outputs_digest"],
                    "data_digest": out["inputs"]["data"], "config_hash": strategy.config_hash,
                    "fills": out["result"]["fills"], "net_quote": out["result"]["end"]["net"],
                    "ready": out["result"]["session"]["running_at"] is not None,
                    "valuation": economic_report(out)["valuation"]["status"]}
                if slot["phase"] == "TEST" and (not result["ready"] or not result["fills"]):
                    result.update(state="NOT_ACTIVE", reason="NO_TRADES" if result["ready"] else "WARMUP_NOT_COMPLETED")
            except (ValueError, ArithmeticError) as error:
                result = {"state": "INCOMPLETE" if isinstance(error, PaperDataUnavailable) else "FAILED",
                          "reason": "NO_QUALIFIED_DATA" if isinstance(error, PaperDataUnavailable) else "REPLAY_REJECTED"}
            registry.append("RESULT", key, {"attempt_id": slot["id"], **result})
            return result

        folds = []
        for index, (a, b, c, d) in enumerate(periods):
            training = [replay(slots[index][i], strategy, a, b) for i, strategy in enumerate(strategies)]
            eligible = [i for i, result in enumerate(training) if result["state"] == "COMPLETED"
                        and result["valuation"] == "CURRENT" and result["fills"] > 0]
            chosen = max(eligible, key=lambda i: (decimal(training[i]["net_quote"].lstrip("-"))
                         * (-1 if training[i]["net_quote"].startswith("-") else 1), strategies[i].config_hash)) if eligible else None
            selected = None if chosen is None else {"candidate": chosen, "strategy": strategies[chosen].name,
                "params": strategies[chosen].params, "config_hash": strategies[chosen].config_hash}
            # Persist selection before touching that fold's test data.
            registry.append("SELECTION", key, {"fold": index, "selected": selected,
                "training_run_ids": [r.get("run_id") for r in training], "selection_count": len(strategies)})
            if chosen is None:
                test = {"state": "ABSTAIN", "reason": "NO_CURRENT_ACTIVE_TRAINING_RESULT"}
                registry.append("RESULT", key, {"attempt_id": slots[index][-1]["id"], **test})
            else:
                test = replay(slots[index][-1], strategies[chosen], c, d)
            folds.append({"window": windows[index], "training": training, "selected": selected, "test": test})
    finally:
        db.c.rollback()
    report = {"schema": "walk-forward/1", "experiment_id": key, "store": registry.store,
        "status": "EVALUATED" if all(f["test"]["state"] == "COMPLETED" and f["test"]["valuation"] == "CURRENT" for f in folds) else "INCOMPLETE",
        "selection_count": len(strategies) * len(periods), "test_slots": len(periods), "folds": folds,
        "final_from": iso(final_from), "final_data_read": False, "independent_final_evidence": False,
        "funded_authority": False,
        "limits": ["Expanding training can include earlier test periods; each later test stays disjoint and is read only after selection.",
                   "Every window starts a separate flat account with its own warmup; returns are not a compounded portfolio.",
                   "Selection maximizes current active net quote after modeled costs, including negative winners.",
                   "Historical test results are exploratory. The final cutoff is not a consume-once or independent custody gate."]}
    registry.append("WALK_FORWARD_REPORT", key, {"report": report})
    return report
