"""Read-only operational health and data-freshness watchdog for TradingGYM collectors, quotes, and journals."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from ...adapters.candle_reader import open_readonly_market_db
from ...domain.model import parse_ts
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from .gru_engine import EnsembleGRU, GRUArtifactError
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .io_utils import read_jsonl_records, readonly_snapshot, write_json_atomic

MAX_FUTURE_SKEW_H = 1.0 / 60.0  # 60 seconds clock skew tolerance


def _age_hours(ts_str: str | None, now: datetime) -> float | None:
    if not ts_str:
        return None
    try:
        dt = parse_ts(ts_str)
        return round((now - dt).total_seconds() / 3600.0, 4)
    except Exception:
        return None


def _is_future(age_h: float | None) -> bool:
    return age_h is not None and age_h < -MAX_FUTURE_SKEW_H


def _check_market_db(wallex_db: Path, now: datetime) -> dict:
    if not wallex_db.is_file():
        return {"status": "FAIL", "reason": "missing_market_db"}
    expected_1d = tuple(dict.fromkeys(BASE_13_SYMBOLS + ("PAXGUSDT",)))
    syms = tuple(dict.fromkeys(expected_1d + IGNITION_18_CRYPTO))
    con = open_readonly_market_db(wallex_db)
    try:
        with readonly_snapshot(con):
            latest_book = con.execute("SELECT MAX(ts_avail) FROM book_top").fetchone()[0]
            latest_trade = con.execute("SELECT MAX(ts_avail) FROM trades").fetchone()[0]
            ph = ",".join("?" * len(syms))
            candle_rows = con.execute(
                f"SELECT i.symbol, c.resolution, COUNT(*), MAX(c.t) "
                f"FROM venue_candles c JOIN instruments i ON i.instrument_id = c.instrument_id "
                f"WHERE i.symbol IN ({ph}) AND c.resolution IN ('1d', '1h', '1min') "
                f"GROUP BY i.symbol, c.resolution",
                syms,
            ).fetchall()
    finally:
        con.close()

    stale_1d: list[str] = []
    stale_1h: list[str] = []
    future_anomalies: list[str] = []
    present_1d: set[str] = set()
    fresh_1min_count = 0
    for sym, res, _, tmax in candle_rows:
        age_h = _age_hours(datetime.fromtimestamp(tmax, UTC).isoformat(), now) if isinstance(tmax, (int, float)) else _age_hours(str(tmax), now)
        if age_h is None:
            continue
        if _is_future(age_h):
            future_anomalies.append(f"{sym}:{res} ({age_h:.2f}h)")
        if res == "1d":
            present_1d.add(sym)
            if age_h > 48.0:
                stale_1d.append(f"{sym} ({age_h:.0f}h)")
        elif res == "1h" and age_h > 24.0:
            stale_1h.append(f"{sym} ({age_h:.0f}h)")
        elif res == "1min" and 0.0 <= age_h <= 24.0:
            fresh_1min_count += 1

    missing_1d = sorted(set(expected_1d) - present_1d)
    book_age_h = _age_hours(latest_book, now)
    trade_age_h = _age_hours(latest_trade, now)
    if _is_future(book_age_h):
        future_anomalies.append(f"book_top ({book_age_h:.2f}h)")
    if _is_future(trade_age_h):
        future_anomalies.append(f"trades ({trade_age_h:.2f}h)")

    status = "OK"
    if book_age_h is None or book_age_h > 1.0 or stale_1d or future_anomalies or not present_1d:
        status = "FAIL"
    elif stale_1h or missing_1d or trade_age_h is None or trade_age_h > 2.0:
        status = "WARN"
    return {
        "status": status,
        "latest_book_ts": latest_book,
        "book_age_hours": book_age_h,
        "latest_trade_ts": latest_trade,
        "trade_age_hours": trade_age_h,
        "stale_1d_symbols": sorted(stale_1d),
        "missing_1d_symbols": missing_1d,
        "stale_1h_symbols_count": len(stale_1h),
        "stale_1h_symbols": sorted(stale_1h),
        "fresh_1min_symbols_count": fresh_1min_count,
        "future_timestamp_anomalies": sorted(future_anomalies),
    }


def _check_multi_venue_db(mv_db: Path, now: datetime) -> dict:
    if not mv_db.is_file():
        return {"status": "FAIL", "reason": "missing_multi_venue_db"}
    con = open_readonly_market_db(mv_db)
    try:
        rows = con.execute(
            "SELECT venue, symbol, COUNT(*), MAX(ts_avail) FROM venue_quotes GROUP BY venue, symbol"
        ).fetchall()
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        pools_cnt = con.execute("SELECT COUNT(*) FROM venue_liquidity_pools").fetchone()[0] if "venue_liquidity_pools" in tables else 0
        usdt_apr_row = (
            con.execute(
                "SELECT apr_pct FROM venue_liquidity_pools WHERE venue='nobitex' AND currency='USDT' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if "venue_liquidity_pools" in tables
            else None
        )
        ratios_cnt = con.execute("SELECT COUNT(*) FROM venue_margin_ratios").fetchone()[0] if "venue_margin_ratios" in tables else 0
        fair_cnt = con.execute("SELECT COUNT(*) FROM venue_fair_prices").fetchone()[0] if "venue_fair_prices" in tables else 0
    finally:
        con.close()
    nbx_fresh, nbx_stale, nbx_future = 0, [], []
    total_rows = 0
    latest_ts: str | None = None
    for venue, sym, cnt, tmax in rows:
        total_rows += cnt
        if latest_ts is None or (tmax and tmax > latest_ts):
            latest_ts = tmax
        if venue == "nobitex" and sym.endswith("USDT"):
            age_h = _age_hours(tmax, now)
            if _is_future(age_h):
                nbx_future.append(sym)
            elif age_h is not None and age_h <= 0.5:
                nbx_fresh += 1
            else:
                nbx_stale.append(sym)
    if nbx_future or nbx_fresh == 0:
        status = "FAIL"
    elif nbx_fresh >= 5 and not nbx_stale:
        status = "OK"
    else:
        status = "WARN"
    return {
        "status": status,
        "total_quote_rows": total_rows,
        "latest_quote_ts": latest_ts,
        "nobitex_fresh_symbols": nbx_fresh,
        "nobitex_stale_symbols": sorted(nbx_stale),
        "nobitex_future_symbols": sorted(nbx_future),
        "nobitex_liquidity_pool_rows": pools_cnt,
        "nobitex_latest_usdt_pool_apr_pct": float(usdt_apr_row[0]) if (usdt_apr_row and usdt_apr_row[0]) else None,
        "wallex_margin_ratio_rows": ratios_cnt,
        "wallex_fair_price_rows": fair_cnt,
    }


def _check_jsonl_file(path: Path, now: datetime, *, max_age_hours: float = 12.0) -> dict:
    if not path.is_file():
        return {"status": "MISSING", "path": str(path), "rows": 0}
    rows, corrupt_lines = read_jsonl_records(path)
    if not rows:
        return {"status": "FAIL" if corrupt_lines else "EMPTY", "path": str(path), "rows": 0, "corrupt_lines": corrupt_lines}
    last = rows[-1]
    ts_s = last.get("as_of") or last.get("ts_avail") or last.get("recorded_at")
    age_h = _age_hours(ts_s, now)
    future_ts = _is_future(age_h)
    future_bar = False
    if ts_s:
        as_of_dt = parse_ts(ts_s)
        for bk in ("signal_2h_bar", "signal_1d_bar"):
            bv = last.get(bk)
            if bv and parse_ts(bv) > as_of_dt:
                future_bar = True
    if corrupt_lines > 0 or future_bar or future_ts or age_h is None:
        status = "FAIL"
    elif age_h <= max_age_hours:
        status = "OK"
    else:
        status = "WARN"
    return {
        "status": status,
        "rows": len(rows),
        "corrupt_lines": corrupt_lines,
        "latest_ts": ts_s,
        "age_hours": age_h,
        "future_bar_violation": future_bar,
        "future_timestamp_violation": future_ts,
    }


def _check_frozen_model(model_path: Path, *, registration_path: Path | None = None) -> dict:
    if not model_path.is_file():
        return {"status": "MISSING", "path": str(model_path)}
    raw = model_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        ensemble, _ = EnsembleGRU.load_json(model_path)
    except GRUArtifactError as exc:
        return {"status": "FAIL", "bytes": len(raw), "sha256": sha, "registration_match": False, "error": str(exc)}
    reg_status = "UNCHECKED"
    reg_match: bool | None = None
    if registration_path is not None:
        if not registration_path.is_file():
            reg_status = "MISSING_REGISTRATION"
            reg_match = False
        else:
            reg = json.loads(registration_path.read_text(encoding="utf-8"))
            reg_sha = reg.get("gru_model_sha256")
            if not reg_sha:
                reg_status = "MISSING_SHA"
                reg_match = False
            else:
                reg_match = (sha == reg_sha)
                reg_status = "MATCH" if reg_match else "MISMATCH"
    ok = reg_match is not False
    return {
        "status": "OK" if ok else "FAIL",
        "bytes": len(raw),
        "n_models": len(ensemble.models),
        "sha256": sha,
        "registration_status": reg_status,
        "registration_match": reg_match,
    }


def _safe_check(fn, *args, **kwargs) -> dict:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"status": "FAIL", "error": type(exc).__name__, "detail": str(exc)[:200]}


def run_operational_health_check(
    data_dir: Path,
    evidence_dir: Path,
    *,
    report_path: Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Run all read-only operational health checks with fault isolation and atomic JSON receipt publication."""
    ts_now = now or datetime.now(UTC)
    live = data_dir / "live"
    fwd = evidence_dir / "forward"
    checks = {
        "market_db": _safe_check(_check_market_db, live / "market.db", ts_now),
        "multi_venue_db": _safe_check(_check_multi_venue_db, live / "multi_venue_quotes.sqlite3", ts_now),
        "s1_s5_leader_journal": _safe_check(_check_jsonl_file, live / "allocation" / "s1-s5-leader-journal.jsonl", ts_now, max_age_hours=28.0),
        "champion_ensemble_journal": _safe_check(_check_jsonl_file, live / "allocation" / "champion-ensemble-journal.jsonl", ts_now, max_age_hours=6.0),
        "champion_v2_journal": _safe_check(_check_jsonl_file, live / "allocation" / "champion-v2-journal.jsonl", ts_now, max_age_hours=6.0),
        "mix_journal_v2": _safe_check(_check_jsonl_file, live / "allocation" / "mix-journal-v2.jsonl", ts_now, max_age_hours=28.0),
        "gru_ignition_model": _safe_check(
            _check_frozen_model,
            live / "models" / "gru-ignition-v1.json",
            registration_path=fwd / "champion-v1-registration.json",
        ),
        "gru_ignition_v2_model": _safe_check(
            _check_frozen_model,
            live / "models" / "gru-ignition-v2-pathpnl.json",
            registration_path=fwd / "champion-v2-registration.json",
        ),
    }
    statuses = [c["status"] for c in checks.values()]
    overall = "FAIL" if "FAIL" in statuses else ("WARN" if any(s in ("WARN", "MISSING", "EMPTY") for s in statuses) else "OK")
    out = {
        "generated_at": ts_now.isoformat(),
        "overall_status": overall,
        "executor_state": "DISARMED",
        "executor_policy_state": "DECLARED_DISARMED",
        "executor_observed_status": "UNKNOWN",
        "checks": checks,
    }
    if report_path is not None:
        write_json_atomic(report_path, out)
    return out
