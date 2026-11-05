"""Durable outcome availability and consume-once preregistered paper evaluations."""
from contextlib import contextmanager
from datetime import timedelta
from decimal import localcontext
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from ..adapters.run_store import save_run
from ..domain.bars import BarSpec
from ..domain.market_models import decimal, fields, rate
from ..domain.model import iso, parse_ts
from ..domain.periods import instant
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .collector import now_utc
from .paper import paper
from .reports import economic_report
from .research_grounding import MetricUnavailable, _number, resolve_run_metric


def _engine_digest():
    root = Path(__file__).resolve().parents[1]
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts})


class ResearchProtocol:
    def __init__(self, root, *, store="live", clock=now_utc):
        self.root, self.store, self.clock = Path(root), store, clock
        if store not in ("live", "demo"):
            raise ValueError("invalid research store")
        path = self.root / "research_protocol.sqlite3"
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("research protocol requires a regular file")
        self.conn = sqlite3.connect(path, timeout=5, isolation_level=None)
        try:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version == 0 and tables:
                raise ValueError("refusing an existing unversioned protocol database")
            if version not in (0, 1):
                raise ValueError("unsupported protocol schema")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            if not version:
                self.conn.executescript("""BEGIN IMMEDIATE;
                    CREATE TABLE evaluations(id TEXT PRIMARY KEY, body TEXT NOT NULL, registered_at TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN ('REGISTERED','CONSUMED','EVALUATED','INCOMPLETE','FAILED')), result TEXT);
                    CREATE TABLE outcomes(run_id TEXT PRIMARY KEY, body TEXT NOT NULL, resolved_at TEXT);
                    CREATE TABLE observations(id TEXT PRIMARY KEY,body TEXT NOT NULL,known_at TEXT NOT NULL);
                    CREATE TRIGGER retain_observation BEFORE DELETE ON observations
                        BEGIN SELECT RAISE(ABORT,'retain observation'); END;
                    CREATE TRIGGER frozen_observation BEFORE UPDATE ON observations
                        BEGIN SELECT RAISE(ABORT,'immutable observation'); END;
                    CREATE TRIGGER frozen_evaluation BEFORE UPDATE OF body,registered_at ON evaluations
                        BEGIN SELECT RAISE(ABORT,'frozen evaluation'); END;
                    CREATE TRIGGER retain_evaluation BEFORE DELETE ON evaluations
                        BEGIN SELECT RAISE(ABORT,'retain evaluation'); END;
                    CREATE TRIGGER retain_outcome BEFORE DELETE ON outcomes
                        BEGIN SELECT RAISE(ABORT,'retain outcome'); END;
                    CREATE TRIGGER resolved_outcome BEFORE UPDATE ON outcomes WHEN OLD.resolved_at IS NOT NULL
                        BEGIN SELECT RAISE(ABORT,'resolved outcome is immutable'); END;
                    PRAGMA user_version=1; COMMIT;""")
            tables = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            triggers = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
            if tables != {"evaluations", "outcomes", "observations"} or triggers != {"frozen_evaluation", "retain_evaluation", "retain_outcome", "resolved_outcome", "retain_observation", "frozen_observation"}:
                raise ValueError("invalid protocol schema")
            if self.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("protocol integrity check failed")
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
        fields(request, "symbol strategy params selection_end test_from test_to resolution cash fee_rate")
        strategy = create_strategy(request["strategy"], request["params"])
        if type(request["symbol"]) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", request["symbol"]):
            raise ValueError("invalid evaluation symbol")
        if any(type(request[key]) is not str for key in ("selection_end", "test_from", "test_to", "resolution")):
            raise ValueError("evaluation timestamps and resolution must be strings")
        selected, start, end = (parse_ts(request[key]) for key in ("selection_end", "test_from", "test_to"))
        now = instant(self.clock())
        if not selected <= now < start < end or end - start > timedelta(days=31):
            raise ValueError("preregister a future, disjoint window of at most 31 days after selection")
        spec = BarSpec(request["resolution"])
        if request["resolution"] == "session" or start - selected < spec.step:
            raise ValueError("final evaluation requires fixed bars and at least one-period purge")
        decimal(request["cash"], "cash", positive=True)
        rate(request["fee_rate"], "fee_rate")
        body = {**request, "params": strategy.params, "config_hash": strategy.config_hash,
                "selection_end": iso(selected), "test_from": iso(start), "test_to": iso(end),
                "engine_digest": _engine_digest(), "store": self.store}
        key = digest(body)
        with self._write():
            existing = self.conn.execute("SELECT 1 FROM evaluations WHERE id=?", (key,)).fetchone()
            if not existing:
                overlap = self.conn.execute("""SELECT 1 FROM evaluations
                    WHERE json_extract(body,'$.symbol')=? AND json_extract(body,'$.test_from')<?
                    AND json_extract(body,'$.test_to')>? LIMIT 1""", (body["symbol"], body["test_to"], body["test_from"])).fetchone()
                if overlap:
                    raise ValueError("evaluation overlaps a previously registered window")
                self.conn.execute("INSERT INTO evaluations VALUES(?,?,?,'REGISTERED',NULL)", (key, json.dumps(body), iso(now)))
        return self.evaluation(key)

    def evaluation(self, key):
        if type(key) is not str or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("invalid evaluation ID")
        row = self.conn.execute("SELECT body,registered_at,state,result FROM evaluations WHERE id=?", (key,)).fetchone()
        if row is None:
            raise ValueError("unknown evaluation")
        body, registered, state, result = row
        if digest(json.loads(body)) != key or json.loads(body)["store"] != self.store:
            raise ValueError("evaluation identity mismatch")
        return {"evaluation_id": key, "registered_at": registered, "state": state, "configuration": json.loads(body),
                "result": json.loads(result) if result else None, "authority": "PAPER_ONLY", "funded_authority": False,
                "independent_final_evidence": False,
                "limitation": "Enforces one attempt through this ledger. It cannot prevent direct access to raw data, "
                              "clock manipulation, another ledger or a malicious filesystem writer. No promotion is authorized."}

    def consume(self, key, db):
        with self._write():
            record = self.evaluation(key)
            body = record["configuration"]
            if record["state"] != "REGISTERED":
                raise ValueError("evaluation has already been consumed; failures cannot be retried")
            if instant(self.clock()) < parse_ts(body["test_to"]):
                raise ValueError("final window is not complete")
            if body["engine_digest"] != _engine_digest():
                raise ValueError("research engine changed after preregistration")
            strategy = create_strategy(body["strategy"], body["params"])
            if strategy.config_hash != body["config_hash"]:
                raise ValueError("strategy changed after preregistration")
            self.conn.execute("UPDATE evaluations SET state='CONSUMED' WHERE id=?", (key,))
        # Commit consumption before reading holdout observations; a crash cannot enable retry.
        try:
            if db.c.in_transaction:
                raise ValueError("final evaluation requires its own market snapshot")
            db.c.execute("BEGIN")
            try:
                result = paper(db, body["symbol"], parse_ts(body["test_from"]), parse_ts(body["test_to"]),
                    resolution=body["resolution"], cash=decimal(body["cash"], "cash", positive=True),
                    cost=CostModel(fee_rate=rate(body["fee_rate"], "fee_rate")), store=self.store,
                    strategy_id=body["strategy"], params=body["params"],
                    subscriptions=getattr(strategy, "required_resolutions", ()), reference_symbol=getattr(strategy, "reference_symbol", None))
                save_run(result, self.root / "runs")
            finally:
                db.c.rollback()
            status = "EVALUATED" if economic_report(result)["valuation"]["status"] == "CURRENT" else "INCOMPLETE"
            result = {"run_id": result["run_id"], "outputs_digest": result["outputs_digest"], "status": status}
        except Exception as error:
            with self._write():
                self.conn.execute("UPDATE evaluations SET state='FAILED',result=? WHERE id=?", (json.dumps({"error_type": type(error).__name__}), key))
            raise
        with self._write():
            self.conn.execute("UPDATE evaluations SET state=?,result=? WHERE id=?", (status, json.dumps(result), key))
        return self.evaluation(key)

    def record_outcome(self, key):
        _, _, source, _ = resolve_run_metric(self.root / "runs", {"run_id": key, "metric": "starting_cash_quote"}, store=self.store)
        now = instant(self.clock())
        body = {"run_id": key, "outputs_digest": source["outputs_digest"], "period": source["period"], "status": "PENDING",
                "lesson": None, "net_quote": None, "cash_benchmark_excess_quote": None, "store": self.store}
        resolved = None
        if parse_ts(source["period"]["to"]) <= now and source["valuation"]["status"] == "CURRENT":
            try:
                net = resolve_run_metric(self.root / "runs", {"run_id": key, "metric": "net_quote"}, store=self.store)[0]
                benchmark = resolve_run_metric(self.root / "runs", {"run_id": key, "metric": "hold_cash_net_quote"}, store=self.store)[0]
            except MetricUnavailable:
                pass
            else:
                with localcontext() as context:
                    context.prec = 160
                    excess = net - benchmark
                body.update(status="RESOLVED", lesson="OUTPERFORMED_CASH" if excess > 0 else "UNDERPERFORMED_CASH" if excess < 0 else "MATCHED_CASH",
                            net_quote=str(net), cash_benchmark_excess_quote=str(excess))
                resolved = iso(now)
        with self._write():
            previous = self.conn.execute("SELECT body,resolved_at FROM outcomes WHERE run_id=?", (key,)).fetchone()
            if previous:
                if json.loads(previous[0])["outputs_digest"] != source["outputs_digest"]:
                    raise ValueError("outcome artifact changed")
                if previous[1] is not None:
                    return {**json.loads(previous[0]), "resolved_at": previous[1]}
            self.conn.execute("INSERT INTO outcomes VALUES(?,?,?) ON CONFLICT(run_id) DO UPDATE SET body=excluded.body,resolved_at=excluded.resolved_at",
                              (key, json.dumps(body), resolved))
        return {**body, "resolved_at": resolved}

    def outcomes(self, as_of):
        cutoff = instant(as_of)
        if cutoff > instant(self.clock()):
            raise ValueError("outcome cutoff is in the future")
        rows = self.conn.execute("SELECT body,resolved_at FROM outcomes WHERE resolved_at<=? AND json_extract(body,'$.store')=? ORDER BY resolved_at,run_id LIMIT 200", (iso(cutoff), self.store))
        return {"authority": "PAPER_ONLY", "funded_authority": False, "as_of": iso(cutoff),
                "outcomes": [{**json.loads(body), "resolved_at": at} for body, at in rows],
                "limitation": "Only resolved numeric outcomes known by this cutoff; no hypothetical lessons or model reasoning."}

    def ingest_observations(self, request):
        fields(request, "observations")
        rows = request["observations"]
        if type(rows) is not list or not 1 <= len(rows) <= 100:
            raise ValueError("import requires 1..100 observations")
        now, prepared = instant(self.clock()), []
        for row in rows:
            names = "source_id series subject kind unit value published_at revision_at"
            optional = ("measured_at", "confirmed_at", "unit_epoch", "components")
            fields(row, names + " " + " ".join(k for k in optional if type(row) is dict and k in row))
            for key in ("source_id", "series", "subject", "unit", "kind"):
                if type(row[key]) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/%-]{0,95}", row[key]):
                    raise ValueError("observation labels must be bounded identifiers")
            if row["kind"] not in ("NEWS", "FUNDAMENTAL", "MACRO", "SOCIAL", "WHALE", "FUNDING", "OPEN_INTEREST"):
                raise ValueError("unsupported observation kind")
            published = parse_ts(row["published_at"]) if type(row["published_at"]) is str else None
            revised = parse_ts(row["revision_at"]) if type(row["revision_at"]) is str else None
            if published is None or (row["revision_at"] is not None and revised is None) or (revised and revised < published):
                raise ValueError("invalid publication/revision timestamps")
            confirmed = None
            if "confirmed_at" in row:
                confirmed = parse_ts(row["confirmed_at"]) if type(row["confirmed_at"]) is str else None
                if confirmed is None or confirmed < (revised or published):
                    raise ValueError("confirmation must follow the publication/revision")
                row = {**row, "confirmed_at": iso(confirmed)}
            if "unit_epoch" in row and (type(row["unit_epoch"]) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", row["unit_epoch"])):
                raise ValueError("unit epoch must be an explicit bounded identifier")
            if "measured_at" in row:
                measured = parse_ts(row["measured_at"]) if type(row["measured_at"]) is str else None
                if measured is None or measured > published or row["kind"] == "NEWS":
                    raise ValueError("numeric measurement must precede publication")
                row = {**row, "measured_at": iso(measured)}
            if row["kind"] == "NEWS":
                if row["unit"] != "text" or type(row["value"]) is not str or not 1 <= len(row["value"]) <= 2000:
                    raise ValueError("news requires bounded text with unit=text")
            else:
                _number(row["value"])
            if "components" in row:
                components = row["components"]
                if row["kind"] == "NEWS" or type(components) is not list or not 1 <= len(components) <= 32:
                    raise ValueError("numeric component form requires 1..32 additive rows")
                labels = set()
                with localcontext() as context:
                    context.prec = 160
                    total = 0
                    for component in components:
                        fields(component, "label value")
                        label = component["label"]
                        if type(label) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", label) or label in labels:
                            raise ValueError("component labels must be distinct bounded identifiers")
                        labels.add(label)
                        total += _number(component["value"])
                    if total != _number(row["value"]):
                        raise ValueError("components must reconcile exactly to the numeric value in its declared unit")
            body = {**row, "published_at": iso(published), "revision_at": iso(revised), "store": self.store,
                    "source_authenticity_verified": False, "rights_verified": False, "origin": "USER_SUPPLIED_OBSERVATION"}
            prepared.append((digest(body), json.dumps(body), iso(max(now, published, revised or published, confirmed or published))))
        with self._write():
            for key, body, known in prepared:
                self.conn.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?)", (key, body, known))
        return {"authority": "PAPER_ONLY", "funded_authority": False, "imported_ids": [key for key, _, _ in prepared],
                "limitation": "Native receipt time prevents backdating knowledge. User-supplied source labels, rights and values remain unverified."}

    def observation(self, reference, as_of):
        """Latest known value for one exact source/series/subject/kind/unit reference."""
        fields(reference, "source_id series subject kind unit")
        for value in reference.values():
            if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/%-]{0,95}", value):
                raise ValueError("invalid observation reference")
        cutoff = instant(as_of)
        if cutoff > instant(self.clock()):
            raise ValueError("observation cutoff is in the future")
        row = self.conn.execute("""SELECT id,body,known_at FROM observations WHERE known_at<=?
            AND json_extract(body,'$.store')=? AND json_extract(body,'$.source_id')=?
            AND json_extract(body,'$.series')=? AND json_extract(body,'$.subject')=?
            AND json_extract(body,'$.kind')=? AND json_extract(body,'$.unit')=?
            ORDER BY coalesce(json_extract(body,'$.measured_at'),json_extract(body,'$.published_at')) DESC,
            json_extract(body,'$.published_at') DESC,
            coalesce(json_extract(body,'$.revision_at'),json_extract(body,'$.published_at')) DESC,
            known_at DESC,id DESC LIMIT 1""",
            (iso(cutoff), self.store, *(reference[k] for k in ("source_id", "series", "subject", "kind", "unit")))).fetchone()
        if row is None:
            return None
        key, raw, known = row
        body = json.loads(raw)
        if digest(body) != key:
            raise ValueError("observation digest mismatch")
        return {**body, "observation_id": key, "known_at": known}

    def screen(self, request):
        fields(request, "source_id series kind unit as_of descending limit max_age_seconds")
        cutoff = parse_ts(request["as_of"]) if type(request["as_of"]) is str else None
        if cutoff is None or cutoff > instant(self.clock()):
            raise ValueError("screen cutoff must be a known zoned instant")
        if type(request["limit"]) is not int or not 1 <= request["limit"] <= 100 or type(request["descending"]) is not bool:
            raise ValueError("screen requires a limit of 1..100 and boolean direction")
        if type(request["max_age_seconds"]) is not int or not 1 <= request["max_age_seconds"] <= 2678400:
            raise ValueError("screen freshness must be 1 second..31 days")
        for name in ("source_id", "series", "kind", "unit"):
            if type(request[name]) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/%-]{0,95}", request[name]):
                raise ValueError("invalid screen label")
        rows = self.conn.execute("""SELECT id,body,known_at FROM observations WHERE known_at<=?
            AND json_extract(body,'$.store')=? AND json_extract(body,'$.source_id')=?
            AND json_extract(body,'$.series')=? AND json_extract(body,'$.kind')=? AND json_extract(body,'$.unit')=?
            ORDER BY known_at,id LIMIT 2001""", (iso(cutoff), self.store, *(request[k] for k in ("source_id", "series", "kind", "unit")))).fetchall()
        if len(rows) > 2000:
            raise ValueError("screen exceeds 2000 matching observations")
        latest = {}
        for key, raw, known in rows:
            body = json.loads(raw)
            if digest(body) != key:
                raise ValueError("observation digest mismatch")
            subject = body["subject"]
            vintage = (body["published_at"], body["revision_at"] or body["published_at"], known, key)
            if subject not in latest or vintage > latest[subject][0]:
                latest[subject] = vintage, {**body, "observation_id": key, "known_at": known}
        eligible = [body for _, body in latest.values()
                    if (cutoff - parse_ts(body["published_at"])).total_seconds() <= request["max_age_seconds"]]
        numeric = request["kind"] != "NEWS"
        ranked = sorted(eligible, key=lambda row: (_number(row["value"]) if numeric else row["published_at"], row["subject"]), reverse=request["descending"])
        return {"authority": "PAPER_ONLY", "funded_authority": False, "as_of": iso(cutoff),
                "matching_observations": len(rows), "subjects": len(latest), "stale_subjects": len(latest) - len(eligible),
                "rows": ranked[:request["limit"]], "source_authenticity_verified": False,
                "ranking": "NUMERIC_VALUE" if numeric else "PUBLICATION_TIME",
                "limitation": "Ranks one supplied source/series/kind/unit using the latest known vintage per subject. "
                              "Missing, future and stale observations are not scored or synthesized; no trade is recommended."}
