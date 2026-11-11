"""Bulk paper sweep: every strategy x resolution x market over one window, without per-run overhead.

`gymctl paper` is built for one auditable run: it reloads quotes, replays two hold baselines, re-queries the
rule version on every quote and writes a ~0.7 MB JSON record. A sweep of 16 strategies x 12 resolutions x 373
markets would repeat that 71,616 times (days of CPU, ~50 GB). This module runs the same engine (`paper.run`, the
same `PaperSession`, costs and point-in-time rules) but shares what does not change between runs:

- quotes are parsed once per market and sliced by time (`CachedPortal`);
- rule versions are resolved in memory from one snapshot of the regime events (`FrozenRules`), the same
  prefix rule as `MarketDB.rules_version_as_of`, instead of one SQL query per quote;
- hold baselines run once per (market, resolution) and hold-BTC once per (quote, resolution), not per strategy;
- each run leaves one compact row in a SQLite results file; any row can be reproduced in full with
  `gymctl paper` using the same window, strategy and resolution;
- markets run in parallel worker processes, largest first, and finished markets are skipped on restart.

Every configuration is recorded as one trial in the trial ledger (source "experiment"), so the sweep's breadth
counts against any later claim of an edge on this window.
"""
from __future__ import annotations

import json
import sqlite3
import time
import traceback
from bisect import bisect_left, bisect_right
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ..adapters.store import MarketDB
from ..domain.model import dec, iso, parse_ts
from ..domain.registry import STRATEGIES, create_strategy
from ..domain.sim import CostModel
from ..domain.strategy import BuyAndHold, digest
from .data_portal import DataPortal, curve_valuation
from .rules import RuleService
from .session import ENGINE_VERSION

RESOLUTIONS = ("1min", "3min", "5min", "15min", "30min", "1h", "2h", "4h", "6h", "12h", "1day", "session")
SCHEMA = """
CREATE TABLE IF NOT EXISTS sweep(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS done(symbol TEXT PRIMARY KEY, seconds REAL NOT NULL, rows INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS runs(
  symbol TEXT NOT NULL, resolution TEXT NOT NULL, strategy TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
  quote TEXT, observations INTEGER, qualified INTEGER, bars INTEGER, fills INTEGER, nonfills INTEGER,
  closed_trades INTEGER, win_rate REAL, profit_factor REAL, exposure REAL, turnover REAL,
  net TEXT, net_usdt_eq TEXT, return_pct REAL, max_drawdown_pct REAL, sharpe_per_period REAL,
  hold_net TEXT, hold_net_usdt_eq TEXT, fees TEXT, spread TEXT, latency_drift TEXT, directional TEXT,
  config_hash TEXT, data_digest TEXT,
  PRIMARY KEY(symbol, resolution, strategy));
"""


class CachedPortal(DataPortal):
    """Quotes for each market parsed once for the sweep window, then sliced; identical rows and order."""

    def __init__(self, db, start: datetime, end: datetime):
        super().__init__(db)
        self.window = (start, end)
        self.cache: dict[str, tuple[list, list]] = {}

    def tops(self, symbol, t0, t1):
        lo, hi = self.window
        if not (lo <= t0 < t1 <= hi):
            return super().tops(symbol, t0, t1)
        if symbol not in self.cache:
            rows = super().tops(symbol, lo, hi)
            self.cache[symbol] = (rows, [r.ts_avail for r in rows])
        rows, times = self.cache[symbol]
        return rows[bisect_left(times, t0):bisect_left(times, t1)]


class FrozenRules:
    """`RuleService.load(at)` over one snapshot of regime events, without a query per call.

    MarketDB.rules_version_as_of(at) is the seq before the first event (in seq order) stamped after `at`. With
    prefix maxima of the stamps, that is the last prefix whose maximum is <= at, found by bisection.
    """

    def __init__(self, db):
        self.svc = RuleService(db)
        events = db.c.execute("SELECT seq, ts FROM regime_events ORDER BY seq").fetchall()
        self.seqs, self.bounds, peak = [], [], None
        for seq, ts in events:
            peak = ts if peak is None or ts > peak else peak
            moment = parse_ts(peak)
            if iso(moment) != peak:  # non-canonical stamp: text order may differ from time order
                raise ValueError("regime event stamps are not canonical; use RuleService")
            self.seqs.append(seq)
            self.bounds.append(moment)
        self.cache: dict[int, list] = {}

    def version(self, at: datetime) -> int:
        j = bisect_right(self.bounds, at)
        return self.seqs[j - 1] if j else 0

    def __call__(self, at: datetime) -> list:
        version = self.version(at)
        if version not in self.cache:
            loaded_version, rules, _ = self.svc.load(at)
            if loaded_version != version:
                raise RuntimeError("rule snapshot changed during the sweep")
            self.cache[version] = rules
        return list(self.cache[version])


def _strategy(strategy_id: str):
    # The same defaults as `paper()`: ema-trend without params means fast 8, slow 21.
    return create_strategy(strategy_id, {"fast": 8, "slow": 21} if strategy_id == "ema-trend" else None)


