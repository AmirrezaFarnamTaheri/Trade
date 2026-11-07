"""gymctl: run the daemon, manage venue rules."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sqlite3
import sys
from datetime import UTC
from decimal import Decimal, DecimalException
from pathlib import Path

from .adapters.store import MarketDB, SegmentWriter
from .domain.bars import FIXED_RESOLUTIONS, RESOLUTIONS
from .domain.model import InstrumentId, iso, parse_ts, strict_loads
from .services.collector import Collector, now_utc, parse_asset_count
from .services.rules import RuleService

DEFAULT_WATCH = "USDTTMN,BTCTMN,BTCUSDT,ETHTMN,ETHUSDT"
DEFAULT_PRESET = "usdt-irt-october-2026"
# Fee default: --fee per run, or set GYM_FEE_RATE once (e.g. `setx GYM_FEE_RATE 0.0015`).
DEFAULT_FEE = os.environ.get("GYM_FEE_RATE", "0.001")
FEE_HELP = f"fee rate per side (default {DEFAULT_FEE}; observed account fee 0.1%%, override with GYM_FEE_RATE)"


def store_root(args) -> Path:
    # Demo data lives in its own directory and never mixes with real observations.
    return Path(args.data) / ("demo" if getattr(args, "demo", False) else "live")


def open_db(args, preset_at=None) -> MarketDB:
    db = MarketDB(store_root(args) / "market.db")
    if not db.rule_events():
        RuleService(db).preset(DEFAULT_PRESET, preset_at or now_utc(), actor="first-run")
    return db


def demo_seed(args) -> int:
    from datetime import timedelta

    from .domain.rules import evaluate

    args.demo = True
    end = now_utc().replace(second=0, microsecond=0)
    start = end - timedelta(hours=args.hours)
    if (store_root(args) / "market.db").exists():
        print(f"error: {store_root(args)} already exists; move it away to reseed", file=sys.stderr)
        return 2
    db = open_db(args, preset_at=start)  # demo: the October rules are known from the start of the synthetic past
    rules = RuleService(db).load()[1]
    def closed(symbol, at):
        return not evaluate(rules, InstrumentId.wallex(symbol), "SELL", "EXIT", at, live=False).allowed
    seg = SegmentWriter(store_root(args) / "raw", db)
    Collector(db, seg, DEFAULT_WATCH.split(","), demo=True, depth_levels=5).demo_history(start, end, closed)
    seg.close()
    print(f"DEMO history {start:%Y-%m-%d %H:%M} .. {end:%Y-%m-%d %H:%M} UTC written to {store_root(args)}")
    return 0


def replay_cmd(args) -> int:
    from .adapters.run_store import save_run
    from .domain.sim import CostModel
    from .services.paper import paper
    from .services.reports import text_report
    from .services.research import compare

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
            from .services.portfolio import portfolio
            options.pop("subscriptions")
            out = portfolio(db, symbols, start, end, strategy_id=args.strategy,
                            params=json.loads(args.params) if args.params else None, **options)
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
            from .services.temporal_validation import validate
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
                             params=json.loads(args.params) if args.params else None,
                             fast=args.fast, slow=args.slow, **options)]
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
    from datetime import timedelta

    from .services.market_statistics import spread_report, trade_flow_report

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
    from .services.technical_analysis import technical_report, technical_reports

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

    from .services.collector import Collector, now_utc
    from .services.data_portal import DataPortal
    from .services.feed_crosscheck import candle_crosscheck

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
            from .services.data_portal import quote_gaps
            # shortcut: at most 50 gaps per call; rerun for more. Candles carry their fetch time as provenance.
            windows = quote_gaps(db, symbol, start, end)[:50] if args.fill_gaps else [(start, end)]

            async def fetch():
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

def raw_move_cmd(args) -> int:
    """Move whole, finished raw/YYYYMMDD day folders to another volume; never today's or a partial move."""
    from .adapters.store import move_raw_days

    days = move_raw_days(store_root(args) / "raw", Path(args.to), args.before)
    print(f"moved {len(days)} day folder(s) to {args.to}")
    return 0


def calibrate_cmd(args) -> int:
    from datetime import timedelta

    from .services.execution_calibration import feed_latency, fill_quality

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
    from .services.model_gateway import ModelGateway
    from .services.model_usage import ModelUsage
    from .services.research_assistant import assist

    db, symbol = open_db(args), args.symbol.upper()
    gateway, usage = ModelGateway(), ModelUsage(store_root(args) / "model_usage.db")

    async def complete(action, value):
        result = await gateway.request(action, value)
        usage.record(result)
        return result

    async def go():
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


def verify_segments_cmd(args) -> int:
    from .adapters.store import verify_segments

    db = open_db(args)
    try:
        report = verify_segments(db, [store_root(args) / "raw", *(Path(p) for p in args.archive)])
    finally:
        db.c.close()
    print(json.dumps(report, indent=2))
    return 1 if report["mismatched"] else 0


def compact_cmd(args) -> int:
    from .adapters.store import compact_quotes

    db = open_db(args)
    try:
        before = parse_ts(args.before)
        removed = compact_quotes(db, before, args.bucket, now_utc())
        if args.vacuum:
            db.c.execute("VACUUM")
    finally:
        db.c.close()
    print(f"removed {removed} quote rows before {args.before} (kept the last per market and {args.bucket})")
    return 0


