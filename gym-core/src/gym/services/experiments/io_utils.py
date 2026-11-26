"""Shared atomic file, JSONL, and SQLite snapshot IO utilities for experiment and journal runners."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

from .._journal_lock import append_jsonl, journal_lock

_SEMANTIC_OPERATIONAL_FILES = (
    "services/experiments/admm_helpers.py",
    "services/experiments/champion_forward_journal.py",
    "services/experiments/champion_v2_journal.py",
    "services/experiments/gru_engine.py",
    "services/experiments/io_utils.py",
    "services/experiments/leader_forward_journal.py",
)


def semantic_engine_digest() -> str:
    """Hash only domain/ and operational execution-journal files so unrelated UI/script edits do not cause cohort drift."""
    root = Path(__file__).resolve().parents[2]
    h = hashlib.sha256()
    paths = sorted(p for p in (root / "domain").rglob("*.py") if "__pycache__" not in p.parts)
    for rel in _SEMANTIC_OPERATIONAL_FILES:
        p = root / rel
        if p.is_file():
            paths.append(p)
    for p in paths:
        h.update(p.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


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
        if journal_path.is_file() and journal_path.stat().st_size > 0:
            with journal_path.open("rb+") as fh:
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    fh.seek(0, os.SEEK_END)
                    fh.write(b"\n")
                    fh.flush()
                    os.fsync(fh.fileno())
        append_jsonl(journal_path, json.dumps(record, sort_keys=True))
        return True
