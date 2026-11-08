"""Append-only research-question trial attempts, independent of frozen run artifacts.

Each invocation is a selection attempt, not an independent return observation.
Market records and paper run identities remain unchanged by this ledger.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from ..domain.model import iso, parse_ts
from ..domain.strategy import digest

_ALLOWED_SOURCES = frozenset(("paper", "portfolio", "compare", "validate", "experiment", "walk-forward", "prospective"))


def _stamp(value: datetime | str) -> str:
    """Canonicalize aware instants so equivalent UTC offsets share a question."""
    if isinstance(value, datetime):
        value = iso(value)
    if type(value) is not str:
        raise ValueError("trial bounds must be zoned timestamps")
    return iso(parse_ts(value))


def _question(symbol: str, start: datetime | str, end: datetime | str, hypothesis: str) -> str:
    """Identify one symbol, frozen window and stated research hypothesis exactly."""
    if type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}(?:,[A-Z0-9]{2,24})*", symbol):
        raise ValueError("trial question requires observed uppercase symbols")
    if type(hypothesis) is not str or not 1 <= len(hypothesis.strip()) <= 500:
        raise ValueError("trial question requires a bounded hypothesis")
    first, last = _stamp(start), _stamp(end)
    if not first < last:
        raise ValueError("trial window must be positive")
    return digest({"schema": "research-question/1", "symbol": symbol, "from": first,
                   "to": last, "hypothesis": hypothesis.strip()})


class TrialLedger:
    """Persist attempts separately from immutable market and strategy run records."""

    def __init__(self, root: Path | str):
        root = Path(root)
        if root.is_symlink():
            raise ValueError("trial ledger root must not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        path = root / "trial_ledger.sqlite3"
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("trial ledger requires a regular file")
        self.conn = sqlite3.connect(path, isolation_level=None, timeout=5)
        try:
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            # Acquire the DDL lock before inspecting the version and tables.
            self.conn.execute("BEGIN IMMEDIATE")
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version not in (0, 1) or version == 0 and tables:
                raise ValueError("unsupported or unversioned trial ledger")
            if not version:
                statements = (
                    "CREATE TABLE trial_attempts("
                    "attempt_id TEXT PRIMARY KEY, question_id TEXT NOT NULL, "
                    "source TEXT NOT NULL, config_hash TEXT NOT NULL, recorded_at TEXT NOT NULL)",
                    "CREATE INDEX trial_question ON trial_attempts(question_id)",
                    "CREATE TRIGGER trial_no_update BEFORE UPDATE ON trial_attempts "
                    "BEGIN SELECT RAISE(ABORT, 'immutable trial attempt'); END",
                    "CREATE TRIGGER trial_no_delete BEFORE DELETE ON trial_attempts "
                    "BEGIN SELECT RAISE(ABORT, 'retain trial attempt'); END",
                    "PRAGMA user_version=1",
                )
                for statement in statements:
                    self.conn.execute(statement)
            names = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            if names != {"trial_no_update", "trial_no_delete"}:
                raise ValueError("trial ledger integrity guards are absent")
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            self.conn.close()
            raise

    def __enter__(self):
        """Support deterministic close/flush of a local trial ledger."""
        return self

    def __exit__(self, *_):
        """Close the SQLite handle on both success and failure."""
        self.conn.close()

    def record(self, *, symbol: str, start: datetime | str, end: datetime | str,
               hypothesis: str, source: str, config_hash: str, attempt_id: str | None = None) -> dict:
        """Register a durable attempt before reading the evaluation data."""
        question = _question(symbol, start, end, hypothesis)
        if source not in _ALLOWED_SOURCES:
            raise ValueError("invalid trial source")
        if type(config_hash) is not str or not 1 <= len(config_hash) <= 128:
            raise ValueError("invalid trial configuration hash")
        if attempt_id is None:
            attempt_id = uuid4().hex
        if type(attempt_id) is not str or not re.fullmatch(r"[A-Za-z0-9_./:-]{1,128}", attempt_id):
            raise ValueError("invalid attempt identifier")
        from .collector import now_utc

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            earlier = self.conn.execute(
                "SELECT question_id, source, config_hash FROM trial_attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if earlier:
                if earlier != (question, source, config_hash):
                    raise ValueError("attempt identifier already belongs to a different trial")
            else:
                self.conn.execute(
                    "INSERT INTO trial_attempts(attempt_id, question_id, source, config_hash, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (attempt_id, question, source, config_hash, iso(now_utc())),
                )
            trials = self.conn.execute("SELECT count(*) FROM trial_attempts WHERE question_id=?", (question,)).fetchone()[0]
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        return {"attempt_id": attempt_id, "question_id": question, "trials": trials,
                "authority": "PAPER_ONLY", "funded_authority": False}

    def count(self, *, symbol: str, start: datetime | str, end: datetime | str, hypothesis: str) -> int:
        """Read the complete durable selection count for one research question."""
        question = _question(symbol, start, end, hypothesis)
        return self.conn.execute("SELECT count(*) FROM trial_attempts WHERE question_id=?", (question,)).fetchone()[0]
