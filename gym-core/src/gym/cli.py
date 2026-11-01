"""gymctl: run the daemon, manage venue rules."""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from decimal import Decimal, DecimalException
from pathlib import Path

from .adapters.store import MarketDB, SegmentWriter
from .domain.model import InstrumentId, parse_ts
from .services.collector import Collector, now_utc
from .services.rules import RuleService

DEFAULT_WATCH = "USDTTMN,BTCTMN,BTCUSDT,ETHTMN,ETHUSDT"
DEFAULT_PRESET = "usdt-irt-october-2026"


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
    Collector(db, seg, DEFAULT_WATCH.split(","), demo=True).demo_history(start, end, closed)
    seg.close()
    print(f"DEMO history {start:%Y-%m-%d %H:%M} .. {end:%Y-%m-%d %H:%M} UTC written to {store_root(args)}")
    return 0


def paper_cmd(args) -> int:
    from .domain.sim import CostModel
    from .adapters.run_store import save_run
    from .services.paper import paper
    from .services.reports import text_report

    if not (store_root(args) / "market.db").exists():
        print(f"error: no data in {store_root(args)}" + ("; run gymctl demo-seed first" if args.demo else ""), file=sys.stderr)
        return 2
    db, sym = open_db(args), args.symbol.upper()
    span = db.c.execute("select min(ts_avail), max(ts_avail) from book_top where instrument_id=?", (f"wallex:{sym}",)).fetchone()
    if not span[0]:
        print(f"error: no {sym} quotes stored", file=sys.stderr)
        return 2
    t0, t1 = parse_ts(args.start or span[0]), parse_ts(args.end or span[1])
    cash = Decimal(args.cash) if args.cash else Decimal(300_000_000 if sym.endswith("TMN") else 1000)
    cost = CostModel(Decimal(args.fee), timedelta_ms(args.latency_ms))
    subscriptions = tuple(x.strip() for x in args.subscribe.split(",") if x.strip())
    out = paper(db, sym, t0, t1, resolution=args.res, fast=args.fast, slow=args.slow, cash=cash, cost=cost,
                rules_mode=args.rules, store="demo" if args.demo else "live", subscriptions=subscriptions)
    path = save_run(out, store_root(args) / "runs")
    print(text_report(out))
    print(f"\nrun record: {path}")
    return 0


def spreads_cmd(args) -> int:
    from datetime import timedelta

    from .services.market_statistics import spread_report

    path = store_root(args) / "market.db"
    if not path.exists():
        raise ValueError(f"no market data in {path.parent}")
    db = MarketDB(path)
    try:
        symbol = args.symbol.upper() if args.symbol else None
        query = "select min(ts_avail), max(ts_avail) from book_top"
        if symbol:
            span = db.c.execute(query + " where instrument_id=?", (f"wallex:{symbol}",)).fetchone()
        else:
            span = db.c.execute(query).fetchone()
        if not span[0]:
            raise ValueError("no stored quotes for the requested markets")
        start = parse_ts(args.start or span[0])
        end = parse_ts(args.end) if args.end else parse_ts(span[1]) + timedelta(microseconds=1)
        report = spread_report(db, start, end, symbol=symbol, store="demo" if args.demo else "live")
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            with Path(args.output).open("x", encoding="utf-8") as output:
                output.write(text + "\n")
            print(f"spread report: {args.output}; {report['samples']} observations, {len(report['groups'])} pair/hour groups")
        else:
            print(text)
    finally:
        db.c.close()
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
        if args.fetch:
            async def fetch():
                seg = SegmentWriter(store_root(args) / "raw", db)
                try:
                    async with aiohttp.ClientSession(headers={"User-Agent": "TradingGYM/0.1 (observatory)"}) as session:
                        return await Collector(db, seg, [symbol]).fetch_candles(session, symbol, "1min", start, end)
                finally:
                    seg.close()
            print(f"fetched {asyncio.run(fetch())} venue candles", file=sys.stderr)
        report = candle_crosscheck(DataPortal(db), symbol, start, end, tolerance_bps=Decimal(args.tolerance_bps))
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
    from .services.live_paper import watch

    if not (store_root(args) / "market.db").exists():
        raise ValueError("start the collector first")
    cash = Decimal(args.cash or (300_000_000 if args.symbol.upper().endswith("TMN") else 1000))
    subscriptions = tuple(x.strip() for x in args.subscribe.split(",") if x.strip())
    asyncio.run(watch(open_db(args), store_root(args) / "runs", args.symbol.upper(), args.seconds,
                      args.res, args.fast, args.slow, cash, args.demo, subscriptions))
    return 0


