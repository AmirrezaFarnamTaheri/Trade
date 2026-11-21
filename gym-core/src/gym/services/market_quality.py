"""Market-data ingestion clocks, raw-SQL provenance, rule vintages, quality calendar, and feed SLOs (M002-M022, C008)."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import zstandard as zstd

from ..adapters.store import MIN_FREE_BYTES, MarketDB, iter_segment
from ..adapters.wallex import parse_channel
from ..domain.model import TradeTick, iso, loads, parse_ts

_REQUIRED_SPEC_FIELDS = ("stepSize", "minQty", "minNotional", "isMarketTypeEnable")
_TEHRAN = timezone(timedelta(hours=3, minutes=30))


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
        candidate = (root / seg_id).resolve()
        if candidate.is_relative_to(root.resolve()) and candidate.is_file():
            return candidate
    return None


def _raw_trade_keys(frame):
    at = parse_ts(frame["t"])
    def key(symbol, data):
        tick = TradeTick.wallex(symbol, data, at)
        return (f"wallex:{tick.symbol}", iso(tick.ts_event), iso(at), str(tick.price), str(tick.qty), tick.aggressor)

    if frame["src"].startswith("rest:/v1/trades?symbol="):
        symbol = frame["src"].split("=", 1)[1]
        for data in loads(frame["raw"])["result"]["latestTrades"]:
            yield key(symbol, data)
        return
    if frame["src"] != "ws":
        return
    for line in frame["raw"].splitlines():
        if not line.strip():
            continue
        push = loads(line).get("push") or {}
        channel = parse_channel(push.get("channel", ""))
        if channel and channel[0] == "trade" and "pub" in push:
            yield key(channel[1], push["pub"]["data"])


def verify_raw_sql_provenance(db: MarketDB, raw_roots: list[Path], *, symbol: str | None = None, limit: int = 500) -> dict:
    """Verify trades/book_top seg_ref pointers map to closed archived segments with intact SHA-256 digests (M006)."""
    seg_rows = {
        row[0]: {"sha256": row[1], "closed_at": row[2]}
        for row in db.c.execute("SELECT seg_id, sha256, closed_at FROM segments").fetchall()
    }
    where = " WHERE instrument_id=?" if symbol else ""
    params = (f"wallex:{symbol}", limit) if symbol else (limit,)
    refs = [
        (source, seg_ref, tuple(fields))
        for source, columns in (("trades", "seg_ref,instrument_id,ts_event,ts_avail,price,qty,aggressor"), ("book_top", "depth_ref"))
        for seg_ref, *fields in db.c.execute(
            f"SELECT {columns} FROM {source}{where} ORDER BY ts_avail DESC, rowid DESC LIMIT ?", params
        )
    ]
    checked, broken, unclosed = 0, [], []
    sequences = defaultdict(set)
    trades = defaultdict(Counter)
    matched_trades = legacy_rest_trades = 0
    for source, seg_ref, fields in refs:
        if not seg_ref:
            broken.append({"source": source, "reason": "MISSING_REFERENCE"})
            continue
        seg_id, marker, raw_sequence = seg_ref.partition("#")
        checked += 1
        if not marker or not raw_sequence.isascii() or not raw_sequence.isdigit() or len(raw_sequence) > 18:
            broken.append({"source": source, "seg_id": seg_id, "reason": "INVALID_FRAME_REFERENCE"})
            continue
        sequences[seg_id].add(int(raw_sequence))
        if source == "trades":
            trades[(seg_id, int(raw_sequence))][fields] += 1
    for seg_id, wanted in sequences.items():
        meta = seg_rows.get(seg_id)
        if not meta:
            broken.append({"seg_id": seg_id, "reason": "UNREGISTERED_SEGMENT"})
            continue
        if not meta["closed_at"]:
            unclosed.append(seg_id)
            continue
        path = _find_segment_file(seg_id, raw_roots)
        if path is None:
            broken.append({"seg_id": seg_id, "reason": "MISSING_FILE"})
            continue
        try:
            with path.open("rb") as archive:
                actual = hashlib.file_digest(archive, "sha256").hexdigest()
            if actual != meta["sha256"]:
                broken.append({"seg_id": seg_id, "reason": "DIGEST_MISMATCH"})
                continue
            seen = set()
            for frame in iter_segment(path):
                sequence = frame["seq"]
                if sequence not in wanted:
                    continue
                if sequence in seen or hashlib.sha256(frame["raw"].encode()).hexdigest() != frame["sha256"]:
                    broken.append({"seg_id": seg_id, "sequence": sequence, "reason": "INVALID_RAW_FRAME"})
                elif expected := trades.get((seg_id, sequence)):
                    if frame["src"] == "rest:/v1/trades":
                        legacy_rest_trades += expected.total()
                    else:
                        actual_trades = Counter(_raw_trade_keys(frame))
                        matched_trades += (expected & actual_trades).total()
                        if expected - actual_trades:
                            broken.append({"seg_id": seg_id, "sequence": sequence, "reason": "TRADE_CONTENT_MISMATCH"})
                seen.add(sequence)
            broken.extend({"seg_id": seg_id, "sequence": sequence, "reason": "MISSING_RAW_FRAME"}
                          for sequence in sorted(wanted - seen))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ArithmeticError, zstd.ZstdError):
            broken.append({"seg_id": seg_id, "reason": "UNREADABLE_ARCHIVE"})
    return {
        "status": "NO_EVIDENCE" if not refs else "FAIL" if broken or unclosed else "PASS",
        "scope": "RECENT_SAMPLE_PER_SOURCE",
        "sample_verified": checked > 0 and not broken and not unclosed,
        "references_checked": checked,
        "trade_rows_content_matched": matched_trades,
        "legacy_rest_trade_rows_missing_request_symbol": legacy_rest_trades,
        "broken": broken,
        "unclosed_referenced": sorted(set(unclosed)),
        "qualified_for_replay": False,
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


def cross_check_feeds(
    *,
    primary_symbol: str,
    secondary_symbol: str,
    primary_quote: str,
    secondary_quote: str,
    primary_price: Decimal,
    secondary_price: Decimal,
    primary_at: datetime,
    secondary_at: datetime,
    max_clock_skew_s: float = 60.0,
    max_diff_bps: Decimal = Decimal("50"),
    corporate_action_note: str | None = None,
) -> dict:
    """Compare two feeds only after normalizing quote currency, event clocks, and corporate actions (M018)."""
    if primary_price <= 0 or secondary_price <= 0:
        raise ValueError("feed prices must be positive")
    if primary_quote.upper() != secondary_quote.upper():
        return {"status": "INCOMPARABLE_QUOTE_CURRENCY", "contradictory": False,
                "primary": primary_symbol, "secondary": secondary_symbol,
                "reason": f"{primary_quote} vs {secondary_quote} requires dated FX route"}
    skew_s = abs((primary_at.astimezone(UTC) - secondary_at.astimezone(UTC)).total_seconds())
    if skew_s > max_clock_skew_s:
        return {"status": "CLOCK_MISMATCH", "contradictory": False,
                "clock_skew_seconds": round(skew_s, 3), "max_clock_skew_s": max_clock_skew_s}
    diff_bps = abs(primary_price - secondary_price) / secondary_price * Decimal("10000")
    if corporate_action_note:
        return {"status": "CORPORATE_ACTION_DISCLOSED", "contradictory": False,
                "diff_bps": str(diff_bps.quantize(Decimal("0.01"))), "note": corporate_action_note}
    contradictory = diff_bps > max_diff_bps
    return {
        "status": "DIVERGENT" if contradictory else "ALIGNED",
        "contradictory": contradictory,
        "clock_skew_seconds": round(skew_s, 3),
        "diff_bps": str(diff_bps.quantize(Decimal("0.01"))),
    }


def time_of_day_liquidity_profile(db: MarketDB, symbol: str, *, days: int = 14, now: datetime | None = None) -> dict:
    """Compute Tehran-hour spread bps and touch size medians with explicit sample counts (U013)."""
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError("days must be an integer in 1..90")
    end = (now or datetime.now(UTC)).astimezone(UTC)
    start_iso = iso(end - timedelta(days=days))
    rows = db.c.execute(
        "SELECT ts_avail, bid, ask, bid_qty, ask_qty FROM book_top "
        "WHERE instrument_id=? AND ts_avail>=? AND (flags='' OR flags IS NULL) ORDER BY ts_avail DESC LIMIT 20000",
        (f"wallex:{symbol}", start_iso),
    ).fetchall()
    buckets: dict[int, tuple[list[float], list[float], list[float]]] = {h: ([], [], []) for h in range(24)}
    for ts_avail, bid_s, ask_s, bq_s, aq_s in rows:
        if not bid_s or not ask_s:
            continue
        bid, ask = float(bid_s), float(ask_s)
        if bid <= 0 or ask <= bid:
            continue
        hour = parse_ts(ts_avail).astimezone(_TEHRAN).hour
        spread_bps = (ask - bid) / ((ask + bid) / 2.0) * 10000.0
        buckets[hour][0].append(spread_bps)
        buckets[hour][1].append(float(bq_s or 0))
        buckets[hour][2].append(float(aq_s or 0))
    hours = []
    for h in range(24):
        spreads, bids, asks = buckets[h]
        spreads.sort()
        bids.sort()
        asks.sort()
        hours.append({
            "tehran_hour": h,
            "samples": len(spreads),
            "status": "QUALIFIED" if len(spreads) >= 3 else "INSUFFICIENT_SAMPLES",
            "median_spread_bps": _percentile(spreads, 0.50),
            "p90_spread_bps": _percentile(spreads, 0.90),
            "median_bid_qty": _percentile(bids, 0.50),
            "median_ask_qty": _percentile(asks, 0.50),
        })
    return {"symbol": symbol, "timezone": "Asia/Tehran", "days": days,
            "total_qualified_quotes": sum(h["samples"] for h in hours), "hours": hours}


def data_eligibility_preflight(db: MarketDB, symbol: str, *, days: int = 14, min_bars: int = 20, now: datetime | None = None) -> dict:
    """Assess pre-research coverage, freshness, historical rule completeness, and prehistory (U017, M021)."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    cal = symbol_quality_calendar(db, symbol, days=days, now=at)
    vintages = as_of_rule_index(db, symbol)
    as_of_vintages = [v for v in vintages["vintages"] if parse_ts(v["valid_from"]) <= at]
    observed_days = sum(1 for row in cal["calendar"] if row["completeness_status"] != "NO_DATA")
    gapped_days = sum(1 for row in cal["calendar"] if row["completeness_status"] == "PARTIAL_GAPPED")
    total_quotes = sum(row["quotes"] for row in cal["calendar"])
    blockers = []
    if not as_of_vintages:
        blockers.append("NO_AS_OF_LISTING_OR_SPEC")
    elif not as_of_vintages[-1]["complete"]:
        blockers.append("INCOMPLETE_AS_OF_RULE_VINTAGE")
    if total_quotes < min_bars:
        blockers.append("INSUFFICIENT_HISTORY")
    if cal["freshness_status"] != "FRESH":
        blockers.append(f"QUOTE_FRESHNESS_{cal['freshness_status']}")
    warnings = ["GAPPED_OBSERVATION_DAYS"] if gapped_days > 0 else []
    status = "BLOCKED" if blockers else "ELIGIBLE_WITH_WARNINGS" if warnings else "ELIGIBLE"
    return {
        "symbol": symbol,
        "as_of": iso(at),
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "observed_days": observed_days,
        "gapped_days": gapped_days,
        "total_quotes": total_quotes,
        "min_bars_required": min_bars,
        "as_of_vintage_count": len(as_of_vintages),
        "funded_authority": False,
    }
