"""Daemon command implementations; invocation stays in gym.cli."""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

from ..adapters.store import SegmentWriter
from ..domain.model import InstrumentId, now_utc
from ..services.collector import Collector
from ..services.rules import RuleService
from .common import (
    DEFAULT_WATCH,
    open_db,
    store_root,
)


def demo_seed(args) -> int:
    from datetime import timedelta

    from ..domain.rules import evaluate

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


async def serve(args):
    from aiohttp import web

    from ..api.server import make_app

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
    from ..services.external_journal import ExternalJournal
    from ..services.offline_review_journal import OfflineReviewJournal
    from ..services.venue_facts import VenueFactsJournal
    external_journal = ExternalJournal(store_root(args) / "external_journal.db")
    venue_facts = VenueFactsJournal(store_root(args) / "venue_facts.db")
    offline_reviews = OfflineReviewJournal(store_root(args) / "offline_reviews.db")
    from ..services.event_log import configure, event
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
