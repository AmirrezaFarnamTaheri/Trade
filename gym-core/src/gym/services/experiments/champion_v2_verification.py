"""Unified v2 Champion vs v1 Champion head-to-head verification on a single shared SelfFinancingLedger.

Combines strictly the 6 empirically verified zero-lookahead winners:
- 1d Core: BASE_13_S1_S5 + ACCEL_BLEND_20 + Multi-issuer defensive metals reserve (XAUT/PAXG/SLVON)
- 2h Ignition: 50/50 phase-invariant twin book (0h + 1h) + 11-feat Coiled-Spring GRU (exact Path-PnL) + Conformal/DD Governor
- Portfolio Layer: Joint Single-ADMM cross-sleeve netting & sector cluster caps (<= 0.40)
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    solve_convex_portfolio,
)
from ...domain.core_signal_geometry import (
    DEFENSIVE_METALS_CAPS,
    compute_defensive_metals_reserve,
)
from ...domain.diffusion_and_netting import _build_cluster_groups
from ...domain.higher_order_and_sparse import compute_second_order_trend_map
from ...domain.ignition_and_intraday_exit import run_shared_ledger_1h_blend
from ...domain.ignition_upgrades import _select_lev_and_col
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.short_and_levered_ignition import (
    _breakdown_or_breakout_z,
    _check_margin_exit,
)
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    extract_daily_breadth,
)
from .ensemble_study import STRESS_REPLAY_START, _daily_returns_map, _portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .ignition_upgrade_ablation_study import (
    _extract_11feat_coiled_spring_dataset,
    _walkforward_gru_scores,
)
from .ignition_validation_study import _extract_daily_s1_s5_targets


def _extract_ignition_target_schedule(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth: dict[str, float],
    score_map: dict[tuple[datetime, str], float] | None,
    *,
    score_is_return: bool,
    base_prob: float | dict[datetime, float],
    use_conformal_dd: bool,
    leg_cost: float,
) -> dict[datetime, dict[str, float]]:
    """Generate causal per-2h-bar target weights for GRU-sized ignition (1.0x/1.5x spot-equivalent weight)."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_h: dict[str, list[float]] = {s: [] for s in symbols}
    vol_h: dict[str, list[float]] = {s: [] for s in symbols}
    high_h: dict[str, list[float]] = {s: [] for s in symbols}
    low_h: dict[str, list[float]] = {s: [] for s in symbols}
    prev_c: dict[str, float] = {}
    recent_sc: list[float] = []

    equity, peak_eq = 1000.0, 1000.0
    active: dict[str, dict] = {}
    schedule: dict[datetime, dict[str, float]] = {}

    for ts in all_ts:
        cands = []
        for sym in symbols:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_c[sym]) / prev_c[sym]) if (sym in prev_c and prev_c[sym] > 0) else 0.0
            if cur.entry_eligible and nxt and nxt.open > 0 and sym not in active:
                hit = _breakdown_or_breakout_z(
                    cur, r, high_h[sym][-72:], low_h[sym][-72:], ret_h[sym][-36:], vol_h[sym][-36:],
                    side="LONG", breakout_bars=72, vol_lookback=36, z_threshold=3.0, vol_mult=2.5,
                )
                if hit is not None:
                    cands.append((hit[0], sym, hit[1]))
            if sym in prev_c and prev_c[sym] > 0:
                ret_h[sym].append(r)
            prev_c[sym] = cur.close
            vol_h[sym].append(cur.volume)
            high_h[sym].append(cur.high)
            low_h[sym].append(cur.low)

        for sym in list(active):
            pos = active[sym]
            is_c, _, pnl, brw, _ = _check_margin_exit(
                pos, by_avail[sym].get(ts), by_start[sym].get(ts),
                side="LONG", leverage=pos["lev"], max_hold_bars=24, trail_stop_mult=2.5,
                hard_stop_pct=0.04, leg_cost=leg_cost, borrow_per_bar=0.000075,
            )
            equity -= brw
            if is_c:
                equity = max(0.0, equity + pnl)
                del active[sym]

        mark_u = sum(
            max(-p["collateral"], p["qty"] * (by_avail[s][ts].close - p["entry_px"]))
            for s, p in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        mark_eq = max(0.0, equity + mark_u)
        peak_eq = max(peak_eq, mark_eq)
        in_dd = use_conformal_dd and peak_eq > 0 and ((peak_eq - mark_eq) / peak_eq >= 0.05)

        if equity > 100.0 and daily_breadth.get(ts.date().isoformat(), 0.0) >= 0.45 and cands and len(active) < 3:
            cands.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in cands:
                sc = score_map.get((ts, sym)) if score_map is not None else None
                if sc is not None:
                    recent_sc.append(sc)
                if len(active) >= 3:
                    break
                nxt = by_start[sym].get(ts)
                if not nxt or nxt.open <= 0:
                    continue
                bp = base_prob.get(ts, 0.46) if isinstance(base_prob, dict) else base_prob
                lev, col_f = _select_lev_and_col(
                    sc, score_is_return=score_is_return, base_prob=bp,
                    use_conformal=use_conformal_dd, recent_scores=recent_sc, in_dd_throttle=in_dd,
                )
                free_c = max(0.0, equity - sum(p["collateral"] for p in active.values()))
                col = min(equity * col_f, free_c)
                if col < 25.0:
                    continue
                notional = col * lev
                ef = notional * leg_cost
                equity = max(0.0, equity - ef)
                active[sym] = {
                    "collateral": col, "notional": notional, "qty": notional / nxt.open,
                    "entry_px": nxt.open, "entry_fee": ef, "extreme": nxt.open,
                    "b_vol": b_vol, "liq_price": nxt.open * max(0.0, 1.0 - (0.85 / lev)) if lev > 1.0 else 0.0,
                    "age": 0, "lev": lev, "slot_w": col_f * lev,
                }
        schedule[ts] = {s: p["slot_w"] for s, p in active.items()}
    return schedule


def _merge_twin_schedules(
    sched_0h: dict[datetime, dict[str, float]],
    sched_1h: dict[datetime, dict[str, float]],
) -> dict[datetime, dict[str, float]]:
    """Merge 50% 0h-phase + 50% +1h-phase ignition schedules onto a unified 1h timestamp clock."""
    all_ts = sorted(set(sched_0h) | set(sched_1h))
    cur_0: dict[str, float] = {}
    cur_1: dict[str, float] = {}
    merged: dict[datetime, dict[str, float]] = {}
    for ts in all_ts:
        if ts in sched_0h:
            cur_0 = sched_0h[ts]
        if ts in sched_1h:
            cur_1 = sched_1h[ts]
        syms = set(cur_0) | set(cur_1)
        merged[ts] = {s: 0.5 * cur_0.get(s, 0.0) + 0.5 * cur_1.get(s, 0.0) for s in syms if (cur_0.get(s, 0.0) + cur_1.get(s, 0.0)) > 1e-6}
    return merged


def _run_v2_joint_shared_ledger(
    panel_1h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    sigs_13: dict,
    accel_13: dict,
    sigs_metals: dict,
    cov_h_by_ts: dict[datetime, tuple[tuple[str, ...], tuple[tuple[float, ...], ...]]],
    ign_sched: dict[datetime, dict[str, float]],
    *,
    slow_budget: float,
    ign_budget: float,
    fee_rate: Decimal,
    use_metals_reserve: bool = True,
) -> dict:
    """Single shared SelfFinancingLedger running unified v2 Champion (1d ACCEL + 11A + Joint ADMM + Twin GRU)."""
    by_avail = {s: {b.ts_avail: b for b in panel_1h.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_1h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    cur_slow: dict[str, float] = {s: 0.0 for s in symbols}
    prev_ign: dict[str, float] = {}
    nav_by_date: dict[str, float] = {}
    sqrt_h = math.sqrt(20.0)

    for ts in all_ts:
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        for sym in symbols:
            nxt, cur = by_start[sym].get(ts), by_avail[sym].get(ts)
            if nxt is not None and nxt.open > 0:
                exec_prices[sym] = Decimal(str(nxt.open))
                last_mark[sym] = exec_prices[sym]
                if cur is not None and cur.entry_eligible:
                    tradable.add(sym)
            elif cur is not None and cur.close > 0:
                exec_prices[sym] = Decimal(str(cur.close))
                last_mark[sym] = exec_prices[sym]
            elif sym in last_mark:
                exec_prices[sym] = last_mark[sym]

        ign_now = ign_sched.get(ts, prev_ign)
        ign_changed = set(ign_now) != set(prev_ign) or any(abs(ign_now.get(s, 0.0) - prev_ign.get(s, 0.0)) > 1e-6 for s in set(ign_now) | set(prev_ign))
        prev_ign = ign_now
        is_daily = ts in cov_h_by_ts and ts in sigs_13

        if is_daily:
            active_slow, cov_h = cov_h_by_ts[ts]
            day_sigs = sigs_13[ts]
            day_acc = accel_13.get(ts, {})
            live_w = ledger.current_weights(active_slow, exec_prices)
            ign_active = {s: ign_budget * ign_now.get(s, 0.0) for s in symbols}
            reserved_ign = min(0.45, sum(ign_active.values()))
            adj_cur = tuple(max(0.0, (lw - ign_active.get(s, 0.0)) / max(slow_budget, 1e-6)) for s, lw in zip(active_slow, live_w, strict=True))

            mu_gross = []
            for sym in active_slow:
                sig = day_sigs[sym]
                s1_v = sig.s1_trend
                if s1_v is not None:
                    s1_v = max(-1.0, min(1.0, 0.80 * s1_v + 0.20 * day_acc.get(sym, 0.0)))
                parts = [v for v in (s1_v, sig.s5_defensive_gold) if v is not None]
                raw = sum(parts) / len(parts) if parts else 0.0
                mu_gross.append(
                    forecast_to_expected_return_bps(raw * 20.0, ic_prior=0.08, horizon_vol_bps=sig.yang_zhang_vol * sqrt_h * 10000.0) / 10000.0
                )
            prob = OptimizationProblem(
                symbols=active_slow, expected_returns=tuple(mu_gross), current_weights=adj_cur,
                covariance=cov_h, l1_fee_costs=(float(fee_rate),) * len(active_slow),
                l2_impact_costs=(0.0020,) * len(active_slow), risk_aversion=2.0,
                max_weight=0.30, cash_buffer=0.05, reserved_open_weight=max(0.0, reserved_ign * 0.5),
                underlying_groups=_build_cluster_groups(active_slow), max_underlying_weight=0.40,
            )
            solved = solve_convex_portfolio(prob).weights
            cur_slow = {s: 0.0 for s in symbols}
            for s, w in zip(active_slow, solved, strict=True):
                cur_slow[s] = w

            if use_metals_reserve:
                day_br = next((s.crypto_breadth for s in day_sigs.values() if s.crypto_breadth is not None), None)
                res_w = compute_defensive_metals_reserve(sigs_metals.get(ts, {}), day_br)
                free_c = max(0.0, 0.95 - sum(cur_slow.values()))
                for ms, mw in res_w.items():
                    if ms in exec_prices and mw > 0:
                        add_w = max(0.0, mw - cur_slow.get(ms, 0.0))
                        take = min(add_w, free_c)
                        cur_slow[ms] = cur_slow.get(ms, 0.0) + take
                        free_c -= take

        if is_daily or ign_changed:
            raw = {
                s: min(0.40, slow_budget * cur_slow.get(s, 0.0) + ign_budget * ign_now.get(s, 0.0))
                for s in symbols
            }
            tot = sum(raw.values())
            if tot > 0.95 and tot > 0:
                sc = 0.95 / tot
                raw = {s: w * sc for s, w in raw.items()}
            ledger.rebalance_to_targets(ts, raw, exec_prices, tradable_symbols=tradable)

        nav_by_date[ts.date().isoformat()] = float(ledger.mark_nav(exec_prices))

    return {
        "nav_by_date": nav_by_date,
        "fills": len(ledger.fills),
        "total_fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "turnover_multiple": round(float(ledger.cumulative_turnover_quote / ledger.starting_cash), 2),
    }


def run_v2_champion_verification(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Head-to-head single-shared-ledger verification of Unified v2 Champion vs v1 Champion & BASE_13."""
    union_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO + tuple(DEFENSIVE_METALS_CAPS)))
    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in union_syms}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in union_syms}
    finally:
        con.close()

    panel_13 = {s: panel_1d[s] for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_breadth = extract_daily_breadth(sigs_13)
    accel_13 = compute_second_order_trend_map(sigs_13, BASE_13_SYMBOLS)
    sigs_metals = compute_slow_sleeves({s: panel_1d[s] for s in DEFENSIVE_METALS_CAPS}, tuple(DEFENSIVE_METALS_CAPS), min_active_crypto=1, warmup_bars=64)

    dated_rets = build_dated_returns_index(panel_13, BASE_13_SYMBOLS)
    cov_h_by_ts = {}
    for ts in eval_dates[:-1]:
        act = tuple(s for s in BASE_13_SYMBOLS if s in sigs_13.get(ts, {}))
        if len(act) >= 2:
            cov_h_by_ts[ts] = (act, build_shrunk_horizon_cov(dated_rets, act, ts))

    daily_v1_targets = _extract_daily_s1_s5_targets(panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0013"))

    p18_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    p18_1 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=1) for s in IGNITION_18_CRYPTO}

    # Purged walk-forward GRU scores for v1 (6-feat BCE on 0h) & v2 (11-feat Path-PnL + 8-feat BCE on BOTH 0h & +1h!)
    d0, s0, x0, yb0, yp0 = _extract_11feat_coiled_spring_dataset(p18_0, IGNITION_18_CRYPTO, daily_breadth)
    d1, s1, x1, yb1, yp1 = _extract_11feat_coiled_spring_dataset(p18_1, IGNITION_18_CRYPTO, daily_breadth)

    sc_v1_0, auc_v1, br_v1 = _walkforward_gru_scores(d0, s0, x0[:, :, :6], yb0, yb0, task="binary")
    sc_v2_p11_0, auc_p11_0, br_p11 = _walkforward_gru_scores(d0, s0, x0, yp0, yb0, task="regression")
    sc_v2_p11_1, auc_p11_1, _ = _walkforward_gru_scores(d1, s1, x1, yp1, yb1, task="regression")
    sc_v2_g8_0, auc_g8_0, br_g8 = _walkforward_gru_scores(d0, s0, x0[:, :, :8], yb0, yb0, task="binary")
    sc_v2_g8_1, auc_g8_1, _ = _walkforward_gru_scores(d1, s1, x1[:, :, :8], yb1, yb1, task="binary")

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    arms_out: list[dict] = []

    for tag, fee_f in (("NBX16", 0.0016), ("WLX25", 0.0025)):
        fee_d = Decimal(str(fee_f))
        # Overlap baseline: 100% BASE_13_S1_S5
        base_run = run_shared_ledger_1h_blend(panel_1h, union_syms, daily_v1_targets, {}, slow_weight=1.0, ignition_weight=0.0, fee_rate=fee_d)
        base_rets = _daily_returns_map(base_run["nav_by_date"])

        # V1 Champion: 70% BASE_13 + 30% 0h GRU6 Ignition (post-hoc)
        ign_v1 = _extract_ignition_target_schedule(p18_0, IGNITION_18_CRYPTO, daily_breadth, sc_v1_0, score_is_return=False, base_prob=br_v1, use_conformal_dd=False, leg_cost=fee_f)
        v1_run = run_shared_ledger_1h_blend(panel_1h, union_syms, daily_v1_targets, ign_v1, slow_weight=0.70, ignition_weight=0.30, fee_rate=fee_d)
        v1_rets = _daily_returns_map(v1_run["nav_by_date"])

        # V2 Twin Schedules: (a) GRU11 Path-PnL + Conformal/DD, (b) GRU8 BCE + Conformal/DD
        ign_v2_p11 = _merge_twin_schedules(
            _extract_ignition_target_schedule(p18_0, IGNITION_18_CRYPTO, daily_breadth, sc_v2_p11_0, score_is_return=True, base_prob=br_p11, use_conformal_dd=True, leg_cost=fee_f),
            _extract_ignition_target_schedule(p18_1, IGNITION_18_CRYPTO, daily_breadth, sc_v2_p11_1, score_is_return=True, base_prob=br_p11, use_conformal_dd=True, leg_cost=fee_f),
        )
        ign_v2_g8 = _merge_twin_schedules(
            _extract_ignition_target_schedule(p18_0, IGNITION_18_CRYPTO, daily_breadth, sc_v2_g8_0, score_is_return=False, base_prob=br_g8, use_conformal_dd=True, leg_cost=fee_f),
            _extract_ignition_target_schedule(p18_1, IGNITION_18_CRYPTO, daily_breadth, sc_v2_g8_1, score_is_return=False, base_prob=br_g8, use_conformal_dd=True, leg_cost=fee_f),
        )

        v2_p11_70 = _run_v2_joint_shared_ledger(panel_1h, union_syms, sigs_13, accel_13, sigs_metals, cov_h_by_ts, ign_v2_p11, slow_budget=0.70, ign_budget=0.30, fee_rate=fee_d)
        v2_p11_60 = _run_v2_joint_shared_ledger(panel_1h, union_syms, sigs_13, accel_13, sigs_metals, cov_h_by_ts, ign_v2_p11, slow_budget=0.60, ign_budget=0.40, fee_rate=fee_d)
        v2_g8_70 = _run_v2_joint_shared_ledger(panel_1h, union_syms, sigs_13, accel_13, sigs_metals, cov_h_by_ts, ign_v2_g8, slow_budget=0.70, ign_budget=0.30, fee_rate=fee_d)
        v2_g8_60 = _run_v2_joint_shared_ledger(panel_1h, union_syms, sigs_13, accel_13, sigs_metals, cov_h_by_ts, ign_v2_g8, slow_budget=0.60, ign_budget=0.40, fee_rate=fee_d)

        for name, run in (
            (f"BASE_13_100PCT_{tag}", base_run),
            (f"V1_CHAMPION_70_30_{tag}", v1_run),
            (f"V2_GRU11_PATHPNL_70_30_{tag}", v2_p11_70),
            (f"V2_GRU11_PATHPNL_60_40_{tag}", v2_p11_60),
            (f"V2_GRU8_CONFORMAL_70_30_{tag}", v2_g8_70),
            (f"V2_GRU8_CONFORMAL_60_40_{tag}", v2_g8_60),
        ):
            nav = run["nav_by_date"]
            rets = _daily_returns_map(nav)
            ub = paired_baseline_uplift(rets, base_rets, simulations=499, seed=42)
            uv = paired_baseline_uplift(rets, v1_rets, simulations=499, seed=42)
            cib = ub.get("ci_95")
            civ = uv.get("ci_95")
            arms_out.append({
                "name": name,
                "full": _portfolio_metrics(nav),
                "stress": _portfolio_metrics({k: v for k, v in nav.items() if k >= stress_iso}),
                "fills": run["fills"],
                "fees_usdt": run["total_fees_usdt"],
                "turnover": run["turnover_multiple"],
                "vs_base_bps": round(float(ub.get("mean_uplift", 0.0)) * 10000.0, 2),
                "ci_base_bps": [round(cib[0] * 10000.0, 2), round(cib[1] * 10000.0, 2)] if cib is not None else None,
                "vs_v1_bps": round(float(uv.get("mean_uplift", 0.0)) * 10000.0, 2),
                "ci_v1_bps": [round(civ[0] * 10000.0, 2), round(civ[1] * 10000.0, 2)] if civ is not None else None,
            })

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "oos_aucs": {
            "v1_gru6_0h": auc_v1,
            "v2_gru11_pathpnl_0h": auc_p11_0,
            "v2_gru11_pathpnl_1h": auc_p11_1,
            "v2_gru8_bce_0h": auc_g8_0,
            "v2_gru8_bce_1h": auc_g8_1,
        },
        "arms": arms_out,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    aucs = p["oos_aucs"]
    lines = [
        "# Unified v2 Champion vs. v1 Champion — End-to-End Single Shared-Ledger Verification",
        "",
        f"- **Generated:** `{p['generated_at']}`",
        f"- **Purged Walk-Forward OOS AUCs:** `v1 GRU6 (0h) = {aucs['v1_gru6_0h']:.4f}` · `v2 GRU11 Path-PnL (0h/1h) = {aucs['v2_gru11_pathpnl_0h']:.4f} / {aucs['v2_gru11_pathpnl_1h']:.4f}` · `v2 GRU8 BCE (0h/1h) = {aucs['v2_gru8_bce_0h']:.4f} / {aucs['v2_gru8_bce_1h']:.4f}`",
        "- **Architecture:** Single `SelfFinancingLedger` over the full `1h` overlap (`2024–2026` chop+bear window, `$1,000` start), combining `1d` `BASE_13 + ACCEL_BLEND_20 + 11A Metals Reserve`, Joint Single-ADMM Cross-Sleeve Netting (`<=0.40` sector caps), and `50/50` Twin-Phase `2h` GRU-Ignition with Conformal Rank + 5% DD Leverage Governor.",
        "",
        "| Arm | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Fills | Fees ($) | vs Base (bps/d, 95% CI) | vs v1 Champion (bps/d, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for r in p["arms"]:
        cb = f"[{r['ci_base_bps'][0]:+.2f}, {r['ci_base_bps'][1]:+.2f}]" if r["ci_base_bps"] is not None else "N/A"
        cv = f"[{r['ci_v1_bps'][0]:+.2f}, {r['ci_v1_bps'][1]:+.2f}]" if r["ci_v1_bps"] is not None else "N/A"
        lines.append(
            f"| `{r['name']}` | `${r['full']['ending_nav']:.2f}` | `{r['full']['ret_pct']:+.2f}%` | `{r['stress']['ret_pct']:+.2f}%` | "
            f"`{r['full']['ann_sharpe']:.3f}` | `{r['full']['max_dd_pct']:.2f}%` | `{r['fills']}` | `${r['fees_usdt']:.2f}` | "
            f"`{r['vs_base_bps']:+.2f} {cb}` | "
            f"`{r['vs_v1_bps']:+.2f} {cv}` |"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
