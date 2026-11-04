"""Shared bounded research actions for the CLI and local web workbench."""
from pathlib import Path
from datetime import timedelta
import re

from ..adapters.store import MarketDB
from ..domain.market_models import decimal, evaluate_artifact, fields
from ..domain.model import iso, parse_ts
from .collector import now_utc
from .research_grounding import check_claims
from .research_ledger import ResearchLedger
from .research_protocol import ResearchProtocol
from .research_review import review_runs
from .market_statistics import spread_report, trade_flow_report
from .technical_analysis import technical_reports
from .research_series import derived_series
from .data_portal import DataPortal
from .feed_crosscheck import candle_crosscheck
from .research_market import coverage_timeline, screen_markets
from .replay_debugger import replay_decisions, execution_quality
from ..domain.portfolio import rebalance_preview
from .experiment_registry import ExperimentRegistry
from .research_notes import prepare_packet, save_notes


PROTOCOL_ACTIONS = frozenset(("outcome-add", "outcomes", "final-register", "final-run",
                              "final-status", "observe-import", "screen", "derived"))
WORKSPACE_ACTIONS = ("coverage", "market-screen", "replay", "rebalance", "execution-quality", "experiment-run",
                     "experiment-list", "experiment-status", "research-packet", "research-notes", "job-recover", "job-catch-up")
OBJECT_ACTIONS = frozenset(("register", "shadow-open", "shadow-close", "schedule", "review",
                           "claim-check", "final-register", "observe-import", "screen", "derived", "diagnostic", "candles",
                           *[a for a in WORKSPACE_ACTIONS if a not in ("experiment-list", "experiment-status")]))


def _market_db(root):
    path = root / "market.db"
    if not path.is_file():
        raise ValueError("research requires an existing market store")
    return MarketDB(path, readonly=True)


def research_action(root, action, value=None, *, store="live", at=None):
    root = Path(root)
    if not isinstance(action, str):
        raise ValueError("invalid research action")
    if store not in ("live", "demo"):
        raise ValueError("invalid research store")
    if at is not None and action not in ("review", "outcomes", "tick"):
        raise ValueError("protocol mutations use the actual clock, without --at overrides")
    if action == "diagnostic":
        return evaluate_artifact(value)
    if action in ("replay", "execution-quality"):
        return (replay_decisions if action == "replay" else execution_quality)(root / "runs", value, store=store)
    if action == "rebalance":
        return rebalance_preview(value)
    if action in ("coverage", "market-screen", "experiment-run"):
        db = _market_db(root)
        try:
            if action != "experiment-run":
                return (coverage_timeline if action == "coverage" else screen_markets)(db, value, store=store)
            with ExperimentRegistry(root, store=store) as registry:
                return registry.run(db, value)
        finally:
            db.c.close()
    if action in ("experiment-list", "experiment-status", "research-packet", "research-notes"):
        with ExperimentRegistry(root, store=store) as registry:
            if action == "experiment-list":
                return registry.listing()
            if action == "experiment-status":
                return registry.read(value)
            return (prepare_packet if action == "research-packet" else save_notes)(registry, value)
    if action in ("job-recover", "job-catch-up"):
        with ResearchLedger(root / "research.sqlite3") as ledger:
            if action == "job-recover":
                return ledger.recover(value, at=now_utc())
            fields(value, "job_id limit")
            if type(value["limit"]) is not int or not 1 <= value["limit"] <= 10:
                raise ValueError("catch-up limit must be 1..10")
            db = _market_db(root)
            try:
                return ledger.run_due(db, iso(now_utc()), store=store, limit=value["limit"], job_id=value["job_id"])
            finally:
                db.c.close()
    if action in ("technicals", "spreads", "trade-flow", "candles"):
        fields(value, {"technicals": "symbol from to resolutions", "candles": "symbol from to as_of tolerance_bps"}.get(action, "symbol from to"))
        if not isinstance(value["from"], str) or not isinstance(value["to"], str):
            raise ValueError("report bounds must be zoned timestamps")
        start, end = parse_ts(value["from"]), parse_ts(value["to"])
        if not start < end or end - start > timedelta(days=31):
            raise ValueError("report window must be positive and at most 31 days")
        if not isinstance(value["symbol"], str) or not re.fullmatch(r"[A-Z0-9]{2,24}", value["symbol"]):
            raise ValueError("report requires one market symbol")
        db = _market_db(root)
        try:
            if action == "technicals":
                return technical_reports(db, value["symbol"], start, end, resolutions=value["resolutions"], store=store)
            db.c.execute("BEGIN")
            table, timestamp = ("trades", "ts_event") if action in ("trade-flow", "candles") else ("book_top", "ts_avail")
            count = db.c.execute(f"SELECT count(*) FROM {table} WHERE instrument_id=? AND substr({timestamp},1,10)>=? AND substr({timestamp},1,10)<=?",
                                ("wallex:" + value["symbol"], start.date().isoformat(), end.date().isoformat())).fetchone()[0]
            if count > 100000:
                raise ValueError("too many observations; narrow the report window")
            if action == "candles":
                if not isinstance(value["as_of"], str) or not isinstance(value["tolerance_bps"], str):
                    raise ValueError("candle cutoff and tolerance must be strings")
                cutoff = parse_ts(value["as_of"])
                if cutoff > now_utc():
                    raise ValueError("candle cutoff cannot be in the future")
                report = candle_crosscheck(DataPortal(db), value["symbol"], start, end,
                                           tolerance_bps=decimal(value["tolerance_bps"], "tolerance_bps"), as_of=cutoff)
                return {**report, "store": store, "funded_authority": False, "order_submitted": False}
            return (trade_flow_report if action == "trade-flow" else spread_report)(db, start, end, symbol=value["symbol"], store=store)
        finally:
            db.c.close()
    if action == "claim-check":
        return check_claims(root / "runs", value, store=store)
    if action == "review":
        fields(value, "run_ids")
        return review_runs(root / "runs", value["run_ids"], as_of=parse_ts(at) if at else now_utc(), store=store)
    if action in PROTOCOL_ACTIONS:
        if action != "outcomes" and value is None:
            raise ValueError("this action requires an input file or ID")
        if action in ("outcomes", "final-run", "final-status", "screen", "derived") and not (root / "research_protocol.sqlite3").is_file():
            raise ValueError("research protocol is not initialized")
        root.mkdir(parents=True, exist_ok=True)
        with ResearchProtocol(root, store=store) as protocol:
            if action == "outcomes":
                return protocol.outcomes(parse_ts(at) if at else now_utc())
            if action == "outcome-add":
                return protocol.record_outcome(value)
            if action == "final-register":
                return protocol.register(value)
            if action == "final-status":
                return protocol.evaluation(value)
            if action == "observe-import":
                return protocol.ingest_observations(value)
            if action == "screen":
                return protocol.screen(value)
            if action == "derived":
                return derived_series(protocol, value)
            db = _market_db(root)
            try:
                return protocol.consume(value, db)
            finally:
                db.c.close()
    actions = {"register": "register", "shadow-open": "open_shadow", "shadow-close": "settle_shadow",
               "schedule": "schedule", "pause": "pause", "resume": "resume", "list": "overview"}
    if action not in actions and action != "tick":
        raise ValueError("unknown research action")
    root.mkdir(parents=True, exist_ok=True)
    with ResearchLedger(root / "research.sqlite3") as ledger:
        if action == "tick":
            db = _market_db(root)
            try:
                return ledger.run_due(db, at or now_utc().isoformat(), store=store)
            finally:
                db.c.close()
        method = getattr(ledger, actions[action])
        return method() if action == "list" else method(value)
