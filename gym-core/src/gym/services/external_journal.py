"""Local non-authoritative Journal of external venue observations.

No money postings, settlement inference, venue writes or network credentials.
A closed/canceled status remains raw until separate account evidence verifies
its economic effect; disappearance from a listing never implies absence.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


SCHEMA = """
CREATE TABLE external_order_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    client_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    raw_status TEXT NOT NULL,
    filled_observed TEXT,
    settlement TEXT NOT NULL CHECK(settlement='UNKNOWN'),
    economic_effect TEXT NOT NULL CHECK(economic_effect='UNVERIFIED'),
    authority TEXT NOT NULL CHECK(authority='READ_ONLY')
);
CREATE INDEX external_order_lookup ON external_order_events(account_id, client_id, sequence);
CREATE TRIGGER external_orders_no_update BEFORE UPDATE ON external_order_events
BEGIN SELECT RAISE(ABORT, 'external observation events are immutable'); END;
CREATE TRIGGER external_orders_no_delete BEFORE DELETE ON external_order_events
BEGIN SELECT RAISE(ABORT, 'external observation events are immutable'); END;
PRAGMA user_version=1;
"""


def _utc(text: str) -> str:
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid external observation time") from None
    if stamp.utcoffset() is None:
        raise ValueError("external observation time needs timezone")
    return stamp.astimezone(timezone.utc).isoformat(timespec="microseconds")


class ExternalJournal:
    """Append-only display projection. This is NOT the Executor money ledger."""
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(Path(path))
        try:
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                self.conn.executescript("BEGIN IMMEDIATE;" + SCHEMA + "COMMIT;")
            elif version != 1:
                raise ValueError("unsupported external Journal version")
            guards = {name for (name,) in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND "
                "name IN ('external_orders_no_update','external_orders_no_delete')")}
            if guards != {"external_orders_no_update", "external_orders_no_delete"}:
                raise ValueError("external Journal immutability guards missing")
        except Exception:
            self.conn.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def record(self, snapshot: dict) -> int:
        if not isinstance(snapshot, dict) or snapshot.get("state") != "OBSERVED" \
            or snapshot.get("authority") != "READ_ONLY" \
            or snapshot.get("source") != "VENUE_EXTERNAL":
            raise ValueError("external Journal requires read-only venue observation")
        account = snapshot.get("account_id")
        if not isinstance(account, str) or not account:
            raise ValueError("unknown external account")
        observed_at = _utc(snapshot.get("observed_at"))
        rows = snapshot.get("orders")
        if not isinstance(rows, list):
            raise ValueError("invalid external order list")
        written = 0
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            for item in rows:
                if not isinstance(item, dict) or item.get("account_id") != account \
                    or item.get("origin") != "EXTERNAL_MANUAL_UNVERIFIED" \
                    or item.get("settlement") != "UNKNOWN" \
                    or item.get("economic_effect") != "UNVERIFIED" \
                    or item.get("funded_trade") is not False:
                    raise ValueError("not a sanitized external/manual order")
                ident, status = item.get("client_id"), item.get("raw_status")
                if not isinstance(ident, str) or not ident or not isinstance(status, str) or not status:
                    raise ValueError("invalid external order identity")
                amount = item.get("filled_observed")
                if amount is not None:
                    amount = Decimal(str(amount))
                    if not amount.is_finite() or amount < 0:
                        raise ValueError("invalid observed fill")
                previous = self.conn.execute(
                    "SELECT observed_at,raw_status,filled_observed FROM external_order_events "
                    "WHERE account_id=? AND client_id=? ORDER BY sequence DESC LIMIT 1",
                    (account, ident),
                ).fetchone()
                if previous is not None:
                    if observed_at < previous[0]:
                        raise ValueError("stale external order observation")
                    prev_amount = Decimal(previous[2]) if previous[2] is not None else None
                    if amount is not None and prev_amount is not None and amount < prev_amount:
                        raise ValueError("regressed cumulative fill observation")
                    if status == previous[1] and (
                        amount is None or (prev_amount is not None and amount == prev_amount)
                    ):
                        continue
                    if amount is None and prev_amount is not None:
                        amount = prev_amount
                self.conn.execute(
                    "INSERT INTO external_order_events(account_id,client_id,observed_at,raw_status,"
                    "filled_observed,settlement,economic_effect,authority) VALUES(?,?,?,?,?,?,?,?)",
                    (account, ident, observed_at, status,
                     None if amount is None else format(amount, "f"), "UNKNOWN", "UNVERIFIED", "READ_ONLY"),
                )
                written += 1
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return written

    def events(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT sequence,account_id,client_id,observed_at,raw_status,filled_observed,"
            "settlement,economic_effect,authority FROM external_order_events ORDER BY sequence"
        ).fetchall()
        keys = ("sequence", "account_id", "client_id", "observed_at", "raw_status",
                "filled_observed", "settlement", "economic_effect", "authority")
        return [dict(zip(keys, row)) for row in rows]
