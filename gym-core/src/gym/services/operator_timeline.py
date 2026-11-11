"""Read-only operator activity timeline across the workspace journals.

One merged, newest-first view over the research ledger, experiment registry, research protocol, backup receipts,
offline ticket reviews, external order events and venue facts. Every store is opened read-only and queried with
a bounded `ORDER BY ... DESC LIMIT`, so a 175k-row registry costs one index walk. A missing or unreadable store
is reported, never created.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# (source, file, SQL returning (at, kind, summary) newest first with one LIMIT parameter)
SOURCES = (
    ("experiments", "experiments.sqlite3",
     ("SELECT json_extract(body,'$.recorded_at'), kind, coalesce(json_extract(body,'$.run_id'), id) || "
      "coalesce(' ' || json_extract(body,'$.state'), '') || coalesce(' net ' || json_extract(body,'$.net_quote'), '') "
      "FROM events ORDER BY seq DESC LIMIT ?")),
    ("research-alerts", "research.sqlite3",
     ("SELECT json_extract(body,'$.due_at'), coalesce(json_extract(body,'$.kind'), 'ALERT'), "
      "coalesce(json_extract(body,'$.job_id') || ': ', '') || coalesce(json_extract(body,'$.message'), '') "
      "FROM alerts ORDER BY rowid DESC LIMIT ?")),
    ("research-reports", "research.sqlite3",
     ("SELECT due_at, 'SCHEDULED_REPORT', job_id || ' ' || coalesce(json_extract(body,'$.run_id'), '') "
      "FROM reports ORDER BY rowid DESC LIMIT ?")),
    ("backups", "backup_status.sqlite3",
     ("SELECT json_extract(body,'$.recorded_at'), kind, coalesce(json_extract(body,'$.status'), '') "
      "FROM receipts ORDER BY seq DESC LIMIT ?")),
    ("protocol-evaluations", "research_protocol.sqlite3",
     "SELECT registered_at, 'EVALUATION_' || state, id FROM evaluations ORDER BY registered_at DESC LIMIT ?"),
    ("protocol-outcomes", "research_protocol.sqlite3",
     "SELECT resolved_at, 'OUTCOME', run_id FROM outcomes ORDER BY resolved_at DESC LIMIT ?"),
    ("ticket-reviews", "offline_reviews.db",
     ("SELECT reviewed_at, 'TICKET_' || decision, substr(preview_sha256, 1, 16) "
      "FROM ticket_review_events ORDER BY sequence DESC LIMIT ?")),
    ("external-orders", "external_journal.db",
     ("SELECT observed_at, 'ORDER_' || raw_status, client_id FROM external_order_events "
      "ORDER BY sequence DESC LIMIT ?")),
    ("venue-facts", "venue_facts.db",
     "SELECT observed_at, 'FACT_' || kind, state FROM venue_facts ORDER BY sequence DESC LIMIT ?"),
)


def _instant(text) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    return value if value.tzinfo else None  # a naive stamp cannot be ordered against zoned ones


def timeline(root: Path, *, limit: int = 100, sources: set[str] | None = None) -> dict:
    """Newest-first merged events; `sources` restricts to named sources."""
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be 1..1000")
    known = {name for name, _, _ in SOURCES}
    if sources is not None and not sources <= known:
        raise ValueError(f"unknown timeline source; choose from {sorted(known)}")
    events, status = [], {}
    for name, file, sql in SOURCES:
        if sources is not None and name not in sources:
            continue
        path = Path(root) / file
        if not path.is_file():
            status[name] = "absent"
            continue
        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            try:
                rows = conn.execute(sql, (limit,)).fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            status[name] = "unreadable"
            continue
        kept = 0
        for at, kind, summary in rows:
            instant = _instant(at)
            if instant is None:
                continue
            events.append({"at": instant.astimezone(UTC).isoformat(), "source": name, "kind": str(kind),
                           "summary": str(summary or "")[:200]})
            kept += 1
        status[name] = kept
    events.sort(key=lambda e: (e["at"], e["source"]), reverse=True)
    return {"as_of": datetime.now(UTC).isoformat(), "read_only": True, "sources": status, "events": events[:limit]}
