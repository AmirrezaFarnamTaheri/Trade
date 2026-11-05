"""Local non-authoritative Journal of external venue observations.

No money postings, settlement inference, venue writes or network credentials.
A closed/canceled status remains raw until separate account evidence verifies
its economic effect; disappearance from a listing never implies absence.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from time import monotonic, sleep

from ..adapters.wallex_account_read import (
    ReadUncertain,
    parse_account_json,
    parse_fee_rates,
)
from ..contracts.account_receipt import service_receipts
from ..domain.account_observations import project_account

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

SNAPSHOT_SCHEMA = """
CREATE TABLE external_account_snapshots (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
);
CREATE INDEX external_account_lookup ON external_account_snapshots(account_id, sequence);
CREATE TRIGGER external_accounts_no_update BEFORE UPDATE ON external_account_snapshots
BEGIN SELECT RAISE(ABORT, 'external account snapshots are immutable'); END;
CREATE TRIGGER external_accounts_no_delete BEFORE DELETE ON external_account_snapshots
BEGIN SELECT RAISE(ABORT, 'external account snapshots are immutable'); END;
PRAGMA user_version=2;
"""

_ORDER_GUARDS = {"external_orders_no_update", "external_orders_no_delete"}
_ACCOUNT_GUARDS = {"external_accounts_no_update", "external_accounts_no_delete"}
_TRANSPORTS = {"MANUAL_IMPORT", "EXECUTOR_SERVICE_WINHTTP", "INTERACTIVE_USER_GET"}
_MAX_SNAPSHOT = 1_048_576


def _execute_schema(conn: sqlite3.Connection, script: str) -> None:
    # executescript commits first; fixed DDL must remain inside the migration lock.
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("incomplete external Journal schema")


def _sanitize_snapshot(snapshot: dict, fee_rates: dict | None, transport: str) -> dict:
    if not isinstance(snapshot, dict) or snapshot.get("state") != "OBSERVED" \
        or snapshot.get("authority") != "READ_ONLY" or snapshot.get("source") != "VENUE_EXTERNAL":
        raise ValueError("external Journal requires read-only venue observation")
    if snapshot.get("funded_authority", False) is not False \
        or snapshot.get("permission_status", "UNVERIFIED") != "UNVERIFIED":
        raise ValueError("external account authority must remain unverified")
    if any(not isinstance(snapshot.get(key), list) for key in ("balances", "orders", "exposure")):
        raise ValueError("invalid account snapshot collections")
    try:
        if transport not in _TRANSPORTS:
            raise ValueError("invalid external observation transport")
        balances, orders, exposure = {}, [], []
        for row in snapshot["balances"]:
            if row.get("spendable") is not None or row.get("protectable") is not None:
                raise ValueError("observed balances cannot be money authority")
            asset = row["asset"]
            if not isinstance(asset, str) or asset.upper() in balances:
                raise ValueError("invalid or duplicate balance asset")
            balances[asset.upper()] = {"value": row["venue_value"], "locked": row["venue_locked"]}
        for row in snapshot["orders"]:
            if row.get("account_id") != snapshot["account_id"] \
                or row.get("origin") != "EXTERNAL_MANUAL_UNVERIFIED" \
                or row.get("settlement") != "UNKNOWN" or row.get("economic_effect") != "UNVERIFIED" \
                or row.get("funded_trade") is not False:
                raise ValueError("not a sanitized external/manual order")
            orders.append({"client_id": row["client_id"], "status": row["raw_status"],
                           "symbol": row.get("symbol"), "filled": row.get("filled_observed")})
        for row in snapshot["exposure"]:
            if row.get("managed") is not False or row.get("status") != "UNVERIFIED" \
                or row.get("spendable") is not None or row.get("protectable") is not None:
                raise ValueError("external exposure cannot be managed money")
            exposure.append({"account_id": row["account_id"], "product": row["raw_product"],
                             "obligation_asset": row.get("obligation_asset"), "obligation": row.get("obligation")})
        clean = project_account(snapshot["account_id"], snapshot["observed_at"],
                                balances=balances, orders=orders, exposure=exposure)
        fees = None if fee_rates is None else parse_fee_rates({"success": True, "result": {
            symbol: {"makerFeeRate": row["maker"], "takerFeeRate": row["taker"]}
            for symbol, row in fee_rates.items()
        }})
    except (KeyError, TypeError, AttributeError, ReadUncertain):
        raise ValueError("invalid sanitized account snapshot") from None
    out = {**clean, "fee_rates": fees, "transport": transport,
           "permission_status": "UNVERIFIED", "funded_authority": False}
    if "service_receipts" in snapshot:
        if transport != "EXECUTOR_SERVICE_WINHTTP" or snapshot["account_id"] != "main":
            raise ValueError("service receipts require the main service account")
        out["service_receipts"] = service_receipts(snapshot["service_receipts"])
    return out


def _utc(text: str) -> str:
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
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
            deadline = monotonic() + 5
            while True:
                try:
                    self.conn.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    # Concurrent first-open mode changes can bypass SQLite's busy timeout.
                    if getattr(exc, "sqlite_errorcode", None) != sqlite3.SQLITE_BUSY or monotonic() >= deadline:
                        raise
                    sleep(0.01)
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.execute("BEGIN IMMEDIATE")
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError("unsupported external Journal version")
            guards = {name for (name,) in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'")}
            if version and not _ORDER_GUARDS.issubset(guards):
                raise ValueError("external Journal immutability guards missing")
            if version in (0, 1):
                schema = (SCHEMA if version == 0 else "") + SNAPSHOT_SCHEMA
                _execute_schema(self.conn, schema)
                guards = {name for (name,) in self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'")}
            if not (_ORDER_GUARDS | _ACCOUNT_GUARDS).issubset(guards):
                raise ValueError("external Journal immutability guards missing")
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            self.conn.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def record(self, snapshot: dict, *, fee_rates: dict | None = None,
               transport: str = "MANUAL_IMPORT") -> int:
        """Atomically append the snapshot and order changes; return changed order count."""
        snapshot = _sanitize_snapshot(snapshot, fee_rates, transport)
        serialized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(serialized.encode("utf-8")) > _MAX_SNAPSHOT:
            raise ValueError("external account snapshot exceeds size limit")
        account = snapshot["account_id"]
        observed_at = _utc(snapshot["observed_at"])
        written = 0
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            previous_at = self.conn.execute(
                "SELECT MAX(observed_at) FROM ("
                "SELECT observed_at FROM external_account_snapshots WHERE account_id=? UNION ALL "
                "SELECT observed_at FROM external_order_events WHERE account_id=?)", (account, account),
            ).fetchone()[0]
            if previous_at is not None and observed_at < previous_at:
                raise ValueError("stale external account snapshot")
            for item in snapshot["orders"]:
                ident, status = item["client_id"], item["raw_status"]
                amount = None if item["filled_observed"] is None else Decimal(item["filled_observed"])
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
            self.conn.execute(
                "INSERT INTO external_account_snapshots(account_id,observed_at,snapshot_json) VALUES(?,?,?)",
                (account, observed_at, serialized),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return written

    def latest_snapshot(self, account_id: str = "main") -> dict | None:
        try:
            row = self.conn.execute(
                "SELECT observed_at,snapshot_json FROM external_account_snapshots WHERE account_id=? "
                "ORDER BY sequence DESC LIMIT 1", (account_id,),
            ).fetchone()
        except sqlite3.Error:
            raise ValueError("persisted account snapshot unavailable") from None
        if row is None:
            return None
        if not isinstance(row[1], str) or len(row[1].encode("utf-8")) > _MAX_SNAPSHOT:
            raise ValueError("invalid persisted account snapshot")
        try:
            saved = parse_account_json(row[1].encode("utf-8"))
            if not isinstance(saved, dict) or saved.get("account_id") != account_id \
                or _utc(saved.get("observed_at")) != row[0]:
                raise ValueError("invalid persisted account snapshot")
            return _sanitize_snapshot(saved, saved.get("fee_rates"), saved.get("transport"))
        except ReadUncertain:
            raise ValueError("invalid persisted account snapshot") from None

    def events(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT sequence,account_id,client_id,observed_at,raw_status,filled_observed,"
            "settlement,economic_effect,authority FROM external_order_events ORDER BY sequence"
        ).fetchall()
        keys = ("sequence", "account_id", "client_id", "observed_at", "raw_status",
                "filled_observed", "settlement", "economic_effect", "authority")
        return [dict(zip(keys, row)) for row in rows]
