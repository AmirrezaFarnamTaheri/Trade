"""C2 durable offline order-ticket review, no funded approvals or venue writes.

Ticket inputs are fully reconstructed from the allowlisted dry-run calculator.
A recovered ACKNOWLEDGE is never a Tier-1 authorization, and no method can
convert a persisted review into a live order.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ..domain.assisted_ticket import (
    PREVIEW_FIELDS, TicketUnsafe, _zoned, prepare_preview_from_json,
)

_GENESIS = bytes(32)
_SCHEMA = """
CREATE TABLE ticket_previews (
    preview_sha256 TEXT PRIMARY KEY,
    canonical_json TEXT NOT NULL
);
CREATE TABLE ticket_review_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    preview_sha256 TEXT NOT NULL UNIQUE REFERENCES ticket_previews(preview_sha256),
    decision TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    previous_hash BLOB NOT NULL,
    event_hash BLOB NOT NULL
);
CREATE TRIGGER ticket_previews_no_update BEFORE UPDATE ON ticket_previews
BEGIN SELECT RAISE(ABORT, 'offline preview is immutable'); END;
CREATE TRIGGER ticket_previews_no_delete BEFORE DELETE ON ticket_previews
BEGIN SELECT RAISE(ABORT, 'offline preview is immutable'); END;
CREATE TRIGGER ticket_review_events_no_update BEFORE UPDATE ON ticket_review_events
BEGIN SELECT RAISE(ABORT, 'offline review is immutable'); END;
CREATE TRIGGER ticket_review_events_no_delete BEFORE DELETE ON ticket_review_events
BEGIN SELECT RAISE(ABORT, 'offline review is immutable'); END;
PRAGMA user_version=1;
"""


class ReviewUnsafe(ValueError):
    """Invalid offline review, forged ticket or corrupted persistence."""


def _canonical(ticket: dict) -> dict:
    if type(ticket) is not dict:
        raise ReviewUnsafe("ticket fields must be a JSON object")
    if set(ticket) != (PREVIEW_FIELDS | {
        "estimated_gross_quote", "worst_gross_quote", "worst_fee_quote",
        "worst_total_quote", "break_even_bid", "mode", "source",
        "fee_assumption", "client_id", "funded_authority",
        "order_submitted", "preview_sha256",
    }):
        raise ReviewUnsafe("ticket fields must match the safe offline schema")
    try:
        rerun = prepare_preview_from_json({key: ticket[key] for key in PREVIEW_FIELDS})
    except (ValueError, TypeError, KeyError):
        raise ReviewUnsafe("ticket integrity: unsupported pricing or risk envelope") from None
    if rerun != ticket:
        raise ReviewUnsafe("ticket integrity: modified preview or forged authority")
    return rerun


def _json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _next_hash(previous: bytes, payload: dict) -> bytes:
    raw = _json(payload).encode("ascii")
    return hashlib.sha256(previous + len(raw).to_bytes(8, "big") + raw).digest()


class OfflineReviewJournal:
    """Append-only local queue. All decisions are offline acknowledgments."""

    def __init__(self, path: Path | str):
        path = Path(path)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ReviewUnsafe("review journal must be a regular unsymlinked file")
        self.conn = sqlite3.connect(path, timeout=5)
        try:
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if self.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name IN "
                    "('ticket_previews','ticket_review_events')"
                ).fetchone():
                    raise ReviewUnsafe("partial offline review journal schema")
                self.conn.executescript("BEGIN IMMEDIATE;" + _SCHEMA + "COMMIT;")
            elif version != 1:
                raise ReviewUnsafe("unsupported offline review journal schema")
            self._verify()
        except Exception:
            self.conn.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def _verify(self) -> bytes:
        if self.conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ReviewUnsafe("offline review integrity: failed SQLite check")
        must = {
            "ticket_previews_no_update", "ticket_previews_no_delete",
            "ticket_review_events_no_update", "ticket_review_events_no_delete",
        }
        actual = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
        if not must.issubset(actual):
            raise ReviewUnsafe("offline review integrity: triggers absent")
        known = {}
        for key, raw in self.conn.execute(
            "SELECT preview_sha256,canonical_json FROM ticket_previews"
        ):
            try:
                record = json.loads(raw)
                canonical = _canonical(record)
                if raw != _json(canonical) or key != canonical["preview_sha256"]:
                    raise ReviewUnsafe("offline review integrity: changed preview bytes")
            except (ValueError, TypeError, KeyError):
                raise ReviewUnsafe("offline review integrity: changed preview") from None
            known[key] = canonical
        previous = _GENESIS
        sequence = 0
        reviewed = set()
        for row in self.conn.execute(
            "SELECT sequence,preview_sha256,decision,reviewed_at,previous_hash,event_hash "
            "FROM ticket_review_events ORDER BY sequence"
        ):
            seq, key, decision, at, prior, claimed = row
            event = {"preview_sha256": key, "decision": decision, "reviewed_at": at}
            if seq != sequence + 1 or key not in known or key in reviewed:
                raise ReviewUnsafe("offline review integrity: missing or duplicated event")
            if decision not in ("ACKNOWLEDGE", "REJECT"):
                raise ReviewUnsafe("offline review integrity: unsupported event")
            try:
                moment = _zoned(at)
                ticket = known[key]
                if not _zoned(ticket["observed_at"]) <= moment < _zoned(ticket["expires_at"]):
                    raise ReviewUnsafe("offline review integrity: expired decision")
            except (TypeError, ValueError):
                raise ReviewUnsafe("offline review integrity: invalid decision timestamp") from None
            if prior != previous or claimed != _next_hash(previous, event):
                raise ReviewUnsafe("offline review integrity: event hash chain invalid")
            reviewed.add(key)
            sequence, previous = seq, claimed
        return previous

    def record(self, ticket: dict) -> str:
        record = _canonical(ticket)
        key = record["preview_sha256"]
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._verify()
            existing = self.conn.execute(
                "SELECT canonical_json FROM ticket_previews WHERE preview_sha256=?", (key,)
            ).fetchone()
            if existing and existing[0] != _json(record):
                raise ReviewUnsafe("offline review integrity: conflicting preview hash")
            if not existing:
                self.conn.execute(
                    "INSERT INTO ticket_previews(preview_sha256,canonical_json) VALUES(?,?)",
                    (key, _json(record)),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return key

    def _status(self, key: str) -> str:
        row = self.conn.execute(
            "SELECT decision FROM ticket_review_events WHERE preview_sha256=?", (key,)
        ).fetchone()
        return "PREVIEWED" if row is None else (
            "ACKNOWLEDGED_OFFLINE" if row[0] == "ACKNOWLEDGE" else "REJECTED_OFFLINE"
        )

    def tickets(self) -> list[dict]:
        self._verify()
        return [
            {"preview_sha256": key, "state": self._status(key),
             "mode": "DRY_RUN", "funded_authority": False,
             "tier1_approval": False, "order_submitted": False}
            for (key,) in self.conn.execute(
                "SELECT preview_sha256 FROM ticket_previews ORDER BY rowid"
            )
        ]

    def review_events(self) -> list[dict]:
        self._verify()
        return [
            {"sequence": seq, "preview_sha256": key,
             "decision": decision, "reviewed_at": at,
             "tier1_approval": False, "funded_authority": False}
            for seq, key, decision, at in self.conn.execute(
                "SELECT sequence,preview_sha256,decision,reviewed_at "
                "FROM ticket_review_events ORDER BY sequence"
            )
        ]

    def review(self, key: str, decision: str, *, at: str) -> dict:
        if decision not in {"ACKNOWLEDGE", "REJECT"}:
            raise ReviewUnsafe("only an offline acknowledgment or rejection is supported")
        try:
            observed = _zoned(at)
        except (ValueError, TypeError):
            raise ReviewUnsafe("invalid review timestamp") from None
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            previous = self._verify()
            row = self.conn.execute(
                "SELECT canonical_json FROM ticket_previews WHERE preview_sha256=?", (key,)
            ).fetchone()
            if not row:
                raise ReviewUnsafe("unknown offline ticket")
            if self._status(key) != "PREVIEWED":
                raise ReviewUnsafe("ticket already reviewed")
            ticket = json.loads(row[0])
            if not _zoned(ticket["observed_at"]) <= observed < _zoned(ticket["expires_at"]):
                raise ReviewUnsafe("ticket expires before review")
            event = {"preview_sha256": key, "decision": decision, "reviewed_at": at}
            digest = _next_hash(previous, event)
            self.conn.execute(
                "INSERT INTO ticket_review_events(preview_sha256,decision,reviewed_at,"
                "previous_hash,event_hash) VALUES(?,?,?,?,?)",
                (key, decision, at, previous, digest),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {
            "preview_sha256": key,
            "state": "ACKNOWLEDGED_OFFLINE" if decision == "ACKNOWLEDGE"
                     else "REJECTED_OFFLINE",
            "mode": "DRY_RUN",
            "tier1_approval": False,
            "funded_authority": False, "order_submitted": False,
        }
