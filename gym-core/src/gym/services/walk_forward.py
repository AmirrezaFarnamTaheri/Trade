"""Frozen expanding-window paper selection using the existing append-only registry."""
import re
from datetime import timedelta
from decimal import Decimal

from ..adapters.run_store import save_run
from ..domain.bars import BarSpec
from ..domain.market_models import decimal, fields, instant, rate
from ..domain.model import iso, parse_ts
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .collector import now_utc
from .data_portal import DataPortal
from .paper import PaperDataUnavailable, paper
from .reports import economic_report
from .research_protocol import _engine_digest
from .trial_ledger import TrialLedger


def warmup_test_replay(db, symbol, test_start, test_end, warmup_start, *, strategy,
                       cash, cost, resolution, store):
    """Prime indicators from earlier quotes while forbidding all pre-test orders."""
    from .paper import ranking, session_result
    from .rules import RuleService
    from .session import PaperSession

    if not warmup_start < test_start < test_end:
        raise ValueError("warm-up must precede a positive test interval")
    # Base report supplies matched test-only baselines and causal FX reference.
    original = paper(db, symbol, test_start, test_end, resolution=resolution, cash=cash,
                     cost=cost, store=store, strategy_id=strategy.name, params=strategy.params)
    portal, rules = DataPortal(db), RuleService(db)
    session = PaperSession(portal, lambda at: rules.load(at)[1],
                           create_strategy(strategy.name, strategy.params), symbol,
                           warmup_start, resolution, cash, cost)
    session.warmup_until = test_start
    observations = portal.tops(symbol, warmup_start, test_end)
    for observation in observations:
        session.feed(observation)
    session.finish(test_end)
    # Warm-up decisions affect indicator state, but not holdings or test-period performance.
    session.decisions = [d for d in session.decisions if parse_ts(d["t"]) > test_start]
    session.curve = [mark for mark in session.curve if parse_ts(mark[0]) > test_start]
    session.bar_events = [event for event in session.bar_events if parse_ts(event["t"]) > test_start]
    test_quotes = [q for q in observations if q.ts_avail >= test_start]
    main = session_result(session, test_quotes, cash)
    if main["qualified"] == 0:
        raise PaperDataUnavailable("no qualified test-period observations")
    main["session"]["warmup_from"] = iso(warmup_start)
    main["session"]["no_pretest_orders"] = all(parse_ts(o["decision_time"]) > test_start for o in main["orders"])
    if not main["session"]["no_pretest_orders"]:
        raise ValueError("warm-up issued an order before the test cutoff")
    quote = main["quote"]
    if main["end"] and quote == "USDT":
        main["end"]["net_usdt_eq"] = main["end"]["net"]
    elif main["end"] and original["fx"]:
        fx = original["fx"]
        main["valuation"] = original["result"].get("valuation")
        main["end"]["net_usdt_eq"] = str(
            (Decimal(main["end"]["equity"]) / Decimal(fx["end"]) - cash / Decimal(fx["start"]))
            .quantize(Decimal("0.0001")))
    result = original
    result["result"] = main
    result["ranking"] = ranking(main, result["baselines"])
    inputs = result["inputs"]
    inputs["engine"] = "walk-forward-warmup/1"
    inputs["data"] = main["data_digest"]
    inputs["snapshots"] = digest([(d["t"], d["snapshot"]) for d in main["decisions"]])
    inputs["warmup_from"] = iso(warmup_start)
    inputs["warmup_digest"] = digest([
        (iso(q.ts_avail), q.bid, q.ask, q.bid_qty, q.ask_qty, sorted(q.flags))
        for q in observations if q.ts_avail < test_start])
    result["run_id"] = digest(inputs)[:16]
    result["outputs_digest"] = digest({key: result[key]
                                        for key in ("result", "baselines", "ranking", "fx")})[:16]
    return result


