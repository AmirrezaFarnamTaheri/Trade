"""Sanitized local receipts of completed operations; never a live archive inventory."""
import json
import re
import sqlite3
from pathlib import Path

from ..adapters.wallex_account_read import parse_account_json
from ..domain.market_models import fields, instant
from ..domain.model import iso
from .collector import now_utc


def _validate(row):
    fields(row, "recorded_at sequence head_hash file_sha256 schema_version mode_after")
    instant(row["recorded_at"])
    if any(type(row[k]) is not int or row[k] < 0 for k in ("sequence", "schema_version")):
        raise ValueError("invalid backup receipt version/sequence")
    if any(type(row[k]) is not str or not re.fullmatch("[0-9a-f]{64}", row[k]) for k in ("head_hash", "file_sha256")) or row["mode_after"] != "DISARMED":
        raise ValueError("invalid backup receipt digest or authority")
    return row


def _path(root):
    path = Path(root) / "backup_status.sqlite3"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("regular backup receipt database required")
    return path


def _schema(conn):
    if (conn.execute("PRAGMA user_version").fetchone()[0] != 1
            or {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} != {"receipts"}
            or {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")} != {"frozen_receipt", "retain_receipt"}):
        raise ValueError("unsupported backup receipt schema or retention guards")


def status(root):
    rows, path = {"BACKUP": None, "RESTORE": None}, _path(root)
    if path.exists():
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            conn.execute("BEGIN")
            _schema(conn)
            for kind in rows:
                row = conn.execute("SELECT body FROM receipts WHERE kind=? ORDER BY json_extract(body,'$.recorded_at') DESC, seq DESC LIMIT 1", (kind,)).fetchone()
                if row:
                    if len(row[0]) > 4096:
                        raise ValueError("backup receipt exceeds bound")
                    rows[kind] = _validate(parse_account_json(row[0].encode()))
        finally:
            conn.close()
    return {"state": "RECORDED" if any(rows.values()) else "NO_RECEIPTS", "latest": rows,
            "archive_availability_verified": False, "off_machine_verified": False, "origin_authenticated": False,
            "funded_authority": False, "limitation": "Local historical receipts only. Current archive presence, independent custody and separate-machine recovery are not established."}


def record(root, kind, report):
    if kind not in ("BACKUP", "RESTORE") or report.get("encrypted") is not True or report.get("authenticated") is not True or (kind == "BACKUP" and report.get("verified_restore") is not True):
        raise ValueError("backup receipt requires a successfully authenticated restore")
    row = _validate({"recorded_at": iso(now_utc()), **{k: report[k] for k in ("sequence", "head_hash", "file_sha256", "schema_version")}, "mode_after": "DISARMED"})
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_path(root), isolation_level=None, timeout=5)
    try:
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if version == 0 and not tables:
            conn.execute("CREATE TABLE receipts(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ('BACKUP','RESTORE')),body TEXT NOT NULL)")
            conn.execute("CREATE TRIGGER frozen_receipt BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT,'immutable receipt'); END")
            conn.execute("CREATE TRIGGER retain_receipt BEFORE DELETE ON receipts BEGIN SELECT RAISE(ABORT,'retain receipt'); END")
            conn.execute("PRAGMA user_version=1")
        elif version != 1 or tables != {"receipts"}:
            raise ValueError("unsupported backup receipt schema")
        _schema(conn)
        conn.execute("INSERT INTO receipts(kind,body) VALUES(?,?)", (kind, json.dumps(row)))
        conn.commit()
    finally:
        conn.close()
    return row


def merge_receipts(root, source_root):
    """Append validated historical receipts to an existing journal; caller retains backups of both stores."""
    target, source = _path(root), _path(source_root)
    if target.resolve() == source.resolve() or not target.is_file() or not source.is_file():
        raise ValueError("two distinct existing receipt journals required")

    def entries(conn):
        _schema(conn)
        values = []
        for kind, body in conn.execute("SELECT kind,body FROM receipts ORDER BY seq LIMIT 10001"):
            if len(values) == 10000 or type(body) is not str or len(body.encode("utf-8")) > 4096:
                raise ValueError("receipt migration budget exceeded")
            if kind not in ("BACKUP", "RESTORE"):
                raise ValueError("invalid receipt kind")
            row = _validate(parse_account_json(body.encode("utf-8")))
            row["recorded_at"] = iso(instant(row["recorded_at"]))
            values.append((kind, json.dumps(row, sort_keys=True, separators=(",", ":"))))
        return values

    reader = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        reader.execute("BEGIN")
        source_rows = entries(reader)
    finally:
        reader.close()
    conn = sqlite3.connect(target, isolation_level=None, timeout=5)
    try:
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        existing = set(entries(conn))
        inserted = 0
        for item in source_rows:
            if item not in existing:
                conn.execute("INSERT INTO receipts(kind,body) VALUES(?,?)", item)
                existing.add(item)
                inserted += 1
        conn.commit()
    finally:
        conn.close()
    return {"source_receipts": len(source_rows), "inserted": inserted, "duplicates": len(source_rows) - inserted}
