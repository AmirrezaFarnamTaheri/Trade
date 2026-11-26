"""Read-only diagnostic, quality-calendar, SLO, FX-route, and action-registry API endpoints (M002-M022, U003-U019, O021)."""
from __future__ import annotations

import asyncio
import re
from decimal import Decimal, InvalidOperation

from aiohttp import web

from ..adapters.run_store import load_run
from ..adapters.store import MarketDB
from ..domain.execution_qualification import depth_walk_liquidation, paired_cost_ladder
from ..domain.model import now_utc, parse_ts
from ..services.backup_status import receipt_chronology
from ..services.conversion_route import DIRECTIONS, recommend
from ..services.data_portal import parse_depth
from ..services.market_quality import (
    as_of_rule_index,
    data_eligibility_preflight,
    feed_slo_report,
    ingestion_clock_metrics,
    symbol_quality_calendar,
    time_of_day_liquidity_profile,
)
from ..services.research_process import HEAVY_ACTIONS
from ..services.trial_governance import journal_continuity_report

_SYMBOL = re.compile(r"^[A-Z0-9]{2,24}$")
_RUN_ID = re.compile(r"^[0-9a-f]{16}$")


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


def _parse_symbol(raw: str | None) -> str:
    symbol = (raw or "").upper()
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError("symbol must be 2..24 uppercase alphanumeric characters")
    return symbol


def _parse_int(raw: str, name: str, lo: int, hi: int) -> int:
    try:
        val = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None
    if not lo <= val <= hi:
        raise ValueError(f"{name} must be in {lo}..{hi}")
    return val


def _size_preview_query(db: MarketDB, symbol: str, side: str, qty: Decimal, fee: Decimal) -> dict:
    row = db.c.execute(
        "SELECT ts_avail, bid, ask, bid_qty, ask_qty, depth FROM book_top WHERE instrument_id=? ORDER BY ts_avail DESC LIMIT 1",
        (f"wallex:{symbol}",),
    ).fetchone()
    if not row:
        return {**depth_walk_liquidation(side, qty, None, fee_rate=fee), "symbol": symbol,
                "depth_scope": "UNAVAILABLE", "order_submitted": False, "funded_authority": False}
    ts_avail, bid, ask, bq, aq, raw_depth = row
    parsed = parse_depth(raw_depth)
    if parsed:
        levels = parsed[1] if side == "BUY" else parsed[0]
        scope = "STORED_BOOK_LEVELS"
    else:
        px, sz = (ask, aq) if side == "BUY" else (bid, bq)
        levels = ((Decimal(px), Decimal(sz)),) if px and sz else None
        scope = "TOP_OF_BOOK_ONLY"
    report = depth_walk_liquidation(side, qty, levels, fee_rate=fee, quote_at=parse_ts(ts_avail))
    return {**report, "symbol": symbol, "depth_scope": scope, "order_submitted": False, "funded_authority": False}