def chained_out_of_sample(folds, records, starting_cash):
    """Chain selected flat-account test growth with strict chronological evidence."""
    equity, peak, worst = Decimal(starting_cash), Decimal(starting_cash), Decimal(0)
    marks, losing, longest = [], 0, 0
    for fold in folds:
        record = records.get(fold["test"].get("run_id"))
        if record is None or not record["result"].get("end") or fold["test"]["state"] != "COMPLETED":
            return {"status": "INCOMPLETE", "completed_folds": len(marks),
                    "limitation": "Missing or unready test evidence prevents a chained economic claim."}
        from ..domain.performance import trade_ledger

        for trade in trade_ledger(record["result"]["orders"], record["result"]["base"])["trades"]:
            losing = losing + 1 if Decimal(trade["pnl"]) < 0 else 0
            longest = max(longest, losing)
        for stamp, balance in record["result"]["curve"]:
            mark_equity = equity * Decimal(balance) / Decimal(record["result"]["start_cash"])
            peak = max(peak, mark_equity)
            if peak:
                worst = max(worst, (peak - mark_equity) / peak)
            marks.append((stamp, str(mark_equity)))
        equity *= Decimal(record["result"]["end"]["equity"]) / Decimal(record["result"]["start_cash"])
        peak = max(peak, equity)
        if peak:
            worst = max(worst, (peak - equity) / peak)
    stride = max(1, (len(marks) + 998) // 999)
    sample = marks[::stride]
    if marks and sample[-1] != marks[-1]:
        sample.append(marks[-1])
    return {"status": "EXPLORATORY_CHAINED", "start_equity_quote": str(starting_cash),
            "end_equity_quote": str(equity), "curve": sample, "source_marks": len(marks),
            "sampling_stride": stride, "max_drawdown_fraction": str(worst),
            "longest_losing_trade_streak": longest,
            "limitation": "Selected flat-account test returns are chained arithmetically as a hypothetical "
                          "reinvestment diagnostic, not an executable multi-fold portfolio; quote currency."}


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

    definition = registry.append("EXPERIMENT", None, {"workflow": "walk-forward/2", "definition": request,
        "engine_digest": _engine_digest(), "selection_is_exploratory": True,
        "final_data_read": False, "independent_final_evidence": False})
    key, slots = definition["id"], []
    # All slots precede market reads; interruption leaves a durable pending attempt.
    for fold in range(len(periods)):
        slots.append([registry.append("ATTEMPT", key, {"fold": fold, "candidate": i if i < len(strategies) else None,
            "phase": "TRAIN" if i < len(strategies) else "TEST", "state": "RESULT_PENDING"})
            for i in range(len(strategies) + 1)])
    with TrialLedger(registry.root) as ledger:
        for fold, (a, b, c, d) in enumerate(periods):
            for i, slot in enumerate(slots[fold]):
                training = i < len(strategies)
                ledger.record(symbol=symbol, start=a if training else c, end=b if training else d,
                              hypothesis=request["hypothesis"], source="walk-forward",
                              config_hash=strategies[i].config_hash if training else "SELECTED_TEST",
                              attempt_id=slot["id"])
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

        test_records = {}

        def replay(slot, strategy, first, last, *, warmup_from=None):
            try:
                out = (warmup_test_replay(db, symbol, first, last, warmup_from, strategy=strategy,
                                         cash=cash, cost=cost, resolution=spec.resolution, store=registry.store)
                       if warmup_from is not None else
                       paper(db, symbol, first, last, resolution=spec.resolution, cash=cash,
                             cost=cost, store=registry.store, strategy_id=strategy.name, params=strategy.params))
                if warmup_from is not None:
                    test_records[out["run_id"]] = out
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
                test = replay(slots[index][-1], strategies[chosen], c, d, warmup_from=a)
            folds.append({"window": windows[index], "training": training, "selected": selected, "test": test})
    finally:
        db.c.rollback()
    out_of_sample = chained_out_of_sample(folds, test_records, cash)
    report = {"schema": "walk-forward/2", "experiment_id": key, "store": registry.store,
        "status": "EVALUATED" if all(f["test"]["state"] == "COMPLETED" and f["test"]["valuation"] == "CURRENT" for f in folds) else "INCOMPLETE",
        "selection_count": len(strategies) * len(periods), "test_slots": len(periods), "folds": folds,
        "out_of_sample": out_of_sample,
        "final_from": iso(final_from), "final_data_read": False, "independent_final_evidence": False,
        "funded_authority": False,
        "limits": ["Expanding training can include earlier test periods; each later test stays disjoint and is read only after selection.",
                   "Pre-test bars warm indicators without simulated orders; tests start with flat cash and ready indicators.",
                   "The chained test curve compounds selected after-cost flat-account results hypothetically; not a funded portfolio.",
                   "Selection maximizes current active net quote after modeled costs, including negative winners.",
                   "Historical test results are exploratory. The final cutoff is not a consume-once or independent custody gate."]}
    registry.append("WALK_FORWARD_REPORT", key, {"report": report})
    return report
