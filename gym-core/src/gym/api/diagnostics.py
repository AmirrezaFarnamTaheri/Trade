"""Read-only diagnostic, quality-calendar, SLO, FX-route, and action-registry API endpoints (M002-M022, U003-U019, O021)."""
from __future__ import annotations

import asyncio
import re
from decimal import Decimal, InvalidOperation

from aiohttp import web

from ..adapters.store import MarketDB
from ..domain.model import now_utc
from ..services.conversion_route import DIRECTIONS, recommend
from ..services.market_quality import (
    as_of_rule_index,
    feed_slo_report,
    ingestion_clock_metrics,
    symbol_quality_calendar,
)
from ..services.research_process import HEAVY_ACTIONS
from ..services.trial_governance import journal_continuity_report

_SYMBOL = re.compile(r"^[A-Z0-9]{2,24}$")


def _attention_items(slo: dict, continuity: dict | None) -> list[dict]:
    """Rank concrete operator next actions by severity and dependency (U008)."""
    items = []
    for breach in slo.get("breaches", []):
        severity = "HIGH" if breach in ("PUBLICATION_STALE_OVER_10M", "STORAGE_RUNWAY_LOW") else "MEDIUM"
        items.append({"severity": severity, "source": "feed_slo", "code": breach})
    if continuity:
        for key in ("btc_daily_trend", "passive_mix", "breadth_trend"):
            row = continuity.get(key) or {}
            status = row.get("evidence_status")
            if status in ("GAP_DETECTED", "BROKEN_DUPLICATE"):
                items.append({
                    "severity": "HIGH" if status == "BROKEN_DUPLICATE" else "MEDIUM",
                    "source": key,
                    "code": status,
                    "missing_days": row.get("missing_days_through_yesterday"),
                })
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(items, key=lambda item: (order.get(item["severity"], 9), item["source"]))


def _with_readonly_market(path, fn):
    db = MarketDB(path, readonly=True)
    try:
        return fn(db)
    finally:
        db.c.close()


def install(app: web.Application, api) -> None:
    """Install token-gated read-only diagnostic routes with zero order or filesystem authority."""

    async def quality_calendar(req: web.Request):
        symbol = (req.query.get("symbol") or "").upper()
        if not _SYMBOL.fullmatch(symbol):
            raise ValueError("symbol must be 2..24 uppercase alphanumeric characters")
        try:
            days = int(req.query.get("days", "14"))
        except ValueError:
            raise ValueError("days must be an integer") from None
        now = now_utc()

        def _query(db):
            return (
                symbol_quality_calendar(db, symbol, days=days, now=now),
                as_of_rule_index(db, symbol),
                ingestion_clock_metrics(db, symbol=symbol, limit=2000),
            )

        cal, vintages, clocks = await asyncio.to_thread(_with_readonly_market, api.market_path, _query)
        return web.json_response({"calendar": cal, "rule_vintages": vintages, "ingestion_clocks": clocks,
                                  "read_only": True, "funded_authority": False})

    async def slo_api(_req: web.Request):
        now = now_utc()
        root = api.runs.parent if api.runs is not None else api.market_path.parent
        slo = await asyncio.to_thread(_with_readonly_market, api.market_path, lambda db: feed_slo_report(db, root, now=now))
        cont = await asyncio.to_thread(journal_continuity_report, root, now=now) if api.runs is not None else None
        return web.json_response({"slo": slo, "journal_continuity": cont,
                                  "attention": _attention_items(slo, cont),
                                  "read_only": True, "funded_authority": False})

    async def fx_route_api(req: web.Request):
        direction = req.query.get("direction", "TMN_TO_USDT")
        if direction not in DIRECTIONS:
            raise ValueError("direction must be TMN_TO_USDT or USDT_TO_TMN")
        try:
            amount = Decimal(req.query.get("amount", ""))
            fee = Decimal(req.query.get("fee", "0.001"))
        except InvalidOperation:
            raise ValueError("amount and fee must be exact decimal strings") from None
        if not amount.is_finite() or amount <= 0 or not fee.is_finite() or not 0 <= fee < 1:
            raise ValueError("amount must be > 0 and fee must be in [0, 1)")
        now = now_utc()
        result = await asyncio.to_thread(
            _with_readonly_market, api.market_path, lambda db: recommend(db, amount, direction, now, fee=fee)
        )
        return web.json_response({**result, "read_only": True, "funded_authority": False})

    async def action_registry_api(_req: web.Request):
        from ..services.research_actions import (
            CLI_ACTIONS,
            CLI_ONLY_ACTIONS,
            OBJECT_ACTIONS,
            WORKSPACE_ACTIONS,
        )

        workspace_set = set(WORKSPACE_ACTIONS)
        manifest = [
            {
                "action": name,
                "browser_allowed": name in workspace_set,
                "requires_object_body": name in OBJECT_ACTIONS,
                "heavy_subprocess_isolated": name in HEAVY_ACTIONS,
                "cli_only_reason": CLI_ONLY_ACTIONS.get(name),
                "authority": "PAPER_RESEARCH_ONLY",
                "funded_authority": False,
            }
            for name in sorted(CLI_ACTIONS)
        ]
        return web.json_response({
            "schema": "action-registry/1",
            "count": len(manifest),
            "actions": manifest,
            "arbitrary_subprocess": False,
            "funded_authority": False,
        })

    app.add_routes([
        web.get("/api/quality-calendar", quality_calendar),
        web.get("/api/slo", slo_api),
        web.get("/api/fx-route", fx_route_api),
        web.get("/api/action-registry", action_registry_api),
    ])
