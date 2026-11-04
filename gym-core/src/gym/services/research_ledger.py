"""Persistent paper research; nothing in this database grants execution authority."""
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal, localcontext
import json
from pathlib import Path
import re
import sqlite3

from ..domain.bars import BarSpec
from ..domain.market_models import decimal, fields, quote, rate
from ..domain.model import iso, parse_ts
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from ..adapters.run_store import save_run
from .paper import paper
from .session import ENGINE_VERSION


_SCHEMA = """
CREATE TABLE hypotheses(id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE shadows(id TEXT PRIMARY KEY, opened TEXT NOT NULL, closed TEXT);
CREATE TABLE jobs(id TEXT PRIMARY KEY, body TEXT NOT NULL, next_at TEXT NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1)));
CREATE TABLE reports(job_id TEXT NOT NULL REFERENCES jobs(id), due_at TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(job_id,due_at));
CREATE TABLE alerts(id TEXT PRIMARY KEY, body TEXT NOT NULL);
PRAGMA user_version=1;
"""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _id(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", value):
        raise ValueError("invalid research identifier")
    return value


def _result(**values):
    return {**values, "authority": "PAPER_ONLY", "funded_authority": False,
            "order_submitted": False, "venue_settled": False}


class ResearchLedger:
    def __init__(self, path, *, readonly=False):
        path = Path(path)
        self.path = path
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("research ledger must be a regular file")
        self.conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5, isolation_level=None) if readonly else sqlite3.connect(path, timeout=5, isolation_level=None)
        try:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0 and self.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
                raise ValueError("refusing an unversioned existing database")
            if readonly and version != 1:
                raise ValueError("research ledger is not initialized")
            if version not in (0, 1):
                raise ValueError("unsupported research ledger version")
            self.conn.execute("PRAGMA foreign_keys=ON")
            if readonly:
                self.conn.execute("PRAGMA query_only=ON")
            else:
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA synchronous=FULL")
            if version == 0:
                self.conn.executescript("BEGIN IMMEDIATE;" + _SCHEMA + "COMMIT;")
            elif version != 1:
                raise ValueError("unsupported research ledger version")
            if self.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("research ledger integrity check failed")
            required = {"hypotheses", "shadows", "jobs", "reports", "alerts"}
            tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != required:
                raise ValueError("unexpected research ledger schema")
        except BaseException:
            self.conn.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    @contextmanager
    def _write(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def register(self, request):
        fields(request, "symbol strategy params")
        if type(request["symbol"]) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", request["symbol"]):
            raise ValueError("invalid hypothesis symbol")
        strategy = create_strategy(request["strategy"], request["params"])
        body = {"symbol": request["symbol"], "strategy": strategy.name,
                "params": strategy.params, "config_hash": strategy.config_hash,
                "engine": ENGINE_VERSION, "version": 1}
        key, encoded = digest(body), _json(body)
        with self._write():
            self.conn.execute("INSERT OR IGNORE INTO hypotheses VALUES(?,?)", (key, encoded))
            if self.conn.execute("SELECT body FROM hypotheses WHERE id=?", (key,)).fetchone()[0] != encoded:
                raise ValueError("conflicting hypothesis digest")
        return _result(hypothesis_id=key, hypothesis=body)

    def _hypothesis(self, key):
        row = self.conn.execute("SELECT body FROM hypotheses WHERE id=?", (_id(key),)).fetchone()
        if row is None:
            raise ValueError("unknown registered hypothesis")
        body = json.loads(row[0])
        if digest(body) != key:
            raise ValueError("hypothesis digest mismatch")
        strategy = create_strategy(body["strategy"], body["params"])
        if body["engine"] != ENGINE_VERSION or body["config_hash"] != strategy.config_hash:
            raise ValueError("registered hypothesis version is unavailable")
        return body

    def open_shadow(self, request):
        fields(request, "position_id hypothesis_id quote gross_quantity fee_rate")
        key = _id(request["position_id"])
        hypothesis = self._hypothesis(request["hypothesis_id"])
        at, _, ask, state = quote(request["quote"])
        if state != "OPEN":
            raise ValueError("cannot open a paper shadow during a closure")
        quantity = decimal(request["gross_quantity"], "quantity", positive=True)
        fee = rate(request["fee_rate"], "fee_rate")
        with localcontext() as ctx:
            ctx.prec = 256
            body = {"hypothesis_id": request["hypothesis_id"], "symbol": hypothesis["symbol"],
                    "at": iso(at), "quote": request["quote"], "gross_quantity": format(quantity, "f"),
                    "net_quantity": format(quantity * (1 - fee), "f"), "basis_quote": format(quantity * ask, "f"),
                    "fee_rate": format(fee, "f"), "source": "OFFLINE_PAPER_INPUT",
                    "fee_assumption": "fee in received asset on each side"}
        encoded = _json(body)
        with self._write():
            self.conn.execute("INSERT OR IGNORE INTO shadows(id,opened) VALUES(?,?)", (key, encoded))
            if self.conn.execute("SELECT opened FROM shadows WHERE id=?", (key,)).fetchone()[0] != encoded:
                raise ValueError("conflicting shadow position ID")
        return self.shadow(key)

    def shadow(self, key):
        row = self.conn.execute("SELECT opened,closed FROM shadows WHERE id=?", (_id(key),)).fetchone()
        if row is None:
            raise ValueError("unknown paper shadow position")
        return _result(position_id=key, state="SHADOW_CLOSED" if row[1] else "SHADOW_OPEN",
                       opened=json.loads(row[0]), closed=json.loads(row[1]) if row[1] else None)

    def settle_shadow(self, request):
        fields(request, "position_id quote")
        key = _id(request["position_id"])
        at, bid, _, state = quote(request["quote"])
        with self._write():
            position = self.shadow(key)
            opening = position["opened"]
            if at < parse_ts(opening["at"]):
                raise ValueError("settlement quote precedes the shadow opening")
            if position["closed"]:
                if position["closed"]["quote"] != request["quote"]:
                    raise ValueError("conflicting final shadow observation")
                return position
            if state == "CLOSED":
                return _result(**{k: v for k, v in position.items() if k != "state"}, state="PENDING_REOPEN")
            with localcontext() as ctx:
                ctx.prec = 256
                quantity, basis = Decimal(opening["net_quantity"]), Decimal(opening["basis_quote"])
                if not quantity.is_finite() or not basis.is_finite() or quantity <= 0 or basis <= 0:
                    raise ValueError("invalid stored shadow amounts")
                proceeds = quantity * bid * (1 - rate(opening["fee_rate"]))
                closed = {"at": iso(at), "quote": request["quote"], "proceeds_quote": format(proceeds, "f"),
                          "net_quote": format(proceeds - basis, "f")}
            self.conn.execute("UPDATE shadows SET closed=? WHERE id=?", (_json(closed), key))
        return self.shadow(key)

    def schedule(self, request):
        fields(request, "hypothesis_id every_seconds lookback_seconds first_at resolution cash fee_rate")
        self._hypothesis(request["hypothesis_id"])
        for name, maximum in (("every_seconds", 86400), ("lookback_seconds", 2678400)):
            if type(request[name]) is not int or not 60 <= request[name] <= maximum:
                raise ValueError(f"invalid {name}")
        if type(request["resolution"]) is not str or type(request["first_at"]) is not str:
            raise ValueError("resolution and first_at must be strings")
        BarSpec(request["resolution"])
        decimal(request["cash"], "cash", positive=True)
        rate(request["fee_rate"], "fee_rate")
        body = {**request, "first_at": iso(parse_ts(request["first_at"]))}
        key, encoded = digest(body), _json(body)
        with self._write():
            self.conn.execute("INSERT OR IGNORE INTO jobs VALUES(?,?,?,1)", (key, encoded, body["first_at"]))
            if self.conn.execute("SELECT body FROM jobs WHERE id=?", (key,)).fetchone()[0] != encoded:
                raise ValueError("conflicting research job digest")
        return _result(job_id=key, next_at=body["first_at"])

    def pause(self, key):
        with self._write():
            if self.conn.execute("UPDATE jobs SET enabled=0 WHERE id=?", (_id(key),)).rowcount != 1:
                raise ValueError("unknown research job")
        return _result(job_id=key, enabled=False)

    def resume(self, key):
        """Resume at the committed due time, retaining reports and retry deadlines."""
        with self._write():
            if self.conn.execute("UPDATE jobs SET enabled=1 WHERE id=?", (_id(key),)).rowcount != 1:
                raise ValueError("unknown research job")
        return _result(job_id=key, enabled=True)

    def run_due(self, db, at, *, store="live", limit=10):
        now = parse_ts(at)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("research tick limit must be 1..100")
        if store not in ("live", "demo") or db.c.in_transaction:
            raise ValueError("research tick requires a separate market read snapshot")
        completed, failed = [], []
        for _ in range(limit):
            with self._write():
                row = self.conn.execute("""SELECT j.id,j.body,j.next_at,r.body FROM jobs j
                    LEFT JOIN reports r ON r.job_id=j.id AND r.due_at=j.next_at
                    WHERE j.enabled=1 AND j.next_at<=? AND
                    (r.body IS NULL OR COALESCE(json_extract(r.body,'$.retry_at'),'')<=?)
                    ORDER BY j.next_at,j.id LIMIT 1""", (iso(now), iso(now))).fetchone()
                if row is None:
                    break
                key, encoded, due, previous = row
                previous = json.loads(previous) if previous else None
                if previous is not None and previous.get("status") != "FAILED":
                    raise ValueError("research clock points to an already completed report")
                job = json.loads(encoded)
                if digest(job) != key:
                    raise ValueError("research job digest mismatch")
                end = parse_ts(due)
                try:
                    hypothesis = self._hypothesis(job["hypothesis_id"])
                    strategy = create_strategy(hypothesis["strategy"], hypothesis["params"])
                    db.c.execute("BEGIN")
                    try:
                        result = paper(db, hypothesis["symbol"], end - timedelta(seconds=job["lookback_seconds"]), end,
                                       strategy_id=hypothesis["strategy"], params=hypothesis["params"],
                                       resolution=job["resolution"], cash=decimal(job["cash"], "cash", positive=True),
                                       cost=CostModel(fee_rate=rate(job["fee_rate"])), store=store,
                                       subscriptions=getattr(strategy, "required_resolutions", ()),
                                       reference_symbol=getattr(strategy, "reference_symbol", None))
                        # Publish immutable results before advancing the durable job clock.
                        save_run(result, self.path.parent / "runs")
                    finally:
                        db.c.rollback()
                except ValueError as error:
                    attempt = 1 + (previous["attempts"] if previous else 0)
                    alert = _result(kind="RESEARCH_FAILED", job_id=key, due_at=due, status="FAILED",
                                    attempts=attempt, error_type=type(error).__name__,
                                    retry_at=iso(now + timedelta(seconds=job["every_seconds"])),
                                    message="Paper replay failed; no result or proposal was produced. Other eligible jobs may continue.")
                    self.conn.execute("INSERT INTO reports VALUES(?,?,?) ON CONFLICT(job_id,due_at) DO UPDATE SET body=excluded.body", (key, due, _json(alert)))
                    self.conn.execute("INSERT INTO alerts VALUES(?,?)", (digest(alert), _json(alert)))
                    failed.append(alert)
                    continue
                self.conn.execute("INSERT INTO reports VALUES(?,?,?) ON CONFLICT(job_id,due_at) DO UPDATE SET body=excluded.body", (key, due, _json(result)))
                alert = _result(kind="RESEARCH_COMPLETED", job_id=key, due_at=due, run_id=result["run_id"],
                                message="Paper replay completed; review matched baselines and warnings. This is not an execution proposal.")
                self.conn.execute("INSERT INTO alerts VALUES(?,?)", (digest(alert), _json(alert)))
                self.conn.execute("UPDATE jobs SET next_at=? WHERE id=?", (iso(end + timedelta(seconds=job["every_seconds"])), key))
                completed.append(alert)
        return _result(completed=completed, failed=failed)

    def overview(self):
        jobs = []
        for key, body, at, enabled, due, status, run_id, retry, attempts in self.conn.execute("""
            SELECT j.id,j.body,j.next_at,j.enabled,r.due_at,json_extract(r.body,'$.status'),
                   json_extract(r.body,'$.run_id'),json_extract(r.body,'$.retry_at'),json_extract(r.body,'$.attempts')
            FROM jobs j LEFT JOIN reports r ON r.job_id=j.id AND r.due_at=(
                SELECT MAX(due_at) FROM reports WHERE job_id=j.id)
            ORDER BY j.id LIMIT 200"""):
            last = None if due is None else {"due_at": due, "status": status or "COMPLETED",
                                             "run_id": run_id, "retry_at": retry, "attempts": attempts}
            jobs.append({"id": key, "next_at": at, "enabled": bool(enabled),
                         **json.loads(body), "last_report": last})
        return _result(hypotheses=[{"id": key, **json.loads(body)} for key, body in self.conn.execute("SELECT id,body FROM hypotheses ORDER BY id LIMIT 200")],
                       shadows=[self.shadow(row[0]) for row in self.conn.execute("SELECT id FROM shadows ORDER BY id LIMIT 200")],
                       jobs=jobs,
                       alerts=[json.loads(row[0]) for row in self.conn.execute("SELECT body FROM alerts ORDER BY rowid DESC LIMIT 200")])
