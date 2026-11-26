"""Quant v3.1 full-catalog DSR, FX dual-factor attribution, empirical slippage, and ML readiness audit.

Strictly read-only against market.db; TradingGYMExecutor remains DISARMED ($0 funded budget).
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean, median, stdev

from ..adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ..domain.bars import Bar, BarSpec
from ..domain.model import TEHRAN, parse_ts
from ..domain.quant_v3_gates import (
    compute_deflated_sharpe_ratio,
    compute_leave_k_out_fragility,
    compute_local_fx_basis_stress,
    consensus_kalman_fx_rate,
    decompose_dual_factor_fx_return,
    pre_trade_implementation_shortfall_gate,
)
from ..domain.registry import catalog, create_strategy
from ..domain.strategy import Snapshot
from .experiments.gru_engine import EnsembleGRU
from .experiments.io_utils import (
    readonly_snapshot,
    semantic_engine_digest,
    write_json_atomic,
    write_text_atomic,
)


def _prepare_snapshots(bars: list, symbol: str) -> list[tuple[Snapshot, float, float]]:
    """Pre-compute (Snapshot, close, bar_ret) once per bar to avoid 18x redundant Decimal/Snapshot allocations."""
    spec = BarSpec("1day", "MID")
    out: list[tuple[Snapshot, float, float]] = []
    for i, c in enumerate(bars):
        close_d = Decimal(str(c.close))
        bar = Bar(
            symbol, spec, c.ts_start, c.ts_avail, c.ts_avail,
            Decimal(str(c.open)), Decimal(str(c.high)), Decimal(str(c.low)), close_d,
            Decimal(str(c.volume)), 1, False,
        )
        snap = Snapshot(
            as_of=c.ts_avail, symbol=symbol, bar=bar,
            bid=close_d * Decimal("0.9994"), ask=close_d * Decimal("1.0006"), quote_time=c.ts_avail,
        )
        prev_close = bars[i - 1].close if i > 0 else c.close
        bar_ret = ((c.close - prev_close) / prev_close) if prev_close > 0 else 0.0
        out.append((snap, c.close, bar_ret))
    return out


def _simulate_strategy_on_bars(strategy_id: str, params: dict, prepared: list[tuple[Snapshot, float, float]]) -> dict:
    """Run a lightweight single-asset spot-only signal simulation on pre-built daily bar snapshots."""
    strat = create_strategy(strategy_id, params)
    holding = False
    entry_px = 0.0
    daily_rets: list[float] = []
    episode_rets_bps: list[float] = []
    signals = 0
    errors = 0
    last_error: str | None = None
    fee_rt = 0.0032  # 32 bps conservative round-trip spot fee (16 bps per leg)
    leg_fee = fee_rt / 2.0

    for snap, close_f, bar_ret in prepared:
        net_ret = bar_ret if holding else 0.0
        try:
            action, _, _, _ = strat.decide(snap, holding)
        except Exception as exc:
            errors += 1
            last_error = f"{type(exc).__name__}: {exc}"
            action = "ERROR"
        if action == "BUY_REQUEST" and not holding:
            holding = True
            entry_px = close_f
            net_ret -= leg_fee
            signals += 1
        elif action == "SELL_REQUEST" and holding:
            holding = False
            net_ret -= leg_fee
            ep_ret = ((close_f - entry_px) / max(1e-9, entry_px)) - fee_rt
            episode_rets_bps.append(ep_ret * 10_000.0)
            signals += 1
        daily_rets.append(net_ret)
    if holding and prepared:
        daily_rets[-1] -= leg_fee
        ep_ret = ((prepared[-1][1] - entry_px) / max(1e-9, entry_px)) - fee_rt
        episode_rets_bps.append(ep_ret * 10_000.0)

    n = len(daily_rets)
    sd = stdev(daily_rets) if n >= 3 else 0.0
    sr = (mean(daily_rets) / sd) if sd > 1e-12 else 0.0
    ann_sr = round(sr * math.sqrt(365.0), 3)
    dsr = compute_deflated_sharpe_ratio(sr, n, n_trials=18)
    lko = compute_leave_k_out_fragility(episode_rets_bps, max_k=3)
    lko_k1 = lko[1]["mean_bps"] if len(lko) > 1 else 0.0
    if errors > 0:
        tier = "ERROR_STRATEGY_EXCEPTION"
    elif len(episode_rets_bps) >= 3 and dsr >= 0.80 and lko_k1 > 0.0:
        tier = "PROMOTE_REFERENCE"
    elif dsr >= 0.50 and signals > 0:
        tier = "SHADOW_CANDIDATE"
    elif signals == 0:
        tier = "HOLD_NEEDS_MULTI_ASSET_OR_INTRADAY"
    else:
        tier = "RETIRE_FAIL_DSR"
    return {
        "strategy_id": strategy_id,
        "signals": signals,
        "episodes": len(episode_rets_bps),
        "errors": errors,
        "last_error": last_error,
        "ann_sharpe": ann_sr,
        "deflated_sharpe_ratio": dsr,
        "lko_k0_mean_bps": lko[0]["mean_bps"] if lko else 0.0,
        "lko_k1_mean_bps": lko_k1,
        "tier": tier,
    }


def audit_18_strategy_catalog(db_path: Path, *, symbol: str = "BTCUSDT") -> dict:
    """Audit all 18 registered strategies with DSR (N=18) and Leave-K-Out fragility."""
    con = open_readonly_market_db(db_path)
    try:
        with readonly_snapshot(con):
            bars = load_keyed_candles(con, symbol, "1d")
    finally:
        con.close()
    prepared = _prepare_snapshots(bars, symbol)
    rows = [_simulate_strategy_on_bars(item["id"], dict(item.get("default_params") or {}), prepared) for item in catalog()]
    return {
        "symbol": symbol,
        "bars": len(bars),
        "strategies_audited": len(rows),
        "rows": sorted(rows, key=lambda r: r["deflated_sharpe_ratio"], reverse=True),
    }


def compute_live_fx_attribution(db_path: Path) -> dict:
    """Decompose local BTCTMN return into global BTCUSDT alpha, USDTTMN FX, and local venue basis."""
    con = open_readonly_market_db(db_path)
    try:
        with readonly_snapshot(con):
            btc_tmn = load_keyed_candles(con, "BTCTMN", "1d")
            usdt_tmn = load_keyed_candles(con, "USDTTMN", "1d")
            btc_usdt = load_keyed_candles(con, "BTCUSDT", "1d")
            fx_rows = con.execute(
                "SELECT bid, ask FROM book_top WHERE instrument_id IN ('wallex:USDTTMN','nobitex:USDTTMN') "
                "ORDER BY rowid DESC LIMIT 200"
            ).fetchall()
    except sqlite3.Error:
        fx_rows = []
        btc_tmn = usdt_tmn = btc_usdt = []
    finally:
        con.close()

    quotes: list[tuple[float, float]] = []
    for bid_s, ask_s in fx_rows:
        try:
            b, a = float(bid_s), float(ask_s)
            if b > 0 and a >= b:
                mid = 0.5 * (b + a)
                sp = max(0.5, (a - b) / mid * 10_000.0)
                quotes.append((mid, sp))
        except (ValueError, TypeError):
            continue
    kalman_fx = consensus_kalman_fx_rate(quotes)

    m_tmn = {c.ts_avail.date(): c.close for c in btc_tmn}
    m_fx = {c.ts_avail.date(): c.close for c in usdt_tmn}
    m_usd = {c.ts_avail.date(): c.close for c in btc_usdt}
    common = sorted(set(m_tmn) & set(m_fx) & set(m_usd))
    if len(common) < 2:
        return {"status": "INSUFFICIENT_OVERLAP", "common_days": len(common), "consensus_usdt_tmn": kalman_fx}
    d0, d1 = common[0], common[-1]
    r_local = math.log(m_tmn[d1] / m_tmn[d0])
    r_fx = math.log(m_fx[d1] / m_fx[d0])
    r_global = math.log(m_usd[d1] / m_usd[d0])
    g_ret, fx_ret, basis_ret = decompose_dual_factor_fx_return(r_local, r_fx, r_global)
    end_basis_bps = compute_local_fx_basis_stress(m_tmn[d1], m_fx[d1], m_usd[d1])
    return {
        "status": "OK",
        "window": [d0.isoformat(), d1.isoformat()],
        "common_days": len(common),
        "global_crypto_log_ret": g_ret,
        "fx_devaluation_log_ret": fx_ret,
        "venue_basis_log_ret": basis_ret,
        "ending_basis_bps": end_basis_bps,
        "consensus_usdt_tmn": kalman_fx,
    }


def calibrate_empirical_slippage_by_hour(
    db_path: Path,
    *,
    instrument_id: str = "wallex:BTCUSDT",
    fee_bps: float = 16.0,
    max_rows: int = 50_000,
) -> dict:
    """Calibrate hourly Tehran spread & 1.5x implementation-shortfall hurdles from recorded book_top snapshots."""
    con = open_readonly_market_db(db_path)
    try:
        rows = con.execute(
            "SELECT ts_avail, bid, ask FROM book_top WHERE instrument_id=? ORDER BY rowid DESC LIMIT ?",
            (instrument_id, max_rows),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()

    by_hour: dict[int, list[float]] = defaultdict(list)
    for ts_s, bid_s, ask_s in rows:
        try:
            b, a = float(bid_s), float(ask_s)
            if b <= 0 or a < b:
                continue
            sp_bps = (a - b) / (0.5 * (a + b)) * 10_000.0
            if 0.0 <= sp_bps <= 500.0:
                hour = parse_ts(ts_s).astimezone(TEHRAN).hour
                by_hour[hour].append(sp_bps)
        except (ValueError, TypeError):
            continue

    hourly: dict[str, dict] = {}
    for hour in sorted(by_hour):
        vals = sorted(by_hour[hour])
        med = round(median(vals), 2)
        p90 = round(vals[int(0.90 * (len(vals) - 1))], 2)
        _, _, hurdle = pre_trade_implementation_shortfall_gate(
            0.0, spread_bps=p90, fee_bps=fee_bps, margin_multiple=1.5,
        )
        hourly[f"{hour:02d}"] = {
            "samples": len(vals),
            "median_spread_bps": med,
            "p90_spread_bps": p90,
            "is_hurdle_bps_1_5x": hurdle,
        }
    return {"instrument_id": instrument_id, "rows_scanned": len(rows), "tehran_hours": hourly}


def evaluate_ml_shadow_readiness(artifact_path: Path | None, *, as_of: datetime | None = None) -> dict:
    """Verify ML shadow artifact expiry, semantic engine digest, and non-zero weight governance."""
    now = as_of or datetime.now(UTC)
    digest = semantic_engine_digest()
    if artifact_path is None or not artifact_path.is_file():
        return {
            "status": "NO_SHADOW_ARTIFACT",
            "permitted_portfolio_weight": 0.0,
            "semantic_engine_digest": digest,
            "checked_at_utc": now.isoformat(),
        }
    try:
        EnsembleGRU.load_json(artifact_path, now=now)
        meta = json.loads(artifact_path.read_text(encoding="utf-8")).get("metadata", {})
        return {
            "status": "SHADOW_READY_UNEXPIRED",
            "permitted_portfolio_weight": 0.0,  # Shadow-only until purged WFO sign-off
            "expires_at": meta.get("expires_at"),
            "semantic_engine_digest": digest,
            "checked_at_utc": now.isoformat(),
        }
    except Exception as exc:
        return {
            "status": "REJECTED",
            "reason": str(exc),
            "permitted_portfolio_weight": 0.0,
            "semantic_engine_digest": digest,
            "checked_at_utc": now.isoformat(),
        }


def run_and_publish_quant_v3_audit(db_path: Path, out_dir: Path) -> dict:
    """Execute all 4 Track-3 quantitative & ML audits and publish JSON + Markdown evidence."""
    report = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "mode": "PAPER_ONLY",
        "executor_state": "DISARMED",
        "catalog_dsr_audit": audit_18_strategy_catalog(db_path),
        "fx_dual_factor_attribution": compute_live_fx_attribution(db_path),
        "empirical_slippage_calibration": calibrate_empirical_slippage_by_hour(db_path),
        "ml_shadow_readiness": evaluate_ml_shadow_readiness(None),
    }
    write_json_atomic(out_dir / "18-strategy-dsr-fx-slippage-audit.json", report)
    lines = [
        "# 18-Strategy DSR, Dual-Factor FX, Empirical Slippage & ML Shadow Audit",
        "",
        f"- **Generated (UTC):** `{report['generated_at_utc']}`",
        "- **Mode:** `PAPER_ONLY` (`TradingGYMExecutor` remains `DISARMED` / `$0`)",
        f"- **Strategies Audited:** `{report['catalog_dsr_audit']['strategies_audited']}` across `{report['catalog_dsr_audit']['bars']}` daily bars",
        "",
        "## 1. 18-Strategy Deflated Sharpe Ratio (N=18) & Leave-K-Out Fragility",
        "",
        "| Strategy | Signals | Episodes | Ann Sharpe | DSR (N=18) | LKO K=0 (bps) | LKO K=1 (bps) | Tier |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for r in report["catalog_dsr_audit"]["rows"]:
        lines.append(
            f"| `{r['strategy_id']}` | {r['signals']} | {r['episodes']} | {r['ann_sharpe']:.3f} | "
            f"{r['deflated_sharpe_ratio']:.4f} | {r['lko_k0_mean_bps']:.1f} | {r['lko_k1_mean_bps']:.1f} | `{r['tier']}` |"
        )
    fx = report["fx_dual_factor_attribution"]
    lines += [
        "",
        "## 2. USD/USDT vs. IRR Dual-Factor Attribution",
        "",
        f"- **Status:** `{fx.get('status')}` | **Consensus Kalman USDT/TMN:** `{fx.get('consensus_usdt_tmn')}`",
    ]
    if fx.get("status") == "OK":
        lines.append(
            f"- **Window:** `{fx['window'][0]}` → `{fx['window'][1]}` ({fx['common_days']} days) | "
            f"**Global Crypto:** `{fx['global_crypto_log_ret']:.4f}` | **FX Devaluation:** `{fx['fx_devaluation_log_ret']:.4f}` | "
            f"**Venue Basis:** `{fx['venue_basis_log_ret']:.4f}` | **Ending Basis:** `{fx['ending_basis_bps']} bps`"
        )
    sl = report["empirical_slippage_calibration"]
    lines += [
        "",
        "## 3. Empirical Slippage & 1.5× Implementation-Shortfall Calibration",
        "",
        f"- **Instrument:** `{sl['instrument_id']}` | **Quotes Scanned:** `{sl['rows_scanned']}` | **Tehran Hours Covered:** `{len(sl['tehran_hours'])}`",
        "",
        "## 4. ML Lifecycle & Shadow Readiness",
        "",
        f"- **Status:** `{report['ml_shadow_readiness']['status']}` | **Permitted Weight:** `{report['ml_shadow_readiness']['permitted_portfolio_weight']}` | **Engine Digest:** `{report['ml_shadow_readiness']['semantic_engine_digest'][:16]}`",
        "",
    ]
    write_text_atomic(out_dir / "18-strategy-dsr-fx-slippage-audit.md", "\n".join(lines))
    return report
