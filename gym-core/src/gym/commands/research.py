"""Research command implementations; invocation stays in gym.cli."""
from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

from ..adapters import wallex
from ..adapters.store import MarketDB, SegmentWriter
from ..domain.model import iso, now_utc, parse_ts
from ..services.collector import Collector
from ..services.process_owner import ProcessOwner
from ..services.research_process import ResearchProcessFailure, calculate
from .common import (
    _strict_offline_json,
    open_db,
    store_root,
    timedelta_ms,
)


def replay_cmd(args) -> int:
    """Replay paper strategy or portfolio evidence and save immutable run records."""
    from ..adapters.run_store import save_run
    from ..domain.market_models import decimal
    from ..domain.strategy import digest
    from ..services.attribution import toman_attribution
    from ..services.cost_defaults import calibrated_cost
    from ..services.data_quality_gate import quote_coverage, recorded_bar_coverage
    from ..services.paper import paper
    from ..services.reports import text_report
    from ..services.research import compare
    from ..services.trial_ledger import TrialLedger

    if args.volatility_model != "close-std" and args.vol_target is None:
        raise ValueError("--volatility-model needs --vol-target")
    if not (store_root(args) / "market.db").exists():
        raise ValueError(f"no data in {store_root(args)}")
    db, symbol = open_db(args), args.symbol.upper()
    symbols = [s.strip() for s in symbol.split(",") if s.strip()]
    symbol = symbols[0]
    try:
        span = db.c.execute("select min(ts_avail), max(ts_avail) from book_top where instrument_id=?", (f"wallex:{symbol}",)).fetchone()
        if not span[0]:
            raise ValueError(f"no {symbol} quotes stored")
        start, end = parse_ts(args.start or span[0]), parse_ts(args.end or span[1])
        cash = Decimal(args.cash) if args.cash else Decimal(300_000_000 if symbol.endswith("TMN") else 1000)
        participation = Decimal(args.participation) if args.participation else None
        cost_profiles = json.loads(args.cost_models_json) if args.cost_models_json else {}
        if type(cost_profiles) is not dict or cost_profiles.keys() - {"impact_models", "hourly_costs"}:
            raise ValueError("invalid opt-in cost-model profiles")
        options = {"resolution": args.res, "cash": cash,
                   "cost": calibrated_cost(store_root(args), symbol, fee=args.fee, maker_fee=args.maker_fee,
                                           latency_ms=args.latency_ms, order_type=args.order_type,
                                           now=start,  # Historical inputs cannot import future receipts.
                                           max_participation=participation, walk_depth=args.walk_depth,
                                           carry_remainder=args.carry_remainder,
                                           max_fraction=Decimal(args.max_fraction) if args.max_fraction else None,
                                           vol_target=Decimal(args.vol_target) if args.vol_target else None,
                                           volatility_model=args.volatility_model, **cost_profiles),
                   "rules_mode": args.rules, "store": "demo" if args.demo else "live",
                   "subscriptions": tuple(x.strip() for x in args.subscribe.split(",") if x.strip())}
        # Attempt receipts live outside frozen run artifacts and survive failed evaluations.
        trial_specs = ([json.loads(candidate) for candidate in args.candidate]
                       if args.cmd in ("compare", "validate") else
                       [{"strategy": args.strategy, "params": json.loads(args.params) if args.params else None,
                         "policy": getattr(args, "policy", None)}])
        if args.max_bad_share is not None:
            threshold = decimal(args.max_bad_share, "maximum bad share")
            if threshold > 1:
                raise ValueError("maximum bad share exceeds one")
        with TrialLedger(store_root(args)) as ledger:
            for trial in trial_specs:
                ledger.record(symbol=",".join(symbols), start=start, end=end,
                              hypothesis=args.hypothesis, source=args.cmd,
                              config_hash=digest({"candidate": trial, "cost": options["cost"].describe(),
                                                  "resolution": args.res, "rules_mode": args.rules,
                                                  "folds": getattr(args, "folds", 1)}))
            ledger_trials = ledger.count(symbol=",".join(symbols), start=start, end=end,
                                         hypothesis=args.hypothesis)
        if args.max_bad_share is not None:
            quality = {market: quote_coverage(db, market, start, end, args.res,
                       max_bad_share=args.max_bad_share) for market in symbols}
            for market, report in quality.items():
                print(f"QUOTE COVERAGE {market}: {report['coverage_share']} "
                      f"(missing {report['missing_share']}, invalid/stale {report['stale_or_invalid_share']}); "
                      f"{report['status']}", file=sys.stderr)
            if any(report["status"] == "INSUFFICIENT_DATA" for report in quality.values()):
                raise ValueError("INSUFFICIENT_DATA: missing/stale quote share exceeds the declared threshold")
        if args.cmd == "portfolio":
            from ..services.portfolio import portfolio
            options.pop("subscriptions")
            out = portfolio(db, symbols, start, end, strategy_id=args.strategy,
                            params=json.loads(args.params) if args.params else None,
                            policy=json.loads(args.policy) if args.policy else None, **options)
            perf = out["performance"]
            print(f"PORTFOLIO {out['run_id']} · {', '.join(symbols)} · shared {out['result']['quote']} cash · PAPER ONLY")
            print(f"end equity {out['result']['end']['equity']}  net {out['result']['end']['net']}  "
                  f"return {perf.get('total_return_pct')}%  max drawdown {perf.get('max_drawdown_pct', 'n/a')}")
            valuation = out["result"]["valuation"]
            print(f"USDT equivalent net {out['result']['end']['net_usdt_eq']}  "
                  f"FX {valuation['start']['status']} -> {valuation['end']['status']} (valuation only)")
            components = toman_attribution(out)
            if components["status"] == "AVAILABLE":
                print(f"TMN return: USDT {components['usdt_return']} + rate {components['toman_move']} "
                      f"+ interaction {components['interaction']} = {components['total_toman_return']}")
            elif out["result"]["quote"] == "TMN":
                print("TMN return attribution UNAVAILABLE: point-in-time FX evidence missing")
            quality_observed = recorded_bar_coverage(out)
            print(f"Recorded portfolio coverage: {quality_observed['status']} "
                  "(qualified-receipt shares, not missing-time coverage).")
            for market, row in out["result"]["markets"].items():
                print(f"  {market:<10} fills {row['fills']:<4} closed trades {row['closed_trades']:<4} realized {row['realized_pnl']}")
            print("portfolio record:", save_run(out, store_root(args) / "runs" / "portfolios"))
            return 0
        if args.cmd in ("compare", "validate"):
            from ..services.temporal_validation import validate
            if args.cmd == "validate":
                options["folds"] = args.folds
            compute = validate if args.cmd == "validate" else compare
            result = compute(db, symbol, start, end, [json.loads(candidate) for candidate in args.candidate],
                             **({**options, "ledger_trials": ledger_trials} if args.cmd == "compare" else options))
            records = result["runs"]
            if args.cmd == "validate":
                report = {"run_id": result["validation_id"], **{k: v for k, v in result.items() if k != "runs"}}
            else:
                print(f"COMPARE {result['comparison_id']} · identical window, costs and snapshots · PAPER ONLY")
        else:
            records = [paper(db, symbol, start, end, strategy_id=args.strategy,
                             params=json.loads(args.params) if args.params else None, **options)]
        for record in records:
            path = save_run(record, store_root(args) / "runs")
            print(text_report(record))
            print(f"\nrun record: {path}")
        if args.cmd == "validate":
            print(json.dumps(report, indent=2))
            print("validation record:", save_run(report, store_root(args) / "runs" / "validations"))
    finally:
        db.c.close()
    return 0