def _cost_lab_for_run(runs_dir, run_id: str) -> dict:
    record = load_run(runs_dir, run_id)
    result = record.get("result") or {}
    end = result.get("end") or {}
    perf = (record.get("evidence") or {}).get("performance") or {}
    cash = Decimal(str((record.get("inputs") or {}).get("cash") or "1000"))
    net = Decimal(str(end.get("net") or "0"))
    base_ret = (net / cash) if cash > 0 else Decimal(0)
    dd = Decimal(str(perf.get("max_drawdown_pct") or "0")) / Decimal(100)
    waterfall = end.get("waterfall") or {}
    fee_drag_quote = abs(Decimal(str(waterfall.get("fees") or "0"))) + abs(Decimal(str(waterfall.get("spread") or "0")))
    base_drag_bps = (fee_drag_quote / cash * Decimal("10000")) if cash > 0 else Decimal(0)
    fills = int(result.get("fills") or 0)
    fill_frac = "1" if fills > 0 else "0"
    ladder = paired_cost_ladder([
        {"name": "Recorded paper baseline", "evidence_tier": "MODELED_PAPER_REFERENCE",
         "net_return": str(base_ret.quantize(Decimal("0.000001"))), "max_drawdown": str(dd),
         "fill_fraction": fill_frac, "cost_drag_bps": str(base_drag_bps.quantize(Decimal("0.01")))},
        {"name": "Adverse +50% fee & spread stress", "evidence_tier": "MODELED_PAPER_REFERENCE",
         "net_return": str((base_ret - (fee_drag_quote * Decimal("0.5") / cash if cash > 0 else Decimal(0))).quantize(Decimal("0.000001"))),
         "max_drawdown": str(dd), "fill_fraction": fill_frac,
         "cost_drag_bps": str((base_drag_bps * Decimal("1.5")).quantize(Decimal("0.01")))},
        {"name": "Adverse 2x cost stress", "evidence_tier": "MODELED_PAPER_REFERENCE",
         "net_return": str((base_ret - (fee_drag_quote / cash if cash > 0 else Decimal(0))).quantize(Decimal("0.000001"))),
         "max_drawdown": str(dd), "fill_fraction": fill_frac,
         "cost_drag_bps": str((base_drag_bps * Decimal("2")).quantize(Decimal("0.01")))},
    ])
    return {"run_id": run_id, "symbol": result.get("symbol"), "strategy": result.get("strategy"),
            "diagnostic_only": True, "funded_authority": False, **ladder}


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
        backup = await asyncio.to_thread(receipt_chronology, root, now=now)
        return web.json_response({"slo": slo, "journal_continuity": cont, "backup_chronology": backup,
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

    async def liquidity_profile_api(req: web.Request):
        symbol = _parse_symbol(req.query.get("symbol"))
        days = _parse_int(req.query.get("days", "14"), "days", 1, 90)
        now = now_utc()
        profile = await asyncio.to_thread(
            _with_readonly_market, api.market_path, lambda db: time_of_day_liquidity_profile(db, symbol, days=days, now=now)
        )
        return web.json_response({**profile, "read_only": True, "funded_authority": False})

    async def size_preview_api(req: web.Request):
        symbol = _parse_symbol(req.query.get("symbol"))
        side = (req.query.get("side") or "SELL").upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        try:
            qty = Decimal(req.query.get("qty", ""))
            fee = Decimal(req.query.get("fee", "0.001"))
        except InvalidOperation:
            raise ValueError("qty and fee must be exact decimal strings") from None
        if not qty.is_finite() or qty <= 0 or not fee.is_finite() or not 0 <= fee < 1:
            raise ValueError("qty must be > 0 and fee in [0, 1)")
        result = await asyncio.to_thread(_with_readonly_market, api.market_path, lambda db: _size_preview_query(db, symbol, side, qty, fee))
        return web.json_response({**result, "read_only": True})

    async def preflight_api(req: web.Request):
        symbol = _parse_symbol(req.query.get("symbol"))
        days = _parse_int(req.query.get("days", "14"), "days", 1, 90)
        min_bars = _parse_int(req.query.get("min_bars", "20"), "min_bars", 1, 10000)
        now = now_utc()
        result = await asyncio.to_thread(
            _with_readonly_market, api.market_path, lambda db: data_eligibility_preflight(db, symbol, days=days, min_bars=min_bars, now=now)
        )
        return web.json_response({**result, "read_only": True})

    async def cost_lab_api(req: web.Request):
        run_id = req.query.get("run_id") or ""
        if not _RUN_ID.fullmatch(run_id) or api.runs is None:
            raise ValueError("valid 16-hex run_id is required")
        result = await asyncio.to_thread(_cost_lab_for_run, api.runs, run_id)
        return web.json_response({**result, "read_only": True})

    app.add_routes([
        web.get("/api/quality-calendar", quality_calendar),
        web.get("/api/slo", slo_api),
        web.get("/api/fx-route", fx_route_api),
        web.get("/api/action-registry", action_registry_api),
        web.get("/api/liquidity-profile", liquidity_profile_api),
        web.get("/api/size-preview", size_preview_api),
        web.get("/api/preflight", preflight_api),
        web.get("/api/cost-lab", cost_lab_api),
    ])
