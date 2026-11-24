"""Read-only operational health and data-freshness watchdog for TradingGYM collectors, quotes, and journals."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from ...adapters.candle_reader import open_readonly_market_db
from ...domain.model import parse_ts
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from .ignition_expansion_study import IGNITION_18_CRYPTO


def _age_hours(ts_str: str | None, now: datetime) -> float | None:
    if not ts_str:
        return None
    try:
        dt = parse_ts(ts_str)
        return round((now - dt).total_seconds() / 3600.0, 2)
    except Exception:
        return None


def _check_market_db(wallex_db: Path, now: datetime) -> dict:
    if not wallex_db.is_file():
        return {"status": "FAIL", "reason": "missing_market_db"}
    con = open_readonly_market_db(wallex_db)
    try:
        latest_book = con.execute("SELECT MAX(ts_avail) FROM book_top").fetchone()[0]
        latest_trade = con.execute("SELECT MAX(ts_avail) FROM trades").fetchone()[0]
        syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO + ("PAXGUSDT",)))
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
    fresh_1min_count = 0
    for sym, res, _, tmax in candle_rows:
        age_h = _age_hours(datetime.fromtimestamp(tmax, UTC).isoformat(), now) if isinstance(tmax, (int, float)) else _age_hours(str(tmax), now)
        if age_h is None:
            continue
        if res == "1d" and age_h > 48.0:
            stale_1d.append(f"{sym} ({age_h:.0f}h)")
        elif res == "1h" and age_h > 24.0:
            stale_1h.append(f"{sym} ({age_h:.0f}h)")
        elif res == "1min" and age_h <= 24.0:
            fresh_1min_count += 1

    book_age_h = _age_hours(latest_book, now)
    trade_age_h = _age_hours(latest_trade, now)
    status = "OK"
    if book_age_h is None or book_age_h > 1.0 or stale_1d:
        status = "FAIL"
    elif stale_1h:
        status = "WARN"
    return {
        "status": status,
        "latest_book_ts": latest_book,
        "book_age_hours": book_age_h,
        "latest_trade_ts": latest_trade,
        "trade_age_hours": trade_age_h,
        "stale_1d_symbols": sorted(stale_1d),
        "stale_1h_symbols_count": len(stale_1h),
        "fresh_1min_symbols_count": fresh_1min_count,
    }


def _check_multi_venue_db(mv_db: Path, now: datetime) -> dict:
    if not mv_db.is_file():
        return {"status": "FAIL", "reason": "missing_multi_venue_db"}
    con = open_readonly_market_db(mv_db)
    try:
        rows = con.execute(
            "SELECT venue, symbol, COUNT(*), MAX(ts_avail) FROM venue_quotes GROUP BY venue, symbol"
        ).fetchall()
    finally:
        con.close()
    nbx_fresh, nbx_stale = 0, []
    total_rows = 0
    latest_ts: str | None = None
    for venue, sym, cnt, tmax in rows:
        total_rows += cnt
        if latest_ts is None or (tmax and tmax > latest_ts):
            latest_ts = tmax
        if venue == "nobitex" and sym.endswith("USDT"):
            age_h = _age_hours(tmax, now)
            if age_h is not None and age_h <= 0.5:
                nbx_fresh += 1
            else:
                nbx_stale.append(sym)
    status = "OK" if nbx_fresh >= 5 and not nbx_stale else ("WARN" if nbx_fresh >= 1 else "FAIL")
    return {
        "status": status,
        "total_quote_rows": total_rows,
        "latest_quote_ts": latest_ts,
        "nobitex_fresh_symbols": nbx_fresh,
        "nobitex_stale_symbols": sorted(nbx_stale),
    }


def _check_jsonl_file(path: Path, now: datetime, *, max_age_hours: float = 36.0) -> dict:
    if not path.is_file():
        return {"status": "MISSING", "path": str(path), "rows": 0}
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return {"status": "EMPTY", "path": str(path), "rows": 0}
    last = json.loads(lines[-1])
    ts_s = last.get("as_of") or last.get("ts_avail") or last.get("recorded_at")
    age_h = _age_hours(ts_s, now)
    status = "OK" if (age_h is not None and age_h <= max_age_hours) else "WARN"
    return {"status": status, "rows": len(lines), "latest_ts": ts_s, "age_hours": age_h}


def _check_frozen_model(model_path: Path) -> dict:
    if not model_path.is_file():
        return {"status": "MISSING", "path": str(model_path)}
    raw = model_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    payload = json.loads(raw.decode("utf-8"))
    return {
        "status": "OK" if payload.get("schema") == "ensemble-gru-weights/1" and payload.get("n_models", 0) >= 1 else "FAIL",
        "bytes": len(raw),
        "n_models": payload.get("n_models", 0),
        "sha256": sha,
    }


def run_operational_health_check(
    data_dir: Path,
    evidence_dir: Path,
    *,
    report_path: Path | None = None,
    now: datetime | None = None,
) -> dict:
    """Run all read-only operational health checks and optionally write a JSON receipt."""
    ts_now = now or datetime.now(UTC)
    live = data_dir / "live"
    checks = {
        "market_db": _check_market_db(live / "market.db", ts_now),
        "multi_venue_db": _check_multi_venue_db(live / "multi_venue_quotes.sqlite3", ts_now),
        "s1_s5_leader_journal": _check_jsonl_file(live / "allocation" / "s1-s5-leader-journal.jsonl", ts_now),
        "champion_ensemble_journal": _check_jsonl_file(live / "allocation" / "champion-ensemble-journal.jsonl", ts_now),
        "champion_v2_journal": _check_jsonl_file(live / "allocation" / "champion-v2-journal.jsonl", ts_now),
        "mix_journal_v2": _check_jsonl_file(live / "allocation" / "mix-journal-v2.jsonl", ts_now),
        "gru_ignition_model": _check_frozen_model(live / "models" / "gru-ignition-v1.json"),
        "gru_ignition_v2_model": _check_frozen_model(live / "models" / "gru-ignition-v2-pathpnl.json"),
    }
    statuses = [c["status"] for c in checks.values()]
    overall = "FAIL" if "FAIL" in statuses else ("WARN" if any(s in ("WARN", "MISSING", "EMPTY") for s in statuses) else "OK")
    out = {
        "generated_at": ts_now.isoformat(),
        "overall_status": overall,
        "executor_state": "DISARMED",
        "checks": checks,
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out