def market_statistics_cmd(args) -> int:
    """Calculate bounded observed market statistics from a local snapshot."""
    from datetime import timedelta

    from ..services.market_statistics import spread_report, trade_flow_report

    path = store_root(args) / "market.db"
    if not path.exists():
        raise ValueError(f"no market data in {path.parent}")
    db = MarketDB(path, readonly=True)
    try:
        symbol = args.symbol.upper() if args.symbol else None
        flow = args.cmd == "trade-flow"
        query = ("select ts_event, ts_avail from trades" if flow else
                 "select min(ts_avail), max(ts_avail) from book_top")
        records = db.c.execute(query + (" where instrument_id=?" if symbol else ""),
                               (f"wallex:{symbol}",) if symbol else ()).fetchall()
        if not records or not records[0][0]:
            raise ValueError("no stored observations for the requested markets")
        first = min(parse_ts(row[0]) for row in records) if flow else parse_ts(records[0][0])
        last = max(parse_ts(value) for row in records for value in row) if flow else parse_ts(records[0][1])
        start = parse_ts(args.start) if args.start else first
        end = parse_ts(args.end) if args.end else last + timedelta(microseconds=1)
        report = (trade_flow_report if flow else spread_report)(
            db, start, end, symbol=symbol, store="demo" if args.demo else "live")
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            with Path(args.output).open("x", encoding="utf-8") as output:
                output.write(text + "\n")
            print(f"{args.cmd} report: {args.output}; {report['samples']} observations, {len(report['groups'])} pair/hour groups")
        else:
            print(text)
    finally:
        db.c.close()
    return 0


