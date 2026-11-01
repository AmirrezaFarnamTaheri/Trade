"""C1 VenueFacts: immutable sanitized observation metadata, NOT money authority.

No venue session, credential, raw response, POST, or order transport exists here.
A hash chain detects local history mutation, but neither a hash nor a caller's
source label authenticates an observation. Only an independently privileged
Executor may eventually certify funded capabilities; this display registry has
no method that can grant them.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

_KINDS = {
    "BALANCES": "ACCOUNT_BALANCES",
    "FEES": "ACCOUNT_FEE",
    "ORDER_STATUS": "ORDER_STATUS",
    "EXTERNAL_EXPOSURE": "EXTERNAL_EXPOSURE",
    "CLIENT_ID_ECHO": "MANUAL_PROBE",
    "DUPLICATE_ID": "MANUAL_PROBE",
    "CANCEL_RACE": "MANUAL_PROBE",
    "VENUE_STOP": "MANUAL_PROBE",
}
_SOURCES = {"SANITIZED_EXPORT", "SYNTHETIC_FIXTURE", "SERVICE_GET_REPORT"}
_STATES = {"OBSERVED", "UNKNOWN", "ERROR", "STALE"}
_FIELDS = {
    "evidence_id", "observed_at", "source", "kind", "endpoint",
    "state", "account_scope", "response_version", "evidence_sha256",
}
_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}\Z")
_VERSION = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,31}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_GENESIS = bytes(32)
_COLUMNS = (
    "evidence_id", "observed_at", "source", "kind", "endpoint", "state",
    "account_scope", "response_version", "evidence_sha256",
)

_SCHEMA = """
CREATE TABLE venue_facts (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id TEXT NOT NULL UNIQUE,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    state TEXT NOT NULL,
    account_scope TEXT NOT NULL,
    response_version TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    previous_hash BLOB NOT NULL,
    event_hash BLOB NOT NULL
);
CREATE TRIGGER venue_facts_no_update BEFORE UPDATE ON venue_facts
BEGIN SELECT RAISE(ABORT, 'VenueFacts are append-only'); END;
CREATE TRIGGER venue_facts_no_delete BEFORE DELETE ON venue_facts
BEGIN SELECT RAISE(ABORT, 'VenueFacts are append-only'); END;
PRAGMA user_version=1;
"""


class VenueFactsUnsafe(ValueError):
    """Unsafe, ambiguous or unsupported C1 evidence, or ledger corruption."""


def _validate(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise VenueFactsUnsafe("VenueFacts require exactly the sanitized evidence fields")
    if not isinstance(value["evidence_id"], str) or not _NAME.fullmatch(value["evidence_id"]):
        raise VenueFactsUnsafe("invalid evidence ID")
    if value["source"] not in _SOURCES:
        raise VenueFactsUnsafe("unsupported or falsely privileged source")
    if value["kind"] not in _KINDS or value["endpoint"] != _KINDS[value["kind"]]:
        raise VenueFactsUnsafe("unknown fact kind or endpoint")
    if value["state"] not in _STATES:
        raise VenueFactsUnsafe("unknown evidence state")
    scope = value["account_scope"]
    if not isinstance(scope, str) or (scope != "main" and
            not (scope.startswith("subaccount:") and _NAME.fullmatch(scope))):
        raise VenueFactsUnsafe("invalid account scope")
    if not isinstance(value["response_version"], str) or not _VERSION.fullmatch(value["response_version"]):
        raise VenueFactsUnsafe("invalid bounded response version")
    if not isinstance(value["evidence_sha256"], str) or not _DIGEST.fullmatch(value["evidence_sha256"]):
        raise VenueFactsUnsafe("evidence digest must be lowercase SHA-256")
    stamp = value["observed_at"]
    if not isinstance(stamp, str) or len(stamp) > 42 or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})",
        stamp,
    ):
        raise VenueFactsUnsafe("timestamp must be zoned ISO 8601")
    try:
        instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        raise VenueFactsUnsafe("invalid observation timestamp") from None
    if instant.utcoffset() is None:
        raise VenueFactsUnsafe("timestamp requires timezone")
    # The value is a safe, primitive-only envelope; never store a raw response,
    # arbitrary notes, headers, a session, API key, cookies or order payload.
    return {key: value[key] for key in _COLUMNS}


def validate_venue_fact(value: dict) -> dict:
    """Public validation for an offline, allowlisted C1 evidence envelope."""
    return _validate(value)


def _payload(record: dict) -> bytes:
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")


def _chain(previous: bytes, payload: bytes) -> bytes:
    return hashlib.sha256(previous + len(payload).to_bytes(8, "big") + payload).digest()


class VenueFactsJournal:
    """Full-synchronous append-only offline evidence metadata for Health."""

    def __init__(self, path: Path | str):
        file = Path(path)
        if file.is_symlink() or (file.exists() and not file.is_file()):
            raise VenueFactsUnsafe("venue facts file must be regular and unsymlinked")
        self.conn = sqlite3.connect(file, timeout=5)
        try:
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if self.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='venue_facts'"
                ).fetchone():
                    raise VenueFactsUnsafe("partial or unversioned schema")
                self.conn.executescript("BEGIN IMMEDIATE;" + _SCHEMA + "COMMIT;")
            elif version != 1:
                raise VenueFactsUnsafe("unsupported VenueFacts schema version")
            self._verify()
        except Exception:
            self.conn.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def _verify(self) -> tuple[int, bytes]:
        if self.conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise VenueFactsUnsafe("VenueFacts integrity check failed")
        guards = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name IN ('venue_facts_no_update','venue_facts_no_delete')"
        )}
        if guards != {"venue_facts_no_update", "venue_facts_no_delete"}:
            raise VenueFactsUnsafe("VenueFacts integrity guards missing")
        previous, sequence = _GENESIS, 0
        cols = ",".join(("sequence",) + _COLUMNS + ("previous_hash", "event_hash"))
        for row in self.conn.execute(f"SELECT {cols} FROM venue_facts ORDER BY sequence"):
            seq = row[0]
            record = dict(zip(_COLUMNS, row[1:1 + len(_COLUMNS)]))
            try:
                _validate(record)
            except (VenueFactsUnsafe, ValueError, TypeError):
                raise VenueFactsUnsafe("VenueFacts integrity: invalid stored observation") from None
            prior, claimed_hash = row[-2:]
            if seq != sequence + 1 or prior != previous or claimed_hash != _chain(previous, _payload(record)):
                raise VenueFactsUnsafe("VenueFacts integrity: hash chain or sequence mismatch")
            sequence, previous = seq, claimed_hash
        return sequence, previous

    def record(self, raw: dict) -> int:
        record = _validate(raw)
        body = _payload(record)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            previous_seq, previous_hash = self._verify()
            existing = self.conn.execute(
                "SELECT sequence," + ",".join(_COLUMNS) + " FROM venue_facts WHERE evidence_id=?",
                (record["evidence_id"],),
            ).fetchone()
            if existing:
                if dict(zip(_COLUMNS, existing[1:])) != record:
                    raise VenueFactsUnsafe("conflicting evidence ID; refusing historical rewrite")
                self.conn.commit()
                return existing[0]
            digest = _chain(previous_hash, body)
            values = [record[key] for key in _COLUMNS]
            self.conn.execute(
                "INSERT INTO venue_facts(" + ",".join(_COLUMNS) + ",previous_hash,event_hash) "
                "VALUES(" + ",".join("?" for _ in range(len(values) + 2)) + ")",
                values + [previous_hash, digest],
            )
            self.conn.commit()
            return previous_seq + 1
        except Exception:
            self.conn.rollback()
            raise

    def facts(self, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise VenueFactsUnsafe("invalid evidence history limit")
        self._verify()
        rows = self.conn.execute(
            "SELECT sequence," + ",".join(_COLUMNS) +
            " FROM venue_facts ORDER BY sequence DESC LIMIT ?", (limit,)
        )
        return [{**dict(zip(("sequence",) + _COLUMNS, row)),
                 "trusted_origin": False, "funded_authority": False}
                for row in rows]

    def capabilities(self) -> dict:
        facts = self.facts(limit=1000)
        latest = {}
        for fact in facts:
            latest.setdefault(fact["kind"], fact["state"])

        def observed(kinds):
            available = [latest[kind] for kind in kinds if kind in latest]
            if not available:
                return "NOT_CONFIGURED"
            return "EVIDENCE_ONLY" if all(state == "OBSERVED" for state in available) else "UNAVAILABLE"

        # These rows are informational and have no executable certification
        # capability. No combination of user-imported facts can authorize POST.
        states = {
            "read_only_account": observed(("BALANCES", "FEES")),
            "order_reconciliation": observed(("ORDER_STATUS",)),
            "external_exposure": observed(("EXTERNAL_EXPOSURE",)),
            "venue_probe": "NOT_CERTIFIED",
            "venue_stop": "NOT_CERTIFIED",
            "assisted_order": "BLOCKED",
            "autopilot": "BLOCKED",
        }
        return {key: {"state": state, "funded_authority": False,
                      "requires_service_t2_acceptance": state in ("NOT_CERTIFIED", "BLOCKED"),
                      "trusted_origin": False}
                for key, state in states.items()}
