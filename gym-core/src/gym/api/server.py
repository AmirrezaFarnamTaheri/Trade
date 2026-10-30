"""Loopback-only local API and static UI."""
from __future__ import annotations

import hmac
import json
from pathlib import Path

from aiohttp import web

from ..domain.model import TOMAN, iso, parse_ts
from ..services.collector import Collector, now_utc
from ..services.rules import RuleService

UI = Path(__file__).resolve().parent.parent / "ui" / "index.html"
LOOPBACK = {"127.0.0.1", "localhost"}


def s(x):
    return None if x is None else str(x)


def make_app(col: Collector, rules: RuleService, token: str) -> web.Application:
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

    async def markets(_):
        now, rows = now_utc(), []
        for sym, inst in col.insts.items():
            t = col.tops.get(sym)
            last = col.trades[sym][0] if col.trades[sym] else None
            rows.append({
                "symbol": sym, "base": inst.base, "quote": inst.quote, "names": col.names[sym],
                "bid": s(t and t.bid), "ask": s(t and t.ask), "bid_qty": s(t and t.bid_qty), "ask_qty": s(t and t.ask_qty),
                "spread": s(t and t.spread), "spread_bps": s(t and t.spread_bps), "flags": sorted(t.flags) if t else ["STALE"],
                "book_age_s": None if not t or not col.books[sym]["bid"] else round((now - col.books[sym]["bid"].ts).total_seconds()),
                "last_trade": last and {"price": s(last.price), "qty": s(last.qty), "aggressor": last.aggressor, "ts": iso(last.ts_event)},
                "unit": {"code": TOMAN.code, "epoch": TOMAN.unit_epoch} if inst.quote == "TMN" else None,
                "act": rules.act(inst, now),
            })
        return web.json_response({"now": iso(now), "demo": col.demo, "markets": rows})

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
            "quality": [dict(zip(("ts", "instrument", "flag", "detail"), r)) for r in col.db.quality(30)],
        })

    app = web.Application(middlewares=[guard], client_max_size=1024 * 1024)
    app.add_routes([
        web.get("/", index), web.get("/api/markets", markets), web.get("/api/health", health),
        web.get("/api/check", check), web.get("/api/rules", rule_list), web.get("/api/rules/export", rule_export),
        web.post("/api/rules", rule_put), web.post("/api/rules/import", rule_import),
        web.post("/api/rules/{id}/disable", rule_disable), web.post("/api/rules/{id}/rollback", rule_rollback),
        web.post("/api/presets/{name}", preset),
    ])
    return app
