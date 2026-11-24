"""Orthogonal alpha study: (3A) 2h capitulation-flush rebound & bear dead-cat short,
(3B) GRU-Vol wired strictly into covariance/vol-target without shrinking mu_h,
(3C) PAXG vs XAUT gold upgrade & standalone non-crypto macro commodity sleeve.
"""
from __future__ import annotations

import json
import math
from bisect import bisect_right
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.async_covariance import coarse_bar_shrunk_covariance_aligned
from ...domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    solve_convex_portfolio,
)
from ...domain.ignition_and_intraday_exit import (
    pearson_correlation,
    run_shared_ledger_1h_blend,
)
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.orthogonal_sleeves import (
    MACRO_COMMODITY_SYMBOLS,
    simulate_capitulation_flush_rebound,
    simulate_dead_cat_exhaustion_short,
    simulate_macro_risk_parity_sleeve,
)
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .ensemble_study import (
    STRESS_REPLAY_START,
    _daily_returns_map,
    _portfolio_metrics,
    _run_self_financing_arm,
)
from .gru_engine import EnsembleGRU
from .gru_prototypes_study import _build_daily_vol_dataset
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .ignition_validation_study import _extract_daily_s1_s5_targets

BASE_13_PAXG_SYMBOLS = tuple("PAXGUSDT" if s == "XAUTUSDT" else s for s in BASE_13_SYMBOLS)


