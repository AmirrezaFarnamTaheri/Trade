"""Calibration data for the paper cost model, from what this machine can actually observe.

Feed latency: venue trade time to local receipt time. Without funded orders this is the closest
measurable stand-in for order round-trip latency, so treat it as a lower bound.
Fill quality: across saved paper runs, how long fills took after decisions and how far the fill
price moved from the decision quote, in basis points.
"""
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import quantiles

from ..adapters.run_store import list_runs, load_run
from ..adapters.store import MarketDB
from ..domain.market_models import fields, instant
from ..domain.model import iso, parse_ts
from ..domain.strategy import digest


def _percentiles(values: list[float]) -> dict | None:
    if len(values) < 20:
        return None
    cut = quantiles(values, n=100, method="inclusive")
    return {"n": len(values), "p50": round(cut[49], 1), "p90": round(cut[89], 1), "p99": round(cut[98], 1)}


def feed_latency(db: MarketDB, since: datetime, *, until=None, symbol=None) -> dict:
    until = until or datetime.now(UTC)
    rows = db.c.execute("""SELECT substr(instrument_id, 8), ts_event, ts_avail,
                           (julianday(ts_avail) - julianday(ts_event)) * 86400000
                           FROM trades WHERE ts_avail >= ? AND ts_avail < ?
                           AND (? IS NULL OR instrument_id=?) ORDER BY ts_avail,instrument_id,ts_event LIMIT 100001""",
                           (iso(since), iso(until), symbol, "wallex:" + symbol if symbol else None)).fetchall()
    if len(rows) > 100000:
        raise ValueError("calibration exceeds 100000 observations; narrow the receipt window")
    delays = [ms for _, _, _, ms in rows if ms is not None]
    by_symbol: dict[str, list[float]] = {}
    for market, _, _, ms in rows:
        if ms is not None and ms >= 0:
            by_symbol.setdefault(market, []).append(ms)
    overall = _percentiles([ms for ms in delays if ms >= 0])
    return {"since": iso(since), "until": iso(until), "trades": len(delays),
            "negative_samples": sum(ms < 0 for ms in delays),
            "last_receipt": max((row[2] for row in rows), default=None), "data_digest": digest(rows),
            # Venue time later than receipt means the clocks disagree; latency below that share is not measurable.
            "negative_share": round(sum(ms < 0 for ms in delays) / len(delays), 4) if delays else None,
            "ms": overall, "by_symbol": {s: p for s, values in sorted(by_symbol.items()) if (p := _percentiles(values))},
            "suggested_latency_ms": int(overall["p90"]) if overall else None,
            "basis": "venue trade time to local receipt; a lower bound for order round-trips"}


def calibration_report(db, request, *, store, at=None):
    fields(request, "symbol from to max_age_seconds")
    symbol = request["symbol"]
    if symbol is not None and (type(symbol) is not str or not re.fullmatch(r"[A-Z0-9]{2,24}", symbol)):
        raise ValueError("calibration needs one market symbol or null for the whole recorded universe")
    if store not in ("live", "demo") or type(request["max_age_seconds"]) is not int or not 1 <= request["max_age_seconds"] <= 86400:
        raise ValueError("invalid calibration store or freshness limit")
    start, end, clock = instant(request["from"]), instant(request["to"]), at or datetime.now(UTC)
    if not start < end <= clock or end - start > timedelta(days=31):
        raise ValueError("calibration needs a historical receipt window of at most 31 days")
    if db.c.in_transaction:
        raise ValueError("calibration requires its own read snapshot")
    db.c.execute("BEGIN")
    try:
        observed = feed_latency(db, start, until=end, symbol=symbol)
    finally:
        db.c.rollback()
    age = (clock - parse_ts(observed["last_receipt"])).total_seconds() if observed["last_receipt"] else None
    status = ("SYNTHETIC" if store == "demo" else "INSUFFICIENT_DATA" if observed["ms"] is None else
              "CLOCK_DISAGREEMENT" if observed["negative_samples"] else
              "STALE" if age is None or age > request["max_age_seconds"] else "PUBLIC_FEED_ONLY")
    result = {"schema": "execution-calibration/1", "store": store, "synthetic": store == "demo",
        "as_of": iso(clock), "request": request, "status": status, "observations": observed,
        "last_receipt_age_seconds": age,
        "candidate_latency_ms": observed["suggested_latency_ms"] if status == "PUBLIC_FEED_ONLY" and symbol else None,
        "fee_rate": None, "slippage_bps": None, "automatic_application": False,
        "execution_costs_verified": False, "funded_authority": False,
        "limits": ["Public venue-event to local-receipt timing is a lower-bound proxy, not authenticated order round-trip latency.",
                   "At least 20 nonnegative samples, the declared freshness limit and no negative-clock observations are required for a candidate.",
                   "Whole-market percentiles mix markets and never propose one shared execution latency.",
                   "Paper fill timing and modeled fees are not independent execution measurements. Fee and slippage remain unknown.",
                   "No assumption is applied automatically; explicitly chosen paper costs remain operator assumptions."]}
    result["report_id"] = digest(result)[:16]
    return result


def fill_quality(runs: Path, limit: int = 200) -> dict:
    delays, slippage, spread, nonfills = [], [], [], {}
    for row in list_runs(runs, limit=limit):
        record = load_run(runs, row["run_id"])
        for order in record["result"].get("orders", []):
            if order.get("status") == "NONFILL":
                nonfills[order.get("reason", "UNKNOWN")] = nonfills.get(order.get("reason", "UNKNOWN"), 0) + 1
                continue
            if order.get("status") != "FILLED" or "costs" not in order:
                continue
            delays.append((parse_ts(order["fill_time"]) - parse_ts(order["decision_time"])).total_seconds() * 1000)
            notional = Decimal(order["qty"]) * Decimal(order["price"])
            if notional > 0:
                slippage.append(float(Decimal(order["costs"]["latency_drift"]) / notional * 10000))
                spread.append(float(Decimal(order["costs"]["spread"]) / notional * 10000))
    return {"fills": len(delays), "decision_to_fill_ms": _percentiles(delays),
            "latency_drift_bps": _percentiles(slippage), "spread_cost_bps": _percentiles(spread), "nonfills": nonfills}
