"""Market-data ingestion clocks, raw-SQL provenance, rule vintages, quality calendar, and feed SLOs (M002-M022, C008)."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ..adapters.store import MIN_FREE_BYTES, MarketDB
from ..domain.model import iso, parse_ts

_REQUIRED_SPEC_FIELDS = ("stepSize", "minQty", "minNotional", "isMarketTypeEnable")


def _percentile(ordered: list[float], pct: float) -> float | None:
    if not ordered:
        return None
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(ordered[idx], 3)


def ingestion_clock_metrics(db: MarketDB, *, symbol: str | None = None, since: datetime | None = None, limit: int = 5000) -> dict:
    """Measure event -> availability lag distribution and backward provider clock anomalies (M002, M010)."""
    clauses, params = [], []
    if symbol:
        clauses.append("instrument_id=?")
        params.append(f"wallex:{symbol}")
    if since:
        clauses.append("ts_avail>=?")
        params.append(iso(since))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db.c.execute(
        f"SELECT ts_event, ts_avail FROM trades{where} ORDER BY rowid DESC LIMIT ?",
        (*params, limit),
    ).fetchall()
    lags, backward = [], 0
    for ts_event, ts_avail in rows:
        if not ts_event or not ts_avail:
            continue
        delta_ms = (parse_ts(ts_avail) - parse_ts(ts_event)).total_seconds() * 1000.0
        if delta_ms < 0:
            backward += 1
        lags.append(delta_ms)
    lags.sort()
    return {
        "samples": len(lags),
        "backward_event_count": backward,
        "lag_ms": {
            "p50": _percentile(lags, 0.50),
            "p95": _percentile(lags, 0.95),
            "p99": _percentile(lags, 0.99),
            "max": round(lags[-1], 3) if lags else None,
        },
        "clock_skew_warning": backward > 0,
    }


def _find_segment_file(seg_id: str, roots: list[Path]) -> Path | None:
    for root in roots:
        candidate = root / seg_id
        if candidate.is_file():
            return candidate
    return None


def verify_raw_sql_provenance(db: MarketDB, raw_roots: list[Path], *, symbol: str | None = None, limit: int = 500) -> dict:
    """Verify trades/book_top seg_ref pointers map to closed archived segments with intact SHA-256 digests (M006)."""
    seg_rows = {
        row[0]: {"sha256": row[1], "closed_at": row[2]}
        for row in db.c.execute("SELECT seg_id, sha256, closed_at FROM segments").fetchall()
    }
    where = " WHERE instrument_id=?" if symbol else ""
    params = (f"wallex:{symbol}", limit) if symbol else (limit,)
    refs = db.c.execute(f"SELECT DISTINCT seg_ref FROM trades{where} ORDER BY rowid DESC LIMIT ?", params).fetchall()
    checked, broken, unclosed, digest_cache = 0, [], [], {}
    for (seg_ref,) in refs:
        if not seg_ref:
            continue
        seg_id = seg_ref.split("#", 1)[0]
        checked += 1
        meta = seg_rows.get(seg_id)
        if not meta:
            broken.append({"seg_id": seg_id, "reason": "UNREGISTERED_SEGMENT"})
            continue
        if not meta["closed_at"]:
            unclosed.append(seg_id)
            continue
        if seg_id not in digest_cache:
            path = _find_segment_file(seg_id, raw_roots)
            if path is None:
                digest_cache[seg_id] = "MISSING_FILE"
            else:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
                digest_cache[seg_id] = "OK" if actual == meta["sha256"] else "DIGEST_MISMATCH"
        if digest_cache[seg_id] != "OK":
            broken.append({"seg_id": seg_id, "reason": digest_cache[seg_id]})
    return {
        "status": "PASS" if not broken else "FAIL",
        "references_checked": checked,
        "broken": broken,
        "unclosed_referenced": sorted(set(unclosed)),
        "qualified_for_replay": not broken and not unclosed,
    }


def as_of_rule_index(db: MarketDB, symbol: str) -> dict:
    """List point-in-time market rule vintages with explicit missingness (M008, U011)."""
    rows = db.c.execute(
        "SELECT valid_from, valid_to, spec, source FROM instrument_specs WHERE instrument_id=? ORDER BY valid_from",
        (f"wallex:{symbol}",),
    ).fetchall()
    vintages = []
    for valid_from, valid_to, raw_spec, source in rows:
        spec = json.loads(raw_spec) if raw_spec else {}
        missing = [f for f in _REQUIRED_SPEC_FIELDS if spec.get(f) is None]
        vintages.append({
            "valid_from": valid_from,
            "valid_to": valid_to,
            "source": source,
            "step_size": spec.get("stepSize"),
            "min_qty": spec.get("minQty"),
            "min_notional": spec.get("minNotional"),
            "market_order_enabled": spec.get("isMarketTypeEnable"),
            "zero_fee": spec.get("is_zero_fee"),
            "missing_fields": missing,
            "complete": not missing,
        })
    return {"symbol": symbol, "vintage_count": len(vintages), "vintages": vintages}


def symbol_quality_calendar(db: MarketDB, symbol: str, *, days: int = 14, now: datetime | None = None) -> dict:
    """Build per-UTC-day source completeness, freshness, and anomaly calendar for one symbol (M011, M012, M019, U012)."""
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError("days must be an integer in 1..90")
    end = (now or datetime.now(UTC)).astimezone(UTC)
    start_day = end.date() - timedelta(days=days - 1)
    start_iso = f"{start_day.isoformat()}T00:00:00.000000Z"
    iid = f"wallex:{symbol}"

    book_rows = db.c.execute(
        "SELECT substr(ts_avail, 1, 10) AS d, count(*), sum(CASE WHEN flags='' OR flags IS NULL THEN 1 ELSE 0 END) "
        "FROM book_top WHERE instrument_id=? AND ts_avail>=? GROUP BY d",
        (iid, start_iso),
    ).fetchall()
    trade_rows = db.c.execute(
        "SELECT substr(ts_avail, 1, 10) AS d, count(*) FROM trades WHERE instrument_id=? AND ts_avail>=? GROUP BY d",
        (iid, start_iso),
    ).fetchall()
    qual_rows = db.c.execute(
        "SELECT substr(ts, 1, 10) AS d, flag, count(*) FROM quality_events WHERE instrument_id=? AND ts>=? GROUP BY d, flag",
        (iid, start_iso),
    ).fetchall()

    books = {d: (total, clean) for d, total, clean in book_rows}
    trades = dict(trade_rows)
    anomalies: dict[str, dict[str, int]] = {}
    for d, flag, cnt in qual_rows:
        anomalies.setdefault(d, {})[flag] = cnt

    calendar = []
    for offset in range(days):
        day_str = (start_day + timedelta(days=offset)).isoformat()
        q_total, q_clean = books.get(day_str, (0, 0))
        t_cnt = trades.get(day_str, 0)
        day_anom = anomalies.get(day_str, {})
        has_gap = day_anom.get("GAP", 0) > 0 or day_anom.get("SOURCE_ERROR", 0) > 0
        completeness = "NO_DATA" if q_total == 0 and t_cnt == 0 else "PARTIAL_GAPPED" if has_gap else "OBSERVED"
        calendar.append({
            "date": day_str,
            "quotes": q_total,
            "clean_quotes": q_clean,
            "trades": t_cnt,
            "anomalies": day_anom,
            "completeness_status": completeness,
        })
    latest = db.c.execute("SELECT ts_avail FROM book_top WHERE instrument_id=? ORDER BY ts_avail DESC LIMIT 1", (iid,)).fetchone()
    fresh_age_s = (end - parse_ts(latest[0])).total_seconds() if latest else None
    freshness = "UNKNOWN" if fresh_age_s is None else "FRESH" if fresh_age_s <= 120 else "STALE"
    return {
        "symbol": symbol,
        "days": days,
        "freshness_status": freshness,
        "latest_quote_age_seconds": round(fresh_age_s, 1) if fresh_age_s is not None else None,
        "calendar": calendar,
    }


def feed_slo_report(db: MarketDB, root: Path, *, now: datetime | None = None) -> dict:
    """Evaluate provenance-based feed SLOs and 24h reliability scorecard (M014, M022, O021)."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    since_24h = at - timedelta(hours=24)
    clocks = ingestion_clock_metrics(db, since=since_24h, limit=2000)
    pub = db.c.execute("SELECT through FROM collector_publication WHERE singleton=1").fetchone()
    pub_age_s = (at - parse_ts(pub[0])).total_seconds() if pub else None
    unclosed = [r[0] for r in db.c.execute("SELECT seg_id FROM segments WHERE closed_at IS NULL").fetchall()]
    live_prefix = at.strftime("%Y%m%d/%H-")
    stale_unclosed = [s for s in unclosed if not s.startswith(live_prefix)]
    probe = root / "raw" if (root / "raw").exists() else root
    free_gib = round(shutil.disk_usage(probe).free / (1024**3), 2) if probe.exists() else None
    errors_24h = db.c.execute(
        "SELECT count(*) FROM quality_events WHERE flag='SOURCE_ERROR' AND ts>=?",
        (iso(since_24h),),
    ).fetchone()[0]
    breaches = []
    if pub_age_s is None or pub_age_s > 600:
        breaches.append("PUBLICATION_STALE_OVER_10M")
    if clocks["lag_ms"]["p95"] is not None and clocks["lag_ms"]["p95"] > 5000:
        breaches.append("INGESTION_P95_LAG_OVER_5S")
    if stale_unclosed:
        breaches.append("STALE_UNCLOSED_SEGMENTS")
    if free_gib is not None and free_gib < (MIN_FREE_BYTES / (1024**3)) * 2:
        breaches.append("STORAGE_RUNWAY_LOW")
    return {
        "as_of": iso(at),
        "status": "BREACH" if breaches else "WITHIN_SLO",
        "breaches": breaches,
        "publication_age_seconds": round(pub_age_s, 1) if pub_age_s is not None else None,
        "ingestion_clocks_24h": clocks,
        "stale_unclosed_segments": stale_unclosed,
        "source_errors_24h": errors_24h,
        "free_disk_gib": free_gib,
    }


