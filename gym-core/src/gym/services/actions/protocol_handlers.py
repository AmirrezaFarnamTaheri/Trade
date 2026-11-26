"""Protocol action handler group extracted from services/research_actions.py."""
from __future__ import annotations

from ...domain.model import now_utc, parse_ts
from ..research_protocol import ResearchProtocol


def handle_protocol_action(root, action, value, store, at, *, market_db_fn, derived_fn, convert_fn):
    """Dispatch research-protocol actions under strict initialization and clock rules."""
    if action != "outcomes" and value is None:
        raise ValueError("this action requires an input file or ID")
    if action in ("outcomes", "final-run", "final-status", "screen", "derived", "unit-convert") and not (
        root / "research_protocol.sqlite3"
    ).is_file():
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
            return derived_fn(protocol, value)
        if action == "unit-convert":
            return convert_fn(protocol, value)
        db = market_db_fn(root)
        try:
            return protocol.consume(value, db)
        finally:
            db.c.close()