def external_observe_cmd(args) -> int:
    """Import only sanitized external observations, never account authority."""
    from .domain.account_observations import project_account
    from .services.external_journal import ExternalJournal

    source = Path(args.path)
    if source.stat().st_size > 1_048_576:
        raise ValueError("external observation file exceeds 1 MiB")
    raw = json.loads(source.read_text("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("external observation must be a JSON object")
    observed = project_account(
        raw["account_id"], raw["observed_at"],
        orders=raw.get("orders"), balances=raw.get("balances"),
        exposure=raw.get("exposure"),
    )
    root = store_root(args)
    root.mkdir(parents=True, exist_ok=True)
    with ExternalJournal(root / "external_journal.db") as journal:
        count = journal.record(observed)
    print(f"{count} external observations recorded (read-only, unverified; not funded).")
    return 0


def venue_fact_import_cmd(args) -> int:
    """Store strict, sanitized C1 evidence metadata; never accept raw API JSON.

    A claimed source is NOT authenticated. This command can never certify
    venue order methods, provision keys or authorize any funded operation.
    """
    from .services.venue_facts import VenueFactsJournal, validate_venue_fact

    source = Path(args.path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 16_384:
        raise ValueError("VenueFacts import must be a regular bounded JSON file")
    raw = json.loads(source.read_text("utf-8"))
    record = validate_venue_fact(raw)  # before creating the journal
    root = store_root(args)
    root.mkdir(parents=True, exist_ok=True)
    with VenueFactsJournal(root / "venue_facts.db") as journal:
        sequence = journal.record(record)
    print(f"VenueFacts evidence #{sequence} recorded (unverified origin; no order authority).")
    return 0


def backup_once_cmd(args) -> int:
    """Manual offline encrypted backup to a pre-existing independent volume.

    No passphrase in arguments, environment variables or command history.
    This is NOT scheduled remote backup, does not provision venue credentials,
    and cannot establish that another machine holds an archive.
    """
    import getpass
    from .services.backup_rotation import backup_once

    if not sys.stdin.isatty():
        raise ValueError("backup-once requires an interactive protected console")
    phrase = getpass.getpass("Offline ledger recovery passphrase (not a venue API key): ")
    try:
        report = backup_once(args.ledger, args.destination,
                             passphrase=phrase, keep=args.keep)
    finally:
        del phrase
    # Never output a recovery passphrase, access token, or private API key.
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
                    add_symbols=added, remove_symbols=removed)
    from .services.external_journal import ExternalJournal
    from .services.venue_facts import VenueFactsJournal
    external_journal = ExternalJournal(store_root(args) / "external_journal.db")
    venue_facts = VenueFactsJournal(store_root(args) / "venue_facts.db")
    runner = web.AppRunner(make_app(col, RuleService(db), secrets.token_urlsafe(24),
                                    store_root(args) / "runs",
                                    external_journal=external_journal, venue_facts=venue_facts))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    print(f"TradingGYM {'DEMO ' if args.demo else ''}Observatory on http://127.0.0.1:{args.port}/  (Ctrl+C to stop)", flush=True)
    try:
        await col.run()
    finally:
        seg.close()
        await runner.cleanup()
        external_journal.conn.close()
        venue_facts.conn.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="gymctl")
    p.add_argument("--data", default="data", help="data directory (default ./data)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run collector + local API + UI")
    r.add_argument("--demo", action="store_true", help="synthetic DEMO feed, stored separately")
    r.add_argument("--port", type=int, default=8765)
    r.add_argument("--assets", type=int, choices=range(25, 501), default=50, metavar="25..500",
                   help="ranked non-risky spot assets to observe (25..500, default 50; live auto-universe only)")
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
    pp = sub.add_parser("paper", help="replay the EMA strategy on stored quotes, with baselines and a cost waterfall")
    pp.add_argument("symbol")
    pp.add_argument("--demo", action="store_true")
    pp.add_argument("--from", dest="start", help="UTC ISO time with zone (default: first stored quote)")
    pp.add_argument("--to", dest="end", help="UTC ISO time with zone (default: last stored quote)")
    pp.add_argument("--res", default="15min", help="primary decision close: 1min | 15min | 1h | 1day | session")
    pp.add_argument("--subscribe", default="", help="comma-separated additional on-close resolutions")
    pp.add_argument("--fast", type=int, default=8)
    pp.add_argument("--slow", type=int, default=21)
    pp.add_argument("--cash", help="starting quote cash (default 1000 USDT or 300,000,000 TMN)")
    pp.add_argument("--fee", default="0.002", help="fee rate per side (default: documentation example 0.2%%)")
    pp.add_argument("--latency-ms", type=int, default=500)
    pp.add_argument("--rules", choices=["point-in-time", "today"], default="point-in-time")
    spreads = sub.add_parser("spreads", help="observed spread distributions by pair and Tehran hour")
    spreads.add_argument("symbol", nargs="?", help="default: every observed market")
    spreads.add_argument("--demo", action="store_true")
    spreads.add_argument("--from", dest="start")
    spreads.add_argument("--to", dest="end")
    spreads.add_argument("--output", help="create a JSON report (never overwrite an existing file)")
    candles = sub.add_parser("candles", help="cross-check internal trade bars against venue candles (DATA-05)")
    candles.add_argument("symbol")
    candles.add_argument("--demo", action="store_true")
    candles.add_argument("--from", dest="start", help="default: two hours before --to")
    candles.add_argument("--to", dest="end", help="default: now")
    candles.add_argument("--tolerance-bps", default="10")
    candles.add_argument("--fetch", action="store_true", help="fetch venue candles for the range first")
    candles.add_argument("--record", action="store_true", help="write CROSS_FEED_DIVERGENCE quality events")
    candles.add_argument("--json", action="store_true")
    bk = sub.add_parser("backup-once", help="manual offline encrypted ledger backup on a separate mounted volume")
    bk.add_argument("ledger", help="Executor ledger database file; no keys or secrets.dat")
    bk.add_argument("destination", help="pre-existing independent-volume backup directory")
    bk.add_argument("--keep", type=int, default=7, help="retain 2..365 verified bundles, default 7")
    vf = sub.add_parser("venue-fact-import", help="import strictly sanitized offline C1 venue validation metadata")
    vf.add_argument("path", help="bounded VenueFacts JSON metadata (never raw API results or credentials)")
    vf.add_argument("--demo", action="store_true", help="record separately from real observations")
    ext = sub.add_parser("external-observe", help="import read-only manual account observation JSON to the local Journal")
    ext.add_argument("path", help="local sanitized observation JSON file; no API keys")
    ext.add_argument("--demo", action="store_true")
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
    se.add_argument("--res", default="15min")
    se.add_argument("--subscribe", default="", help="comma-separated additional on-close resolutions")
    se.add_argument("--fast", type=int, default=8)
    se.add_argument("--slow", type=int, default=21)
    se.add_argument("--cash")
    sub.add_parser("demo-seed", help="write synthetic DEMO history into data/demo").add_argument("--hours", type=int, default=72)
    args = p.parse_args(argv)

    commands = {"venue-fact-import": venue_fact_import_cmd, "backup-once": backup_once_cmd, "external-observe": external_observe_cmd, "evidence": evidence_cmd, "session": session_cmd, "paper": paper_cmd,
                "demo-seed": demo_seed, "spreads": spreads_cmd, "candles": candles_cmd}
    if args.cmd in commands:
        try:
            return commands[args.cmd](args)
        except (ValueError, OSError, DecimalException) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    if args.cmd == "run":
        try:
            asyncio.run(serve(args))
        except KeyboardInterrupt:
            pass
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
