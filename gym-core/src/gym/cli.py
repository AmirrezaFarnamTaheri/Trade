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


def open_db(args) -> MarketDB:
    # Demo data lives in its own directory and never mixes with real observations.
    root = Path(args.data) / ("demo" if getattr(args, "demo", False) else "live")
    db = MarketDB(root / "market.db")
    if not db.rule_events():
        RuleService(db).preset(DEFAULT_PRESET, now_utc(), actor="first-run")
    return db


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
    args = p.parse_args(argv)

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
