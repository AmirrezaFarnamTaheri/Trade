"""Four-part Nobitex Pay-As-You-Go Margin (0.05%/day, 16 bps) vs. Wallex Margin & Trade-Credit study.

1. Bull-regime 1.35x / 1.50x leverage on 1d BASE_13 + ACCEL_BLEND_20 (breadth >= 0.55) + idle USDT pool yield.
2. Event-scoped 1.5x / 2.0x leverage on top-tercile 2h GRU-Ignition (Conformal + 5% DD Governor) under exact
   Nobitex EOD UTC borrow (0% intraday) vs. Wallex 4h borrow + Unified v2 Champion shared-ledger check.
3. 1d Structural Bear-Laggard Short on exact Nobitex Margin (17/18 live eligible pairs) vs. Wallex Margin + blend check.
4. Wallex Fixed Trade-Credit (5x: $200 collateral + $1,000 credit, fixed $15/30d, 13% stop-out) stress test.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.core_signal_geometry import DEFENSIVE_METALS_CAPS
from ...domain.higher_order_and_sparse import (
    compute_second_order_trend_map,
    simulate_structural_breakdown_short,
)
from ...domain.ignition_and_intraday_exit import pearson_correlation
from ...domain.ignition_upgrades import combine_twin_phase_navs
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from ...domain.venue_leverage_models import (
    NOBITEX_MARGIN_ELIGIBLE_USDT,
    simulate_bull_levered_1d_core,
    simulate_nobitex_margin_ignition,
    simulate_wallex_trade_credit_contract,
)
from .admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    extract_daily_breadth,
    solve_s1_s5_admm_weights,
)
from .champion_v2_verification import _merge_twin_schedules, _run_v2_joint_shared_ledger
from .ensemble_study import STRESS_REPLAY_START, _daily_returns_map, _portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .ignition_upgrade_ablation_study import (
    _extract_11feat_coiled_spring_dataset,
    _walkforward_gru_scores,
)

NOBITEX_IDLE_USDT_APR = 0.0264  # Observed live 2026-11-25 via GET /liquidity-pools/list


def _extract_accel20_targets(
    panel_13: dict[str, list[BarPoint]],
    sigs_13: dict,
    eval_dates: list[datetime],
) -> dict[datetime, dict[str, float]]:
    """Compute strictly causal daily ADMM target weights for BASE_13 + ACCEL_BLEND_20."""
    accel_map = compute_second_order_trend_map(sigs_13, BASE_13_SYMBOLS)
    by_start = {s: {b.ts_start: b for b in panel_13.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_13.get(s, [])} for s in BASE_13_SYMBOLS}
    dated_rets = build_dated_returns_index(panel_13, BASE_13_SYMBOLS)

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=Decimal("0.0016"), fee_in_received_asset=True)
    targets_by_ts: dict[datetime, dict[str, float]] = {}
    for t_avail in eval_dates[:-1]:
        day_sigs = sigs_13.get(t_avail, {})
        day_acc = accel_map.get(t_avail, {})
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        for sym in BASE_13_SYMBOLS:
            nxt, cur = by_start[sym].get(t_avail), by_avail[sym].get(t_avail)
            if nxt and nxt.open > 0:
                exec_prices[sym] = Decimal(str(nxt.open))
                if cur and cur.entry_eligible:
                    tradable.add(sym)
            elif cur and cur.close > 0:
                exec_prices[sym] = Decimal(str(cur.close))
        active = tuple(s for s in BASE_13_SYMBOLS if s in day_sigs and s in exec_prices)
        if len(active) < 2:
            targets = {s: 0.0 for s in BASE_13_SYMBOLS}
        else:
            cur_w = ledger.current_weights(active, exec_prices)
            cov_h = build_shrunk_horizon_cov(dated_rets, active, t_avail)
            s1_ovr = {
                sym: max(-1.0, min(1.0, 0.80 * day_sigs[sym].s1_trend + 0.20 * day_acc.get(sym, 0.0)))
                if day_sigs[sym].s1_trend is not None else None
                for sym in active
            }
            solved = solve_s1_s5_admm_weights(active, day_sigs, cur_w, cov_h, s1_override=s1_ovr)
            targets = {s: w for s, w in zip(active, solved, strict=True)}
        ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
        targets_by_ts[t_avail] = targets
    return targets_by_ts


def _run_part1_bull_levered_core(
    panel_13: dict[str, list[BarPoint]],
    targets_1d: dict[datetime, dict[str, float]],
    daily_breadth: dict[str, float],
) -> tuple[list[dict], dict[str, dict[str, float]]]:
    """Part 1: Bull-regime 1.35x/1.50x leverage on 1d BASE_13 + ACCEL_BLEND_20 (Nobitex vs Wallex)."""
    specs = [
        ("CORE_1.0X_NBX16", 1.0, 0.0016, 0.0005, 0.0),
        ("CORE_1.0X_NBX16_POOL264", 1.0, 0.0016, 0.0005, NOBITEX_IDLE_USDT_APR),
        ("CORE_BULL_1.35X_NBX16", 1.35, 0.0016, 0.0005, 0.0),
        ("CORE_BULL_1.50X_NBX16", 1.50, 0.0016, 0.0005, 0.0),
        ("CORE_BULL_1.50X_NBX16_POOL264", 1.50, 0.0016, 0.0005, NOBITEX_IDLE_USDT_APR),
        ("CORE_1.0X_WLX25", 1.0, 0.0025, 0.0009, 0.0),
        ("CORE_BULL_1.35X_WLX25", 1.35, 0.0025, 0.0009, 0.0),
        ("CORE_BULL_1.50X_WLX25", 1.50, 0.0025, 0.0009, 0.0),
    ]
    navs: dict[str, dict[str, float]] = {}
    raw_res = []
    for label, lev, cost, brw, pool_apr in specs:
        res, nav = simulate_bull_levered_1d_core(
            panel_13, BASE_13_SYMBOLS, targets_1d, daily_breadth,
            label=label, bull_leverage=lev, bull_breadth_threshold=0.55,
            leg_cost=cost, borrow_per_day=brw, idle_usdt_apr=pool_apr,
        )
        navs[label] = nav
        raw_res.append(res)

    base_nbx_rets = _daily_returns_map(navs["CORE_1.0X_NBX16"])
    rows: list[dict] = []
    for r in raw_res:
        up = paired_baseline_uplift(_daily_returns_map(navs[r.label]), base_nbx_rets, simulations=499, seed=42)
        ci = up.get("ci_95") or (0.0, 0.0)
        rows.append({
            **asdict(r),
            "vs_nbx_1x_bps": round(float(up.get("mean_uplift", 0.0)) * 10000.0, 2),
            "vs_nbx_1x_ci": [round(ci[0] * 10000.0, 2), round(ci[1] * 10000.0, 2)],
        })
    return rows, navs


def _run_part2_event_levered_ignition(
    panel_1h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
) -> tuple[list[dict], dict[str, float], dict[datetime, dict[str, float]], dict[datetime, dict[str, float]]]:
    """Part 2: Event-scoped 1.0x/1.5x/2.0x top-tercile 2h GRU-Ignition under exact Nobitex EOD vs Wallex 4h borrow."""
    p2_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    p2_1 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=1) for s in IGNITION_18_CRYPTO}

    d0, s0, x0, yb0, yp0 = _extract_11feat_coiled_spring_dataset(p2_0, IGNITION_18_CRYPTO, daily_breadth)
    d1, s1, x1, yb1, yp1 = _extract_11feat_coiled_spring_dataset(p2_1, IGNITION_18_CRYPTO, daily_breadth)

    sc8_0, auc8_0, br8_0 = _walkforward_gru_scores(d0, s0, x0[:, :, :8], yb0, yb0, task="binary")
    sc8_1, auc8_1, br8_1 = _walkforward_gru_scores(d1, s1, x1[:, :, :8], yb1, yb1, task="binary")
    sc11_0, auc11_0, _ = _walkforward_gru_scores(d0, s0, x0, yp0, yb0, task="regression")
    sc11_1, auc11_1, _ = _walkforward_gru_scores(d1, s1, x1, yp1, yb1, task="regression")
    aucs = {
        "gru8_0h": round(auc8_0, 4), "gru8_1h": round(auc8_1, 4),
        "gru11_path_0h": round(auc11_0, 4), "gru11_path_1h": round(auc11_1, 4),
    }

    configs = [
        ("IGN_GRU8_TWIN_1.0X_NBX16", sc8_0, sc8_1, False, br8_0, br8_1, 1.0, 0.0016, "eod_utc", 0.0005),
        ("IGN_GRU8_TWIN_1.5X_NBX16", sc8_0, sc8_1, False, br8_0, br8_1, 1.5, 0.0016, "eod_utc", 0.0005),
        ("IGN_GRU8_TWIN_2.0X_NBX16", sc8_0, sc8_1, False, br8_0, br8_1, 2.0, 0.0016, "eod_utc", 0.0005),
        ("IGN_GRU11_TWIN_1.5X_NBX16", sc11_0, sc11_1, True, 0.46, 0.46, 1.5, 0.0016, "eod_utc", 0.0005),
        ("IGN_GRU11_TWIN_2.0X_NBX16", sc11_0, sc11_1, True, 0.46, 0.46, 2.0, 0.0016, "eod_utc", 0.0005),
        ("IGN_GRU8_TWIN_1.5X_WLX25", sc8_0, sc8_1, False, br8_0, br8_1, 1.5, 0.0025, "continuous_4h", 0.000075),
        ("IGN_GRU8_TWIN_2.0X_WLX25", sc8_0, sc8_1, False, br8_0, br8_1, 2.0, 0.0025, "continuous_4h", 0.000075),
    ]

    rows: list[dict] = []
    twin_15_sched: dict[datetime, dict[str, float]] = {}
    twin_20_sched: dict[datetime, dict[str, float]] = {}
    for label, m0, m1, is_ret, b0, b1, top_lev, cost, bmode, brate in configs:
        r0, n0, sch0 = simulate_nobitex_margin_ignition(
            p2_0, IGNITION_18_CRYPTO, daily_breadth, m0,
            label=f"{label}_0H", offset_hours=0, score_is_return=is_ret, base_prob=b0,
            top_tercile_leverage=top_lev, leg_cost=cost, borrow_mode=bmode, borrow_rate=brate,
        )
        r1, n1, sch1 = simulate_nobitex_margin_ignition(
            p2_1, IGNITION_18_CRYPTO, daily_breadth, m1,
            label=f"{label}_1H", offset_hours=1, score_is_return=is_ret, base_prob=b1,
            top_tercile_leverage=top_lev, leg_cost=cost, borrow_mode=bmode, borrow_rate=brate,
        )
        twin = combine_twin_phase_navs(label, n0, n1, r0, r1)
        twin.pop("nav_by_date", None)
        rows.append({
            **twin,
            "top_leverage": top_lev,
            "borrow_mode": bmode,
            "entries_avg": round(0.5 * (r0.entries + r1.entries), 1),
            "liquidations_sum": r0.liquidations + r1.liquidations,
            "borrow_usdt_avg": round(0.5 * (r0.total_borrow_usdt + r1.total_borrow_usdt), 2),
            "fees_usdt_avg": round(0.5 * (r0.total_fees_usdt + r1.total_fees_usdt), 2),
        })
        if label == "IGN_GRU8_TWIN_1.5X_NBX16":
            twin_15_sched = _merge_twin_schedules(sch0, sch1)
        elif label == "IGN_GRU8_TWIN_2.0X_NBX16":
            twin_20_sched = _merge_twin_schedules(sch0, sch1)

    return rows, aucs, twin_15_sched, twin_20_sched


def _blend_two_nav_series(nav_a: dict[str, float], nav_b: dict[str, float], w_a: float, w_b: float) -> dict[str, float]:
    """Combine two daily NAV series using constant rebalanced daily return weights on shared dates."""
    dates = sorted(set(nav_a) & set(nav_b))
    if len(dates) < 2:
        return {}
    eq = 1000.0
    out = {dates[0]: eq}
    for i in range(1, len(dates)):
        d0, d1 = dates[i - 1], dates[i]
        ra = (nav_a[d1] / nav_a[d0] - 1.0) if nav_a[d0] > 0 else 0.0
        rb = (nav_b[d1] / nav_b[d0] - 1.0) if nav_b[d0] > 0 else 0.0
        eq = max(0.0, eq * (1.0 + w_a * ra + w_b * rb))
        out[d1] = eq
    return out


def _run_part3_structural_short(
    panel_1d_all: dict[str, list[BarPoint]],
    core_nbx_nav: dict[str, float],
    v2_nbx_nav: dict[str, float],
) -> tuple[list[dict], list[dict]]:
    """Part 3: 1d Structural Bear-Laggard Short on live Nobitex Margin vs. Wallex Margin + portfolio overlay."""
    elig_ign = tuple(s for s in IGNITION_18_CRYPTO if s in NOBITEX_MARGIN_ELIGIBLE_USDT)
    sigs_18 = compute_slow_sleeves({s: panel_1d_all[s] for s in IGNITION_18_CRYPTO}, IGNITION_18_CRYPTO)
    core_rets = _daily_returns_map(core_nbx_nav)
    stress_iso = STRESS_REPLAY_START.date().isoformat()

    short_rows: list[dict] = []
    short_navs: dict[str, dict[str, float]] = {}
    for label, syms, cost, brw, liq_mr in (
        ("STRUCT_SHORT_1D_NOBITEX_MARGIN", elig_ign, 0.0016, 0.0005, 0.182),
        ("STRUCT_SHORT_1D_WALLEX_MARGIN", IGNITION_18_CRYPTO, 0.0025, 0.0009, 0.15),
        ("STRUCT_SHORT_1D_PERP_ZERO_BORROW", elig_ign, 0.0010, 0.0, 0.15),
    ):
        res, nav = simulate_structural_breakdown_short(
            {s: panel_1d_all[s] for s in syms}, syms, sigs_18,
            label=label, leg_cost=cost, borrow_per_day=brw, liq_margin_ratio=liq_mr,
        )
        short_navs[label] = nav
        short_rows.append({
            **asdict(res),
            "corr_vs_core": round(pearson_correlation(core_rets, _daily_returns_map(nav)), 4),
        })

    # Test blending 10% and 15% Nobitex structural bear short with Core (1,638d) and v2 Champion (2024-2026)
    nbx_sh = short_navs["STRUCT_SHORT_1D_NOBITEX_MARGIN"]
    overlay_rows: list[dict] = []
    for base_label, base_nav in (("CORE_1D_ACCEL20_NBX16", core_nbx_nav), ("V2_CHAMPION_60_40_NBX16", v2_nbx_nav)):
        b_rets = _daily_returns_map(base_nav)
        for sh_w in (0.0, 0.10, 0.15):
            nav = base_nav if sh_w == 0.0 else _blend_two_nav_series(base_nav, nbx_sh, 1.0 - sh_w, sh_w)
            up = paired_baseline_uplift(_daily_returns_map(nav), b_rets, simulations=499, seed=42)
            ci = up.get("ci_95") or (0.0, 0.0)
            overlay_rows.append({
                "label": f"{base_label}_PLUS_{int(sh_w * 100)}PCT_NBX_SHORT",
                "short_weight": sh_w,
                "full": _portfolio_metrics(nav),
                "stress": _portfolio_metrics({k: v for k, v in nav.items() if k >= stress_iso}),
                "vs_unhedged_bps": round(float(up.get("mean_uplift", 0.0)) * 10000.0, 2),
                "vs_unhedged_ci": [round(ci[0] * 10000.0, 2), round(ci[1] * 10000.0, 2)],
            })
    return short_rows, overlay_rows


def _run_v2_overlap_comparison(
    panel_1h: dict[str, list[BarPoint]],
    panel_13: dict[str, list[BarPoint]],
    sigs_13: dict,
    sigs_metals: dict,
    eval_dates: list[datetime],
    twin_15: dict[datetime, dict[str, float]],
    twin_20: dict[datetime, dict[str, float]],
) -> tuple[list[dict], dict[str, float], dict[str, float]]:
    """Run Unified v2 Champion shared-ledger comparison on NBX16 (1.5x vs 2.0x ignition) & WLX25."""
    union_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO + tuple(DEFENSIVE_METALS_CAPS)))
    accel_13 = compute_second_order_trend_map(sigs_13, BASE_13_SYMBOLS)
    dated_rets = build_dated_returns_index(panel_13, BASE_13_SYMBOLS)
    cov_h_by_ts: dict[datetime, tuple[tuple[str, ...], tuple[tuple[float, ...], ...]]] = {}
    for t in eval_dates[:-1]:
        active = tuple(s for s in BASE_13_SYMBOLS if s in sigs_13.get(t, {}))
        if len(active) >= 2:
            cov_h_by_ts[t] = (active, build_shrunk_horizon_cov(dated_rets, active, t))

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    v2_nbx_15 = _run_v2_joint_shared_ledger(
        panel_1h, union_syms, sigs_13, accel_13, sigs_metals, cov_h_by_ts, twin_15,
        slow_budget=0.60, ign_budget=0.40, fee_rate=Decimal("0.0016"),
    )
    v2_nbx_20 = _run_v2_joint_shared_ledger(
        panel_1h, union_syms, sigs_13, accel_13, sigs_metals, cov_h_by_ts, twin_20,
        slow_budget=0.60, ign_budget=0.40, fee_rate=Decimal("0.0016"),
    )
    v2_wlx_15 = _run_v2_joint_shared_ledger(
        panel_1h, union_syms, sigs_13, accel_13, sigs_metals, cov_h_by_ts, twin_15,
        slow_budget=0.60, ign_budget=0.40, fee_rate=Decimal("0.0025"),
    )

    ref_rets = _daily_returns_map(v2_nbx_15["nav_by_date"])
    rows = []
    for name, run in (
        ("V2_60_40_IGN1.5X_NBX16", v2_nbx_15),
        ("V2_60_40_IGN2.0X_NBX16", v2_nbx_20),
        ("V2_60_40_IGN1.5X_WLX25", v2_wlx_15),
    ):
        nav = run["nav_by_date"]
        up = paired_baseline_uplift(_daily_returns_map(nav), ref_rets, simulations=499, seed=42)
        ci = up.get("ci_95") or (0.0, 0.0)
        rows.append({
            "name": name,
            "full": _portfolio_metrics(nav),
            "stress": _portfolio_metrics({k: v for k, v in nav.items() if k >= stress_iso}),
            "fills": run["fills"],
            "fees_usdt": run["total_fees_usdt"],
            "vs_v2_nbx15_bps": round(float(up.get("mean_uplift", 0.0)) * 10000.0, 2),
            "vs_v2_nbx15_ci": [round(ci[0] * 10000.0, 2), round(ci[1] * 10000.0, 2)],
        })
    return rows, v2_nbx_15["nav_by_date"], v2_wlx_15["nav_by_date"]


def run_venue_leverage_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Execute all 4 Nobitex Margin vs. Wallex Trade-Credit studies strictly read-only."""
    union_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO + tuple(DEFENSIVE_METALS_CAPS)))
    con = open_readonly_market_db(db_path)
    try:
        panel_1d_all = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in union_syms}
        panel_1h_all = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in union_syms}
    finally:
        con.close()

    panel_13 = {s: panel_1d_all[s] for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    metal_syms = tuple(DEFENSIVE_METALS_CAPS)
    sigs_metals = compute_slow_sleeves({s: panel_1d_all[s] for s in metal_syms}, metal_syms)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_breadth = extract_daily_breadth(sigs_13)

    targets_1d = _extract_accel20_targets(panel_13, sigs_13, eval_dates)
    part_1, core_navs = _run_part1_bull_levered_core(panel_13, targets_1d, daily_breadth)
    part_2, aucs, twin_15, twin_20 = _run_part2_event_levered_ignition(panel_1h_all, daily_breadth)
    v2_rows, v2_nbx_nav, v2_wlx_nav = _run_v2_overlap_comparison(
        panel_1h_all, panel_13, sigs_13, sigs_metals, eval_dates, twin_15, twin_20,
    )
    part_3_short, part_3_overlay = _run_part3_structural_short(
        panel_1d_all, core_navs["CORE_1.0X_NBX16"], v2_nbx_nav,
    )

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    core_wlx_full = core_navs["CORE_1.0X_WLX25"]
    core_wlx_bull = {d: v for d, v in core_wlx_full.items() if "2023-10-01" <= d <= "2024-12-31"}
    core_wlx_bear = {d: v for d, v in core_wlx_full.items() if d >= stress_iso}
    v2_wlx_bear = {d: v for d, v in v2_wlx_nav.items() if d >= stress_iso}

    part_4 = [
        asdict(simulate_wallex_trade_credit_contract(core_wlx_full, label="WLX_5X_CREDIT_ON_1D_CORE_FULL_1638D")),
        asdict(simulate_wallex_trade_credit_contract(core_wlx_bull, label="WLX_5X_CREDIT_ON_1D_CORE_BULL_2023_2024")),
        asdict(simulate_wallex_trade_credit_contract(core_wlx_bear, label="WLX_5X_CREDIT_ON_1D_CORE_BEAR_2025_2026")),
        asdict(simulate_wallex_trade_credit_contract(v2_wlx_nav, label="WLX_5X_CREDIT_ON_V2_CHAMPION_2024_2026")),
        asdict(simulate_wallex_trade_credit_contract(v2_wlx_bear, label="WLX_5X_CREDIT_ON_V2_CHAMPION_BEAR_YEAR")),
    ]

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "authority": "PAPER_ONLY / TradingGYMExecutor DISARMED ($0 funded budget)",
        "nobitex_live_eligibility": {
            "base_13_eligible": sum(1 for s in BASE_13_SYMBOLS if s in NOBITEX_MARGIN_ELIGIBLE_USDT),
            "base_13_total": len(BASE_13_SYMBOLS),
            "ign_18_eligible": sum(1 for s in IGNITION_18_CRYPTO if s in NOBITEX_MARGIN_ELIGIBLE_USDT),
            "ign_18_total": len(IGNITION_18_CRYPTO),
            "spot_only_exceptions": [s for s in IGNITION_18_CRYPTO if s not in NOBITEX_MARGIN_ELIGIBLE_USDT],
            "daily_borrow_rate": 0.0005,
            "idle_usdt_pool_apr": NOBITEX_IDLE_USDT_APR,
        },
        "part_1_bull_levered_1d_core": part_1,
        "part_2_event_levered_2h_ignition": part_2,
        "part_2_gru_aucs": aucs,
        "part_2b_v2_shared_ledger": v2_rows,
        "part_3_structural_bear_short": part_3_short,
        "part_3b_short_portfolio_overlays": part_3_overlay,
        "part_4_wallex_5x_trade_credit_stress": part_4,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(payload, report_path)
    return payload


def _write_markdown(p: dict, report_path: Path) -> None:
    el = p["nobitex_live_eligibility"]
    lines = [
        "# Nobitex Pay-As-You-Go Margin vs. Wallex Margin & Fixed Trade-Credit Study",
        "",
        f"- **Generated:** `{p['generated_at']}`",
        f"- **Authority:** `{p['authority']}`",
        f"- **Live Nobitex Margin Eligibility (`GET /margin/markets/list`):** `BASE_13 = {el['base_13_eligible']}/{el['base_13_total']}` (incl. `XAUTUSDT`), `IGN18 = {el['ign_18_eligible']}/{el['ign_18_total']}` (spot-only: `{', '.join(el['spot_only_exceptions'])}`), rate `0.05%/day` (`18.25%/yr`), idle USDT pool `{el['idle_usdt_pool_apr']*100:.2f}% APR`.",
        "",
        "## 1. Bull-Regime Leverage (`breadth >= 0.55`) on `1d BASE_13 + ACCEL_BLEND_20` (1,638 Days)",
        "",
        "| Arm | Bull Lev | Cost | Borrow APR | Pool APR | Ending NAV | Return | CAGR | Bear Stress | Sharpe | MaxDD | Liqs | Borrow ($) | Pool ($) | vs NBX 1x (bps/d, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in p["part_1_bull_levered_1d_core"]:
        ci = r["vs_nbx_1x_ci"]
        lines.append(
            f"| `{r['label']}` | `{r['bull_leverage']:.2f}x` | `{r['leg_cost_bps']:.0f}bp` | `{r['borrow_apr_pct']:.1f}%` | `{r['idle_pool_apr_pct']:.2f}%` | "
            f"`${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['cagr_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | "
            f"`{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['liquidations']}` | `${r['total_borrow_usdt']:.2f}` | `${r['total_pool_yield_usdt']:.2f}` | "
            f"`{r['vs_nbx_1x_bps']:+.2f} [{ci[0]:+.2f}, {ci[1]:+.2f}]` |"
        )

    lines += [
        "",
        "## 2. Event-Scoped Top-Tercile Leverage (`1.0x / 1.5x / 2.0x`) on Twin-Phase `2h` GRU-Ignition (Conformal + 5% DD)",
        "",
        f"- **Walk-Forward OOS AUCs:** `GRU8 (0h/1h) = {p['part_2_gru_aucs']['gru8_0h']} / {p['part_2_gru_aucs']['gru8_1h']}` · `GRU11 Path-PnL (0h/1h) = {p['part_2_gru_aucs']['gru11_path_0h']} / {p['part_2_gru_aucs']['gru11_path_1h']}`",
        "",
        "| Arm | Top Lev | Borrow Model | Ending NAV | Return | Bear Stress | Sharpe | MaxDD | Avg Entries | Liqs | Avg Borrow ($) | Avg Fees ($) |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in p["part_2_event_levered_2h_ignition"]:
        lines.append(
            f"| `{r['label']}` | `{r['top_leverage']:.1f}x` | `{r['borrow_mode']}` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | "
            f"`{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['entries_avg']:.1f}` | "
            f"`{r['liquidations_sum']}` | `${r['borrow_usdt_avg']:.2f}` | `${r['fees_usdt_avg']:.2f}` |"
        )

    lines += [
        "",
        "### 2B. Unified v2 Champion (`60/40` Single Shared Ledger, `2024–2026` Overlap)",
        "",
        "| Arm | Ending NAV | Return | Bear Stress | Sharpe | MaxDD | Fills | Fees ($) | vs NBX 1.5x (bps/d, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in p["part_2b_v2_shared_ledger"]:
        f_, s_, ci = r["full"], r["stress"], r["vs_v2_nbx15_ci"]
        lines.append(
            f"| `{r['name']}` | `${f_['ending_nav']:.2f}` | `{f_['ret_pct']:+.2f}%` | `{s_['ret_pct']:+.2f}%` | "
            f"`{f_['ann_sharpe']:.3f}` | `{f_['max_dd_pct']:.2f}%` | `{r['fills']}` | `${r['fees_usdt']:.2f}` | "
            f"`{r['vs_v2_nbx15_bps']:+.2f} [{ci[0]:+.2f}, {ci[1]:+.2f}]` |"
        )

    lines += [
        "",
        "## 3. `1d` Structural Bear-Laggard Short (Nobitex Margin vs. Wallex Margin vs. Zero-Borrow)",
        "",
        "| Arm | Cost | Ending NAV | Full Return | Bear Year | Sharpe | MaxDD | Entries | Win% | Liqs | Borrow ($) | Corr vs Core |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in p["part_3_structural_bear_short"]:
        lines.append(
            f"| `{r['label']}` | `{r['cost_bps']:.0f}bp` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | "
            f"`{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['entries']}` | `{r['win_rate_pct']:.1f}%` | "
            f"`{r['liquidations']}` | `${r['total_borrow_usdt']:.2f}` | `{r['corr_vs_core']:+.4f}` |"
        )

    lines += [
        "",
        "### 3B. Bear-Short Portfolio Overlay Check (`0% / 10% / 15%` Nobitex Bear Short)",
        "",
        "| Portfolio | Short Wt | Ending NAV | Return | Bear Stress | Sharpe | MaxDD | vs Unhedged (bps/d, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in p["part_3b_short_portfolio_overlays"]:
        f_, s_, ci = r["full"], r["stress"], r["vs_unhedged_ci"]
        lines.append(
            f"| `{r['label']}` | `{r['short_weight']*100:.0f}%` | `${f_['ending_nav']:.2f}` | `{f_['ret_pct']:+.2f}%` | "
            f"`{s_['ret_pct']:+.2f}%` | `{f_['ann_sharpe']:.3f}` | `{f_['max_dd_pct']:.2f}%` | "
            f"`{r['vs_unhedged_bps']:+.2f} [{ci[0]:+.2f}, {ci[1]:+.2f}]` |"
        )

    lines += [
        "",
        "## 4. Wallex Fixed Trade-Credit (`5x`: `$200` Equity + `$1,000` Credit, `$15/30d`, `13%` Stop-Out) Stress Test",
        "",
        "| Window / Strategy | 30d Cycles | Profitable | Cash-Bleed | Stop-Outs | Single-Life Survived? | First Blow-Up | 5x Ending ($200 start) | 1x Unlev ($200 start) | Fixed Interest ($) | Median / Mean 30d ROI |",
        "| --- | ---: | ---: | ---: | ---: | :---: | --- | ---: | ---: | ---: | --- |",
    ]
    for r in p["part_4_wallex_5x_trade_credit_stress"]:
        lines.append(
            f"| `{r['label']}` | `{r['total_30d_cycles']}` | `{r['profitable_cycles']}` | `{r['cash_bleed_cycles']}` | `{r['stop_out_cycles']}` | "
            f"`{'YES' if r['single_life_survived'] else 'NO'}` | `{r['first_stop_out_date'] or 'None'}` | "
            f"`${r['single_life_ending_equity_usdt']:.2f} ({r['single_life_return_pct']:+.1f}%)` | "
            f"`${r['unlevered_ending_equity_usdt']:.2f} ({r['unlevered_return_pct']:+.1f}%)` | "
            f"`${r['total_fixed_interest_paid_usdt']:.2f}` | `{r['median_cycle_equity_roi_pct']:+.1f}% / {r['mean_cycle_equity_roi_pct']:+.1f}%` |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