def summary_cmd(args):
    from .adapters.run_store import load_run
    from .services.portable_report import render_html
    from .services.reports import paper_summary

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
    from .adapters.run_store import record_decision, run_path
    from .services.diagnostics import diagnostics
    from .services.reports import economic_report, markdown

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
    from .domain.sim import CostModel
    from .services.live_paper import watch

    if not (store_root(args) / "market.db").exists():
        raise ValueError("start the collector first")
    cash = Decimal(args.cash or (300_000_000 if args.symbol.upper().endswith("TMN") else 1000))
    subscriptions = tuple(x.strip() for x in args.subscribe.split(",") if x.strip())
    cost = CostModel(Decimal(args.fee), timedelta_ms(args.latency_ms))
    db = open_db(args)
    try:
        asyncio.run(watch(db, store_root(args) / "runs", args.symbol.upper(), args.seconds,
                          args.res, args.fast, args.slow, cash, args.demo, subscriptions, cost,
                          strategy_id=args.strategy, params=json.loads(args.params) if args.params else None))
    finally:
        db.c.close()
    return 0


def key_cmd(args) -> int:
    """Store a Wallex key DPAPI-encrypted for this Windows user; never echoes it."""
    import getpass
    import os

    from .adapters import secret_store

    if args.op == "set-backup":
        phrase = getpass.getpass("Offline backup passphrase (sealed to this Windows user): ")
        if phrase != getpass.getpass("Repeat: "):
            raise ValueError("passphrases differ; nothing stored")
        print(f"backup passphrase stored at {secret_store.save_backup_passphrase(phrase)}")
        return 0
    if args.op == "show":
        for role in secret_store.ROLES:
            try:
                print(f"{role}: {secret_store.masked(secret_store.load(role))}")
            except ValueError:
                print(f"{role}: not stored")
        return 0
    key = os.environ.pop("WALLEX_KEY_INPUT", "") or getpass.getpass(f"Wallex {args.role} key: ")
    path = secret_store.save(args.role, key)
    print(f"{args.role} key {secret_store.masked(key.strip())} stored at {path}")
    return 0


def account_cmd(args) -> int:
    """Sanitized account observations from the selected read-only transport."""
    from .adapters.wallex_account_read import ReadUncertain
    from .domain.account_observations import project_account
    from .domain.model import iso
    from .services.external_journal import ExternalJournal

    if len(args.order) > 100 or len(set(args.order)) != len(args.order):
        print("error: provide at most 100 distinct order identities (nothing recorded)", file=sys.stderr)
        return 3

    async def observe(reader):
        balances = await reader.balances()
        fee = await reader.fee_rates()
        evidence = [await reader.manual_order_evidence(cid) for cid in args.order]
        pages = []
        for kind, field in (("OPEN", "open_orders_page"), ("HISTORY", "history_page")):
            number = getattr(args, field, None)
            if number is not None:
                pages.append(await reader.order_page(kind=kind, page=number, per_page=getattr(args, "per_page", 100)))
        by_id = {row["client_id"]: row for row in evidence}
        for page in pages:
            for row in page["orders"]:
                prior = by_id.get(row["client_id"])
                if prior is not None and prior != row:
                    raise ReadUncertain("order changed across separate observations; refresh before recording")
                by_id[row["client_id"]] = row
        evidence = list(by_id.values())
        orders = [{"client_id": row["client_id"], "status": row["raw_status"],
                   "symbol": row["symbol"], "filled": row["executed_qty"]} for row in evidence]
        return balances, fee, orders, evidence, pages, getattr(reader, "receipts", [])

    service_source = getattr(args, "source", "user") == "service"

    async def read():
        if service_source:
            from .adapters.service_account_read import ServiceAccountReader
            return await observe(ServiceAccountReader())
        import aiohttp

        from .adapters import secret_store
        from .adapters.wallex_account_read import WallexAccountReader
        headers = {"x-api-key": secret_store.load("read")}
        async with aiohttp.ClientSession(headers=headers) as session:
            return await observe(WallexAccountReader(session))

    try:
        balances, fee, orders, evidence, pages, receipts = asyncio.run(read())
    except ReadUncertain as e:
        print(f"error: {e} (state UNKNOWN, nothing recorded)", file=sys.stderr)
        return 3
    observed = project_account("main", iso(now_utc()), balances=balances, orders=orders)
    if evidence:
        observed["order_evidence"] = evidence
    if pages:
        observed["order_pages"] = pages
    if receipts:
        observed["service_receipts"] = receipts
    nonzero = [b for b in observed["balances"] if Decimal(b["venue_value"]) or Decimal(b["venue_locked"])]
    fee_rates = fee
    transport = "EXECUTOR_SERVICE_WINHTTP" if service_source else "INTERACTIVE_USER_GET"
    pairs = sorted({(r["maker"], r["taker"]) for r in fee.values()})
    fee = {"symbols": len(fee), "maker_taker_rates": [list(p) for p in pairs],
           **{s: fee[s] for s in ("BTCUSDT", "USDTTMN", "BTCTMN") if s in fee}}
    print(json.dumps({"observed_at": observed["observed_at"], "fee": fee, "balances": nonzero,
                      "orders": observed["orders"], "order_evidence": evidence,
                      "order_pages": pages, "collection_complete": False,
                      "transport": transport,
                      **({"service_receipts": receipts} if receipts else {}),
                      "permission_status": "UNVERIFIED",
                      "funded_authority": False}, ensure_ascii=False, indent=2))
    if args.record:
        root = store_root(args)
        root.mkdir(parents=True, exist_ok=True)
        with ExternalJournal(root / "external_journal.db") as journal:
            print(f"{journal.record(observed, fee_rates=fee_rates, transport=transport)} order events and account snapshot recorded to the Journal")
    return 0


def external_observe_cmd(args) -> int:
    """Import only sanitized external observations, never account authority."""
    from .services.operator_actions import operator_action
    report = operator_action(store_root(args), "external-import", _strict_offline_json(args.path, max_bytes=1_048_576))
    print(f"{report['recorded_observations']} external observations recorded (read-only, unverified; not funded).")
    return 0


