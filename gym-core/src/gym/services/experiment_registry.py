"""Append-only local experiment/attempt evidence; never a selection or funding gate."""
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3

from ..adapters.run_store import save_run
from ..domain.bars import BarSpec
from ..domain.market_models import decimal, fields, instant, rate
from ..domain.model import iso
from ..domain.registry import create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import digest
from .collector import now_utc
from .paper import PaperDataUnavailable, paper
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
        if db.c.in_transaction:
            raise ValueError("experiment needs its own market snapshot")
        db.c.execute("BEGIN")
        try:
            for start, end in periods:
                count = db.c.execute("SELECT count(*) FROM book_top WHERE ts_avail>=? AND ts_avail<?", (iso(start - timedelta(days=1)), iso(end))).fetchone()[0]
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
