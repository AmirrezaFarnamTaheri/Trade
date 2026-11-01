"""C1 offline probe-ladder evidence and immutable loss-budget planner.

No credentials, network transport, order POST, cancellations or certification
exist in this module. Staging a probe is NEVER permission to trade. The
restricted Executor must enforce any real T2 consent and money budget again.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from decimal import Decimal, localcontext
from pathlib import Path

from ..domain.account_observations import parse_wallex_balances

_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?\Z")
_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}\Z")
_ASSET = re.compile(r"[A-Z0-9]{2,12}\Z")
_SYMBOL = re.compile(r"[A-Z0-9]{5,32}\Z")
_PROBES = {
    "CLIENT_ID_ECHO", "DUPLICATE_ID", "LIMIT_PARTIAL_FILL",
    "CANCEL_RACE", "STOP_LIMIT", "STOP_MARKET", "FEE_ASSET",
    "MARKET_PRICE_GUARD",
}


class ProbeUnsafe(ValueError):
    """Missing, contradictory or over-budget manual probe evidence."""


def _decimal(raw: object, name: str) -> Decimal:
    if type(raw) is not str or not _DECIMAL.fullmatch(raw):
        raise ProbeUnsafe(f"{name} must be a positive exact decimal string")
    value = Decimal(raw)
    if value <= 0:
        raise ProbeUnsafe(f"{name} must be positive")
    return value


def _no_duplicates(pairs):
    value = {}
    for k, v in pairs:
        if k in value:
            raise ValueError("duplicate response key")
        value[k] = v
    return value


def assess_probe_read(*, resource: str, http_status: int,
                      response_bytes: bytes, max_bytes: int = 1_048_576) -> dict:
    """Validate the transport-independent outcome of a *read*.

    This never calls a venue. HTTP 200 alone does NOT prove a status
    mapping, a missing order, a fee schedule or settlement.
    """
    if resource not in {"BALANCES", "FEES", "ORDER_STATUS", "EXTERNAL_EXPOSURE"}:
        raise ProbeUnsafe("unsupported private read resource")
    if type(http_status) is not int or http_status < 100 or http_status > 599:
        raise ProbeUnsafe("invalid HTTP status")
    if type(max_bytes) is not int or not 256 <= max_bytes <= 4_194_304:
        raise ProbeUnsafe("invalid response bound")
    if type(response_bytes) is not bytes:
        raise ProbeUnsafe("response must be bounded bytes")
    result = {
        "resource": resource,
        "state": "UNKNOWN",
        "http_status": http_status,
        "body_sha256": hashlib.sha256(response_bytes).hexdigest()
            if len(response_bytes) <= max_bytes else None,
        "absent_proven": False,
        "method_certified": False,
        "funded_authority": False,
        "authority": "READ_ONLY_UNVERIFIED",
    }
    if http_status != 200 or not 1 <= len(response_bytes) <= max_bytes:
        return result
    try:
        payload = json.loads(
            response_bytes.decode("utf-8"), object_pairs_hook=_no_duplicates,
            parse_float=lambda _: (_ for _ in ()).throw(ValueError("floating venue amount")),
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite venue amount")),
        )
        if not isinstance(payload, dict) or payload.get("success") is not True:
            return result
        if resource == "BALANCES":
            parse_wallex_balances(payload)
        elif resource == "ORDER_STATUS":
            row = payload.get("result")
            if not isinstance(row, dict) or not isinstance(row.get("status"), str) \
                or not 1 <= len(row["status"]) <= 128:
                return result
        else:
            # Shape of fee/exposure contract remains unvalidated; do not
            # promote a nominal 200 into an accepted economic fact.
            return result
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return result
    return {**result, "state": "OBSERVED"}


_SCHEMA = """
CREATE TABLE probe_limits (
    id INTEGER PRIMARY KEY CHECK(id=1),
    quote_asset TEXT NOT NULL,
    total_loss_limit TEXT NOT NULL
);
CREATE TABLE probe_stages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    probe_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    worst_case_total_loss TEXT NOT NULL,
    venue_minimum_quote TEXT NOT NULL
);
CREATE TRIGGER probe_limits_no_update BEFORE UPDATE ON probe_limits
BEGIN SELECT RAISE(ABORT, 'probe budget is immutable'); END;
CREATE TRIGGER probe_limits_no_delete BEFORE DELETE ON probe_limits
BEGIN SELECT RAISE(ABORT, 'probe budget is immutable'); END;
CREATE TRIGGER probe_stages_no_update BEFORE UPDATE ON probe_stages
BEGIN SELECT RAISE(ABORT, 'probe stages are immutable'); END;
CREATE TRIGGER probe_stages_no_delete BEFORE DELETE ON probe_stages
BEGIN SELECT RAISE(ABORT, 'probe stages are immutable'); END;
PRAGMA user_version=1;
"""


class ProbeBudgetBook:
    """Durable offline reservations of the operator's total-loss envelope.

    No release path: after a staged probe, its full possible loss continues
    consuming the envelope. A new risk budget requires a separately controlled
    ledger, NOT a quiet reset or a venue-minimum override.
    """
    def __init__(self, path: Path | str, *, total_loss_limit: str, quote_asset: str):
        amount = _decimal(total_loss_limit, "total_loss_limit")
        if type(quote_asset) is not str or not _ASSET.fullmatch(quote_asset):
            raise ProbeUnsafe("invalid quote asset")
        path = Path(path)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ProbeUnsafe("probe ledger must be a regular unsymlinked file")
        self.conn = sqlite3.connect(path, timeout=5)
        try:
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.execute("PRAGMA journal_mode=WAL")
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if self.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE name IN ('probe_limits','probe_stages')"
                ).fetchone():
                    raise ProbeUnsafe("partial probe ledger schema")
                self.conn.executescript("BEGIN IMMEDIATE;" + _SCHEMA + "COMMIT;")
                self.conn.execute(
                    "INSERT INTO probe_limits(id,quote_asset,total_loss_limit) VALUES(1,?,?)",
                    (quote_asset, total_loss_limit),
                )
                self.conn.commit()
            elif version != 1:
                raise ProbeUnsafe("unsupported probe ledger schema")
            self._verify()
            row = self.conn.execute(
                "SELECT quote_asset,total_loss_limit FROM probe_limits WHERE id=1"
            ).fetchone()
            if not row or row[0] != quote_asset or _decimal(row[1], "recorded limit") != amount:
                raise ProbeUnsafe("probe total-loss budget is immutable")
            self.cap = amount
            self.quote_asset = quote_asset
        except Exception:
            self.conn.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def _verify(self):
        if self.conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ProbeUnsafe("probe ledger failed SQLite integrity")
        required = {
            "probe_limits_no_update", "probe_limits_no_delete",
            "probe_stages_no_update", "probe_stages_no_delete",
        }
        guards = {name for (name,) in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
        if not required.issubset(guards):
            raise ProbeUnsafe("probe ledger immutability guards absent")

    def proposals(self) -> list[dict]:
        self._verify()
        columns = ("probe_id", "kind", "symbol", "worst_case_total_loss", "venue_minimum_quote")
        return [dict(zip(columns, row)) for row in self.conn.execute(
            "SELECT " + ",".join(columns) + " FROM probe_stages ORDER BY seq"
        )]

    def remaining(self) -> str:
        with localcontext() as ctx:
            ctx.prec = 128
            spent = sum((_decimal(r["worst_case_total_loss"], "recorded budget")
                         for r in self.proposals()), Decimal(0))
            left = self.cap - spent
            if left < 0:
                raise ProbeUnsafe("budget ledger exceeds committed operator limit")
            return format(left, "f")

    def stage(self, *, probe_id: str, kind: str, symbol: str,
              worst_case_total_loss: str, venue_minimum_quote: str) -> dict:
        if type(probe_id) is not str or not _NAME.fullmatch(probe_id):
            raise ProbeUnsafe("unsafe probe ID")
        if type(kind) is not str or kind not in _PROBES:
            raise ProbeUnsafe("unknown probe kind")
        if type(symbol) is not str or not _SYMBOL.fullmatch(symbol):
            raise ProbeUnsafe("invalid instrument")
        if not symbol.endswith(self.quote_asset):
            raise ProbeUnsafe("instrument quote asset differs from probe budget unit")
        loss = _decimal(worst_case_total_loss, "worst_case_total_loss")
        minimum = _decimal(venue_minimum_quote, "venue_minimum_quote")
        if minimum > loss:
            raise ProbeUnsafe("venue minimum exceeds accepted per-probe loss")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._verify()
            if self.conn.execute("SELECT 1 FROM probe_stages WHERE probe_id=?", (probe_id,)).fetchone():
                raise ProbeUnsafe("duplicate probe ID")
            if loss > Decimal(self.remaining()):
                raise ProbeUnsafe("probe exceeds remaining budget")
            self.conn.execute(
                "INSERT INTO probe_stages(probe_id,kind,symbol,worst_case_total_loss,venue_minimum_quote) "
                "VALUES(?,?,?,?,?)",
                (probe_id, kind, symbol, worst_case_total_loss, venue_minimum_quote),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {
            "probe_id": probe_id, "kind": kind, "symbol": symbol,
            "max_full_loss_quote": worst_case_total_loss,
            "quote_asset": self.quote_asset, "remaining_after": self.remaining(),
            "state": "OFFLINE_REVIEW_ONLY", "order_submitted": False,
            "client_id": None, "funded_authority": False,
            "requires_independent_t2_consent": True,
        }