def technical_report_cmd(args) -> int:
    """Render local technical diagnostics using recorded observations only."""
    from ..services.technical_analysis import technical_report, technical_reports

    path = store_root(args) / "market.db"
    if not path.is_file():
        raise ValueError("technicals require an existing market store")
    db = MarketDB(path, readonly=True)
    try:
        resolutions = args.res or ["15min"]
        options = {"store": "demo" if args.demo else "live"}
        if len(resolutions) == 1:
            report = technical_report(db, args.symbol.upper(), parse_ts(args.start), parse_ts(args.end),
                                      resolution=resolutions[0], **options)
        else:
            report = technical_reports(db, args.symbol.upper(), parse_ts(args.start), parse_ts(args.end),
                                       resolutions=resolutions, **options)
    finally:
        db.c.close()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with Path(args.output).open("x", encoding="utf-8") as destination:
            destination.write(text + "\n")
    print(text)
    return 0


def candles_cmd(args) -> int:
    """DATA-05: compare internal LAST bars from collected trades with venue candles."""
    from datetime import timedelta

    from ..services.data_portal import DataPortal
    from ..services.feed_crosscheck import candle_crosscheck

    if args.demo:
        raise ValueError("demo data has no venue candles; run the cross-check on the live store")
    path = store_root(args) / "market.db"
    if not path.exists():
        raise ValueError(f"no market data in {path.parent}")
    symbol = args.symbol.upper()
    db = MarketDB(path)
    try:
        end = parse_ts(args.end) if args.end else now_utc()
        start = parse_ts(args.start) if args.start else end - timedelta(hours=2)
        if args.fetch or args.fill_gaps:
            from ..services.data_portal import quote_gaps
            # shortcut: at most 50 gaps per call; rerun for more. Candles carry their fetch time as provenance.
            windows = quote_gaps(db, symbol, start, end)[:50] if args.fill_gaps else [(start, end)]

            async def fetch():
                """Fetch or inspect candle windows while respecting the local data boundary."""
                seg = SegmentWriter(store_root(args) / "raw", db)
                try:
                    async with wallex.public_session() as session:
                        collector, total = Collector(db, seg, [symbol]), 0
                        for gap_start, gap_end in windows:
                            got = await collector.fetch_candles(session, symbol, "1min", gap_start, gap_end)
                            total += got
                            if args.fill_gaps:
                                db.add_quality(now_utc(), symbol, "GAP_BACKFILLED",
                                               f"{iso(gap_start)}..{iso(gap_end)} venue 1min candles={got}; quotes stay missing")
                        return total
                finally:
                    seg.close()
            print(f"fetched {asyncio.run(fetch())} venue candles over {len(windows)} window(s)", file=sys.stderr)
        report = candle_crosscheck(DataPortal(db), symbol, start, end, tolerance_bps=Decimal(args.tolerance_bps),
                                  as_of=parse_ts(args.as_of) if args.as_of else None)
        if args.record:
            for row in report["periods"]:
                if row["status"] in ("DIVERGENT", "MISSING_INTERNAL"):
                    db.add_quality(now_utc(), symbol, "CROSS_FEED_DIVERGENCE", json.dumps(row))
        print(json.dumps(report, indent=2) if args.json else
              f"{symbol} 1min {report['from']} .. {report['to_exclusive']}: " +
              (", ".join(f"{k} {v}" for k, v in sorted(report["counts"].items())) or "no periods"))
    finally:
        db.c.close()
    return 0


HISTORY_STEP = {"1min": 60, "1h": 3600, "1d": 86400}  # 1min: the venue answers nothing for a window of two days or more
HISTORY_PAGE_BARS = 1000  # shortcut: assumed per-request bar limit (undocumented); smaller pages only cost requests


