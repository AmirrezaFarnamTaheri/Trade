"""Research command implementations; invocation stays in gym.cli."""
from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

from ..adapters.store import MarketDB, SegmentWriter
from ..domain.model import iso, parse_ts
from ..services.collector import Collector, now_utc
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
    from ..domain.sim import CostModel
    from ..services.paper import paper
    from ..services.reports import text_report
    from ..services.research import compare

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
        options = {"resolution": args.res, "cash": cash, "cost": CostModel(Decimal(args.fee), timedelta_ms(args.latency_ms),
                                                                           max_participation=participation,
                                                                           walk_depth=args.walk_depth, carry_remainder=args.carry_remainder,
                                                                           max_fraction=Decimal(args.max_fraction) if args.max_fraction else None,
                                                                           vol_target=Decimal(args.vol_target) if args.vol_target else None,
                                                                           order_type=args.order_type,
                                                                           maker_fee_rate=Decimal(args.maker_fee) if args.maker_fee else None),
                   "rules_mode": args.rules, "store": "demo" if args.demo else "live",
                   "subscriptions": tuple(x.strip() for x in args.subscribe.split(",") if x.strip())}
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
            for market, row in out["result"]["markets"].items():
                print(f"  {market:<10} fills {row['fills']:<4} closed trades {row['closed_trades']:<4} realized {row['realized_pnl']}")
            print("portfolio record:", save_run(out, store_root(args) / "runs" / "portfolios"))
            return 0
        if args.cmd in ("compare", "validate"):
            from ..services.temporal_validation import validate
            if args.cmd == "validate":
                options["folds"] = args.folds
            compute = validate if args.cmd == "validate" else compare
            result = compute(db, symbol, start, end, [json.loads(candidate) for candidate in args.candidate], **options)
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

    import aiohttp

    from ..services.collector import now_utc
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
                    async with aiohttp.ClientSession(headers={"User-Agent": "TradingGYM/0.1 (observatory)"}) as session:
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


def calibrate_cmd(args) -> int:
    """Produce measured execution assumptions without enabling live trading."""
    from datetime import timedelta

    from ..services.execution_calibration import feed_latency, fill_quality

    db = open_db(args)
    try:
        report = {"feed": feed_latency(db, now_utc() - timedelta(hours=args.hours)),
                  "paper_fills": fill_quality(store_root(args) / "runs")}
    finally:
        db.c.close()
    print(json.dumps(report, indent=2))
    return 0


def assistant_cmd(args) -> int:
    """A model proposes configurations; this machine tests them on paper within the trial budget."""
    from ..services.model_gateway import ModelGateway
    from ..services.model_usage import ModelUsage
    from ..services.research_assistant import assist

    db, symbol = open_db(args), args.symbol.upper()
    gateway, usage = ModelGateway(), ModelUsage(store_root(args) / "model_usage.db")

    async def complete(action, value):
        """Return a bounded advisory result while recording model usage."""
        result = await gateway.request(action, value)
        usage.record(result)
        return result

    async def go():
        """Close the model gateway and usage store after an advisory request."""
        try:
            span = db.c.execute("select min(ts_avail), max(ts_avail) from book_top where instrument_id=?", (f"wallex:{symbol}",)).fetchone()
            if not span[0]:
                raise ValueError(f"no {symbol} quotes stored")
            start, end = parse_ts(args.start or span[0]), parse_ts(args.end or span[1])
            cash = Decimal(args.cash) if args.cash else Decimal(300_000_000 if symbol.endswith("TMN") else 1000)
            return await assist(complete, db, store_root(args) / "runs", symbol, start, end, preset=args.preset, budget=args.budget,
                                resolution=args.res, cash=cash, store="demo" if args.demo else "live")
        finally:
            await gateway.close()
    try:
        print(json.dumps(asyncio.run(go()), indent=2, ensure_ascii=False, default=str))
    finally:
        usage.close()
        db.c.close()
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
