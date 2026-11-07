"""Calibration data for the paper cost model, from what this machine can actually observe.

Feed latency: venue trade time to local receipt time. Without funded orders this is the closest
measurable stand-in for order round-trip latency, so treat it as a lower bound.
Fill quality: across saved paper runs, how long fills took after decisions and how far the fill
price moved from the decision quote, in basis points.
"""
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import quantiles

from ..adapters.run_store import list_runs, load_run
from ..adapters.store import MarketDB
from ..domain.model import iso, parse_ts


def _percentiles(values: list[float]) -> dict | None:
    if len(values) < 20:
        return None
    cut = quantiles(values, n=100, method="inclusive")
    return {"n": len(values), "p50": round(cut[49], 1), "p90": round(cut[89], 1), "p99": round(cut[98], 1)}


def feed_latency(db: MarketDB, since: datetime) -> dict:
    rows = db.c.execute("""SELECT substr(instrument_id, 8), (julianday(ts_avail) - julianday(ts_event)) * 86400000
                           FROM trades WHERE ts_avail >= ?""", (iso(since),)).fetchall()
    delays = [ms for _, ms in rows if ms is not None]
    by_symbol: dict[str, list[float]] = {}
    for symbol, ms in rows:
        if ms is not None and ms >= 0:
            by_symbol.setdefault(symbol, []).append(ms)
    overall = _percentiles([ms for ms in delays if ms >= 0])
    return {"since": iso(since), "trades": len(delays),
            # Venue time later than receipt means the clocks disagree; latency below that share is not measurable.
            "negative_share": round(sum(ms < 0 for ms in delays) / len(delays), 4) if delays else None,
            "ms": overall, "by_symbol": {s: p for s, values in sorted(by_symbol.items()) if (p := _percentiles(values))},
            "suggested_latency_ms": int(overall["p90"]) if overall else None,
            "basis": "venue trade time to local receipt; a lower bound for order round-trips"}


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