def _metrics(main: dict, t0: datetime, t1: datetime, symbol: str, baselines: dict) -> dict:
    from ..domain.performance import performance, sampled_drawdown
    record = {"result": main, "inputs": {"from": iso(t0), "to": iso(t1), "symbol": symbol}, "baselines": baselines}
    perf = performance(record, sampled_drawdown(record))
    trades = perf.get("trades") or {}
    returns = perf.get("returns") or {}

    def num(value):
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    exposure = trades.get("exposure")
    return {"closed_trades": trades.get("closed_trades"), "win_rate": num(trades.get("win_rate")),
            "profit_factor": num(trades.get("profit_factor")),
            "exposure": num(exposure.get("fraction") if isinstance(exposure, dict) else exposure),
            "turnover": num(trades.get("turnover")), "return_pct": num(perf.get("total_return_pct")),
            "max_drawdown_pct": num(perf.get("max_drawdown_pct")),
            "sharpe_per_period": num(returns.get("sharpe_per_period"))}


def sweep_market(db_path: str, symbol: str, t0: datetime, t1: datetime, resolutions, strategies,
                 cash_usdt: Decimal, cash_tmn: Decimal, fee: Decimal) -> list[dict]:
    from .paper import run

    db = MarketDB(Path(db_path), readonly=True)
    try:
        portal = CachedPortal(db, t0 - timedelta(days=1), t1)
        rules_for = FrozenRules(db)
        inst = portal.instrument(symbol)
        cash = cash_tmn if inst.quote == "TMN" else cash_usdt
        cost = CostModel(fee)
        fx_tops = portal.tops("USDTTMN", t0 - timedelta(days=1), t1) if inst.quote == "TMN" else None
        baseline_cache: dict = {}
        digests: dict = {}
        rows = []

        def usdt_eq(end, valuation):
            if end is None:
                return None
            if inst.quote == "USDT":
                return end["net"]
            if not valuation or not (valuation["start"]["rate"] and valuation["end"]["rate"]):
                return None
            return str((dec(end["equity"]) / dec(valuation["end"]["rate"])
                        - cash / dec(valuation["start"]["rate"])).quantize(Decimal("0.0001")))

        for resolution in resolutions:
            for strategy_id in strategies:
                row = {"symbol": symbol, "resolution": resolution, "strategy": strategy_id, "quote": inst.quote}
                try:
                    strategy = _strategy(strategy_id)
                    subs = tuple(dict.fromkeys((resolution, *getattr(strategy, "required_resolutions", ()))))
                    reference = getattr(strategy, "reference_symbol", None)
                    main = run(portal, rules_for, strategy, symbol, t0, t1, resolution, cash, cost, subs, reference,
                               digest_cache=digests)
                    if main["qualified"] == 0:
                        rows.append({**row, "status": "NO_DATA", "observations": main["observations"]})
                        continue
                    key = (resolution, subs)
                    if key not in baseline_cache:
                        hold = run(portal, rules_for, BuyAndHold(), symbol, t0, t1, resolution, cash, cost, subs,
                                   digest_cache=digests)
                        baseline_cache[key] = hold
                    hold = baseline_cache[key]
                    valuation = (curve_valuation(inst.quote, main["curve"], t0, t1, fx_tops, rules_for)
                                 if inst.quote == "TMN" else None)
                    hold_val = (curve_valuation(inst.quote, hold["curve"], t0, t1, fx_tops, rules_for)
                                if inst.quote == "TMN" and hold["end"] else None)
                    end = main["end"] or {}
                    waterfall = end.get("waterfall", {})
                    baselines = {f"hold {inst.base}": {k: hold[k] for k in ("symbol", "end", "fills", "nonfills")}}
                    rows.append({**row, "status": "OK", "observations": main["observations"],
                                 "qualified": main["qualified"], "bars": main["bars"], "fills": main["fills"],
                                 "nonfills": sum(main["nonfills"].values()),
                                 "net": end.get("net"), "net_usdt_eq": usdt_eq(main["end"], valuation),
                                 "hold_net": (hold["end"] or {}).get("net"),
                                 "hold_net_usdt_eq": usdt_eq(hold["end"], hold_val),
                                 "fees": waterfall.get("fees"), "spread": waterfall.get("spread"),
                                 "latency_drift": waterfall.get("latency_drift"),
                                 "directional": waterfall.get("directional"),
                                 "config_hash": strategy.config_hash, "data_digest": main["data_digest"],
                                 **_metrics(main, t0, t1, symbol, baselines)})
                except Exception as error:  # noqa: BLE001 - one refused configuration must not stop the market
                    rows.append({**row, "status": "REFUSED", "error": f"{type(error).__name__}: {error}"[:300]})
        return rows
    finally:
        db.c.close()


def _worker(args):
    started = time.perf_counter()
    try:
        rows = sweep_market(*args)
    except Exception:  # noqa: BLE001 - report the market as failed, keep the sweep going
        rows = [{"symbol": args[1], "resolution": "*", "strategy": "*", "status": "FAILED",
                 "error": traceback.format_exc()[-300:]}]
    return args[1], time.perf_counter() - started, rows


