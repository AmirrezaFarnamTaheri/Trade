"""Loopback-only local API and static UI."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from decimal import Decimal, DecimalException
from hashlib import sha256
from pathlib import Path

from aiohttp import web

from ..adapters.run_store import list_runs, load_run
from ..adapters.store import MarketDB, storage_forecast
from ..domain.account_observations import project_account
from ..domain.assisted_ticket import prepare_preview_from_json
from ..domain.bars import FIXED_RESOLUTIONS, qualified
from ..domain.model import TOMAN, InstrumentId, iso, parse_ts, strict_loads
from ..domain.registry import catalog
from ..domain.rules import is_closed
from ..domain.sim import CostModel
from ..services.backup_status import status as backup_status
from ..services.capabilities import market_catalog, workspace_capabilities
from ..services.collector import Collector, now_utc
from ..services.external_journal import ExternalJournal
from ..services.liquidity import liquidity_snapshot
from ..services.offline_review_journal import OfflineReviewJournal
from ..services.operator_timeline import timeline
from ..services.portable_report import render_html
from ..services.readiness import current_top, operational_readiness
from ..services.reports import economic_report, paper_summary
from ..services.research import coverage
from ..services.research_ledger import ResearchLedger
from ..services.research_process import ResearchProcessFailure, calculate
from ..services.rules import RuleService
from ..services.venue_facts import VenueFactsJournal
from . import finish, guard
from .models import install as install_models
from .offline_reviews import install as install_offline_reviews
from .operator_reviews import install as install_operator_reviews
from .research import install as install_research

UI = Path(__file__).resolve().parent.parent / "ui" / "index.html"


def _decimal_text(value):
    return None if value is None else str(value)


# Served next to index.html, each with a content-hash query so a browser never runs a stale copy.
UI_ASSETS = ("app.js", "markets.js", "research-controls.js", "operations.js", "charts.js", "runs.js", "models.js", "replay-chart.js", "research.js", "margin.js", "portfolio.js", "native-review.js",
             "workspace-config.js", "workspace-utils.js", "workspace-overview.js", "workspace-alerts.js",
             "markets-events.js", "research-events.js", "operator-events.js", "shell-events.js", "styles.css")

class _WorkspaceApi:
    """Route handlers of `make_app`, one method each."""

    def __init__(self, col: Collector, rules: RuleService, token: str, runs: Path | None = None,
                 account_observation: dict | None = None,
                 external_journal: ExternalJournal | None = None,
                 venue_facts: VenueFactsJournal | None = None,
                 offline_review_journal: OfflineReviewJournal | None = None,
                 chaos_report: Path | None = None):
        self.col = col
        self.rules = rules
        self.token = token
        self.runs = runs
        self.account_observation = account_observation
        self.external_journal = external_journal
        self.venue_facts = venue_facts
        self.offline_review_journal = offline_review_journal
        self.chaos_report = chaos_report
        self.comparison_lock = asyncio.Lock()
        self.market_path = Path(self.col.db.c.execute("PRAGMA database_list").fetchone()[2])
        self.research_tick_lock = asyncio.Lock()

    async def index(self, _):
        """Render content-hashed asset references without disclosing the session token."""
        # Never embed the token: any local process can fetch "/". The browser receives it in the URL fragment.
        html = UI.read_text("utf-8").replace("__GYM_DEMO__", json.dumps(self.col.demo))
        html = html.replace("__GYM_RESOLUTIONS__", json.dumps(list(FIXED_RESOLUTIONS)))
        for asset in UI_ASSETS:
            placeholder = f'"/{asset}"'
            if placeholder not in html:
                continue  # An allowlisted asset unused by this page needs no content hash.
            version = sha256(UI.with_name(asset).read_bytes()).hexdigest()[:16]
            html = html.replace(placeholder, f'"/{asset}?v={version}"')
        return web.Response(text=html, content_type="text/html")

    async def browser_asset(self, req):
        """Serve only assets from the explicit UI_ASSETS route allowlist."""
        return web.FileResponse(UI.with_name(req.path[1:]))

    async def markets(self, _):
        now, rows = now_utc(), []
        for sym, inst in self.col.insts.items():
            t = current_top(self.col, sym, now)
            last = self.col.trades[sym][0] if self.col.trades[sym] else None
            rows.append({
                "symbol": sym, "base": inst.base, "quote": inst.quote, "names": self.col.names[sym],
                "bid": _decimal_text(t and t.bid), "ask": _decimal_text(t and t.ask),
                "bid_qty": _decimal_text(t and t.bid_qty), "ask_qty": _decimal_text(t and t.ask_qty),
                "spread": _decimal_text(t and t.spread), "spread_bps": _decimal_text(t and t.spread_bps),
                "flags": sorted(t.flags) if t else ["STALE"],
                "qualified": bool(t and qualified(t)),
                "liquidity": liquidity_snapshot(self.col.books[sym], now, self.col.lim),
                "book_age_s": max((now - side.ts).total_seconds() for side in self.col.books[sym].values())
                              if all(self.col.books[sym].values()) else None,
                "last_trade": last and {"price": _decimal_text(last.price), "qty": _decimal_text(last.qty),
                                       "aggressor": last.aggressor, "ts": iso(last.ts_event)},
                "unit": {"code": TOMAN.code, "epoch": TOMAN.unit_epoch} if inst.quote == "TMN" else None,
                "act": self.rules.act(inst, now),
                "data_quality": self.col.data_quality.get(sym),
            })
        return web.json_response({"now": iso(now), "demo": self.col.demo, "fx": self.fx_factor(now),
                                  "universe": self.col.universe, "markets": rows,
                                  "catalog": market_catalog(self.col), "capabilities": workspace_capabilities(self.col)})

    async def capabilities(self, _):
        return web.json_response(workspace_capabilities(self.col))

    def fx_factor(self, now):
        """USDT/IRT valuation factor: STALE_CLOSED during a closure (last mid kept), LIVE when quoted."""
        top = current_top(self.col, "USDTTMN", now) if "USDTTMN" in self.col.books else None
        mid = top and qualified(top) and (top.bid + top.ask) / 2
        if is_closed(self.rules.load()[1], InstrumentId.wallex("USDTTMN"), now, live=True):
            status = "STALE_CLOSED"
        else:
            status = "LIVE" if mid else "UNAVAILABLE"
        return {"pair": "USDTTMN", "mid": _decimal_text(mid or None), "status": status}

    async def rule_list(self, _):
        return web.json_response(self.rules.listing(now_utc(), list(self.col.insts.values())))

    async def rule_put(self, req):
        return web.json_response({"seq": self.rules.put(await req.json(), now_utc())})

    async def rule_disable(self, req):
        return web.json_response({"seq": self.rules.disable(req.match_info["id"], now_utc())})

    async def rule_rollback(self, req):
        return web.json_response({"seq": self.rules.rollback(req.match_info["id"], int((await req.json())["seq"]), now_utc())})

    async def rule_import(self, req):
        return web.json_response(self.rules.import_(await req.json(), now_utc()))

    async def rule_export(self, _):
        return web.json_response(self.rules.export(), dumps=lambda o: json.dumps(o, ensure_ascii=False, indent=2),
                                 headers={"Content-Disposition": "attachment; filename=venue-rules.json"})

    async def preset(self, req):
        return web.json_response(self.rules.preset(req.match_info["name"], now_utc()))

    async def check(self, req):
        q = req.query
        inst = self.col.insts.get(q["symbol"])
        if inst is None:
            raise ValueError("symbol not watched")
        at = parse_ts(q["at"]) if q.get("at") else now_utc()
        return web.json_response(self.rules.check(inst, q.get("side", "BUY"), q.get("intent", "ENTRY"), at))

    def storage_report(self):
        db = MarketDB(self.market_path, readonly=True)  # this runs off the loop thread; the collector's connection stays there
        try:
            return storage_forecast(db, self.col.seg.root, now_utc())
        finally:
            db.c.close()

    async def health(self, _):
        st = self.col.status
        lf = st["last_frame"]
        return web.json_response({
            "demo": self.col.demo, "connected": st["connected"], "fatal": st["fatal"], "reconnects": st["reconnects"],
            "last_frame_age_s": None if lf is None else round((now_utc() - lf).total_seconds(), 1),
            "errors": list(st["errors"]),
            "readiness": operational_readiness(self.col, now_utc()),
            "venue_validation": {"state": "EVIDENCE_ONLY" if self.venue_facts and self.venue_facts.facts(limit=1) else "NOT_CONFIGURED"},
            "quality": [dict(zip(("ts", "instrument", "flag", "detail"), r)) for r in self.col.db.quality(30)],
            "storage": await asyncio.to_thread(self.storage_report),
            "shards": [{"shard": shard, "markets": s["markets"], "connected": shard in self.col.connected_shards,
                        "reconnects": s["reconnects"],
                        "last_frame_age_s": None if s["last_frame"] is None else round((now_utc() - s["last_frame"]).total_seconds(), 1)}
                       for shard, s in sorted(st["shard_stats"].items())],
            "archived": st["archived"], "integrity": st["integrity"], "clock_paused": bool(st.get("clock_paused")),
            "event_loop_lag": self.col.loop_lag.report() if hasattr(self.col, "loop_lag") else None,
        })

    async def ready(self, _):
        report = operational_readiness(self.col, now_utc())
        return web.json_response(report, status=200 if report["ready"] else 503)

    async def account_observations(self, req):
        if self.account_observation is None:
            try:
                safe = self.external_journal.latest_snapshot() if self.external_journal else None
            except (ValueError, TypeError):
                return web.json_response(
                    {"state": "ERROR", "authority": "READ_ONLY", "error": "invalid account observation"},
                    status=503)
            if safe is None:
                safe = {"state": "NOT_CONFIGURED", "source": "VENUE_EXTERNAL",
                        "authority": "READ_ONLY", "account_id": None, "observed_at": None,
                        "balances": [], "orders": [], "exposure": []}
        else:
            # Never reflect untrusted raw data or secret-like unknown fields.
            try:
                safe = project_account(
                    self.account_observation["account_id"], self.account_observation["observed_at"],
                    balances=self.account_observation.get("balances"),
                    orders=self.account_observation.get("orders"),
                    exposure=self.account_observation.get("exposure"),
                )
            except (KeyError, ValueError, TypeError):
                return web.json_response(
                    {"state": "ERROR", "authority": "READ_ONLY", "error": "invalid account observation"},
                    status=503)
        return web.json_response(safe)

    async def external_events(self, req):
        if self.external_journal is None:
            result = {"state": "NOT_CONFIGURED", "authority": "READ_ONLY", "events": []}
        else:
            result = {"state": "OBSERVED", "authority": "READ_ONLY",
                      "events": self.external_journal.events()}
        return web.json_response(result)

    async def venue_facts_api(self, req):
        # C1 is a private operator history. Never return raw venue payloads,
        # account credentials or a claim that a write method is certified.
        facts = [] if self.venue_facts is None else self.venue_facts.facts()
        return web.json_response({
            "state": "EVIDENCE_ONLY" if facts else "NOT_CONFIGURED",
            "authority": "READ_ONLY", "facts": facts, "capabilities": {} if self.venue_facts is None else self.venue_facts.capabilities(),
        })

    async def dry_run_ticket(self, req):
        # The browser has no money path. Strictly bound this small JSON input
        # and never forward it to any Executor or venue transport.
        raw = await req.read()
        if not raw or len(raw) > 8192:
            raise ValueError("offline ticket JSON exceeds size limit")
        payload = strict_loads(raw, "offline ticket JSON")
        preview = prepare_preview_from_json(payload)
        return web.json_response(preview)

    async def automation_safety(self, req):
        # This is a conservative description of THIS unprivileged process.
        # Never infer T2 service state from a browser-supplied claim.
        return web.json_response({
            "mode": "DISARMED", "protection": "UNAVAILABLE",
            "venue_stops": "NOT_CERTIFIED",
            "entries_enabled": False, "autopilot_enabled": False,
            "funded_authority": False, "source": "LOCAL_UNPRIVILEGED_PROCESS",
            "executor_state_verified": False,
        })

    def observed_symbols(self, db):
        # Index skip-scan: one seek per distinct market instead of reading every stored quote.
        return [row[0][7:] for row in db.c.execute("""WITH RECURSIVE m(id) AS (
            SELECT min(instrument_id) FROM book_top
            UNION ALL SELECT (SELECT min(instrument_id) FROM book_top WHERE instrument_id > m.id) FROM m WHERE m.id IS NOT NULL)
            SELECT id FROM m WHERE id IS NOT NULL""")]

    def setup_snapshot(self, symbol):
        # Own read-only connection: the collector's connection belongs to the event-loop thread.
        reader = MarketDB(self.market_path, readonly=True)
        try:
            observed = self.observed_symbols(reader)
            symbol = symbol or ("BTCTMN" if "BTCTMN" in observed else observed[0] if observed else "BTCUSDT")
            return observed, coverage(reader, symbol)
        finally:
            reader.c.close()

    async def research_setup(self, req):
        observed, covered = await asyncio.to_thread(self.setup_snapshot, req.query.get("symbol"))
        return web.json_response({"strategies": catalog(), "symbols": observed, "resolutions": list(FIXED_RESOLUTIONS),
                                  "coverage": covered,
                                  "portfolio_replay": True,
                                  "defaults": {"fee_rate": os.environ.get("GYM_FEE_RATE", str(CostModel().fee_rate)),
                                               "latency_ms": 500, "resolution": "15min"},
                                  "authority": "PAPER_ONLY"})

    async def compare_runs(self, req):
        validation = req.path == "/api/validate"
        if self.runs is None:
            raise ValueError("paper run storage is not configured")
        body = await req.json()
        allowed = {"symbol", "from", "to", "resolution", "cash", "fee_rate", "latency_ms", "rules_mode", "candidates", "participation",
                   "walk_depth", "carry_remainder", "max_fraction", "vol_target", "order_type", "maker_fee_rate"}
        if validation:
            allowed.add("folds")
        if not isinstance(body, dict) or body.keys() - allowed:
            raise ValueError("invalid comparison fields")
        folds = body.get("folds", 1)
        if validation and (type(folds) is not int or not 1 <= folds <= 5):
            raise ValueError("validation folds must be an integer from 1 to 5")
        if any(key in body and not isinstance(body[key], str) for key in ("symbol", "resolution", "rules_mode")):
            raise ValueError("comparison symbol, resolution and rules_mode must be strings")
        try:
            if not all(isinstance(body.get(key), str) for key in ("from", "to")):
                raise ValueError("zoned timestamp strings required")
            cash_text = body.get("cash", "1000")
            fee_text = body.get("fee_rate", os.environ.get("GYM_FEE_RATE", "0.001"))
            if any(not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r"[0-9]+(?:[.][0-9]+)?", value)
                   for value in (cash_text, fee_text)):
                raise ValueError("bounded decimal strings required")
            start, end = parse_ts(body["from"]), parse_ts(body["to"])
            cash, fee = Decimal(cash_text), Decimal(fee_text)
            latency = body.get("latency_ms", 500)
            if type(latency) is not int or not 0 <= latency <= 60000 or end > now_utc():
                raise ValueError("invalid comparison bounds")
            if not cash.is_finite() or cash <= 0:
                raise ValueError("cash must be positive and finite")
            from datetime import timedelta
            participation = body.get("participation")
            if participation is not None and (not isinstance(participation, str) or not re.fullmatch(r"0?\.[0-9]{1,6}|1(?:\.0+)?", participation)):
                raise ValueError("participation must be a decimal string in (0, 1]")
            flags = {key: body.get(key, False) for key in ("walk_depth", "carry_remainder")}
            if any(type(value) is not bool for value in flags.values()):
                raise ValueError("walk_depth and carry_remainder must be booleans")
            sizing = {key: body.get(key) for key in ("max_fraction", "vol_target")}
            if any(value is not None and (not isinstance(value, str) or not re.fullmatch(r"0?\.[0-9]{1,6}|1(?:\.0+)?", value))
                   for value in sizing.values()):
                raise ValueError("max_fraction and vol_target must be decimal strings in (0, 1]")
            order_type, maker = body.get("order_type", "market"), body.get("maker_fee_rate")
            if order_type not in ("market", "limit") or maker is not None and (
                    not isinstance(maker, str) or not re.fullmatch(r"0?\.[0-9]{1,6}", maker)):
                raise ValueError("order_type must be market or limit; maker_fee_rate a decimal string below 1")
            cost = CostModel(fee, timedelta(milliseconds=latency), order_type=order_type,
                             maker_fee_rate=Decimal(maker) if maker is not None else None,
                             max_participation=Decimal(participation) if participation is not None else None, **flags,
                             **{key: Decimal(value) for key, value in sizing.items() if value is not None})
        except (ValueError, TypeError, KeyError, DecimalException):
            raise ValueError("invalid comparison window, cash or costs") from None
        if self.market_path.resolve() != (self.runs.parent / "market.db").resolve():
            raise ValueError("comparison market/run stores must share a root")
        normalized = {"symbol": body.get("symbol"), "from": iso(start), "to": iso(end),
                      "resolution": body.get("resolution", "15min"), "cash": str(cash), "fee_rate": str(cost.fee_rate),
                      "latency_ms": latency, "rules_mode": body.get("rules_mode", "point-in-time"),
                      "candidates": body.get("candidates"), "folds": folds,
                      "participation": None if cost.max_participation is None else str(cost.max_participation),
                      "walk_depth": cost.walk_depth, "carry_remainder": cost.carry_remainder,
                      "max_fraction": None if cost.max_fraction is None else str(cost.max_fraction),
                      "vol_target": None if cost.vol_target is None else str(cost.vol_target),
                      "order_type": cost.order_type,
                      "maker_fee_rate": None if cost.maker_fee_rate is None else str(cost.maker_fee_rate)}
        if self.comparison_lock.locked():
            return web.json_response({"error": "a comparison is already running"}, status=409)
        from ..services.event_log import event
        event("comparison_started", mode="validation" if validation else "comparison", symbol=normalized["symbol"],
              window=[normalized["from"], normalized["to"]], candidates=len(normalized["candidates"] or []))
        async with self.comparison_lock:
            try:
                result = await finish(calculate(self.runs.parent, "validation" if validation else "comparison", normalized,
                                                 store="demo" if self.col.demo else "live"))
            except ResearchProcessFailure as error:
                event("comparison_failed", status=error.status)
                return web.json_response(error.report, status=error.status)
        event("comparison_finished", id=result.get("comparison_id") or result.get("validation_id"),
              runs=[record["run_id"] for record in result.get("runs", [])])
        return web.json_response(result)

    async def run_list(self, request):
        query = request.query
        if set(query) - {"limit", "offset", "symbol", "strategy"}:
            raise ValueError("unknown run list parameter")
        limit, offset = int(query.get("limit", "50")), int(query.get("offset", "0"))
        if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
            raise ValueError("limit must be 1..200 and offset 0..1000000")
        return web.json_response([] if self.runs is None else await asyncio.to_thread(
            list_runs, self.runs, limit, offset, query.get("symbol") or None, query.get("strategy") or None))

    def research_path(self):
        if self.runs is None or not (self.runs.parent / "research.sqlite3").exists():
            return None
        return self.runs.parent / "research.sqlite3"

    async def research_state(self, req):
        path = self.research_path()
        if path is None:
            value = {"state": "NOT_CONFIGURED", "jobs": [], "alerts": [], "hypotheses": [], "shadows": [],
                     "authority": "PAPER_ONLY"}
        else:
            try:
                with ResearchLedger(path, readonly=True) as ledger:
                    value = {"state": "CONFIGURED", **ledger.overview()}
            except (ValueError, OSError, sqlite3.Error):
                return web.json_response({"error": "research ledger unavailable"}, status=503,
                                         )
        return web.json_response(value)

    async def research_control(self, req):
        if await req.json() != {}:
            raise ValueError("research control requires an empty object")
        path = self.research_path()
        if path is None:
            raise ValueError("research schedules are not configured")
        try:
            with ResearchLedger(path) as ledger:
                value = getattr(ledger, req.match_info["action"])(req.match_info["id"])
        except (OSError, sqlite3.Error):
            return web.json_response({"error": "research ledger unavailable"}, status=503)
        return web.json_response(value)

    async def research_tick(self, req):
        if await req.json() != {}:
            raise ValueError("research tick requires an empty object")
        path = self.research_path()
        if path is None:
            raise ValueError("research schedules are not configured")
        if self.research_tick_lock.locked():
            return web.json_response({"error": "paper research is already running"}, status=409)
        async with self.research_tick_lock:
            try:
                value = await finish(calculate(path.parent, "tick", store="demo" if self.col.demo else "live", at=iso(now_utc())))
            except ResearchProcessFailure as error:
                return web.json_response(error.report, status=error.status)
        return web.json_response(value)

    def _load_run(self, run_id):
        if self.runs is None:
            raise web.HTTPNotFound()
        try:
            return load_run(self.runs, run_id)
        except FileNotFoundError:
            raise web.HTTPNotFound() from None

    async def run_summary(self, req):
        return await asyncio.to_thread(self._run_summary_response, req.match_info["id"], req.path.endswith("/summary.html"))

    def _run_summary_response(self, run_id, as_html):
        record = self._load_run(run_id)
        if record["run_id"] != run_id:
            raise ValueError("run identity mismatch")
        if as_html:
            return web.Response(text=render_html(record), content_type="text/html", headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="paper-' + record["run_id"] + '.html"'})
        return web.json_response(paper_summary(record), headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="paper-' + record["run_id"] + '.json"'})

    async def run_detail(self, req):
        return await asyncio.to_thread(self._run_detail_response, req.match_info["id"])

    def _run_detail_response(self, run_id):
        record = self._load_run(run_id)
        if record["evidence"] is None:
            record["evidence"] = economic_report(record)
        return web.json_response(record)

    async def chaos_report_api(self, req):
        # B2 Fake Venue chaos-suite report written by `gym-chaos`; read-only evidence, never authority.
        try:
            raw = self.chaos_report.read_bytes() if self.chaos_report else None
        except FileNotFoundError:
            raw = None
        if raw is None:
            return web.json_response({"state": "NOT_RUN"})
        if len(raw) > 4 * 1024 * 1024:
            return web.json_response({"state": "UNREADABLE"}, status=503)
        try:
            report = json.loads(raw)
        except ValueError:
            return web.json_response({"state": "UNREADABLE"}, status=503)
        return web.json_response({"state": "REPORTED", **report})

    async def timeline_api(self, req):
        if self.runs is None:
            return web.json_response({"events": [], "sources": {}, "read_only": True})
        try:
            limit = int(req.query.get("limit", "100"))
            sources = set(req.query["source"].split(",")) if req.query.get("source") else None
            value = await asyncio.to_thread(timeline, self.runs.parent, limit=limit, sources=sources)
        except ValueError as error:
            return web.json_response({"error": str(error)}, status=400)
        return web.json_response(value)

    async def backup_status_api(self, req):
        if self.runs is None:
            return web.json_response({"state": "NOT_CONFIGURED"})
        try:
            value = backup_status(self.runs.parent)
        except (ValueError, OSError, RuntimeError, sqlite3.Error):
            return web.json_response({"state": "UNREADABLE"}, status=503)
        return web.json_response(value)


def make_app(col: Collector, rules: RuleService, token: str, runs: Path | None = None,
             account_observation: dict | None = None,
             external_journal: ExternalJournal | None = None,
             venue_facts: VenueFactsJournal | None = None,
             offline_review_journal: OfflineReviewJournal | None = None,
             chaos_report: Path | None = None) -> web.Application:
    """Serve only the loopback research UI and bounded, non-authorizing API routes."""
    api = _WorkspaceApi(col, rules, token, runs, account_observation, external_journal, venue_facts,
                        offline_review_journal, chaos_report)
    app = web.Application(middlewares=[guard(token)], client_max_size=1024 * 1024)
    app.add_routes([
        web.get("/", api.index), *(web.get("/" + asset, api.browser_asset) for asset in UI_ASSETS),
        web.get("/api/markets", api.markets), web.get("/api/health", api.health), web.get("/api/ready", api.ready),
        web.get("/api/capabilities", api.capabilities),
        web.get("/api/backup-status", api.backup_status_api), web.get("/api/timeline", api.timeline_api),
        web.get("/api/account-observations", api.account_observations),
        web.get("/api/external-order-events", api.external_events),
        web.get("/api/venue-facts", api.venue_facts_api), web.get("/api/chaos-report", api.chaos_report_api),
        web.post("/api/dry-run/ticket", api.dry_run_ticket),
        web.get("/api/automation-safety", api.automation_safety),
        web.get("/api/research", api.research_setup), web.post("/api/compare", api.compare_runs),
        web.post("/api/validate", api.compare_runs),
        web.get("/api/research-state", api.research_state),
        web.post("/api/research/jobs/{id}/{action:pause|resume}", api.research_control),
        web.post("/api/research/tick", api.research_tick),
        web.get("/api/runs", api.run_list), web.get("/api/runs/{id}", api.run_detail),
        web.get("/api/runs/{id}/summary", api.run_summary),
        web.get("/api/runs/{id}/summary.html", api.run_summary),
        web.get("/api/check", api.check), web.get("/api/rules", api.rule_list), web.get("/api/rules/export", api.rule_export),
        web.post("/api/rules", api.rule_put), web.post("/api/rules/import", api.rule_import),
        web.post("/api/rules/{id}/disable", api.rule_disable), web.post("/api/rules/{id}/rollback", api.rule_rollback),
        web.post("/api/presets/{name}", api.preset),
    ])
    install_models(app, runs.parent / "model_usage.db" if runs is not None else None)
    install_operator_reviews(app, enabled=not col.demo)
    install_research(app, runs.parent if runs is not None else None, store="demo" if col.demo else "live")
    review_path = (Path(offline_review_journal.conn.execute("PRAGMA database_list").fetchone()[2])
                   if offline_review_journal is not None else runs.parent / "offline_reviews.db" if runs is not None else None)
    install_offline_reviews(app, review_path)
    return app
