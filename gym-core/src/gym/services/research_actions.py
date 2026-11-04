"""Shared bounded research actions for the CLI and local web workbench."""
from pathlib import Path
from datetime import timedelta
import re

from ..adapters.store import MarketDB
from ..domain.market_models import evaluate_artifact, fields
from ..domain.model import parse_ts
from .collector import now_utc
from .research_grounding import check_claims
from .research_ledger import ResearchLedger
from .research_protocol import ResearchProtocol
from .research_review import review_runs
from .market_statistics import spread_report, trade_flow_report
from .technical_analysis import technical_reports


PROTOCOL_ACTIONS = frozenset(("outcome-add", "outcomes", "final-register", "final-run",
                              "final-status", "observe-import", "screen"))
OBJECT_ACTIONS = frozenset(("register", "shadow-open", "shadow-close", "schedule", "review",
                           "claim-check", "final-register", "observe-import", "screen", "diagnostic"))


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
    if action in ("technicals", "spreads", "trade-flow"):
        fields(value, "symbol from to resolutions" if action == "technicals" else "symbol from to")
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
            table, timestamp = ("trades", "ts_event") if action == "trade-flow" else ("book_top", "ts_avail")
            count = db.c.execute(f"SELECT count(*) FROM {table} WHERE instrument_id=? AND substr({timestamp},1,10)>=? AND substr({timestamp},1,10)<=?",
                                ("wallex:" + value["symbol"], start.date().isoformat(), end.date().isoformat())).fetchone()[0]
            if count > 100000:
                raise ValueError("too many observations; narrow the report window")
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
        if action in ("outcomes", "final-run", "final-status", "screen") and not (root / "research_protocol.sqlite3").is_file():
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
