"""One read-only answer to "is this workspace intact?": runs the existing verifiers and reports each result.

Nothing here repairs, creates or deletes data. Missing optional stores are SKIP, not FAIL. The protected
executor ledger is not read: it belongs to the service account and has its own `verify()`.
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
BACKUP_STALE = timedelta(hours=36)


def _check(name, status, detail):
    return {"check": name, "status": status, "detail": detail}


def _market(root: Path, now: datetime, full: bool, archives: list[Path]):
    from ..adapters.store import MarketDB, verify_segments
    path = root / "market.db"
    if not path.is_file():
        return [_check("market_db", FAIL, f"{path} not found")]
    db = MarketDB(path, readonly=True)
    try:
        quick = db.c.execute("PRAGMA quick_check").fetchone()[0]
        out = [_check("market_db", PASS if quick == "ok" else FAIL, f"SQLite quick_check: {quick}")]
        since = "" if full else (now - timedelta(days=1)).strftime("%Y%m%d")
        report = verify_segments(db, [root / "raw", *archives], since)
    finally:
        db.c.close()
    scope = "all days" if full else f"days from {since}"
    bad = report["mismatched"] + report["missing"]
    out.append(_check("raw_segments", FAIL if bad else PASS,
                      f"{report['checked']} re-hashed ({scope}); mismatched {report['mismatched'] or 'none'}; "
                      f"missing {report['missing'] or 'none'}"))
    # An unclosed row for the current UTC hour is the file a running collector has open; older ones are crash tails.
    live = now.astimezone(UTC).strftime("%Y%m%d/%H-")
    loose = report["unregistered"] + [seg for seg in report["unclosed"] if not seg.startswith(live)]
    out.append(_check("segment_manifest", WARN if loose else PASS,
                      f"unclosed {report['unclosed'] or 'none'}; unregistered {report['unregistered'] or 'none'}"))
    return out


def _disk(root: Path):
    from ..adapters.store import MIN_FREE_BYTES
    probe = root / "raw" if (root / "raw").exists() else root
    if not probe.exists():
        return _check("free_space", SKIP, f"{probe} not found")
    free = shutil.disk_usage(probe).free
    gib = 1024 ** 3
    status = FAIL if free < MIN_FREE_BYTES else WARN if free < 4 * MIN_FREE_BYTES else PASS
    return _check("free_space", status, f"{free / gib:.1f} GiB free; collection stops below {MIN_FREE_BYTES / gib:.0f} GiB")


def _journal(name: str, path: Path, opener):
    if not path.exists():
        return _check(name, SKIP, "not created yet")
    try:
        with opener(path):
            return _check(name, PASS, "integrity and append-only guards verified")
    except (ValueError, OSError, sqlite3.Error) as e:
        return _check(name, FAIL, str(e))


def _sqlite_only(name: str, path: Path):
    if not path.exists():
        return _check(name, SKIP, "not created yet")
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as e:
        return _check(name, FAIL, str(e))
    return _check(name, PASS if result == "ok" else FAIL, f"SQLite integrity_check: {result}")


def _backup(root: Path, now: datetime):
    from .backup_status import status
    try:
        report = status(root)
    except (ValueError, OSError, sqlite3.Error) as e:
        return _check("backup_receipts", FAIL, str(e))
    latest = report["latest"]["BACKUP"]
    if latest is None:
        return _check("backup_receipts", WARN, "no backup receipt recorded; run backup-once or install the schedule")
    age = now - datetime.fromisoformat(latest["recorded_at"])
    hours = age.total_seconds() / 3600
    return _check("backup_receipts", WARN if age > BACKUP_STALE else PASS,
                  f"last backup {hours:.1f} h ago (sequence {latest['sequence']}); off-machine copy not verified")


def _keys(today):
    from ..adapters import secret_store
    out = []
    for role in secret_store.ROLES:
        if not secret_store._path(role, None).is_file():
            continue
        note = secret_store.expiry_note(role, today)
        status = FAIL if note.startswith("EXPIRED") else WARN if "unknown" in note or "soon" in note else PASS
        out.append(_check(f"key_{role}", status, note))
    return out


def diagnose(root: Path, now: datetime, *, full: bool = False, archives: list[Path] | None = None) -> dict:
    from .offline_review_journal import OfflineReviewJournal
    from .venue_facts import VenueFactsJournal
    checks = []
    checks += _market(root, now, full, archives or [])
    checks.append(_disk(root))
    checks.append(_journal("venue_facts", root / "venue_facts.db", VenueFactsJournal))
    checks.append(_journal("offline_reviews", root / "offline_reviews.db", OfflineReviewJournal))
    checks.append(_sqlite_only("external_journal", root / "external_journal.db"))
    checks.append(_sqlite_only("probe_budget", root / "probe_budget.db"))
    checks.append(_backup(root, now))
    checks += _keys(now.date())
    checks.append(_check("executor_ledger", SKIP, "owned by the protected service; verified by the executor at startup"))
    worst = FAIL if any(c["status"] == FAIL for c in checks) else WARN if any(c["status"] == WARN for c in checks) else PASS
    return {"as_of": now.isoformat(), "root": str(root), "status": worst, "checks": checks,
            "read_only": True, "funded_authority": False}