def history_cmd(args) -> int:
    """Backfill long public venue candles so slow strategies can be studied on years, not days, of history."""
    from datetime import timedelta


    if args.demo:
        raise ValueError("demo data has no venue history; backfill the live store")
    start, end = parse_ts(args.start), parse_ts(args.end) if args.end else now_utc()
    if not start < end:
        raise ValueError("--from must be before --to")
    page = timedelta(seconds=HISTORY_STEP[args.resolution] * HISTORY_PAGE_BARS)
    symbols = [s.upper() for s in args.symbols]
    db = MarketDB(store_root(args) / "market.db")

    async def fetch():
        """Page backwards from --to; stop at --from or after three empty pages (before the market listed)."""
        seg = SegmentWriter(store_root(args) / "raw", db)
        totals = {}
        try:
            async with wallex.public_session() as session:
                collector = Collector(db, seg, symbols)
                for symbol in symbols:
                    total, empty, hi = 0, 0, end
                    while hi > start and empty < 3:
                        lo = max(start, hi - page)
                        got = await collector.fetch_candles(session, symbol, args.resolution, lo, hi)
                        total, empty, hi = total + got, 0 if got else empty + 1, lo
                    totals[symbol] = total
                    print(f"{symbol} {args.resolution}: {total} candles", file=sys.stderr)
        finally:
            seg.close()
        return totals

    try:
        totals = asyncio.run(fetch())
    finally:
        db.c.close()
    print(json.dumps({"resolution": args.resolution, "from": iso(start), "to": iso(end), "candles": totals}))
    return 0


def allocate_cmd(args) -> int:
    """Append today's daily-trend allocation decisions and paper fills to the allocation journal."""
    from ..services.allocation import run_day

    db = open_db(args)
    try:
        entries = run_day(db, store_root(args), [s.upper() for s in args.symbols], now_utc(),
                          cash=Decimal(args.cash), lookback=args.lookback, vol_target=args.vol_target, band=args.band)
    finally:
        db.c.close()
    print(json.dumps(entries, indent=2))
    return 0


def calibrate_cmd(args) -> int:
    """Produce measured execution assumptions without enabling live trading."""
    from datetime import timedelta

    from ..services.cost_defaults import save_calibration
    from ..services.execution_calibration import feed_latency, fill_quality

    db = open_db(args)
    try:
        at = now_utc()
        report = {"feed": feed_latency(db, at - timedelta(hours=args.hours), until=at),
                  "paper_fills": fill_quality(store_root(args) / "runs"),
                  "synthetic": bool(args.demo)}
        report["calibration_receipt"] = str(save_calibration(store_root(args), report, at=at))
    finally:
        db.c.close()
    print(json.dumps(report, indent=2))
    return 0


def summary_cmd(args):
    """Summarize persisted paper evidence without altering the source run."""
    from ..adapters.run_store import load_run
    from ..services.portable_report import render_html
    from ..services.reports import paper_summary

    try:
        out = load_run(store_root(args) / "runs", args.run_id)
        text = render_html(out) if args.format == "html" else json.dumps(paper_summary(out), ensure_ascii=False)
    except (KeyError, TypeError, AttributeError, RecursionError, UnicodeDecodeError):
        raise ValueError("invalid run artifact structure") from None
    if args.output:
        with Path(args.output).open("x", encoding="utf-8") as destination:
            destination.write(text)
        print(args.output)
    else:
        print(text)
    return 0


