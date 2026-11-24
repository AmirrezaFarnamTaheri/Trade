"""Daily idempotent Track B mix-journal-v2.jsonl recorder (spec §6.5 & §7.3).

Reads completed daily candles and live displayed top-5 depth from read-only market.db,
computes horizon-matched Convex L1 target weights (MultiHorizonEwmac + CrossMarketBreadthRegime),
and appends one UTC-date-deduplicated entry per symbol to mix-journal-v2.jsonl.
Never reads or modifies v1 mix-journal.jsonl.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from gym.adapters.mix_journal_store import append_mix_journal_v2
from gym.domain.async_covariance import coarse_bar_shrunk_covariance
from gym.domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    solve_convex_portfolio,
)
from gym.domain.forecast_graph import (
    CrossMarketBreadthRegimeNode,
    MultiHorizonEwmacNode,
)
from gym.domain.model import dec, parse_ts
from gym.domain.signal_gatekeeper import build_mix_journal_v2_entry
from gym.domain.volatility_models import OhlcBar, yang_zhang_volatility

MIX_V2_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XAUTUSDT")


def _open_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=10.0)


def _existing_journal_state(path: Path) -> tuple[datetime | None, set[str], dict[str, float]]:
    """Return (cohort_start, recorded_utc_dates, last_weights_by_symbol) from existing mix-journal-v2.jsonl."""
    if not path.exists():
        return None, set(), {s: 0.0 for s in MIX_V2_SYMBOLS}
    cohort_start: datetime | None = None
    dates: set[str] = set()
    last_sizes: dict[str, float] = {s: 0.0 for s in MIX_V2_SYMBOLS}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        item = json.loads(raw)
        if cohort_start is None and item.get("start_date"):
            cohort_start = parse_ts(item["start_date"])
        as_of_s = item.get("as_of")
        if as_of_s:
            dates.add(parse_ts(as_of_s).date().isoformat())
        sym = item.get("symbol")
        if sym in last_sizes and item.get("intended_size_usdt") is not None:
            last_sizes[sym] = float(item["intended_size_usdt"])
    total_ref = 1000.0
    last_weights = {s: max(0.0, min(1.0, v / total_ref)) for s, v in last_sizes.items()}
    return cohort_start, dates, last_weights


def _load_daily_candles(con: sqlite3.Connection, symbol: str, *, limit: int = 400) -> list[tuple[datetime, float, float, float, float]]:
    rows = con.execute(
        "SELECT vc.t, vc.o, vc.h, vc.l, vc.c FROM venue_candles vc "
        "JOIN instruments i ON i.instrument_id = vc.instrument_id "
        "WHERE i.symbol = ? AND vc.resolution = '1d' ORDER BY vc.t DESC LIMIT ?",
        (symbol, limit),
    ).fetchall()
    rows.reverse()
    out = []
    for ts_s, o, h, lo, c in rows:
        if None not in (o, h, lo, c) and float(o) > 0 and float(c) > 0:
            out.append((parse_ts(ts_s), float(o), float(h), float(lo), float(c)))
    return out


def _displayed_depth_usdt(con: sqlite3.Connection, symbol: str) -> Decimal:
    """Estimate live displayed top-5 liquidity in USDT from the newest book_top row."""
    row = con.execute(
        "SELECT b.bid, b.ask, b.bid_qty, b.ask_qty, b.depth FROM book_top b "
        "JOIN instruments i ON i.instrument_id = b.instrument_id "
        "WHERE i.symbol = ? AND b.bid IS NOT NULL AND b.ask IS NOT NULL "
        "ORDER BY b.rowid DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if not row:
        return Decimal("0")
    bid, ask, bq, aq, depth_raw = row
    if depth_raw:
        try:
            d = json.loads(depth_raw)
            if isinstance(d, list) and len(d) == 2 and d[0] and d[1]:
                bid_val = sum((dec(p) * dec(q) for p, q in d[0]), Decimal(0))
                ask_val = sum((dec(p) * dec(q) for p, q in d[1]), Decimal(0))
                return min(bid_val, ask_val).quantize(Decimal("0.01"))
        except Exception:
            pass
    mid = (dec(bid) + dec(ask)) / Decimal(2)
    qty = min(dec(bq or "0"), dec(aq or "0"))
    return (mid * qty).quantize(Decimal("0.01"))


def record_daily_mix_v2(
    db_path: Path,
    journal_path: Path,
    *,
    as_of: datetime | None = None,
    reference_equity_usdt: Decimal = Decimal("1000"),
    holding_horizon_days: float = 25.0,
    ic_prior: float = 0.08,
    risk_aversion: float = 1.5,
) -> dict:
    """Compute today's horizon-matched Convex L1 target weights and append idempotently to mix-journal-v2.jsonl."""
    if journal_path.name == "mix-journal.jsonl":
        raise ValueError("refusing to touch v1 control mix-journal.jsonl")
    now = as_of or datetime.now(UTC)
    today_iso = now.date().isoformat()
    cohort_start, existing_dates, prev_weights = _existing_journal_state(journal_path)
    if today_iso in existing_dates:
        return {"status": "ALREADY_RECORDED", "date": today_iso, "entries_written": 0}
    cohort_start = cohort_start or now

    con = _open_ro(db_path)
    try:
        candles = {sym: _load_daily_candles(con, sym) for sym in MIX_V2_SYMBOLS}
        common = sorted(set.intersection(*(set(t for t, *_ in candles[s]) for s in MIX_V2_SYMBOLS)))
        if len(common) < 70:
            return {"status": "INSUFFICIENT_CANDLES", "common_days": len(common), "entries_written": 0}

        by_date = {s: {t: (o, h, lo, c) for t, o, h, lo, c in candles[s]} for s in MIX_V2_SYMBOLS}
        ewmacs = {s: MultiHorizonEwmacNode(pairs=((8, 32), (16, 64), (32, 128))) for s in MIX_V2_SYMBOLS}
        ret_hist: dict[str, list[float]] = {s: [] for s in MIX_V2_SYMBOLS}
        ohlc_hist: dict[str, list[OhlcBar]] = {s: [] for s in MIX_V2_SYMBOLS}
        raw_f = [0.0] * len(MIX_V2_SYMBOLS)

        for idx, dt in enumerate(common):
            for s_i, sym in enumerate(MIX_V2_SYMBOLS):
                o, h, lo, c = by_date[sym][dt]
                raw_f[s_i] = ewmacs[sym].update(c)
                ohlc_hist[sym].append(OhlcBar(o, h, lo, c))
                if idx > 0:
                    c_prev = by_date[sym][common[idx - 1]][3]
                    ret_hist[sym].append((c - c_prev) / c_prev)

        pos_frac = sum(1 for f in raw_f if f > 0) / len(MIX_V2_SYMBOLS)
        reg_mult = CrossMarketBreadthRegimeNode().evaluate(pos_frac, floor=0.25)
        window_rets = {s: ret_hist[s][-60:] for s in MIX_V2_SYMBOLS}
        _, cov_daily = coarse_bar_shrunk_covariance(window_rets, shrinkage=0.25)
        cov_h = tuple(tuple(v * holding_horizon_days for v in row) for row in cov_daily)
        sqrt_h = math.sqrt(holding_horizon_days)
        vols_h_bps = [yang_zhang_volatility(ohlc_hist[s][-20:]) * sqrt_h * 10000.0 for s in MIX_V2_SYMBOLS]
        mu_h = tuple(
            forecast_to_expected_return_bps(f * reg_mult, ic_prior=ic_prior, horizon_vol_bps=vb) / 10000.0
            for f, vb in zip(raw_f, vols_h_bps, strict=True)
        )
        prob = OptimizationProblem(
            symbols=MIX_V2_SYMBOLS,
            expected_returns=mu_h,
            current_weights=tuple(prev_weights[s] for s in MIX_V2_SYMBOLS),
            covariance=cov_h,
            l1_fee_costs=(0.0013,) * len(MIX_V2_SYMBOLS),
            l2_impact_costs=(0.0020,) * len(MIX_V2_SYMBOLS),
            risk_aversion=risk_aversion,
            max_weight=0.35,
            cash_buffer=0.05,
        )
        target_w = solve_convex_portfolio(prob).weights

        written = 0
        for sym, tw in zip(MIX_V2_SYMBOLS, target_w, strict=True):
            intended = (reference_equity_usdt * Decimal(str(round(tw, 6)))).quantize(Decimal("0.01"))
            depth = _displayed_depth_usdt(con, sym)
            missed = max(Decimal("0"), intended - depth).quantize(Decimal("0.01"))
            entry = build_mix_journal_v2_entry(
                as_of=now,
                cohort_start=cohort_start,
                symbol=sym,
                intended_size_usdt=intended,
                displayed_depth_usdt=depth,
                fee_vintage="PUBLISHED_STRUCTURED_FEE_L1",
                missed_qty_usdt=missed,
                tracking_error_bps=Decimal("0"),
                status="RECORDED",
            )
            append_mix_journal_v2(journal_path, entry)
            written += 1
    finally:
        con.close()

    return {
        "status": "RECORDED",
        "date": today_iso,
        "entries_written": written,
        "weights": {s: round(w, 4) for s, w in zip(MIX_V2_SYMBOLS, target_w, strict=True)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Append daily horizon-matched Convex L1 allocation to mix-journal-v2.jsonl")
    parser.add_argument("--db", type=Path, default=Path("D:/Github/Trade/data/live/market.db"))
    parser.add_argument("--journal", type=Path, default=Path("D:/Github/Trade/data/live/allocation/mix-journal-v2.jsonl"))
    args = parser.parse_args()
    res = record_daily_mix_v2(args.db, args.journal)
    print(json.dumps(res, sort_keys=True))


if __name__ == "__main__":
    main()
