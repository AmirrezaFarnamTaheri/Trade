"""Daily idempotent prospective forward paper journal for the standing leader (S1 + S5 + ADMM)."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...adapters.mix_journal_store import append_mix_journal_v2
from ...domain.async_covariance import coarse_bar_shrunk_covariance_aligned
from ...domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    solve_convex_portfolio,
)
from ...domain.model import dec, parse_ts
from ...domain.signal_gatekeeper import build_mix_journal_v2_entry
from ...domain.strategy_sleeves import compute_slow_sleeves
from .ensemble_study import COHORT_SYMBOLS, _dated_returns


def _package_engine_digest() -> str:
    root = Path(__file__).resolve().parents[2]
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        h.update(p.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _existing_leader_state(path: Path) -> tuple[datetime | None, set[str], dict[str, float]]:
    if not path.is_file():
        return None, set(), {s: 0.0 for s in COHORT_SYMBOLS}
    cohort_start: datetime | None = None
    dates: set[str] = set()
    last_sizes: dict[str, float] = {s: 0.0 for s in COHORT_SYMBOLS}
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
    last_weights = {s: max(0.0, min(1.0, v / 1000.0)) for s, v in last_sizes.items()}
    return cohort_start, dates, last_weights


def _displayed_depth_usdt(con, symbol: str) -> Decimal:
    row = con.execute(
        "SELECT b.bid, b.ask, b.bid_qty, b.ask_qty, b.depth "
        "FROM book_top b JOIN instruments i ON i.instrument_id = b.instrument_id "
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
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    mid = (dec(bid) + dec(ask)) / Decimal(2)
    qty = min(dec(bq or "0"), dec(aq or "0"))
    return (mid * qty).quantize(Decimal("0.01"))


def record_s1_s5_leader_journal(
    db_path: Path,
    journal_path: Path,
    *,
    registration_path: Path | None = None,
    as_of: datetime | None = None,
    reference_equity_usdt: Decimal = Decimal("1000"),
    fee_rate: Decimal = Decimal("0.0013"),
    holding_horizon_days: float = 20.0,
) -> dict:
    """Compute today's 13-asset S1+S5 (DROP_S2) + ADMM target weights and append idempotently."""
    if journal_path.name == "mix-journal.jsonl":
        raise ValueError("refusing to touch v1 control mix-journal.jsonl")
    now = as_of or datetime.now(UTC)
    today_iso = now.date().isoformat()
    cohort_start, existing_dates, prev_weights = _existing_leader_state(journal_path)
    cohort_start = cohort_start or now

    engine_digest = _package_engine_digest()
    if registration_path is not None and not registration_path.exists():
        reg_payload = {
            "schema": "prospective-leader-registration/1",
            "strategy_id": "S1_S5_DROP_S2_ADMM_LEADER",
            "registered_at": now.isoformat(),
            "selection_end": now.date().isoformat() + "T00:00:00+00:00",
            "cohort_start": cohort_start.isoformat(),
            "engine_digest": engine_digest,
            "universe": list(COHORT_SYMBOLS),
            "optimizer": {
                "solver": "admm_dykstra",
                "holding_horizon_days": holding_horizon_days,
                "risk_aversion": 2.0,
                "max_weight": 0.30,
                "cash_buffer": 0.05,
                "l1_fee_rate": str(fee_rate),
                "l2_impact": "0.0020",
            },
            "funded_authority": False,
            "executor_state": "DISARMED",
        }
        registration_path.parent.mkdir(parents=True, exist_ok=True)
        registration_path.write_text(json.dumps(reg_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if today_iso in existing_dates:
        return {"status": "ALREADY_RECORDED", "date": today_iso, "entries_written": 0, "engine_digest": engine_digest}

    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {sym: load_keyed_candles(con, sym, "1d", limit=400) for sym in COHORT_SYMBOLS}
        signals = compute_slow_sleeves(panel_1d, COHORT_SYMBOLS)
        dated_rets = _dated_returns(panel_1d)
        eligible_dates = sorted(ts for ts, d in signals.items() if any(s.eligible_for_entry for s in d.values()))
        if not eligible_dates:
            return {"status": "INSUFFICIENT_CANDLES", "date": today_iso, "entries_written": 0}

        latest_ts = eligible_dates[-1]
        day_sigs = signals[latest_ts]
        active_syms = tuple(s for s in COHORT_SYMBOLS if s in day_sigs)
        if len(active_syms) < 2:
            return {"status": "INSUFFICIENT_SYMBOLS", "date": today_iso, "entries_written": 0}

        win_trimmed = {
            s: dict(sorted((dt, r) for dt, r in dated_rets[s].items() if dt <= latest_ts)[-60:])
            for s in active_syms
        }
        cov_d = coarse_bar_shrunk_covariance_aligned(win_trimmed, active_syms, shrinkage=0.25)
        cov_h = tuple(tuple(v * holding_horizon_days for v in row) for row in cov_d)
        sqrt_h = math.sqrt(holding_horizon_days)

        mu_gross = []
        for sym in active_syms:
            sig = day_sigs[sym]
            parts = [v for v in (sig.s1_trend, sig.s5_defensive_gold) if v is not None]
            raw_score = sum(parts) / len(parts) if parts else 0.0
            vol_h_bps = sig.yang_zhang_vol * sqrt_h * 10000.0
            mu_bps = forecast_to_expected_return_bps(raw_score * 20.0, ic_prior=0.08, horizon_vol_bps=vol_h_bps)
            mu_gross.append(mu_bps / 10000.0)

        prob = OptimizationProblem(
            symbols=active_syms,
            expected_returns=tuple(mu_gross),
            current_weights=tuple(prev_weights.get(s, 0.0) for s in active_syms),
            covariance=cov_h,
            l1_fee_costs=(float(fee_rate),) * len(active_syms),
            l2_impact_costs=(0.0020,) * len(active_syms),
            risk_aversion=2.0,
            max_weight=0.30,
            cash_buffer=0.05,
        )
        solved = solve_convex_portfolio(prob).weights

        written = 0
        weights_out: dict[str, float] = {}
        for sym, tw in zip(active_syms, solved, strict=True):
            weights_out[sym] = round(tw, 4)
            intended = (reference_equity_usdt * Decimal(str(round(tw, 6)))).quantize(Decimal("0.01"))
            depth = _displayed_depth_usdt(con, sym)
            missed = max(Decimal("0"), intended - depth).quantize(Decimal("0.01"))
            entry = build_mix_journal_v2_entry(
                as_of=now,
                cohort_start=cohort_start,
                symbol=sym,
                intended_size_usdt=intended,
                displayed_depth_usdt=depth,
                fee_vintage="S1_S5_LEADER_WALLEX_L1",
                missed_qty_usdt=missed,
                tracking_error_bps=Decimal("0"),
                status="RECORDED",
            )
            if append_mix_journal_v2(journal_path, entry):
                written += 1
    finally:
        con.close()

    return {
        "status": "RECORDED",
        "date": today_iso,
        "signal_bar": latest_ts.isoformat(),
        "entries_written": written,
        "engine_digest": engine_digest,
        "weights": weights_out,
        "cash_weight": round(max(0.0, 1.0 - sum(weights_out.values())), 4),
    }