def _strict_offline_json(path: str, *, max_bytes: int) -> dict:
    """Never deserialize raw authenticated venue responses or secret fields."""
    source = Path(path)
    if source.is_symlink() or not source.is_file() or not 1 <= source.stat().st_size <= max_bytes:
        raise ValueError("offline input must be a bounded unsymlinked regular JSON file")
    result = strict_loads(source.read_text("utf-8"), "offline JSON input")
    if type(result) is not dict:
        raise ValueError("offline input must be a JSON object")
    return result


def ticket_queue_add_cmd(args) -> int:
    """Persist the fully reconstructed dry-run ticket, never an approval."""
    from .services.offline_review_journal import OfflineReviewJournal

    preview = _strict_offline_json(args.path, max_bytes=16384)
    root = store_root(args)
    root.mkdir(parents=True, exist_ok=True)
    with OfflineReviewJournal(root / "offline_reviews.db") as reviews:
        key = reviews.record(preview)
    print(json.dumps({
        "preview_sha256": key, "state": "PREVIEWED",
        "tier1_approval": False, "funded_authority": False,
        "order_submitted": False,
    }, ensure_ascii=False, indent=2))
    return 0


def ticket_queue_review_cmd(args) -> int:
    """Record offline ACKNOWLEDGE/REJECT; never issue T1 or live permission."""
    from .services.offline_review_journal import OfflineReviewJournal

    root = store_root(args)
    root.mkdir(parents=True, exist_ok=True)
    with OfflineReviewJournal(root / "offline_reviews.db") as reviews:
        result = reviews.review(args.preview_sha256, args.decision, at=args.at)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def probe_budget_stage_cmd(args) -> int:
    """Stage a fake/manual probe within an immutable offline full-loss budget."""
    from .services.operator_actions import operator_action

    record = _strict_offline_json(args.path, max_bytes=8192)
    report = operator_action(store_root(args), "probe-stage", {"total_loss_limit": args.total_loss_limit,
                             "quote_asset": args.quote_asset, "probe": record})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def conversion_report_cmd(args) -> int:
    """Compute synthetic implementation shortfall; never submits orders."""
    from .services.operator_actions import operator_action
    report = operator_action(store_root(args), "conversion-report", _strict_offline_json(args.path, max_bytes=65_536))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def paper_research_cmd(args) -> int:
    """Evaluate a bounded offline artifact without opening a store or venue."""
    from .domain.market_models import evaluate_artifact

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


def ticket_preview_cmd(args) -> int:
    """Build an exact-cost OFFLINE preview, never an Executor order command."""
    from .domain.assisted_ticket import prepare_preview_from_json

    params = _strict_offline_json(args.path, max_bytes=8192)
    print(json.dumps(prepare_preview_from_json(params), ensure_ascii=False, indent=2))
    return 0


def venue_fact_import_cmd(args) -> int:
    """Store strict, sanitized C1 evidence metadata; never accept raw API JSON.

    A claimed source is NOT authenticated. This command can never certify
    venue order methods, provision keys or authorize any funded operation.
    """
    from .services.operator_actions import operator_action
    report = operator_action(store_root(args), "venue-fact-import", _strict_offline_json(args.path, max_bytes=16_384))
    print(f"VenueFacts evidence #{report['sequence']} recorded (unverified origin; no order authority).")
    return 0


