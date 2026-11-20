"""Append-only custody of test (holdout) windows: each look is recorded, repeated looks are counted.

The price digest identifies a particular window. Per-market spans detect reused evidence even when a digest
changes. Earlier entries without coverage count as potentially overlapping. An explicit rescore counts the
configurations across all overlapping looks.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS looks(seq INTEGER PRIMARY KEY AUTOINCREMENT, window TEXT NOT NULL, spec TEXT NOT NULL,
    configurations INTEGER NOT NULL CHECK(configurations > 0), at TEXT NOT NULL, purpose TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS looks_no_update BEFORE UPDATE ON looks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS looks_no_delete BEFORE DELETE ON looks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
"""


def window_id(symbols, interval: str, start: str, end: str, prices) -> str:
    """Identity of a test window: what it covers and exactly which prices are in it."""
    body = json.dumps({"schema": "holdout-window/1", "symbols": sorted(symbols), "interval": interval,
                       "start": start, "end": end, "prices": [[t, repr(p)] for t, p in prices]},
                      separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def _overlaps(current: dict, previous: dict) -> bool:
    if "coverage" not in previous or "coverage" not in current:
        return True
    return any(
        start <= previous["coverage"][symbol][1] and previous["coverage"][symbol][0] <= end
        for symbol, (start, end) in current["coverage"].items()
        if symbol in previous["coverage"]
    )


class HoldoutRefused(ValueError):
    """The window was already scored and no rescore was requested."""


class HoldoutLedger:
    def __init__(self, path: Path):
        if path.is_symlink():
            raise ValueError("holdout ledger must not be a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, isolation_level=None, timeout=5)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript(_SCHEMA)

    def close(self):
        self.conn.close()

    def looks(self, window: str) -> list[dict]:
        rows = self.conn.execute("SELECT seq, spec, configurations, at, purpose FROM looks WHERE window=? ORDER BY seq",
                                 (window,)).fetchall()
        return [{"seq": s, "spec": json.loads(spec), "configurations": n, "at": at, "purpose": p}
                for s, spec, n, at, p in rows]

    def look(self, window: str, spec: dict, configurations: int, *, rescore: bool, now: datetime | None = None) -> dict:
        """Record a look, refusing overlapping evidence unless explicitly rescored."""
        if type(configurations) is not int or configurations < 1:
            raise ValueError("a look needs the number of configurations behind it")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            rows = self.conn.execute("SELECT window, spec, configurations, at FROM looks ORDER BY seq")
            prior = [(n, at) for key, previous, n, at in rows
                     if key == window or _overlaps(spec, json.loads(previous))]
            if prior and not rescore:
                raise HoldoutRefused(f"overlapping or unscoped test evidence already scored {len(prior)} time(s), first at {prior[0][1]}")
            at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
            self.conn.execute("INSERT INTO looks(window, spec, configurations, at, purpose) VALUES(?,?,?,?,?)",
                              (window, json.dumps(spec, sort_keys=True), configurations, at,
                               "rescore" if prior else "first"))
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        return {"window": window, "look": len(prior) + 1, "first_at": prior[0][1] if prior else at,
                "configurations_all_looks": sum(n for n, _ in prior) + configurations}
