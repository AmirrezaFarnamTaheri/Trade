"""gymctl: one entry point for observatory, research and operator commands."""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from decimal import Decimal, DecimalException
from pathlib import Path

from .commands.account import (
    account_cmd,
    conversion_report_cmd,
    external_observe_cmd,
    key_cmd,
    operator_review_cmd,
    probe_budget_stage_cmd,
    ticket_preview_cmd,
    ticket_queue_add_cmd,
    ticket_queue_review_cmd,
    venue_fact_import_cmd,
)
from .commands.common import (
    DEFAULT_FEE,
    FEE_HELP,
    default_data_root,
    open_db,
)
from .commands.daemon import demo_seed, serve
from .commands.maintenance import (
    backup_once_cmd,
    compact_cmd,
    raw_move_cmd,
    restore_backup_cmd,
    restore_drill_cmd,
    update_check_cmd,
    verify_backup_manifest_cmd,
    verify_segments_cmd,
)
from .commands.research import (
    assistant_cmd,
    calibrate_cmd,
    candles_cmd,
    evidence_cmd,
    market_statistics_cmd,
    paper_research_cmd,
    replay_cmd,
    research_cmd,
    session_cmd,
    summary_cmd,
    technical_report_cmd,
)
from .domain.bars import FIXED_RESOLUTIONS, RESOLUTIONS
from .domain.model import InstrumentId, parse_ts
from .services.collector import now_utc, parse_asset_count
from .services.rules import RuleService


def main(argv=None):
    """Parse the native CLI and invoke the selected bounded command handler."""
    p = argparse.ArgumentParser(prog="gymctl")
    p.add_argument("--data", default=str(default_data_root()),
                   help="data directory (defaults to repository data/ in source checkouts)")
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
    comparison = sub.add_parser("compare", help="paired PAPER ONLY replay on identical data, costs and snapshots")
    comparison.add_argument("--candidate", action="append", required=True,
                            help='candidate JSON, e.g. {"strategy":"ema-trend","params":{"fast":3,"slow":8}}; repeat 2..4 times')
    validation = sub.add_parser("validate", help="chronological 70/30 paper selection diagnostic, with one decision period purged")
    validation.add_argument("--candidate", action="append", required=True, help="registered candidate JSON; repeat 2..4 times")
    validation.add_argument("--folds", type=int, choices=range(1, 6), default=1,
                            help="1..5 successive independent 70/30 windows; default 1, not an expanding training run")
    shared = sub.add_parser("portfolio", help="one strategy over 2..500 markets sharing one cash balance (PAPER ONLY)")
    shared.add_argument("--strategy", choices=[entry["id"] for entry in catalog()], default="ema-trend")
    shared.add_argument("--params", help="strategy parameter JSON; omitted values use registry defaults")
    shared.add_argument("--policy", help="portfolio allocation and risk policy JSON; paper only")
    for command in (replay, comparison, validation, shared):
        command.add_argument("symbol", help="market, or comma-separated markets for portfolio")
        command.add_argument("--demo", action="store_true")
        command.add_argument("--from", dest="start", help="UTC ISO time with zone (default: first stored quote)")
        command.add_argument("--to", dest="end", help="exclusive UTC ISO cut (default: last stored quote)")
        command.add_argument("--res", default="15min", choices=list(RESOLUTIONS), help="decision close from the shared bar engine")
        command.add_argument("--subscribe", default="", help="comma-separated additional on-close resolutions")
        command.add_argument("--cash", help="starting quote cash (default 1000 USDT or 300,000,000 TMN)")
        command.add_argument("--fee", default=None, help=FEE_HELP + "; if omitted, use recent read-only fee snapshot if available")
        command.add_argument("--latency-ms", type=int, default=None,
                             help="explicit milliseconds; otherwise recent local feed calibration if available")
        command.add_argument("--participation", help="max share (0..1] of the displayed best-level size per fill; larger orders are resized")
        command.add_argument("--walk-depth", action="store_true",
                             help="fill across stored order-book levels at their volume-weighted price (needs run --depth-levels)")
        command.add_argument("--order-type", choices=["market", "limit"], default="market",
                             help="limit: rest at the near touch and fill from later trade prints (queue-aware) or expire")
        command.add_argument("--maker-fee", help="limit maker fee fraction; otherwise latest read-only fee snapshot or --fee")
        command.add_argument("--max-fraction", help="cap every entry at this share (0..1] of cash, e.g. a fractional-Kelly figure")
        command.add_argument("--vol-target", help="scale entries so the position's per-bar volatility is about this (0..1], e.g. 0.002")
        command.add_argument("--volatility-model", choices=["close-std", "parkinson-ewma"], default="close-std",
                             help="opt-in high-low EWMA paper sizing; defaults preserve run identity")
        command.add_argument("--carry-remainder", action="store_true",
                             help="keep working a resized order on later quotes until it fills or max wait passes")
        command.add_argument("--rules", choices=["point-in-time", "today"], default="point-in-time")
        command.add_argument("--max-bad-share",
                             help="opt-in maximum missing plus stale share 0..1 before recording paper results")
        command.add_argument("--hypothesis", default="ad-hoc",
                             help="research-question label for durable global trial counting; no change to run IDs")
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
    kset = kys.add_parser("set")
    kset.add_argument("role", choices=["read", "trade"])
    kset.add_argument("--expires", help="the key's expiry date chosen on Wallex (YYYY-MM-DD, at most 90 days ahead)")
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
