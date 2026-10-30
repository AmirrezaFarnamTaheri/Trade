"""gymctl: run the daemon, manage venue rules."""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from decimal import Decimal
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
    closed = lambda s, t: not evaluate(rules, InstrumentId.wallex(s), "SELL", "EXIT", t, live=False).allowed  # noqa: E731
    seg = SegmentWriter(store_root(args) / "raw", db)
    Collector(db, seg, DEFAULT_WATCH.split(","), demo=True).demo_history(start, end, closed)
    seg.close()
    print(f"DEMO history {start:%Y-%m-%d %H:%M} .. {end:%Y-%m-%d %H:%M} UTC written to {store_root(args)}")
    return 0


def paper_cmd(args) -> int:
    from .domain.sim import CostModel
    from .services.paper import paper, save, text_report

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
    out = paper(db, sym, t0, t1, resolution=args.res, fast=args.fast, slow=args.slow, cash=cash, cost=cost,
                rules_mode=args.rules, store="demo" if args.demo else "live")
    path = save(out, store_root(args) / "runs")
    print(text_report(out))
    print(f"\nrun record: {path}")
    return 0


def timedelta_ms(ms: int):
    from datetime import timedelta

    return timedelta(milliseconds=ms)


async def serve(args):
    from aiohttp import web

    from .api.server import make_app

    db = open_db(args)
    seg = SegmentWriter(Path(args.data) / ("demo" if args.demo else "live") / "raw", db)
    col = Collector(db, seg, [s.strip().upper() for s in args.watch.split(",") if s.strip()], demo=args.demo)
    runner = web.AppRunner(make_app(col, RuleService(db), secrets.token_urlsafe(24)))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    print(f"TradingGYM {'DEMO ' if args.demo else ''}Observatory on http://127.0.0.1:{args.port}/  (Ctrl+C to stop)", flush=True)
    try:
        await col.run()
    finally:
        seg.close()
        await runner.cleanup()


def main(argv=None):
    p = argparse.ArgumentParser(prog="gymctl")
    p.add_argument("--data", default="data", help="data directory (default ./data)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run collector + local API + UI")
    r.add_argument("--demo", action="store_true", help="synthetic DEMO feed, stored separately")
    r.add_argument("--port", type=int, default=8765)
    r.add_argument("--watch", default=DEFAULT_WATCH)
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
    pp.add_argument("--res", default="15min", help="1min | 15min | 1h | 1day")
    pp.add_argument("--fast", type=int, default=8)
    pp.add_argument("--slow", type=int, default=21)
    pp.add_argument("--cash", help="starting quote cash (default 1000 USDT or 300,000,000 TMN)")
    pp.add_argument("--fee", default="0.002", help="fee rate per side (default: documentation example 0.2%%)")
    pp.add_argument("--latency-ms", type=int, default=500)
    pp.add_argument("--rules", choices=["point-in-time", "today"], default="point-in-time")
    sub.add_parser("demo-seed", help="write synthetic DEMO history into data/demo").add_argument("--hours", type=int, default=72)
    args = p.parse_args(argv)

    if args.cmd in ("paper", "demo-seed"):
        try:
            return paper_cmd(args) if args.cmd == "paper" else demo_seed(args)
        except (ValueError, OSError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    if args.cmd == "run":
        try:
            asyncio.run(serve(args))
        except KeyboardInterrupt:
            pass
        return 0

    svc, now = RuleService(open_db(args)), now_utc()
    out = lambda o: print(json.dumps(o, ensure_ascii=False, indent=2, default=str))  # noqa: E731
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
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