COLUMNS = ("symbol", "resolution", "strategy", "status", "error", "quote", "observations", "qualified", "bars",
           "fills", "nonfills", "closed_trades", "win_rate", "profit_factor", "exposure", "turnover", "net",
           "net_usdt_eq", "return_pct", "max_drawdown_pct", "sharpe_per_period", "hold_net", "hold_net_usdt_eq",
           "fees", "spread", "latency_drift", "directional", "config_hash", "data_digest")


def sweep(root: Path, out: Path, t0: datetime, t1: datetime, *, symbols=None, resolutions=RESOLUTIONS,
          strategies=None, workers: int = 8, fee: Decimal = Decimal("0.001"), cash_usdt: Decimal = Decimal(1000),
          cash_tmn: Decimal = Decimal(300_000_000), progress=print) -> dict:
    db_path = Path(root) / "market.db"
    strategies = tuple(strategies or STRATEGIES)
    reader = MarketDB(db_path, readonly=True)
    try:
        counts = dict(reader.c.execute(
            "SELECT substr(instrument_id, 8), count(*) FROM book_top WHERE ts_avail>=? AND ts_avail<? "
            "GROUP BY instrument_id", (iso(t0), iso(t1))).fetchall())
    finally:
        reader.c.close()
    targets = sorted((s for s in (symbols or counts) if counts.get(s)), key=lambda s: -counts[s])
    out.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(out)
    conn.executescript(SCHEMA)
    meta = {"from": iso(t0), "to": iso(t1), "fee": str(fee), "cash_usdt": str(cash_usdt), "cash_tmn": str(cash_tmn),
            "engine": ENGINE_VERSION, "resolutions": list(resolutions), "strategies": list(strategies)}
    stored = dict(conn.execute("SELECT key, value FROM sweep").fetchall())
    if stored and json.loads(stored["meta"]) != meta:
        raise ValueError(f"{out} holds a sweep with different settings; choose another output file")
    conn.execute("INSERT OR IGNORE INTO sweep VALUES('meta', ?)", (json.dumps(meta),))
    conn.commit()
    finished = {row[0] for row in conn.execute("SELECT symbol FROM done")}
    todo = [s for s in targets if s not in finished]
    progress(f"{len(targets)} markets with quotes, {len(finished)} already done, {len(todo)} to run; "
             f"{len(resolutions)} resolutions x {len(strategies)} strategies each")
    started, done_quotes = time.perf_counter(), 0
    total_quotes = sum(counts[s] for s in todo)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_worker, (str(db_path), s, t0, t1, tuple(resolutions), strategies, cash_usdt,
                                         cash_tmn, fee)) for s in todo]
        for n, future in enumerate(as_completed(futures), 1):
            symbol, seconds, rows = future.result()
            conn.executemany(f"INSERT OR REPLACE INTO runs({','.join(COLUMNS)}) VALUES({','.join('?' * len(COLUMNS))})",
                             [tuple(r.get(c) for c in COLUMNS) for r in rows])
            conn.execute("INSERT OR REPLACE INTO done VALUES(?,?,?)", (symbol, seconds, len(rows)))
            conn.commit()
            done_quotes += counts[symbol]
            elapsed = time.perf_counter() - started
            eta = elapsed / done_quotes * (total_quotes - done_quotes) if done_quotes else 0
            progress(f"[{n}/{len(todo)}] {symbol:<12} {counts[symbol]:>7} quotes {seconds:7.1f}s  "
                     f"elapsed {elapsed / 60:6.1f} min  eta {eta / 60:6.1f} min")
    _record_trials(Path(root), conn, t0, t1)
    summary = {"markets": len(targets), "runs": conn.execute("SELECT count(*) FROM runs").fetchone()[0],
               "ok": conn.execute("SELECT count(*) FROM runs WHERE status='OK'").fetchone()[0],
               "seconds": round(time.perf_counter() - started, 1), "output": str(out)}
    conn.close()
    return summary


def _record_trials(root: Path, conn, t0, t1) -> None:
    """One trial per configuration that ran, in one transaction: the sweep's breadth is on the record."""
    from .trial_ledger import TrialLedger, _question
    rows = conn.execute("SELECT symbol, resolution, strategy, config_hash FROM runs WHERE status='OK'").fetchall()
    with TrialLedger(root) as ledger:
        now = iso(datetime.now().astimezone())
        ledger.conn.execute("BEGIN IMMEDIATE")
        try:
            for symbol, resolution, strategy, config_hash in rows:
                attempt = digest(["sweep", iso(t0), iso(t1), symbol, resolution, strategy, config_hash])[:32]
                ledger.conn.execute(
                    "INSERT OR IGNORE INTO trial_attempts(attempt_id, question_id, source, config_hash, recorded_at) "
                    "VALUES (?, ?, 'experiment', ?, ?)",
                    (attempt, _question(symbol, t0, t1, f"sweep {strategy} {resolution}"), config_hash, now))
            ledger.conn.commit()
        except BaseException:
            ledger.conn.rollback()
            raise
