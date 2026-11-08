"""Append-only local experiment/attempt evidence; never a selection or funding gate."""
import json
import re
import sqlite3
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from ..adapters.run_store import load_verified_run, save_run
from ..domain.bars import BarSpec
from ..domain.market_models import decimal, fields, instant, rate
from ..domain.model import iso
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .collector import now_utc
from .data_portal import DataPortal
from .paper import PaperDataUnavailable, paper
from .process_owner import process_status
from .research_protocol import ResearchProtocol, _engine_digest


class ExperimentRegistry:
    def __init__(self, root, *, store):
        self.root, self.store = Path(root), store
        if store not in ("live", "demo"):
            raise ValueError("invalid experiment store")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "experiments.sqlite3"
        if path.is_symlink():
            raise ValueError("experiment store must not be a link")
        self.conn = sqlite3.connect(path, timeout=5, isolation_level=None)
        try:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version not in (0, 1) or (version == 0 and tables):
                raise ValueError("unsupported experiment store")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            if not version:
                self.conn.executescript("""BEGIN IMMEDIATE;
                    CREATE TABLE events(seq INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,parent TEXT,body TEXT NOT NULL);
                    CREATE TRIGGER frozen_event BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable event'); END;
                    CREATE TRIGGER retain_event BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'retain event'); END;
                    PRAGMA user_version=1; COMMIT;""")
            if {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} != {"events"}:
                raise ValueError("invalid experiment schema")
            if {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")} != {"frozen_event", "retain_event"}:
                raise ValueError("invalid experiment retention triggers")
            if self.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("experiment integrity check failed")
        except BaseException:
            self.conn.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def append(self, kind, parent, value):
        body = {"kind": kind, "parent": parent, "store": self.store, "recorded_at": iso(now_utc()), **value}
        key = digest(body)
        self.conn.execute("INSERT INTO events(id,kind,parent,body) VALUES(?,?,?,?)", (key, kind, parent, json.dumps(body, default=str, allow_nan=False)))
        return {"id": key, **body}

    def read(self, key):
        if type(key) is not str or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("invalid registry ID")
        row = self.conn.execute("SELECT body FROM events WHERE id=?", (key,)).fetchone()
        if not row:
            raise ValueError("unknown registry ID")
        body = json.loads(row[0])
        if digest(body) != key or body["store"] != self.store:
            raise ValueError("registry digest/store mismatch")
        children = [self.read_record(r[0], r[1]) for r in self.conn.execute("SELECT id,body FROM events WHERE parent=? ORDER BY seq LIMIT 500", (key,))]
        return {"id": key, **body, "events": children}

    def read_record(self, key, encoded):
        body = json.loads(encoded)
        if digest(body) != key or body["store"] != self.store:
            raise ValueError("registry digest/store mismatch")
        return {"id": key, **body}

    def listing(self):
        return {"schema": "experiment-registry/1", "records": [self.read(r[0]) for r in self.conn.execute(
            "SELECT id FROM events WHERE kind='EXPERIMENT' AND json_extract(body,'$.store')=? ORDER BY seq DESC LIMIT 50", (self.store,))],
            "funded_authority": False, "independent_custody": False}

    def progress(self, request):
        fields(request, "limit")
        limit = request["limit"]
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("progress sample limit must be 1..100")
        self.conn.execute("BEGIN")
        try:
            through = self.conn.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE json_extract(body,'$.store')=?", (self.store,)).fetchone()[0]
            counts = dict(self.conn.execute("SELECT kind,COUNT(*) FROM events WHERE seq<=? AND json_extract(body,'$.store')=? GROUP BY kind", (through, self.store)))
            states = dict(self.conn.execute("""WITH latest AS (
                SELECT MAX(seq) AS seq FROM events WHERE kind='RESULT' AND seq<=? AND json_extract(body,'$.store')=?
                GROUP BY json_extract(body,'$.attempt_id'))
                SELECT json_extract(e.body,'$.state'),COUNT(*) FROM events e JOIN latest l ON e.seq=l.seq
                GROUP BY json_extract(e.body,'$.state')""", (through, self.store)))
            rows = self.conn.execute("SELECT id,body FROM events WHERE kind='RESULT' AND seq<=? AND json_extract(body,'$.store')=? ORDER BY seq DESC LIMIT ?", (through, self.store, limit)).fetchall()
            samples, ready, traded, unavailable = [], 0, 0, 0
            for key, encoded in rows:
                receipt = self.read_record(key, encoded)
                run_id = receipt.get("run_id")
                row = {"attempt_id": receipt["attempt_id"], "state": receipt["state"], "run_id": run_id, "reason": receipt.get("reason")}
                if run_id:
                    try:
                        out = load_verified_run(self.root / "runs", run_id, store=self.store)
                        if out["outputs_digest"] != receipt.get("outputs_digest"):
                            raise ValueError("result receipt and saved run differ")
                        result = out["result"]
                        is_ready = result.get("session", {}).get("running_at") is not None
                        fills = result.get("fills", 0)
                        row.update(verification="VERIFIED_NATIVE", symbol=out["inputs"]["symbol"], strategy=out["inputs"]["strategy"],
                                   ready=is_ready, fills=fills, net_quote=result.get("end", {}).get("net"), quote=result.get("quote"))
                        ready += is_ready
                        traded += fills > 0
                    except (ValueError, OSError):
                        row["verification"] = "UNAVAILABLE_OR_CHANGED"
                        unavailable += 1
                samples.append(row)
            at = self.conn.execute("SELECT json_extract(body,'$.recorded_at') FROM events WHERE seq=?", (through,)).fetchone()
            return {"schema": "campaign-progress/1", "store": self.store, "as_of": iso(now_utc()), "through": through,
                    "last_recorded_progress": at[0] if at else None, "defined_experiments": counts.get("EXPERIMENT", 0),
                    "registered_attempts": counts.get("ATTEMPT", 0), "terminal_states": states,
                    "completed": states.get("COMPLETED", 0), "unreported_attempts": max(0, counts.get("ATTEMPT", 0) - sum(states.values())),
                    "verified_sample": {"results_sampled": len(samples), "ready_runs": ready, "traded_runs": traded, "unavailable_runs": unavailable, "rows": samples},
                    "process_liveness": "UNKNOWN", "processes": process_status(self.root, store=self.store), "funded_authority": False,
                    "scope": "Journal-wide counts retain repeated trials and failures. Readiness/trades are verified only for the bounded newest result sample, not extrapolated to the campaign. Saved RUNNING/progress timestamps do not prove a process is alive. External/frozen campaign definitions not registered here are outside these counts."}
        finally:
            self.conn.rollback()

    def page(self, request):
        fields(request, "kind parent after through limit")
        kind, parent = request["kind"], request["parent"]
        if kind not in (None, "EXPERIMENT", "ATTEMPT", "RESULT", "SELECTION", "WALK_FORWARD_REPORT", "EVIDENCE_PACKET", "RESEARCH_NOTES", "REPLAY_ANNOTATION", "REPLAY_CHECKPOINT", "PORTFOLIO_CHECKPOINT"):
            raise ValueError("invalid registry event kind")
        if parent is not None and (type(parent) is not str or not 1 <= len(parent) <= 160):
            raise ValueError("invalid registry parent")
        after, through, limit = request["after"], request["through"], request["limit"]
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("registry page requires after >= 0 and limit 1..100")
        if through is not None and (type(through) is not int or through < after):
            raise ValueError("invalid registry snapshot cursor")
        self.conn.execute("BEGIN")
        try:
            maximum = self.conn.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
            through = maximum if through is None else through
            if through > maximum or after > through:
                raise ValueError("registry snapshot cursor is beyond recorded events")
            rows = self.conn.execute("""SELECT seq,id,body FROM events WHERE seq>? AND seq<=?
                AND json_extract(body,'$.store')=? AND (? IS NULL OR kind=?) AND (? IS NULL OR parent=?)
                ORDER BY seq LIMIT ?""", (after, through, self.store, kind, kind, parent, parent, limit + 1)).fetchall()
            events, size = [], 0
            for seq, key, encoded in rows[:limit]:
                record = {"seq": seq, **self.read_record(key, encoded)}
                used = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
                if size + used > 262144:
                    if not events:
                        raise ValueError("single registry event exceeds page byte budget; inspect its saved ID")
                    break
                events.append(record)
                size += used
            more = len(rows) > len(events)
            return {"schema": "registry-page/1", "store": self.store, "through": through, "after": after,
                    "events": events, "next_after": events[-1]["seq"] if more and events else None,
                    "event_bytes": size, "funded_authority": False, "independent_custody": False}
        finally:
            self.conn.rollback()

    def run(self, db, request):
        fields(request, "hypothesis symbol strategy trials windows resolution cash scenarios final_evaluation_id")
        if type(request["hypothesis"]) is not str or not 1 <= len(request["hypothesis"].strip()) <= 500:
            raise ValueError("need a bounded experiment hypothesis")
        symbol = request["symbol"]
        if type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol):
            raise ValueError("invalid experiment symbol")
        trials, windows, scenarios = request["trials"], request["windows"], request["scenarios"]
        if any(type(x) is not list or not 1 <= len(x) <= 8 for x in (trials, windows, scenarios)) or len(trials) * len(windows) * len(scenarios) > 32:
            raise ValueError("need nonempty bounded selections with at most 32 attempted runs")
        if type(request["resolution"]) is not str:
            raise ValueError("resolution must be a string")
        spec = BarSpec(request["resolution"])
        if spec.resolution == "session":
            raise ValueError("experiments require fixed bar resolution")
        cash = decimal(request["cash"], "cash", positive=True)
        for params in trials:
            create_strategy(request["strategy"], params)
        periods, previous = [], None
        for window in windows:
            fields(window, "from to")
            start, end = instant(window["from"]), instant(window["to"])
            if not start < end <= now_utc() or end - start > timedelta(days=31) or (previous and start < previous):
                raise ValueError("need chronological disjoint historical windows of at most 31 days")
            if (end - start) // spec.step > 5000:
                raise ValueError("at most 5000 bars per experiment window")
            periods.append((start, end))
            previous = end
        costs = []
        for scenario in scenarios:
            fields(scenario, "fee_rate latency_ms outages")
            fee = rate(scenario["fee_rate"], "fee_rate")
            latency, outages = scenario["latency_ms"], scenario["outages"]
            if type(latency) is not int or not 0 <= latency <= 60000 or type(outages) is not list or len(outages) > 8:
                raise ValueError("scenario needs latency 0..60000ms and at most eight outages")
            excluded = []
            for outage in outages:
                fields(outage, "from to")
                start, end = instant(outage["from"]), instant(outage["to"])
                if not start < end or not any(a <= start < end <= b for a, b in periods):
                    raise ValueError("each outage must belong to one experiment window")
                excluded.append((start, end))
            costs.append((CostModel(fee_rate=fee, latency=timedelta(milliseconds=latency)), excluded))
        final = request["final_evaluation_id"]
        engine = _engine_digest()
        if final is not None:
            with ResearchProtocol(self.root, store=self.store) as protocol:
                final = protocol.evaluation(final)
            frozen = final["configuration"]
            if (any(frozen[key] != request[key] for key in ("symbol", "strategy", "resolution"))
                    or Decimal(frozen["cash"]) != cash or frozen["engine_digest"] != engine
                    or frozen["params"] not in [create_strategy(request["strategy"], params).params for params in trials]
                    or any(end > instant(frozen["selection_end"]) for _, end in periods)):
                raise ValueError("final evaluation does not match the experiment selection and engine")
        definition = self.append("EXPERIMENT", None, {"definition": request, "engine_digest": engine,
                                "final_evaluation_at_registration": final, "selection_is_exploratory": True})
        key = definition["id"]
        attempts = []
        # Register every planned attempt before market reads; a crash leaves visible unfinished attempts.
        for trial, params in enumerate(trials):
            for window, period in enumerate(periods):
                for scenario in range(len(scenarios)):
                    attempts.append((self.append("ATTEMPT", key, {"trial": trial, "window": window, "scenario": scenario, "state": "RESULT_PENDING"}), params, period, scenario))
        from .trial_ledger import TrialLedger
        with TrialLedger(self.root) as ledger:
            for attempt, params, (start, end), scenario in attempts:
                ledger.record(symbol=symbol, start=start, end=end, hypothesis=request["hypothesis"],
                              source="experiment", config_hash=digest({"params": params, "scenario": scenario}),
                              attempt_id=attempt["id"])
        if db.c.in_transaction:
            raise ValueError("experiment needs its own market snapshot")
        db.c.execute("BEGIN")
        try:
            instrument = DataPortal(db).instrument(symbol)
            sources = {symbol}
            if instrument.base != "BTC":
                sources.add("BTC" + instrument.quote)
            references = {getattr(create_strategy(request["strategy"], params), "reference_symbol", None) for params in trials} - {None}
            sources.update(references)
            if instrument.quote == "TMN":
                sources.add("USDTTMN")
            for start, end in periods:
                count = 0
                for source in sorted(sources):
                    begin = (start - timedelta(days=1) if source == "USDTTMN" and instrument.quote == "TMN"
                             else start - timedelta(seconds=120) if source in references else start)
                    finish = end + timedelta(microseconds=1) if source in references else end
                    count += db.c.execute("SELECT count(*) FROM (SELECT 1 FROM book_top WHERE instrument_id=? AND ts_avail>=? AND ts_avail<? LIMIT ?)",
                                          ("wallex:" + source, iso(begin), iso(finish), 100001 - count)).fetchone()[0]
                    if count > 100000:
                        raise ValueError("experiment observation budget exceeded; narrow windows")
            for attempt, params, (start, end), scenario in attempts:
                cost, excluded = costs[scenario]
                try:
                    out = paper(db, symbol, start, end, resolution=spec.resolution, cash=cash, cost=cost,
                                store=self.store, strategy_id=request["strategy"], params=params,
                                outages=[(a, b) for a, b in excluded if start <= a < b <= end])
                    save_run(out, self.root / "runs")
                    self.append("RESULT", key, {"attempt_id": attempt["id"], "state": "COMPLETED", "run_id": out["run_id"],
                        "outputs_digest": out["outputs_digest"], "data_digest": out["inputs"]["data"],
                        "net_quote": out["result"]["end"] and out["result"]["end"]["net"], "baselines": out["baselines"]})
                except (ValueError, ArithmeticError) as error:
                    self.append("RESULT", key, {"attempt_id": attempt["id"], "state": "INCOMPLETE" if isinstance(error, PaperDataUnavailable) else "FAILED",
                                               "reason": "NO_QUALIFIED_DATA" if isinstance(error, PaperDataUnavailable) else "REPLAY_REJECTED"})
        finally:
            db.c.rollback()
        return {"schema": "experiment-registry/1", "experiment": self.read(key), "funded_authority": False}
