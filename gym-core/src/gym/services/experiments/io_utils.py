"""Shared atomic file, JSONL, and SQLite snapshot IO utilities for experiment and journal runners."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

from .._journal_lock import append_jsonl, journal_lock


@contextmanager
def readonly_snapshot(con):
    """Hold a single SQLite read snapshot across multi-table queries."""
    con.execute("BEGIN DEFERRED")
    try:
        yield con
    finally:
        if con.in_transaction:
            con.execute("ROLLBACK")


def write_text_atomic(path: Path, text: str) -> None:
    """Atomically write UTF-8 text via temp file + fsync + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def write_json_atomic(path: Path, payload: dict) -> None:
    """Atomically write pretty-printed JSON so readers never see partial writes."""
    write_text_atomic(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_jsonl_records(journal_path: Path) -> tuple[list[dict], int]:
    """Read valid JSONL dict records, counting any torn or corrupt lines instead of crashing."""
    if not journal_path.is_file():
        return [], 0
    rows: list[dict] = []
    corrupt = 0
    for ln in journal_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            corrupt += 1
    return rows, corrupt


def append_jsonl_locked(journal_path: Path, record: dict, *, timeout_s: float = 15.0) -> bool:
    """Append one JSONL record under an OS-released lock with atomic slot_key deduplication.

    Returns True if appended, False if an identical slot_key already existed in the journal.
    """
    with journal_lock(journal_path, timeout=timeout_s):
        slot_key = record.get("slot_key")
        if slot_key is not None and journal_path.is_file():
            existing, _ = read_jsonl_records(journal_path)
            if any(r.get("slot_key") == slot_key for r in existing):
                return False
        append_jsonl(journal_path, json.dumps(record, sort_keys=True))
        return True