def parse_structured_fee(payload: dict, *, fetched_at: datetime) -> dict:
    """Parse Wallex /v2/structured-fee tiers into dated exact-Decimal fee vintages (M009)."""
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise ValueError("invalid structured-fee payload")
    tiers = {}
    for market_group, rows in result.items():
        if not isinstance(rows, list):
            continue
        parsed_rows = []
        for row in rows:
            if not isinstance(row, dict) or "maker_fee" not in row or "taker_fee" not in row:
                continue
            maker, taker = Decimal(str(row["maker_fee"])), Decimal(str(row["taker_fee"]))
            if not (0 <= maker < 1 and 0 <= taker < 1):
                raise ValueError("structured fee rate out of [0, 1)")
            parsed_rows.append({"level": row.get("level"), "maker": str(maker), "taker": str(taker)})
        if parsed_rows:
            tiers[str(market_group)] = parsed_rows
    if not tiers:
        raise ValueError("no valid fee tiers in structured-fee payload")
    return {"schema": "structured-fee-vintage/1", "fetched_at": iso(fetched_at), "groups": tiers}


def parse_margin_ratio(symbol: str, payload: dict, *, fetched_at: datetime) -> dict:
    """Parse Wallex public /public/ratio/{market} long/short ratio with explicit source limits (C008)."""
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise ValueError("invalid public margin ratio payload")
    long_raw = result.get("long", result.get("long_ratio"))
    short_raw = result.get("short", result.get("short_ratio"))
    if long_raw is None or short_raw is None:
        raise ValueError("margin ratio requires long and short fields")
    long_r, short_r = Decimal(str(long_raw)), Decimal(str(short_raw))
    if not (long_r.is_finite() and short_r.is_finite() and long_r >= 0 and short_r >= 0):
        raise ValueError("margin ratios must be finite and nonnegative")
    return {
        "schema": "public-margin-ratio/1",
        "symbol": symbol,
        "fetched_at": iso(fetched_at),
        "long_ratio": str(long_r),
        "short_ratio": str(short_r),
        "account_borrow_eligibility_established": False,
    }
