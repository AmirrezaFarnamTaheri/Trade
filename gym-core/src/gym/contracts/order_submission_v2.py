"""Dry-run v2 venue client-id and placement-rate contract, no executor transport."""
import re
import sqlite3
from datetime import timedelta
from pathlib import Path

from ..domain.model import iso

CLIENT_ID = re.compile(r"[A-Za-z0-9_]{1,64}\Z")
ACCOUNT_ID = re.compile(r"[A-Za-z0-9_]{1,32}\Z")


def valid_submit_client_id(value):
    """Validate a *proposed submit* ID; read-side venue IDs remain unchanged."""
    if type(value) is not str or CLIENT_ID.fullmatch(value) is None:
        raise ValueError("proposed Wallex client_id accepts only ASCII letters, digits, underscores")
    return value


class PaperSubmissionGate:
    """Durable duplicate and 20/10-second admission checks with no order method."""

    def __init__(self, path):
        """Open a durable, non-executable proposal ledger for duplicate and rate checks."""
        path = Path(path)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("invalid paper admission journal path")
        self.conn = sqlite3.connect(path, isolation_level=None, timeout=5)
        try:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            existing = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version not in (0, 1) or (version == 0 and existing):
                raise ValueError("unsupported paper admission schema")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            if version == 0:
                self.conn.executescript("""BEGIN IMMEDIATE;
                    CREATE TABLE proposals(account TEXT NOT NULL, client_id TEXT NOT NULL,
                        at TEXT NOT NULL, PRIMARY KEY(account,client_id));
                    CREATE INDEX proposal_pace ON proposals(account,at);
                    CREATE TRIGGER immutable_proposals BEFORE UPDATE ON proposals
                      BEGIN SELECT RAISE(ABORT,'immutable proposal'); END;
                    CREATE TRIGGER retained_proposals BEFORE DELETE ON proposals
                      BEGIN SELECT RAISE(ABORT,'retained proposal'); END;
                    PRAGMA user_version=1; COMMIT;""")
            if self.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("paper submission journal integrity failure")
        except BaseException:
            self.conn.close()
            raise

    def __enter__(self):
        """Return the scoped dry-run submission journal."""
        return self

    def __exit__(self, *_):
        """Close the submission journal without submitting an order."""
        self.conn.close()

    def stage(self, account, client_id, *, at):
        """Record only a bounded paper proposal if duplicate/pacing checks pass."""
        if (type(account) is not str or ACCOUNT_ID.fullmatch(account) is None
                or at.tzinfo is None):
            raise ValueError("invalid paper proposal identity or time")
        valid_submit_client_id(client_id)
        stamp = iso(at)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self.conn.execute(
                "SELECT 1 FROM proposals WHERE account=? AND client_id=?",
                (account, client_id)).fetchone()
            if existing is not None:
                raise ValueError("duplicate proposed Wallex client_id")
            previous = self.conn.execute(
                "SELECT MAX(at) FROM proposals WHERE account=?", (account,)).fetchone()[0]
            if previous is not None and stamp < previous:
                raise ValueError("nonmonotonic proposal time cannot reset a rate window")
            count = self.conn.execute(
                "SELECT count(*) FROM proposals WHERE account=? AND at>? AND at<=?",
                (account, iso(at - timedelta(seconds=10)), stamp)).fetchone()[0]
            if count >= 20:
                raise ValueError("paper proposal rate exceeds 20 per rolling 10 seconds")
            self.conn.execute("INSERT INTO proposals VALUES(?,?,?)",
                              (account, client_id, stamp))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        return {"status": "PAPER_ADMISSION_RECORDED", "client_id": client_id,
                "account": account, "at": stamp,
                "contract": "submit-client-id-and-rate-v2-dry-run",
                "order_submitted": False, "funded_authority": False,
                "executor_authorized": False,
                "limitation": "No native review IPC, authenticated account, transport or real order pacing installed"}