def backup_once_cmd(args) -> int:
    """Manual offline encrypted backup to a pre-existing independent volume.

    No passphrase in arguments, environment variables or command history.
    This is NOT scheduled remote backup, does not provision venue credentials,
    and cannot establish that another machine holds an archive.
    """
    import getpass

    from .services.backup_rotation import backup_once

    if getattr(args, "stored_passphrase", False):
        from .adapters.secret_store import load_backup_passphrase
        phrase = load_backup_passphrase()
    elif not sys.stdin.isatty():
        raise ValueError("backup-once requires an interactive protected console or --stored-passphrase")
    else:
        phrase = getpass.getpass("Offline ledger recovery passphrase (not a venue API key): ")
    try:
        report = backup_once(args.ledger, args.destination,
                             passphrase=phrase, keep=args.keep)
    finally:
        del phrase
    _backup_receipt(args, "BACKUP", report)
    # Never output a recovery passphrase, access token, or private API key.
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def restore_backup_cmd(args) -> int:
    """Restore an encrypted offline backup into a new ledger file (B3 second-machine restore).

    Passphrase only from an interactive console. Never overwrites; restored ledger
    is DISARMED evidence until the Executor reconciles it.
    """
    import getpass

    from .services.encrypted_backup import restore_backup

    if not sys.stdin.isatty():
        raise ValueError("restore-backup requires an interactive protected console")
    phrase = getpass.getpass("Offline ledger recovery passphrase: ")
    try:
        report = restore_backup(args.bundle, args.destination, passphrase=phrase)
    finally:
        del phrase
    import platform
    from datetime import datetime
    report |= {"restored_at": iso(datetime.now(UTC)), "host": platform.node(), "mode_after": "DISARMED"}
    _backup_receipt(args, "RESTORE", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def restore_drill_cmd(args) -> int:
    """Prove the newest bundle restores: decrypt and verify into a temporary ledger, then remove it."""
    import getpass
    import tempfile

    from .services.encrypted_backup import restore_backup

    bundles = sorted(Path(args.folder).glob("*.tgbak"), key=lambda p: p.stat().st_mtime)
    if not bundles:
        raise ValueError(f"no .tgbak bundles in {args.folder}")
    if args.stored_passphrase:
        from .adapters.secret_store import load_backup_passphrase
        phrase = load_backup_passphrase()
    elif not sys.stdin.isatty():
        raise ValueError("restore-drill requires an interactive console or --stored-passphrase")
    else:
        phrase = getpass.getpass("Offline ledger recovery passphrase: ")
    with tempfile.TemporaryDirectory(prefix="gym-restore-drill-") as scratch:
        try:
            report = restore_backup(bundles[-1], Path(scratch) / "ledger.db", passphrase=phrase)
        finally:
            del phrase
    report |= {"bundle": str(bundles[-1]), "drill": True, "restored_copy": "deleted"}
    _backup_receipt(args, "RESTORE", report)  # a drill is a verified restore; the copy is gone
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


def _backup_receipt(args, kind, report):
    from .services.backup_status import record
    try:
        record(store_root(args), kind, report)
        report["status_recorded"] = True
    except (ValueError, OSError, sqlite3.Error, KeyError, AttributeError):
        # A display receipt failure cannot undo the completed encrypted backup/restore.
        report["status_recorded"] = False
        report["status_error"] = "Operation completed; local display receipt unavailable. Do not repeat the operation automatically."


def update_check_cmd(args) -> int:
    """Admission check before an Executor update; exit 2 with the reason when unsafe."""
    from .services.restore_gate import RestoreUnsafe, inspect_ledger
    from .services.update_gate import assess_update

    try:
        ledger = inspect_ledger(args.ledger)
    except RestoreUnsafe as e:
        ledger = {"error": str(e)}
    report = assess_update(open_positions=args.open_positions, unknown_orders=args.unknown_orders,
                           alternative_protection=args.alternative_protection,
                           accepted_outage=args.accepted_outage,
                           ledger_integrity_ok="error" not in ledger)
    print(json.dumps(report | {"ledger": ledger}, ensure_ascii=False, indent=2))
    return 0


def verify_backup_manifest_cmd(args) -> int:
    """Verify ciphertext against an *independently pinned* public key.

    The public key is NOT fetched from the backup, manifest or network.
    This operation does not restore a ledger or establish off-machine custody.
    """
    from .services import backup_manifest

    def read_regular(path_str: str, limit: int, label: str, exact: int | None = None) -> bytes:
        source = Path(path_str)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"{label} must be a regular unsymlinked file")
        if not 1 <= source.stat().st_size <= limit:
            raise ValueError(f"{label} exceeds size limit")
        # These bounded inputs are signatures and public metadata, never
        # private signing keys or recovery passphrases.
        raw = source.read_bytes()
        if len(raw) > limit or (exact is not None and len(raw) != exact):
            raise ValueError(f"{label} has an invalid length")
        return raw

    manifest = read_regular(args.manifest, 4096, "manifest")
    signature = read_regular(args.signature, 64, "signature", 64)
    public_key = read_regular(args.pinned_public_key, 32, "pinned public key", 32)
    report = backup_manifest.verify_signed_backup(
        Path(args.bundle), manifest_bytes=manifest, signature=signature,
        trusted_public_key=public_key,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def timedelta_ms(ms: int):
    from datetime import timedelta

    return timedelta(milliseconds=ms)


async def serve(args):
    from aiohttp import web

    from .api.server import make_app

    symbols = ([s.strip().upper() for s in args.watch.split(",") if s.strip()] if args.watch
               else DEFAULT_WATCH.split(",") if args.demo else None)
    added = tuple(s.strip().upper() for s in args.add_symbols.split(",") if s.strip())
    removed = tuple(s.strip().upper() for s in args.remove_symbols.split(",") if s.strip())
    if args.demo and (added or removed):
        raise SystemExit("--add-symbols/--remove-symbols require the live Wallex catalog")
    db = open_db(args)
    seg = SegmentWriter(Path(args.data) / ("demo" if args.demo else "live") / "raw", db)
    col = Collector(db, seg, symbols, demo=args.demo, asset_count=args.assets,
                    add_symbols=added, remove_symbols=removed, depth_levels=args.depth_levels,
                    archive=(Path(args.archive_to), args.keep_days) if args.archive_to else None)
    from .services.external_journal import ExternalJournal
    from .services.offline_review_journal import OfflineReviewJournal
    from .services.venue_facts import VenueFactsJournal
    external_journal = ExternalJournal(store_root(args) / "external_journal.db")
    venue_facts = VenueFactsJournal(store_root(args) / "venue_facts.db")
    offline_reviews = OfflineReviewJournal(store_root(args) / "offline_reviews.db")
    from .services.event_log import configure, event
    events = configure(store_root(args))
    event("collector_started", store="demo" if args.demo else "live", port=args.port, events=str(events))
    token = secrets.token_urlsafe(24)
    runner = web.AppRunner(make_app(col, RuleService(db), token,
                                    store_root(args) / "runs", external_journal=external_journal,
                                    venue_facts=venue_facts, offline_review_journal=offline_reviews,
                                    chaos_report=Path(args.data) / "chaos" / "report.json"))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    # The fragment carries the session key; browsers never send it to the server or other local processes.
    url = f"http://127.0.0.1:{args.port}/#t={token}"
    print(f"TradingGYM {'DEMO ' if args.demo else ''}Observatory: {url}  (private link; Ctrl+C to stop)", flush=True)
    if args.link_file:
        # For background starts with no console. Owner-only on POSIX; on Windows the profile folder's ACL applies.
        link = Path(args.link_file)
        link.parent.mkdir(parents=True, exist_ok=True)
        link.write_text(url + "\n", "utf-8")
        link.chmod(0o600)
    if not args.no_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        await col.run()
    finally:
        seg.close()
        await runner.cleanup()
        external_journal.conn.close()
        venue_facts.conn.close()
        offline_reviews.conn.close()


def research_cmd(args):
    from .services.research_actions import OBJECT_ACTIONS, research_action

    root = store_root(args)
    if args.action == "mcp":
        from .services.research_mcp import serve_stdio
        return serve_stdio(root)
    if args.action == "start":
        from .services.research_runner import watch
        root.mkdir(parents=True, exist_ok=True)
        result = asyncio.run(watch(root, store="demo" if args.demo else "live", poll_seconds=args.poll_seconds))
    else:
        value = args.input
        if args.action in OBJECT_ACTIONS:
            if not value:
                raise ValueError("this research action requires an input JSON file")
            value = _strict_offline_json(value, max_bytes=65536)
        from .services.research_process import (
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


def operator_review_cmd(args):
    from .adapters.service_review import review
    from .adapters.wallex_account_read import ReadUncertain
    try:
        result = asyncio.run(review(_strict_offline_json(args.input, max_bytes=16384)))
    except ReadUncertain:
        print(json.dumps({"error": "native review unacknowledged; inspect the same identity before retry",
            "operation_may_have_committed": True, "automatic_retry_allowed": False, "funded_authority": False, "order_submitted": False}))
        return 3
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 3 if result["state"] in ("DEFERRED", "REFUSED", "MISSING") else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="gymctl")
    p.add_argument("--data", default="data", help="data directory (default ./data)")
    sub = p.add_subparsers(dest="cmd", required=True)
    native_review = sub.add_parser("operator-review", help="explicit protected Windows operator intent; never submits an order")
    native_review.add_argument("input", help="native review JSON file (status, inspect, approve, prepare or revoke)")
    models = sub.add_parser("models", help="optional advisory provider/auth/key/preset gateway")
    models.add_argument("model_args", nargs=argparse.REMAINDER)
    research = sub.add_parser("research", help="paper hypothesis, shadow, schedule and read-only MCP workflows")
    from .services.research_actions import WORKSPACE_ACTIONS
    research.add_argument("action", choices=("register", "shadow-open", "shadow-close", "schedule", "tick", "start", "pause", "resume", "list", "mcp", "claim-check",
                                            "review", "outcome-add", "outcomes", "final-register", "final-run", "final-status", "observe-import", "screen", "derived", "candles", *WORKSPACE_ACTIONS))
    research.add_argument("input", nargs="?", help="input JSON file, or job ID for pause/resume")
    research.add_argument("--at", help="zoned ISO time for a bounded scheduler tick")
    research.add_argument("--poll-seconds", type=float, default=5, help="supervised research polling interval, 1..60 seconds")
    research.add_argument("--demo", action="store_true", help="use the isolated DEMO research ledger")
    r = sub.add_parser("run", help="run collector + local API + UI")
    r.add_argument("--demo", action="store_true", help="synthetic DEMO feed, stored separately")
    r.add_argument("--port", type=int, default=8765)
    r.add_argument("--no-browser", action="store_true", help="print the private workspace link without opening a browser")
    r.add_argument("--link-file", help="also write the private link to this file (for starts without a console); keep it in your profile")
    r.add_argument("--archive-to", metavar="FOLDER",
                   help="once a day, move finished raw day folders older than --keep-days to this folder (another drive)")
    r.add_argument("--keep-days", type=int, default=7, choices=range(1, 366), metavar="1..365")
    r.add_argument("--depth-levels", type=int, default=0, metavar="0..20",
                   help="store this many order-book levels per side with each quote for --walk-depth replays (more disk)")
    r.add_argument("--assets", type=parse_asset_count, default=None, metavar="all|1..500",
                   help="all supported spot assets by default (including flagged listings), or a ranked non-risky count; live auto-universe only")
    r.add_argument("--watch", help="explicit comma-separated market override; otherwise select --assets from the full catalog")
    r.add_argument("--add-symbols", default="", help="comma-separated catalog markets to add after selection")
    r.add_argument("--remove-symbols", default="", help="comma-separated markets to remove after selection")
    ru = sub.add_parser("rules", help="venue rules")
    ru.add_argument("--demo", action="store_true", help="operate on the demo store")
    rs = ru.add_subparsers(dest="op", required=True)
    rs.add_parser("list").add_argument("--at", help="rule vintage as of this ISO time")
    for name in ("add", "edit", "import"):
        rs.add_parser(name).add_argument("file", help="JSON file (import: a list)")
    rs.add_parser("export").add_argument("file", nargs="?")
    rs.add_parser("disable").add_argument("id")
    rb = rs.add_parser("rollback")
    rb.add_argument("id")
    rb.add_argument("seq", type=int)
    rs.add_parser("preset").add_argument("name")
    ck = rs.add_parser("check", help="what does the rule set say for this order?")
    ck.add_argument("symbol")
    ck.add_argument("side", choices=["BUY", "SELL"])
    ck.add_argument("intent", choices=["ENTRY", "EXIT"])
    ck.add_argument("--at")
    ck.add_argument("--used", default="0", help="quota already used today (all channels)")
    from .domain.registry import catalog
    replay = sub.add_parser("paper", help="replay a registered strategy with matched baselines and costs")
    replay.add_argument("--strategy", choices=[entry["id"] for entry in catalog()], default="ema-trend")
    replay.add_argument("--params", help="strategy parameter JSON; omitted values use registry defaults")
    replay.add_argument("--fast", type=int, default=8, help="legacy EMA fast length; use --params for other strategies")
    replay.add_argument("--slow", type=int, default=21, help="legacy EMA slow length")
    comparison = sub.add_parser("compare", help="paired PAPER ONLY replay on identical data, costs and snapshots")
    comparison.add_argument("--candidate", action="append", required=True,
                            help='candidate JSON, e.g. {"strategy":"ema-trend","params":{"fast":3,"slow":8}}; repeat 2..4 times')
    validation = sub.add_parser("validate", help="chronological 70/30 paper selection diagnostic, with one decision period purged")
    validation.add_argument("--candidate", action="append", required=True, help="registered candidate JSON; repeat 2..4 times")
    validation.add_argument("--folds", type=int, choices=range(1, 6), default=1,
                            help="1..5 successive independent 70/30 windows; default 1, not an expanding training run")
    shared = sub.add_parser("portfolio", help="one strategy over 2..8 markets sharing one cash balance (PAPER ONLY)")
    shared.add_argument("--strategy", choices=[entry["id"] for entry in catalog()], default="ema-trend")
    shared.add_argument("--params", help="strategy parameter JSON; omitted values use registry defaults")
    for command in (replay, comparison, validation, shared):
        command.add_argument("symbol", help="market, or comma-separated markets for portfolio")
        command.add_argument("--demo", action="store_true")
        command.add_argument("--from", dest="start", help="UTC ISO time with zone (default: first stored quote)")
        command.add_argument("--to", dest="end", help="exclusive UTC ISO cut (default: last stored quote)")
        command.add_argument("--res", default="15min", choices=list(RESOLUTIONS), help="decision close from the shared bar engine")
        command.add_argument("--subscribe", default="", help="comma-separated additional on-close resolutions")
        command.add_argument("--cash", help="starting quote cash (default 1000 USDT or 300,000,000 TMN)")
        command.add_argument("--fee", default=DEFAULT_FEE, help=FEE_HELP)
        command.add_argument("--latency-ms", type=int, default=500)
        command.add_argument("--participation", help="max share (0..1] of the displayed best-level size per fill; larger orders are resized")
        command.add_argument("--walk-depth", action="store_true",
                             help="fill across stored order-book levels at their volume-weighted price (needs run --depth-levels)")
        command.add_argument("--order-type", choices=["market", "limit"], default="market",
                             help="limit: rest at the near touch and fill from later trade prints (queue-aware) or expire")
        command.add_argument("--maker-fee", help="fee fraction for limit fills (default: --fee)")
        command.add_argument("--max-fraction", help="cap every entry at this share (0..1] of cash, e.g. a fractional-Kelly figure")
        command.add_argument("--vol-target", help="scale entries so the position's per-bar volatility is about this (0..1], e.g. 0.002")
        command.add_argument("--carry-remainder", action="store_true",
                             help="keep working a resized order on later quotes until it fills or max wait passes")
        command.add_argument("--rules", choices=["point-in-time", "today"], default="point-in-time")
    research = sub.add_parser("paper-research", help="offline market, portfolio, cash-flow return and forecast scoring diagnostics")
    research.add_argument("path", help='JSON object with "model" and exact "parameters"; decimals are strings')
    research.add_argument("--output", help="create a JSON report outside data/; never overwrite")
    for name, help_text in (("spreads", "observed spread distributions by pair and Tehran hour"),
                            ("trade-flow", "observed VWAP, volume and aggressor flow, bounded by receipt time")):
        statistics = sub.add_parser(name, help=help_text)
        statistics.add_argument("symbol", nargs="?", help="default: every observed market")
        statistics.add_argument("--demo", action="store_true")
        statistics.add_argument("--from", dest="start")
        statistics.add_argument("--to", dest="end")
        statistics.add_argument("--output", help="create a JSON report (never overwrite an existing file)")
    technicals = sub.add_parser("technicals", help="read-only closed-bar averages, RSI/MACD, ATR/ADX, Keltner and TRIX; no trading signals")
    technicals.add_argument("symbol")
    technicals.add_argument("--from", dest="start", required=True)
    technicals.add_argument("--to", dest="end", required=True)
    technicals.add_argument("--res", action="append", choices=list(FIXED_RESOLUTIONS), help="fixed resolution; repeat for up to four views of one snapshot (default: 15min)")
    technicals.add_argument("--demo", action="store_true")
    technicals.add_argument("--output", help="create a new JSON report; never overwrite")
    candles = sub.add_parser("candles", help="cross-check internal trade bars against venue candles (DATA-05)")
    candles.add_argument("symbol")
    candles.add_argument("--demo", action="store_true")
    candles.add_argument("--from", dest="start", help="default: two hours before --to")
    candles.add_argument("--to", dest="end", help="default: now")
    candles.add_argument("--tolerance-bps", default="10")
    candles.add_argument("--as-of", help="exclude receipts/fetches at or after this zoned knowledge cutoff")
    candles.add_argument("--fetch", action="store_true", help="fetch venue candles for the range first")
    candles.add_argument("--fill-gaps", action="store_true", help="fetch venue 1min candles only for quote gaps over 120 s and log each backfill")
    candles.add_argument("--record", action="store_true", help="write CROSS_FEED_DIVERGENCE quality events")
    candles.add_argument("--json", action="store_true")
    bk = sub.add_parser("backup-once", help="manual offline encrypted ledger backup on a separate mounted volume")
    bk.add_argument("ledger", help="Executor ledger database file; no keys or secrets.dat")
    bk.add_argument("destination", help="pre-existing independent-volume backup directory")
    bk.add_argument("--keep", type=int, default=7, help="retain 2..365 verified bundles, default 7")
    bk.add_argument("--stored-passphrase", action="store_true", help="use the passphrase sealed by `key set-backup` (scheduled runs)")
    rd = sub.add_parser("restore-drill", help="restore the newest backup into a temporary file, verify it, then delete it")
    rd.add_argument("folder", help="backup folder holding .tgbak bundles")
    rd.add_argument("--stored-passphrase", action="store_true", help="use the passphrase sealed by `key set-backup`")
    rb = sub.add_parser("restore-backup", help="decrypt and verify an offline backup into a NEW ledger file (no overwrite)")
    rb.add_argument("bundle", help="encrypted .tgbak bundle")
    rb.add_argument("destination", help="new ledger path; must not exist")
    uc = sub.add_parser("update-check", help="refuse an unsafe Executor update (verifies ledger; installs nothing)")
    uc.add_argument("ledger", help="quiescent Executor ledger snapshot to verify")
    uc.add_argument("--open-positions", type=int, required=True)
    uc.add_argument("--unknown-orders", type=int, required=True)
    uc.add_argument("--alternative-protection", action="store_true", help="independently verified venue-side protection exists")
    uc.add_argument("--accepted-outage", action="store_true", help="operator accepts unprotected positions during the update")
    ticket = sub.add_parser("ticket-preview", help="preview a quote-fee order ticket OFFLINE; no funded approval or POST")
    ticket.add_argument("path", help="safe market snapshot and bounds JSON; never credentials")
    tq = sub.add_parser("ticket-queue-add", help="persist a fully validated DRY_RUN preview; no live permission")
    tq.add_argument("path", help="JSON output from ticket-preview")
    tq.add_argument("--demo", action="store_true")
    tr = sub.add_parser("ticket-queue-review", help="ACKNOWLEDGE or REJECT an offline preview; not a T1 approval")
    tr.add_argument("preview_sha256", help="immutable DRY_RUN preview hash")
    tr.add_argument("decision", help="ACKNOWLEDGE or REJECT, never APPROVE_LIVE")
    tr.add_argument("--at", required=True, help="zoned review timestamp within ticket validity")
    tr.add_argument("--demo", action="store_true")
    probe = sub.add_parser("probe-budget-stage", help="stage one manual probe within immutable OFFLINE full-loss budget; cannot place orders")
    probe.add_argument("--total-loss-limit", required=True, help="total amount operator accepts losing in full; not a venue credential")
    probe.add_argument("--quote-asset", choices=["USDT", "TMN"], required=True)
    probe.add_argument("path", help="bounded sanitized manual probe metadata")
    probe.add_argument("--demo", action="store_true")
    conversion = sub.add_parser("conversion-report", help="offline Fake Venue conversion and arrival-benchmark shortfall")
    conversion.add_argument("path", help="synthetic conversion instruction and fake fills JSON")
    vf = sub.add_parser("venue-fact-import", help="import strictly sanitized offline C1 venue validation metadata")
    vf.add_argument("path", help="bounded VenueFacts JSON metadata (never raw API results or credentials)")
    vf.add_argument("--demo", action="store_true", help="record separately from real observations")
    bv = sub.add_parser("verify-backup-manifest",
                        help="verify detached signed archive against an operator-pinned Ed25519 public key")
    bv.add_argument("bundle", help="encrypted ciphertext .tgbak, never secrets.dat")
    bv.add_argument("manifest", help="canonical detached manifest JSON")
    bv.add_argument("signature", help="detached raw 64-byte Ed25519 signature")
    bv.add_argument("pinned_public_key", help="trusted out-of-band raw 32-byte Ed25519 public key")
    ky = sub.add_parser("key", help="store Wallex API keys encrypted for this Windows user (DPAPI)")
    kys = ky.add_subparsers(dest="op", required=True)
    kys.add_parser("set").add_argument("role", choices=["read", "trade"])
    kys.add_parser("show", help="masked key IDs only")
    kys.add_parser("set-backup", help="seal the offline-backup passphrase to this Windows user for scheduled backups")
    ac = sub.add_parser("account", help="read-only Wallex balances, fee and order status with the stored read key")
    ac.add_argument("--source", choices=("user", "service"), default="user",
                    help="user: stored read key; service: protected installed helper (administrator only)")
    ac.add_argument("--order", action="append", default=[], metavar="CLIENT_ID", help="order to look up (repeatable)")
    ac.add_argument("--open-orders-page", type=int, choices=range(1, 1001), metavar="1..1000", help="read one explicit open-order page")
    ac.add_argument("--history-page", type=int, choices=range(1, 1001), metavar="1..1000", help="read one explicit history page")
    ac.add_argument("--per-page", type=int, choices=range(1, 101), default=100, metavar="1..100", help="bounded page size; no automatic walk or absence inference")
    ac.add_argument("--record", action="store_true", help="append the observation to the local Journal")
    ext = sub.add_parser("external-observe", help="import read-only manual account observation JSON to the local Journal")
    ext.add_argument("path", help="local sanitized observation JSON file; no API keys")
    ext.add_argument("--demo", action="store_true")
    summary = sub.add_parser("summary", help="allowlisted portable paper summary, without private notes or account records")
    summary.add_argument("run_id")
    summary.add_argument("--format", choices=("json", "html"), default="json")
    summary.add_argument("--output", help="create a new report file; never overwrite")
    summary.add_argument("--demo", action="store_true")
    ev = sub.add_parser("evidence", help="economic report and optional immutable claim/capital decision (never arms trading)")
    ev.add_argument("run_id")
    ev.add_argument("--demo", action="store_true")
    ev.add_argument("--diagnostics", action="store_true", help="run repeatability, truncation, warmup and total-cost stress")
    ev.add_argument("--decide", choices=["NONE", "EXPERIMENTAL"])
    ev.add_argument("--cap", default="0")
    ev.add_argument("--ccy", choices=["USDT", "TMN"], default="USDT")
    ev.add_argument("--note", default="")
    se = sub.add_parser("session", help="live paper on the collector database; Ctrl+C preserves ABORTED cursor")
    se.add_argument("symbol")
    se.add_argument("--demo", action="store_true")
    se.add_argument("--seconds", type=int, default=3600, help="duration after warmup")
    se.add_argument("--res", default="15min", choices=list(RESOLUTIONS))
    se.add_argument("--subscribe", default="", help="comma-separated additional on-close resolutions")
    se.add_argument("--fast", type=int, default=8)
    se.add_argument("--slow", type=int, default=21)
    se.add_argument("--strategy", choices=[entry["id"] for entry in catalog()], default="ema-trend")
    se.add_argument("--params", help="strategy parameters as JSON; uses registry defaults when omitted")
    se.add_argument("--cash")
    se.add_argument("--fee", default=DEFAULT_FEE, help=FEE_HELP)
    se.add_argument("--latency-ms", type=int, default=500)
    sub.add_parser("demo-seed", help="write synthetic DEMO history into data/demo").add_argument("--hours", type=int, default=72)
    cal = sub.add_parser("calibrate", help="feed latency and paper fill quality, to set --latency-ms and judge costs")
    cal.add_argument("--hours", type=int, default=24, choices=range(1, 24 * 31 + 1), metavar="1..744")
    cal.add_argument("--demo", action="store_true")
    asst = sub.add_parser("assistant", help="a model proposes 2..4 strategy configurations; they are tested on paper and saved")
    asst.add_argument("symbol")
    asst.add_argument("--preset", required=True, help="model preset from the AI connections page")
    asst.add_argument("--budget", type=int, default=3, choices=range(2, 5), help="configurations to test (2..4)")
    asst.add_argument("--res", default="15min", choices=list(RESOLUTIONS))
    asst.add_argument("--from", dest="start")
    asst.add_argument("--to", dest="end")
    asst.add_argument("--cash")
    asst.add_argument("--demo", action="store_true")
    vs = sub.add_parser("verify-segments", help="re-hash every closed raw segment against the manifest")
    vs.add_argument("--archive", action="append", default=[], help="also look in this archive folder (repeatable)")
    vs.add_argument("--demo", action="store_true")
    cq = sub.add_parser("compact", help="keep one quote row per market and second/minute before a cut (raw archive keeps all)")
    cq.add_argument("--before", required=True, help="zoned ISO time; only older rows are compacted")
    cq.add_argument("--bucket", choices=["1s", "1min"], default="1s")
    cq.add_argument("--vacuum", action="store_true", help="return the freed space to the disk (slow; stop the collector first)")
    cq.add_argument("--demo", action="store_true")
    rm = sub.add_parser("raw-move", help="move finished raw archive day folders to another volume")
    rm.add_argument("--before", required=True, help="move days strictly before YYYYMMDD (UTC)")
    rm.add_argument("--to", required=True, help="destination directory, ideally on another drive")
    rm.add_argument("--demo", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "models":
        from .services.model_gateway import run
        return run(args.model_args)

    commands = {"summary": summary_cmd, "research": research_cmd, "paper-research": paper_research_cmd, "key": key_cmd, "account": account_cmd, "ticket-queue-add": ticket_queue_add_cmd, "ticket-queue-review": ticket_queue_review_cmd, "probe-budget-stage": probe_budget_stage_cmd, "conversion-report": conversion_report_cmd, "ticket-preview": ticket_preview_cmd, "venue-fact-import": venue_fact_import_cmd, "verify-backup-manifest": verify_backup_manifest_cmd, "backup-once": backup_once_cmd, "restore-backup": restore_backup_cmd, "restore-drill": restore_drill_cmd, "update-check": update_check_cmd, "external-observe": external_observe_cmd, "evidence": evidence_cmd, "session": session_cmd, "paper": replay_cmd, "compare": replay_cmd, "portfolio": replay_cmd,
                "demo-seed": demo_seed, "spreads": market_statistics_cmd, "trade-flow": market_statistics_cmd,
                "candles": candles_cmd, "validate": replay_cmd, "technicals": technical_report_cmd, "raw-move": raw_move_cmd, "compact": compact_cmd, "verify-segments": verify_segments_cmd,
                "assistant": assistant_cmd, "calibrate": calibrate_cmd}
    commands["operator-review"] = operator_review_cmd
    if args.cmd in commands:
        try:
            return commands[args.cmd](args)
        except (ValueError, OSError, DecimalException, sqlite3.Error) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    if args.cmd == "run":
        from .adapters.store import DiskLow
        try:
            asyncio.run(serve(args))
        except KeyboardInterrupt:
            pass
        except BaseExceptionGroup as group:  # the collector TaskGroup wraps a low-disk stop
            low = group.subgroup(DiskLow)
            if low is None:
                raise
            print(f"error: {low.exceptions[0]}", file=sys.stderr)
            return 2
        return 0

    svc, now = RuleService(open_db(args)), now_utc()
    def out(value):
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    try:
        if args.op == "list":
            version, rules, q = svc.load(parse_ts(args.at) if args.at else None)
            for x in rules:
                print(f"{'-' if x.disabled else '+'} {x.id:36} {x.cls:8} {x.family:14} {x.status:9} {x.action:11} "
                      f"{x.effective_from:%Y-%m-%d}..{x.effective_until and f'{x.effective_until:%Y-%m-%d}' or ''}")
            for x in q:
                print(f"! {x['id']:36} QUARANTINED: {x['error']}")
            print(f"ruleset version {version}")
        elif args.op in ("add", "edit"):
            out({"seq": svc.put(json.loads(Path(args.file).read_text("utf-8")), now, args.op)})
        elif args.op == "import":
            out(svc.import_(json.loads(Path(args.file).read_text("utf-8")), now))
        elif args.op == "export":
            text = json.dumps(svc.export(), ensure_ascii=False, indent=2)
            Path(args.file).write_text(text, "utf-8") if args.file else print(text)
        elif args.op == "disable":
            out({"seq": svc.disable(args.id, now)})
        elif args.op == "rollback":
            out({"seq": svc.rollback(args.id, args.seq, now)})
        elif args.op == "preset":
            out(svc.preset(args.name, now))
        elif args.op == "check":
            at = parse_ts(args.at) if args.at else now
            out(svc.check(InstrumentId.wallex(args.symbol.upper()), args.side, args.intent, at, used=Decimal(args.used)))
    except (ValueError, OSError, DecimalException) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
