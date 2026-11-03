"""Loopback-only local API and static UI."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
from decimal import Decimal, DecimalException
from pathlib import Path

from aiohttp import web

from ..adapters.run_store import list_runs, load_run, save_run
from ..adapters.store import MarketDB
from ..domain.registry import catalog
from ..domain.sim import CostModel
from ..services.research import compare, coverage
from ..domain.account_observations import project_account
from ..domain.bars import qualified
from ..domain.model import TOMAN, InstrumentId, iso, parse_ts
from ..domain.rules import is_closed
from ..services.collector import Collector, now_utc
from ..services.rules import RuleService
from ..services.reports import economic_report
from ..services.external_journal import ExternalJournal
from ..services.venue_facts import VenueFactsJournal
from ..domain.assisted_ticket import prepare_preview_from_json
from ..services.offline_review_journal import OfflineReviewJournal

UI = Path(__file__).resolve().parent.parent / "ui" / "index.html"
LOOPBACK = {"127.0.0.1", "localhost"}


def s(x):
    return None if x is None else str(x)


def make_app(col: Collector, rules: RuleService, token: str, runs: Path | None = None,
             account_observation: dict | None = None,
             external_journal: ExternalJournal | None = None,
             venue_facts: VenueFactsJournal | None = None,
             offline_review_journal: OfflineReviewJournal | None = None,
             chaos_report: Path | None = None) -> web.Application:
    @web.middleware
    async def guard(req: web.Request, handler):
        # DNS-rebinding and CSRF defence: loopback Host only, and a per-run token on every write.
        if (req.host or "").rsplit(":", 1)[0] not in LOOPBACK:
            return web.json_response({"error": "loopback only"}, status=403)
        if req.method != "GET" and not hmac.compare_digest(req.headers.get("X-Gym-Token", ""), token):
            return web.json_response({"error": "missing or bad X-Gym-Token"}, status=403)
        try:
            return await handler(req)
        except (ValueError, KeyError) as e:
            return web.json_response({"error": str(e)}, status=400)

    async def index(_):
        html = UI.read_text("utf-8").replace("__GYM_TOKEN__", token).replace("__GYM_DEMO__", json.dumps(col.demo))
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def browser_asset(req):
        return web.FileResponse(UI.with_name(req.path[1:]))

    async def markets(_):
        now, rows = now_utc(), []
        for sym, inst in col.insts.items():
            t = col.tops.get(sym)
            last = col.trades[sym][0] if col.trades[sym] else None
            rows.append({
                "symbol": sym, "base": inst.base, "quote": inst.quote, "names": col.names[sym],
                "bid": s(t and t.bid), "ask": s(t and t.ask), "bid_qty": s(t and t.bid_qty), "ask_qty": s(t and t.ask_qty),
                "spread": s(t and t.spread), "spread_bps": s(t and t.spread_bps), "flags": sorted(t.flags) if t else ["STALE"],
                "qualified": bool(t and qualified(t)),
                "book_age_s": None if not t or not col.books[sym]["bid"] else round((now - col.books[sym]["bid"].ts).total_seconds()),
                "last_trade": last and {"price": s(last.price), "qty": s(last.qty), "aggressor": last.aggressor, "ts": iso(last.ts_event)},
                "unit": {"code": TOMAN.code, "epoch": TOMAN.unit_epoch} if inst.quote == "TMN" else None,
                "act": rules.act(inst, now),
            })
        return web.json_response({"now": iso(now), "demo": col.demo, "fx": fx_factor(now),
                                  "universe": col.universe, "markets": rows})

    def fx_factor(now):
        """USDT/IRT valuation factor: STALE_CLOSED during a closure (last mid kept), LIVE when quoted."""
        top = col.tops.get("USDTTMN")
        mid = top and qualified(top) and (top.bid + top.ask) / 2
        if is_closed(rules.load()[1], InstrumentId.wallex("USDTTMN"), now, live=True):
            status = "STALE_CLOSED"
        else:
            status = "LIVE" if mid else "UNAVAILABLE"
        return {"pair": "USDTTMN", "mid": s(mid or None), "status": status}

    async def rule_list(_):
        return web.json_response(rules.listing(now_utc(), list(col.insts.values())))

    async def rule_put(req):
        return web.json_response({"seq": rules.put(await req.json(), now_utc())})

    async def rule_disable(req):
        return web.json_response({"seq": rules.disable(req.match_info["id"], now_utc())})

    async def rule_rollback(req):
        return web.json_response({"seq": rules.rollback(req.match_info["id"], int((await req.json())["seq"]), now_utc())})

    async def rule_import(req):
        return web.json_response(rules.import_(await req.json(), now_utc()))

    async def rule_export(_):
        return web.json_response(rules.export(), dumps=lambda o: json.dumps(o, ensure_ascii=False, indent=2),
                                 headers={"Content-Disposition": "attachment; filename=venue-rules.json"})

    async def preset(req):
        return web.json_response(rules.preset(req.match_info["name"], now_utc()))

    async def check(req):
        q = req.query
        inst = col.insts.get(q["symbol"])
        if inst is None:
            raise ValueError("symbol not watched")
        at = parse_ts(q["at"]) if q.get("at") else now_utc()
        return web.json_response(rules.check(inst, q.get("side", "BUY"), q.get("intent", "ENTRY"), at))

    async def health(_):
        st = col.status
        lf = st["last_frame"]
        return web.json_response({
            "demo": col.demo, "connected": st["connected"], "fatal": st["fatal"], "reconnects": st["reconnects"],
            "last_frame_age_s": None if lf is None else round((now_utc() - lf).total_seconds(), 1),
            "errors": list(st["errors"]),
            "venue_validation": {"state": "EVIDENCE_ONLY" if venue_facts and venue_facts.facts(limit=1) else "NOT_CONFIGURED",
                                 "funded_authority": False, "trusted_origin": False},
            "quality": [dict(zip(("ts", "instrument", "flag", "detail"), r)) for r in col.db.quality(30)],
        })

    async def account_observations(req):
        # Private local portfolio read, not a public market endpoint. The
        # browser already carries the per-run token on GET requests.
        if not hmac.compare_digest(req.headers.get("X-Gym-Token", ""), token):
            return web.json_response({"error": "read-only account token required"}, status=403)
        if account_observation is None:
            safe = {"state": "NOT_CONFIGURED", "source": "VENUE_EXTERNAL",
                    "authority": "READ_ONLY", "account_id": None, "observed_at": None,
                    "balances": [], "orders": [], "exposure": []}
        else:
            # Never reflect untrusted raw data or secret-like unknown fields.
            try:
                safe = project_account(
                    account_observation["account_id"], account_observation["observed_at"],
                    balances=account_observation.get("balances"),
                    orders=account_observation.get("orders"),
                    exposure=account_observation.get("exposure"),
                )
            except (KeyError, ValueError, TypeError):
                return web.json_response(
                    {"state": "ERROR", "authority": "READ_ONLY", "error": "invalid account observation"},
                    status=503, headers={"Cache-Control": "no-store"})
        return web.json_response(safe, headers={"Cache-Control": "no-store"})

    async def external_events(req):
        if not hmac.compare_digest(req.headers.get("X-Gym-Token", ""), token):
            return web.json_response({"error": "external Journal token required"}, status=403)
        if external_journal is None:
            result = {"state": "NOT_CONFIGURED", "authority": "READ_ONLY", "events": []}
        else:
            result = {"state": "OBSERVED", "authority": "READ_ONLY",
                      "events": external_journal.events()}
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def venue_facts_api(req):
        # C1 is a private operator history. Never return raw venue payloads,
        # account credentials or a claim that a write method is certified.
        if not hmac.compare_digest(req.headers.get("X-Gym-Token", ""), token):
            return web.json_response({"error": "VenueFacts token required"}, status=403)
        facts = [] if venue_facts is None else venue_facts.facts()
        return web.json_response({
            "state": "EVIDENCE_ONLY" if facts else "NOT_CONFIGURED",
            "authority": "READ_ONLY", "funded_authority": False, "trusted_origin": False,
            "facts": facts, "capabilities": {} if venue_facts is None else venue_facts.capabilities(),
        }, headers={"Cache-Control": "no-store"})

    async def dry_run_ticket(req):
        # The browser has no money path. Strictly bound this small JSON input
        # and never forward it to any Executor or venue transport.
        raw = await req.read()
        if not raw or len(raw) > 8192:
            raise ValueError("offline ticket JSON exceeds size limit")
        def unique_pairs(pairs):
            fields = {}
            for name, value in pairs:
                if name in fields:
                    raise ValueError("ambiguous duplicate JSON field")
                fields[name] = value
            return fields
        try:
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("invalid offline ticket JSON") from None
        preview = prepare_preview_from_json(payload)
        return web.json_response(preview, headers={"Cache-Control": "no-store"})

    async def automation_safety(req):
        # This is a conservative description of THIS unprivileged process.
        # Never infer T2 service state from a browser-supplied claim.
        if not hmac.compare_digest(req.headers.get("X-Gym-Token", ""), token):
            return web.json_response({"error": "local operator token required"}, status=403)
        return web.json_response({
            "mode": "DISARMED", "protection": "UNAVAILABLE",
            "venue_stops": "NOT_CERTIFIED",
            "entries_enabled": False, "autopilot_enabled": False,
            "funded_authority": False, "source": "LOCAL_UNPRIVILEGED_PROCESS",
            "executor_state_verified": False,
        }, headers={"Cache-Control": "no-store"})

    async def offline_ticket_reviews(req):
        if not hmac.compare_digest(req.headers.get("X-Gym-Token", ""), token):
            return web.json_response({"error": "offline review token required"}, status=403)
        return web.json_response({
            "state": "NOT_CONFIGURED" if offline_review_journal is None else "OFFLINE_ONLY",
            "authority": "OFFLINE_ONLY", "funded_authority": False,
            "tickets": [] if offline_review_journal is None else offline_review_journal.tickets(),
            "reviews": [] if offline_review_journal is None else offline_review_journal.review_events(),
        }, headers={"Cache-Control": "no-store"})

    comparison_lock = asyncio.Lock()

    async def research_setup(req):
        observed = [row[0] for row in col.db.c.execute("select distinct substr(instrument_id, 8) from book_top order by 1")]
        symbol = req.query.get("symbol") or ("BTCTMN" if "BTCTMN" in observed else observed[0] if observed else "BTCUSDT")
        return web.json_response({"strategies": catalog(), "symbols": observed,
                                  "coverage": coverage(col.db, symbol),
                                  "defaults": {"fee_rate": os.environ.get("GYM_FEE_RATE", str(CostModel().fee_rate)),
                                               "latency_ms": 500, "resolution": "15min"},
                                  "authority": "PAPER_ONLY", "funded_authority": False},
                                 headers={"Cache-Control": "no-store"})

    async def compare_runs(req):
        if runs is None:
            raise ValueError("paper run storage is not configured")
        if comparison_lock.locked():
            return web.json_response({"error": "a comparison is already running"}, status=409)
        body = await req.json()
        allowed = {"symbol", "from", "to", "resolution", "cash", "fee_rate", "latency_ms", "rules_mode", "candidates"}
        if not isinstance(body, dict) or body.keys() - allowed:
            raise ValueError("invalid comparison fields")
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
            cost = CostModel(fee, timedelta(milliseconds=latency))
        except (ValueError, TypeError, KeyError, DecimalException):
            raise ValueError("invalid comparison window, cash or costs") from None
        database_path = col.db.c.execute("pragma database_list").fetchone()[2]
        def compute():
            db = MarketDB(Path(database_path), readonly=True)
            try:
                symbol = body.get("symbol")
                if not isinstance(symbol, str) or not db.c.execute(
                    "select 1 from book_top where instrument_id=? limit 1", ("wallex:" + symbol,)
                ).fetchone():
                    raise ValueError("comparison requires an observed symbol")
                result = compare(db, symbol, start, end, body.get("candidates"),
                                 resolution=body.get("resolution", "15min"), cash=cash, cost=cost,
                                 rules_mode=body.get("rules_mode", "point-in-time"), store="demo" if col.demo else "live")
                for record in result["runs"]:
                    save_run(record, runs)
                result["runs"] = [{"run_id": record["run_id"], "inputs": record["inputs"],
                                   "result": {key: record["result"][key] for key in ("strategy", "quote", "end", "fills", "observations", "qualified")},
                                   "warnings": record["warnings"]} for record in result["runs"]]
                return result
            finally:
                db.c.close()
        if comparison_lock.locked():
            return web.json_response({"error": "a comparison is already running"}, status=409)
        async with comparison_lock:
            result = await asyncio.to_thread(compute)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    async def run_list(_):
        return web.json_response([] if runs is None else list_runs(runs))

    async def run_detail(req):
        if runs is None:
            raise web.HTTPNotFound()
        try:
            record = load_run(runs, req.match_info["id"])
        except FileNotFoundError:
            raise web.HTTPNotFound() from None
        if record["evidence"] is None:
            record["evidence"] = economic_report(record)
        return web.json_response(record)

    async def chaos_report_api(req):
        # B2 Fake Venue chaos-suite report written by `gym-chaos`; read-only evidence, never authority.
        try:
            raw = chaos_report.read_bytes() if chaos_report else None
        except FileNotFoundError:
            raw = None
        if raw is None:
            return web.json_response({"state": "NOT_RUN"}, headers={"Cache-Control": "no-store"})
        if len(raw) > 4 * 1024 * 1024:
            return web.json_response({"state": "UNREADABLE"}, status=503, headers={"Cache-Control": "no-store"})
        try:
            report = json.loads(raw)
        except ValueError:
            return web.json_response({"state": "UNREADABLE"}, status=503, headers={"Cache-Control": "no-store"})
        return web.json_response({"state": "REPORTED", **report}, headers={"Cache-Control": "no-store"})

    app = web.Application(middlewares=[guard], client_max_size=1024 * 1024)
    app.add_routes([
        web.get("/", index), web.get("/app.js", browser_asset), web.get("/styles.css", browser_asset),
        web.get("/api/markets", markets), web.get("/api/health", health),
        web.get("/api/account-observations", account_observations),
        web.get("/api/external-order-events", external_events),
        web.get("/api/venue-facts", venue_facts_api), web.get("/api/chaos-report", chaos_report_api),
        web.post("/api/dry-run/ticket", dry_run_ticket),
        web.get("/api/automation-safety", automation_safety),
        web.get("/api/offline-ticket-reviews", offline_ticket_reviews),
        web.get("/api/research", research_setup), web.post("/api/compare", compare_runs),
        web.get("/api/runs", run_list), web.get("/api/runs/{id}", run_detail),
        web.get("/api/check", check), web.get("/api/rules", rule_list), web.get("/api/rules/export", rule_export),
        web.post("/api/rules", rule_put), web.post("/api/rules/import", rule_import),
        web.post("/api/rules/{id}/disable", rule_disable), web.post("/api/rules/{id}/rollback", rule_rollback),
        web.post("/api/presets/{name}", preset),
    ])
    return app