def evidence_cmd(args):
    """Read saved economic evidence and record an independent operator decision."""
    from ..adapters.run_store import record_decision, run_path
    from ..services.diagnostics import diagnostics
    from ..services.reports import economic_report, markdown

    root = store_root(args) / "runs"
    out = json.loads(run_path(root, args.run_id).read_text("utf-8"))
    diag = diagnostics(open_db(args), out) if args.diagnostics and out["inputs"].get("kind") != "live-session" else None
    if args.diagnostics and diag is None:
        diag = {"status": "NOT_RUN", "reason": "Live-session matched replay is required."}
    report = economic_report(out, diag)
    (root / (args.run_id + ".evidence.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    path = root / (args.run_id + ".evidence.md")
    path.write_text(markdown(report), "utf-8")
    print(path)
    if args.decide:
        print(record_decision(root, out, args.decide, args.cap, args.ccy, args.note, now_utc()))
    return 0


def session_cmd(args):
    """Start a bounded paper session with no funded execution authority."""
    from ..domain.sim import CostModel
    from ..services.live_paper import watch

    if not (store_root(args) / "market.db").exists():
        raise ValueError("start the collector first")
    cash = Decimal(args.cash or (300_000_000 if args.symbol.upper().endswith("TMN") else 1000))
    subscriptions = tuple(x.strip() for x in args.subscribe.split(",") if x.strip())
    cost = CostModel(Decimal(args.fee), timedelta_ms(args.latency_ms))
    db = open_db(args)
    try:
        asyncio.run(watch(db, store_root(args) / "runs", args.symbol.upper(), args.seconds,
                          args.res, cash, args.demo, subscriptions, cost,
                          strategy_id=args.strategy, params=json.loads(args.params) if args.params else None))
    finally:
        db.c.close()
    return 0


def paper_research_cmd(args) -> int:
    """Evaluate a bounded offline artifact without opening a store or venue."""
    from ..domain.market_models import evaluate_artifact

    report = evaluate_artifact(_strict_offline_json(args.path, max_bytes=2_000_000))
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        destination = Path(args.output).resolve()
        data_root = Path(args.data).resolve()
        if data_root == destination or data_root in destination.parents or any(part.lower() == "data" for part in destination.parts):
            raise ValueError("paper-research output must be outside data/")
        with destination.open("x", encoding="utf-8") as output:
            output.write(text + "\n")
    print(text)
    return 0


def research_cmd(args):
    """Dispatch local research commands through their bounded execution owners."""
    from ..services.research_actions import OBJECT_ACTIONS, research_action

    root = store_root(args)
    if args.action == "mcp":
        from ..services.research_mcp import serve_stdio
        return serve_stdio(root)
    if args.action == "start":
        root.mkdir(parents=True, exist_ok=True)
        result = asyncio.run(watch(root, store="demo" if args.demo else "live", poll_seconds=args.poll_seconds))
    else:
        value = args.input
        if args.action in OBJECT_ACTIONS:
            if not value:
                raise ValueError("this research action requires an input JSON file")
            value = _strict_offline_json(value, max_bytes=65536)
        from ..services.research_process import (
            HEAVY_ACTIONS,
            ResearchProcessFailure,
            calculate,
        )
        try:
            result = (asyncio.run(calculate(root, args.action, value, store="demo" if args.demo else "live", at=args.at))
                      if args.action in HEAVY_ACTIONS else
                      research_action(root, args.action, value, store="demo" if args.demo else "live", at=args.at))
        except ResearchProcessFailure as error:
            print(json.dumps(error.report, ensure_ascii=False))
            return 3
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 3 if "error" in result or (args.action == "claim-check" and not result["all_matched"]) else 0


# The foreground scheduler is owned by the CLI; no separate pass-through module.

async def watch(root: Path | str, *, store: str = "live", poll_seconds: float = 5,
                stop: asyncio.Event | None = None) -> dict[str, object]:
    """Poll local data only; Ctrl+C or an event stops without disabling scheduled jobs."""
    if store not in ("live", "demo"):
        raise ValueError("research store must be live or demo")
    if (type(poll_seconds) not in (int, float) or not math.isfinite(poll_seconds)
            or not 1 <= poll_seconds <= 60):
        raise ValueError("research poll interval must be 1..60 seconds")
    root, stop = Path(root), stop if stop is not None else asyncio.Event()
    if not (root / "market.db").is_file():
        raise sqlite3.OperationalError("paper market store missing")
    with ProcessOwner(root, "scheduler", store=store):
        return await _watch(root, store, poll_seconds, stop)


async def _watch(root, store, poll_seconds, stop):
    """Run scheduler ticks under the process lock until explicitly interrupted."""
    ticks = completed = failed = 0
    reason = "Stop requested"
    try:
        while not stop.is_set():
            result = await calculate(root, "tick", store=store, at=now_utc().isoformat())
            ticks += 1
            completed += len(result["completed"])
            failed += len(result["failed"])
            if not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
                except TimeoutError:
                    pass
    except asyncio.CancelledError:
        reason = "Operator interrupted"
    except ResearchProcessFailure as error:
        return {"state": "STOPPED", **error.report, "ticks": ticks, "completed": completed, "failed": failed}
    return {"state": "STOPPED", "reason": reason, "ticks": ticks, "completed": completed, "failed": failed}