def _run_gru_vol_cov_only(
    panel_13: dict[str, list[BarPoint]],
    sigs_13: dict,
    eval_dates: list[datetime],
    base_13: dict,
) -> dict:
    """Study 3B: Feed purged walk-forward GRU-Vol ONLY into covariance & portfolio vol-target (mu_h untouched)."""
    dts, syms, x_all, y_all, _ = _build_daily_vol_dataset(panel_13, BASE_13_SYMBOLS)
    fold_bounds = [
        (datetime(2022, 6, 1, tzinfo=UTC), datetime(2023, 6, 1, tzinfo=UTC)),
        (datetime(2023, 6, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC)),
        (datetime(2024, 6, 1, tzinfo=UTC), datetime(2025, 11, 24, tzinfo=UTC)),
        (datetime(2025, 11, 24, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    ]
    pred_vol_map: dict[tuple[datetime, str], float] = {}
    purge = timedelta(days=21)
    for test_start, test_end in fold_bounds:
        tr_idx = [k for k, dt in enumerate(dts) if dt < test_start - purge]
        te_idx = [k for k, dt in enumerate(dts) if test_start <= dt < test_end]
        if len(tr_idx) < 200 or not te_idx:
            continue
        model = EnsembleGRU(input_dim=6, hidden_dim=12, task="regression", seeds=(42, 101, 202))
        model.fit(x_all[tr_idx], y_all[tr_idx], epochs=22, batch_size=128, lr=5e-3, l2_reg=3e-3)
        preds = model.predict(x_all[te_idx])
        for kp, rk in enumerate(te_idx):
            pred_vol_map[(dts[rk], syms[rk])] = float(np.clip(np.exp(preds[kp]), 0.005, 0.25))

    by_start = {s: {b.ts_start: b for b in panel_13.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_13.get(s, [])} for s in BASE_13_SYMBOLS}
    dated_rets = {
        s: (
            [panel_13[s][i].ts_avail for i in range(1, len(panel_13[s])) if panel_13[s][i - 1].close > 0],
            [(panel_13[s][i].close - panel_13[s][i - 1].close) / panel_13[s][i - 1].close
             for i in range(1, len(panel_13[s])) if panel_13[s][i - 1].close > 0],
        )
        for s in BASE_13_SYMBOLS
    }

    def _sim(vol_target_ann: float | None) -> dict:
        ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=Decimal("0.0013"), fee_in_received_asset=True)
        nav_by_date: dict[str, float] = {}
        sqrt_h = math.sqrt(20.0)
        for t_avail in eval_dates[:-1]:
            day_sigs = sigs_13.get(t_avail, {})
            exec_prices: dict[str, Decimal] = {}
            tradable: set[str] = set()
            for sym in BASE_13_SYMBOLS:
                nxt, cur = by_start[sym].get(t_avail), by_avail[sym].get(t_avail)
                if nxt and nxt.open > 0:
                    exec_prices[sym] = Decimal(str(nxt.open))
                    if nxt.entry_eligible and cur and cur.entry_eligible:
                        tradable.add(sym)
                elif cur and cur.close > 0:
                    exec_prices[sym] = Decimal(str(cur.close))
            active = tuple(s for s in BASE_13_SYMBOLS if s in day_sigs and s in exec_prices)
            if len(active) < 2:
                targets = {s: 0.0 for s in BASE_13_SYMBOLS}
            else:
                cur_w = ledger.current_weights(active, exec_prices)
                win = {}
                for s in active:
                    dt_l, rt_l = dated_rets[s]
                    hi = bisect_right(dt_l, t_avail)
                    win[s] = dict(zip(dt_l[max(0, hi - 60) : hi], rt_l[max(0, hi - 60) : hi], strict=True))
                cov_d = [list(row) for row in coarse_bar_shrunk_covariance_aligned(win, active, shrinkage=0.25)]
                for i, sym in enumerate(active):
                    gv = pred_vol_map.get((t_avail, sym), day_sigs[sym].yang_zhang_vol)
                    old_v = math.sqrt(max(cov_d[i][i], 1e-8))
                    scale = max(0.5, min(2.0, gv / old_v))
                    for j in range(len(active)):
                        cov_d[i][j] *= scale
                        cov_d[j][i] *= scale
                cov_h = tuple(tuple(v * 20.0 for v in row) for row in cov_d)
                # Keep expected return mu_h 100% UNTOUCHED (original Yang-Zhang vol scaling)
                mu_gross = []
                for sym in active:
                    sig = day_sigs[sym]
                    parts = [v for v in (sig.s1_trend, sig.s5_defensive_gold) if v is not None]
                    raw = sum(parts) / len(parts) if parts else 0.0
                    mu_gross.append(
                        forecast_to_expected_return_bps(raw * 20.0, ic_prior=0.08, horizon_vol_bps=sig.yang_zhang_vol * sqrt_h * 10000.0) / 10000.0
                    )
                prob = OptimizationProblem(
                    symbols=active,
                    expected_returns=tuple(mu_gross),
                    current_weights=cur_w,
                    covariance=cov_h,
                    l1_fee_costs=(0.0013,) * len(active),
                    l2_impact_costs=(0.0020,) * len(active),
                    risk_aversion=2.0,
                    max_weight=0.30,
                    cash_buffer=0.05,
                )
                solved = list(solve_convex_portfolio(prob).weights)
                if vol_target_ann is not None:
                    port_var_d = sum(
                        solved[i] * solved[j] * cov_d[i][j]
                        for i in range(len(active)) for j in range(len(active))
                    )
                    port_vol_ann = math.sqrt(max(port_var_d, 1e-10) * 365.0)
                    if port_vol_ann > vol_target_ann:
                        cap_scale = vol_target_ann / port_vol_ann
                        solved = [w * cap_scale for w in solved]
                targets = {s: w for s, w in zip(active, solved, strict=True)}
            ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
            nav_by_date[t_avail.date().isoformat()] = float(ledger.mark_nav(exec_prices))
        stress_iso = STRESS_REPLAY_START.date().isoformat()
        return {
            "nav_by_date": nav_by_date,
            "full": _portfolio_metrics(nav_by_date),
            "stress": _portfolio_metrics({k: v for k, v in nav_by_date.items() if k >= stress_iso}),
            "fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        }

    arm_cov = _sim(vol_target_ann=None)
    arm_vt = _sim(vol_target_ann=0.22)
    base_rets = _daily_returns_map(base_13["nav_by_date"])
    return {
        "baseline_13": {"full": base_13["metrics_full"], "stress": base_13["metrics_stress"], "fees_usdt": base_13["total_fees_usdt"]},
        "gru_vol_cov_only": {
            "full": arm_cov["full"],
            "stress": arm_cov["stress"],
            "fees_usdt": arm_cov["fees_usdt"],
            "uplift_vs_base": paired_baseline_uplift(_daily_returns_map(arm_cov["nav_by_date"]), base_rets, simulations=499, seed=42),
        },
        "gru_vol_cov_plus_vt22": {
            "full": arm_vt["full"],
            "stress": arm_vt["stress"],
            "fees_usdt": arm_vt["fees_usdt"],
            "uplift_vs_base": paired_baseline_uplift(_daily_returns_map(arm_vt["nav_by_date"]), base_rets, simulations=499, seed=42),
        },
    }


def _run_custom_s1_s5_arm(
    panel: dict[str, list[BarPoint]],
    sigs: dict,
    eval_dates: list[datetime],
    symbols: tuple[str, ...],
    *,
    fee_rate: Decimal = Decimal("0.0013"),
) -> dict:
    """Run canonical S1+S5 (DROP_S2) + ADMM on an arbitrary symbol tuple (e.g., PAXG instead of XAUT)."""
    by_start = {s: {b.ts_start: b for b in panel.get(s, [])} for s in symbols}
    by_avail = {s: {b.ts_avail: b for b in panel.get(s, [])} for s in symbols}
    dated_rets = {
        s: (
            [panel[s][i].ts_avail for i in range(1, len(panel[s])) if panel[s][i - 1].close > 0],
            [(panel[s][i].close - panel[s][i - 1].close) / panel[s][i - 1].close
             for i in range(1, len(panel[s])) if panel[s][i - 1].close > 0],
        )
        for s in symbols
    }
    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    nav_by_date: dict[str, float] = {}
    sqrt_h = math.sqrt(20.0)
    for t_avail in eval_dates[:-1]:
        day_sigs = sigs.get(t_avail, {})
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        for sym in symbols:
            nxt, cur = by_start[sym].get(t_avail), by_avail[sym].get(t_avail)
            if nxt and nxt.open > 0:
                exec_prices[sym] = Decimal(str(nxt.open))
                if nxt.entry_eligible and cur and cur.entry_eligible:
                    tradable.add(sym)
            elif cur and cur.close > 0:
                exec_prices[sym] = Decimal(str(cur.close))
        active = tuple(s for s in symbols if s in day_sigs and s in exec_prices)
        if len(active) < 2:
            targets = {s: 0.0 for s in symbols}
        else:
            cur_w = ledger.current_weights(active, exec_prices)
            win = {}
            for s in active:
                dt_l, rt_l = dated_rets[s]
                hi = bisect_right(dt_l, t_avail)
                win[s] = dict(zip(dt_l[max(0, hi - 60) : hi], rt_l[max(0, hi - 60) : hi], strict=True))
            cov_d = coarse_bar_shrunk_covariance_aligned(win, active, shrinkage=0.25)
            cov_h = tuple(tuple(v * 20.0 for v in row) for row in cov_d)
            mu_gross = []
            for sym in active:
                sig = day_sigs[sym]
                parts = [v for v in (sig.s1_trend, sig.s5_defensive_gold) if v is not None]
                raw = sum(parts) / len(parts) if parts else 0.0
                mu_gross.append(
                    forecast_to_expected_return_bps(raw * 20.0, ic_prior=0.08, horizon_vol_bps=sig.yang_zhang_vol * sqrt_h * 10000.0) / 10000.0
                )
            prob = OptimizationProblem(
                symbols=active,
                expected_returns=tuple(mu_gross),
                current_weights=cur_w,
                covariance=cov_h,
                l1_fee_costs=(float(fee_rate),) * len(active),
                l2_impact_costs=(0.0020,) * len(active),
                risk_aversion=2.0,
                max_weight=0.30,
                cash_buffer=0.05,
            )
            solved = solve_convex_portfolio(prob).weights
            targets = {s: w for s, w in zip(active, solved, strict=True)}
        ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
        nav_by_date[t_avail.date().isoformat()] = float(ledger.mark_nav(exec_prices))
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    return {
        "nav_by_date": nav_by_date,
        "metrics_full": _portfolio_metrics(nav_by_date),
        "metrics_stress": _portfolio_metrics({k: v for k, v in nav_by_date.items() if k >= stress_iso}),
        "total_fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
    }


def _run_gold_and_macro_study(
    panel_all: dict[str, list[BarPoint]],
    base_13: dict,
    base_sigs: dict,
    eval_dates: list[datetime],
) -> dict:
    """Study 3C: PAXG vs XAUT gold upgrade + standalone non-crypto macro commodity sleeve."""
    panel_paxg = {s: panel_all[s] for s in BASE_13_PAXG_SYMBOLS}
    sigs_paxg = compute_slow_sleeves(panel_paxg, BASE_13_PAXG_SYMBOLS, gold_symbol="PAXGUSDT")
    eval_paxg = [d for d in sorted(sigs_paxg) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    arm_paxg = _run_custom_s1_s5_arm(panel_paxg, sigs_paxg, eval_paxg, BASE_13_PAXG_SYMBOLS, fee_rate=Decimal("0.0013"))
    base_rets = _daily_returns_map(base_13["nav_by_date"])
    paxg_uplift = paired_baseline_uplift(_daily_returns_map(arm_paxg["nav_by_date"]), base_rets, simulations=499, seed=42)

    panel_macro = {s: panel_all[s] for s in MACRO_COMMODITY_SYMBOLS}
    macro_res, macro_nav, macro_targets = simulate_macro_risk_parity_sleeve(panel_macro, MACRO_COMMODITY_SYMBOLS)
    macro_rets = _daily_returns_map(macro_nav)
    macro_corr = pearson_correlation(base_rets, macro_rets)

    # Blend 80% BASE_13_PAXG + 20% MACRO_COMMODITIES on single daily shared ledger
    all_blend_syms = tuple(dict.fromkeys(BASE_13_PAXG_SYMBOLS + MACRO_COMMODITY_SYMBOLS))
    daily_base_targets = _extract_daily_s1_s5_targets(panel_paxg, sigs_paxg, eval_paxg, BASE_13_PAXG_SYMBOLS, fee_rate=Decimal("0.0013"))
    blend_panel = {s: panel_all[s] for s in all_blend_syms}
    blend_run = run_shared_ledger_1h_blend(
        blend_panel, all_blend_syms, daily_base_targets, macro_targets,
        slow_weight=0.80, ignition_weight=0.20, fee_rate=Decimal("0.0013"),
        max_asset_weight=0.35, max_gross_weight=0.95,
    )
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    b_nav = blend_run["nav_by_date"]
    blend_pack = {
        "name": "BLEND_80_PAXG13_20_MACRO",
        "full": _portfolio_metrics(b_nav),
        "stress": _portfolio_metrics({k: v for k, v in b_nav.items() if k >= stress_iso}),
        "fills": blend_run.get("fills", 0),
        "fees_usdt": blend_run.get("total_fees_usdt", 0.0),
        "turnover": blend_run.get("turnover_multiple", 0.0),
    }
    blend_vs_paxg = paired_baseline_uplift(
        _daily_returns_map(blend_run["nav_by_date"]),
        _daily_returns_map(arm_paxg["nav_by_date"]),
        simulations=499,
        seed=42,
    )

    return {
        "xaut_base_13": {"full": base_13["metrics_full"], "stress": base_13["metrics_stress"], "fees_usdt": base_13["total_fees_usdt"]},
        "paxg_base_13": {
            "full": arm_paxg["metrics_full"],
            "stress": arm_paxg["metrics_stress"],
            "fees_usdt": arm_paxg["total_fees_usdt"],
            "uplift_vs_xaut_base": paxg_uplift,
        },
        "macro_standalone": {**asdict(macro_res), "corr_vs_base_13": round(macro_corr, 4)},
        "blend_80_paxg13_20_macro": {**blend_pack, "uplift_vs_paxg_base": blend_vs_paxg},
        "note_2026_active_commodities": {
            s: len(panel_all.get(s, [])) for s in MACRO_COMMODITY_SYMBOLS
        },
    }


def run_orthogonal_alpha_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Execute Studies 3A, 3B, and 3C on strictly causal archived candles."""
    con = open_readonly_market_db(db_path)
    try:
        all_1d_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + MACRO_COMMODITY_SYMBOLS))
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in all_1d_syms}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in IGNITION_18_CRYPTO}
    finally:
        con.close()

    panel_13 = {s: panel_1d[s] for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    base_13 = _run_self_financing_arm("DROP_S2", panel_13, sigs_13, eval_dates)
    base_rets = _daily_returns_map(base_13["nav_by_date"])

    daily_breadth: dict[str, float] = {}
    for ts, d in sigs_13.items():
        br = next((s.crypto_breadth for s in d.values() if s.crypto_breadth is not None), None)
        if br is not None:
            daily_breadth[ts.date().isoformat()] = br

    panel_2h_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    panel_2h_1 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=1) for s in IGNITION_18_CRYPTO}

    # Study 3A: Flush Rebound (Long) + Bear Dead-Cat Exhaustion (Short)
    flush_arms: list[dict] = []
    flush_nav_0_nbx: dict[str, float] = {}
    for off, p2h in ((0, panel_2h_0), (1, panel_2h_1)):
        for tag, cost in (("NBX16", 0.0016), ("WLX25", 0.0025)):
            r_all, nav_all, _ = simulate_capitulation_flush_rebound(
                p2h, IGNITION_18_CRYPTO, daily_breadth,
                label=f"FLUSH_REBOUND_2H_{tag}_OFF{off}H", offset_hours=off, leg_cost=cost, max_breadth_gate=1.0,
            )
            flush_arms.append({**asdict(r_all), "corr_vs_base_13": round(pearson_correlation(base_rets, _daily_returns_map(nav_all)), 4)})
            if off == 0 and tag == "NBX16":
                flush_nav_0_nbx = nav_all

    # Also test bear-gated flush rebound (breadth <= 0.45) and 48h hold on 0h/1h
    for off, p2h in ((0, panel_2h_0), (1, panel_2h_1)):
        r_bear, nav_bear, _ = simulate_capitulation_flush_rebound(
            p2h, IGNITION_18_CRYPTO, daily_breadth,
            label=f"FLUSH_REBOUND_BEAR45_NBX16_OFF{off}H", offset_hours=off, leg_cost=0.0016, max_breadth_gate=0.45, hold_hours=36,
        )
        flush_arms.append({**asdict(r_bear), "corr_vs_base_13": round(pearson_correlation(base_rets, _daily_returns_map(nav_bear)), 4)})

    deadcat_arms: list[dict] = []
    for off, p2h in ((0, panel_2h_0), (1, panel_2h_1)):
        for tag, cost in (("NBX16", 0.0016), ("WLX25", 0.0025)):
            r_dc, nav_dc = simulate_dead_cat_exhaustion_short(
                p2h, IGNITION_18_CRYPTO, daily_breadth,
                label=f"DEADCAT_SHORT_2H_{tag}_OFF{off}H", offset_hours=off, leg_cost=cost,
            )
            deadcat_arms.append({**asdict(r_dc), "corr_vs_base_13": round(pearson_correlation(base_rets, _daily_returns_map(nav_dc)), 4)})

    study_3b = _run_gru_vol_cov_only(panel_13, sigs_13, eval_dates, base_13)
    study_3c = _run_gold_and_macro_study(panel_1d, base_13, sigs_13, eval_dates)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "study_3a_flush_rebound": flush_arms,
        "study_3a_deadcat_short": deadcat_arms,
        "study_3a_flush_days": len(flush_nav_0_nbx),
        "study_3b_gru_vol_cov_only": study_3b,
        "study_3c_gold_and_macro": study_3c,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    lines = [
        "# Orthogonal Alpha Study (3A: Flush Rebound & Dead-Cat Short, 3B: Covariance-Only GRU-Vol, 3C: PAXG & Macro Commodities)",
        "",
        f"- **Generated:** `{p['generated_at']}`",
        "- **Causality:** Strict next-bar open execution, purged yearly walk-forward for GRU-Vol, exact Wallex `0.015%/4h` borrow & bar-high liquidations on shorts.",
        "",
        "## Study 3A — 2h Spot Capitulation-Flush Rebound & Bear Dead-Cat Exhaustion Short",
        "",
        "| Arm | Offset | Cost (bps) | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Entries | Win% | Liqs | Borrow | Corr vs Base |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in p["study_3a_flush_rebound"] + p["study_3a_deadcat_short"]:
        lines.append(
            f"| `{r['label']}` | `+{r['offset_hours']}h` | `{r['cost_bps']:.1f}` | `${r['ending_nav']:.2f}` | "
            f"`{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | "
            f"`{r['entries']}` | `{r['win_rate_pct']:.1f}%` | `{r['liquidations']}` | `${r['total_borrow_usdt']:.2f}` | `{r['corr_vs_base_13']:+.3f}` |"
        )

    b3 = p["study_3b_gru_vol_cov_only"]
    lines.extend([
        "",
        "## Study 3B — GRU-Vol Wired Strictly Into Covariance / Vol-Target (mu_h Untouched)",
        "",
        "| Arm | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Fees | Mean Uplift (bps/d) | 95% CI (bps/d) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        f"| `BASE_13_S1_S5` | `${b3['baseline_13']['full']['ending_nav']:.2f}` | `{b3['baseline_13']['full']['ret_pct']:+.2f}%` | `{b3['baseline_13']['stress']['ret_pct']:+.2f}%` | `{b3['baseline_13']['full']['ann_sharpe']:.3f}` | `{b3['baseline_13']['full']['max_dd_pct']:.2f}%` | `${b3['baseline_13']['fees_usdt']:.2f}` | `0.00` | `baseline` |",
    ])
    for key, label in (("gru_vol_cov_only", "GRU_VOL_COV_ONLY"), ("gru_vol_cov_plus_vt22", "GRU_VOL_COV_PLUS_VT22")):
        arm = b3[key]
        up = arm["uplift_vs_base"]
        lines.append(
            f"| `{label}` | `${arm['full']['ending_nav']:.2f}` | `{arm['full']['ret_pct']:+.2f}%` | `{arm['stress']['ret_pct']:+.2f}%` | "
            f"`{arm['full']['ann_sharpe']:.3f}` | `{arm['full']['max_dd_pct']:.2f}%` | `${arm['fees_usdt']:.2f}` | "
            f"`{up['mean_uplift'] * 10000:+.2f}` | `[{up['ci_95'][0] * 10000:+.2f}, {up['ci_95'][1] * 10000:+.2f}]` |"
        )

    c3 = p["study_3c_gold_and_macro"]
    px = c3["paxg_base_13"]
    px_up = px["uplift_vs_xaut_base"]
    mc = c3["macro_standalone"]
    bl = c3["blend_80_paxg13_20_macro"]
    bl_up = bl["uplift_vs_paxg_base"]
    lines.extend([
        "",
        "## Study 3C — PAXG Gold Upgrade & Standalone Non-Crypto Macro Commodity Sleeve",
        "",
        "| Arm | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Fees | Corr / Uplift |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        f"| `BASE_13_XAUT (841d gold)` | `${c3['xaut_base_13']['full']['ending_nav']:.2f}` | `{c3['xaut_base_13']['full']['ret_pct']:+.2f}%` | `{c3['xaut_base_13']['stress']['ret_pct']:+.2f}%` | `{c3['xaut_base_13']['full']['ann_sharpe']:.3f}` | `{c3['xaut_base_13']['full']['max_dd_pct']:.2f}%` | `${c3['xaut_base_13']['fees_usdt']:.2f}` | `baseline` |",
        f"| `BASE_13_PAXG (1635d gold)` | `${px['full']['ending_nav']:.2f}` | `{px['full']['ret_pct']:+.2f}%` | `{px['stress']['ret_pct']:+.2f}%` | `{px['full']['ann_sharpe']:.3f}` | `{px['full']['max_dd_pct']:.2f}%` | `${px['fees_usdt']:.2f}` | `vs XAUT: {px_up['mean_uplift']*10000:+.2f} bps/d [{px_up['ci_95'][0]*10000:+.2f}, {px_up['ci_95'][1]*10000:+.2f}]` |",
        f"| `MACRO_COMMODITIES_RP_TREND` | `${mc['ending_nav']:.2f}` | `{mc['ret_pct']:+.2f}%` | `{mc['stress_ret_pct']:+.2f}%` | `{mc['ann_sharpe']:.3f}` | `{mc['max_dd_pct']:.2f}%` | `${mc['total_fees_usdt']:.2f}` | `corr vs Base: {mc['corr_vs_base_13']:+.3f}, avg exp {mc['avg_gross_exposure_pct']:.1f}%` |",
        f"| `BLEND_80_PAXG13_20_MACRO` | `${bl['full']['ending_nav']:.2f}` | `{bl['full']['ret_pct']:+.2f}%` | `{bl['stress']['ret_pct']:+.2f}%` | `{bl['full']['ann_sharpe']:.3f}` | `{bl['full']['max_dd_pct']:.2f}%` | `${bl['fees_usdt']:.2f}` | `vs PAXG13: {bl_up['mean_uplift']*10000:+.2f} bps/d [{bl_up['ci_95'][0]*10000:+.2f}, {bl_up['ci_95'][1]*10000:+.2f}]` |",
    ])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
