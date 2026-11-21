"""Sanitized local receipts of completed operations; never a live archive inventory."""
import json
import re
import sqlite3
from pathlib import Path

from ..adapters.wallex_account_read import parse_account_json
from ..domain.market_models import fields, instant
from ..domain.model import iso, now_utc, parse_ts


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
            "funded_authority": False, "limitation": "Local historical receipts only. Current archive presence, provenance and runtime readiness are not established."}


def receipt_chronology(root, *, now=None) -> dict:
    """Report local receipt ages while keeping unverifiable off-machine backup age explicitly UNKNOWN (O013)."""
    at = now or now_utc()
    snap = status(root)
    latest = snap["latest"]

    def _age_hours(row):
        if not row or not row.get("recorded_at"):
            return None
        return round(max(0.0, (at - parse_ts(row["recorded_at"])).total_seconds() / 3600.0), 2)

    return {
        "as_of": iso(at),
        "state": snap["state"],
        "latest_local_backup_at": latest["BACKUP"]["recorded_at"] if latest["BACKUP"] else None,
        "latest_local_restore_at": latest["RESTORE"]["recorded_at"] if latest["RESTORE"] else None,
        "local_backup_age_hours": _age_hours(latest["BACKUP"]),
        "local_restore_age_hours": _age_hours(latest["RESTORE"]),
        "off_machine_status": "UNKNOWN",
        "off_machine_backup_age_hours": None,
        "owner_policy_exception": "Off-machine backup scheduling canceled by owner on 2026-11-16; local receipts do not verify off-machine availability.",
        "funded_authority": False,
    }


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
