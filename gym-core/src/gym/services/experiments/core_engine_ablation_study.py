"""Track I rigorous zero-lookahead ablations for the 1d Core Engine:
- #1 Amended: Absolute-anchored Path-Efficiency IC modulation
- #7: Causal right-edge Savitzky-Golay minimum-lag velocity & curvature
- #8: HRP-anchored convex turnover-buffered allocation (13-asset core & 22-asset expanded universe)
- #11A: Multi-issuer precious-metals defensive cash reserve (XAUT <=25%, PAXG <=15%, SLVON <=10%)
"""
from __future__ import annotations

import json
import math
from bisect import bisect_right
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.async_covariance import coarse_bar_shrunk_covariance_aligned
from ...domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    solve_convex_portfolio,
)
from ...domain.core_signal_geometry import (
    DEFENSIVE_METALS_CAPS,
    compute_defensive_metals_reserve,
    compute_hrp_trend_target_weights,
    compute_path_efficiency_ic_map,
    compute_savgol_velocity_curvature,
)
from ...domain.higher_order_and_sparse import compute_second_order_trend_map
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint
from .admm_helpers import build_dated_returns_index, build_shrunk_horizon_cov
from .ensemble_study import (
    STRESS_REPLAY_START,
    _daily_returns_map,
    _portfolio_metrics,
    _run_self_financing_arm,
)

EXPANDED_22_MAJORS = BASE_13_SYMBOLS + (
    "AVAXUSDT",
    "NEARUSDT",
    "UNIUSDT",
    "ATOMUSDT",
    "DOTUSDT",
    "FILUSDT",
    "XLMUSDT",
    "ETCUSDT",
    "DASHUSDT",
)


def _exec_prices_for_day(
    symbols: tuple[str, ...],
    by_start: dict[str, dict[datetime, BarPoint]],
    by_avail: dict[str, dict[datetime, BarPoint]],
    t_avail: datetime,
    last_mark: dict[str, Decimal],
) -> tuple[dict[str, Decimal], set[str]]:
    prices: dict[str, Decimal] = {}
    tradable: set[str] = set()
    for sym in symbols:
        nxt, cur = by_start[sym].get(t_avail), by_avail[sym].get(t_avail)
        if nxt and nxt.open > 0:
            prices[sym] = Decimal(str(nxt.open))
            last_mark[sym] = prices[sym]
            if nxt.entry_eligible and cur and cur.entry_eligible:
                tradable.add(sym)
        elif cur and cur.close > 0:
            prices[sym] = Decimal(str(cur.close))
            last_mark[sym] = prices[sym]
        elif sym in last_mark:
            prices[sym] = last_mark[sym]
    return prices, tradable


def _run_1d_variant(
    panel_1d: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    sigs_1d: dict,
    eval_dates: list[datetime],
    *,
    label: str,
    ic_map: dict[datetime, dict[str, float]] | None = None,
    accel_map: dict[datetime, dict[str, float]] | None = None,
    savgol_map: dict[datetime, dict[str, tuple[float, float]]] | None = None,
    use_savgol_replace: bool = False,
    use_hrp_anchor: bool = False,
    metals_sigs: dict | None = None,
    metals_panel: dict[str, list[BarPoint]] | None = None,
    fee_rate: Decimal = Decimal("0.0013"),
) -> dict:
    """Strictly causal 1d SelfFinancingLedger replay supporting clean single-factor and combo ablations."""
    all_syms = tuple(dict.fromkeys(symbols + (tuple(DEFENSIVE_METALS_CAPS) if metals_panel else ())))
    src_panel = {s: (panel_1d[s] if s in panel_1d else metals_panel[s]) for s in all_syms if (s in panel_1d or (metals_panel and s in metals_panel))}
    by_start = {s: {b.ts_start: b for b in src_panel.get(s, [])} for s in all_syms}
    by_avail = {s: {b.ts_avail: b for b in src_panel.get(s, [])} for s in all_syms}
    dated_rets = build_dated_returns_index(panel_1d, symbols)

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    nav_by_date: dict[str, float] = {}
    sqrt_h = math.sqrt(20.0)
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    exposures: list[float] = []

    for t_avail in eval_dates[:-1]:
        day_sigs = sigs_1d.get(t_avail, {})
        exec_prices, tradable = _exec_prices_for_day(all_syms, by_start, by_avail, t_avail, last_mark)
        active = tuple(s for s in symbols if s in day_sigs and s in exec_prices)
        if len(active) < 2:
            targets = {s: 0.0 for s in all_syms}
        else:
            cur_w = ledger.current_weights(active, exec_prices)
            s1_ovr: dict[str, float | None] = {}
            for sym in active:
                s1_v = day_sigs[sym].s1_trend
                if savgol_map is not None and sym in savgol_map.get(t_avail, {}):
                    vel, curv = savgol_map[t_avail][sym]
                    if use_savgol_replace:
                        s1_v = max(-1.0, min(1.0, 0.80 * vel + 0.20 * curv))
                    elif s1_v is not None:
                        s1_v = max(-1.0, min(1.0, 0.80 * s1_v + 0.20 * curv))
                elif accel_map is not None and s1_v is not None:
                    acc = accel_map.get(t_avail, {}).get(sym, 0.0)
                    s1_v = max(-1.0, min(1.0, 0.80 * s1_v + 0.20 * acc))
                s1_ovr[sym] = s1_v

            if use_hrp_anchor:
                win = {}
                for s in active:
                    dts, rts = dated_rets[s]
                    hi = bisect_right(dts, t_avail)
                    win[s] = dict(zip(dts[max(0, hi - 60) : hi], rts[max(0, hi - 60) : hi], strict=True))
                cov_d = coarse_bar_shrunk_covariance_aligned(win, active, shrinkage=0.25)
                hrp_t = compute_hrp_trend_target_weights(active, day_sigs, cov_d, s1_override=s1_ovr)
                # Apply ADMM L1 turnover deadzone: only move if weight delta > 2.5%
                targets = {s: 0.0 for s in all_syms}
                for sym, cw in zip(active, cur_w, strict=True):
                    tw = hrp_t[sym]
                    targets[sym] = tw if abs(tw - cw) >= 0.025 else cw
            else:
                cov_h = build_shrunk_horizon_cov(dated_rets, active, t_avail)
                mu_gross = []
                for sym in active:
                    sig = day_sigs[sym]
                    ic_val = ic_map.get(t_avail, {}).get(sym, 0.08) if ic_map is not None else 0.08
                    parts = [v for v in (s1_ovr[sym], sig.s5_defensive_gold) if v is not None]
                    raw = sum(parts) / len(parts) if parts else 0.0
                    mu_gross.append(
                        forecast_to_expected_return_bps(raw * 20.0, ic_prior=ic_val, horizon_vol_bps=sig.yang_zhang_vol * sqrt_h * 10000.0) / 10000.0
                    )
                prob = OptimizationProblem(
                    symbols=active, expected_returns=tuple(mu_gross), current_weights=cur_w,
                    covariance=cov_h, l1_fee_costs=(float(fee_rate),) * len(active),
                    l2_impact_costs=(0.0020,) * len(active), risk_aversion=2.0,
                    max_weight=0.30, cash_buffer=0.05,
                )
                solved = solve_convex_portfolio(prob).weights
                targets = {s: 0.0 for s in all_syms}
                for s, w in zip(active, solved, strict=True):
                    targets[s] = w

            # Optional Idea #11A: Multi-issuer precious-metals defensive reserve using idle cash
            if metals_sigs is not None:
                day_br = next((s.crypto_breadth for s in day_sigs.values() if s.crypto_breadth is not None), None)
                res_w = compute_defensive_metals_reserve(metals_sigs.get(t_avail, {}), day_br)
                free_cash = max(0.0, 0.95 - sum(targets.values()))
                for m_sym, mw in res_w.items():
                    if m_sym in exec_prices and mw > 0:
                        add_w = max(0.0, mw - targets.get(m_sym, 0.0))
                        take = min(add_w, free_cash)
                        targets[m_sym] = targets.get(m_sym, 0.0) + take
                        free_cash -= take

        ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
        exposures.append(sum(targets.values()))
        nav_by_date[t_avail.date().isoformat()] = float(ledger.mark_nav(exec_prices))

    return {
        "label": label,
        "nav_by_date": nav_by_date,
        "full": _portfolio_metrics(nav_by_date),
        "stress": _portfolio_metrics({k: v for k, v in nav_by_date.items() if k >= stress_iso}),
        "fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "turnover": round(float(ledger.cumulative_turnover_quote / ledger.starting_cash), 2),
        "avg_exposure_pct": round(sum(exposures) / max(1, len(exposures)) * 100.0, 1),
    }


def run_core_engine_ablation_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Execute Track I ablations (#1 Amended, #7, #8, #11A) cleanly against BASE_13_S1_S5 and ACCEL_BLEND_20."""
    all_load = tuple(dict.fromkeys(EXPANDED_22_MAJORS + tuple(DEFENSIVE_METALS_CAPS)))
    con = open_readonly_market_db(db_path)
    try:
        panel_all = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in all_load}
    finally:
        con.close()

    panel_13 = {s: panel_all[s] for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    base_13 = _run_self_financing_arm("DROP_S2", panel_13, sigs_13, eval_dates)
    base_rets = _daily_returns_map(base_13["nav_by_date"])

    ic_13 = compute_path_efficiency_ic_map(panel_13, BASE_13_SYMBOLS)
    accel_13 = compute_second_order_trend_map(sigs_13, BASE_13_SYMBOLS)
    savgol_13 = compute_savgol_velocity_curvature(panel_13, BASE_13_SYMBOLS)

    panel_metals = {s: panel_all[s] for s in DEFENSIVE_METALS_CAPS}
    sigs_metals = compute_slow_sleeves(panel_metals, tuple(DEFENSIVE_METALS_CAPS), min_active_crypto=1, warmup_bars=64)

    panel_22 = {s: panel_all[s] for s in EXPANDED_22_MAJORS}
    sigs_22 = compute_slow_sleeves(panel_22, EXPANDED_22_MAJORS)
    eval_22 = [d for d in sorted(sigs_22) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    accel_22 = compute_second_order_trend_map(sigs_22, EXPANDED_22_MAJORS)

    arms = [
        _run_1d_variant(panel_13, BASE_13_SYMBOLS, sigs_13, eval_dates, label="BENCH_ACCEL_BLEND_20", accel_map=accel_13),
        _run_1d_variant(panel_13, BASE_13_SYMBOLS, sigs_13, eval_dates, label="IDEA_1_PATH_EFF_IC", ic_map=ic_13),
        _run_1d_variant(panel_13, BASE_13_SYMBOLS, sigs_13, eval_dates, label="IDEA_7A_S1_PLUS_SAVGOL_CURV", savgol_map=savgol_13, use_savgol_replace=False),
        _run_1d_variant(panel_13, BASE_13_SYMBOLS, sigs_13, eval_dates, label="IDEA_7B_FULL_SAVGOL_VEL_CURV", savgol_map=savgol_13, use_savgol_replace=True),
        _run_1d_variant(panel_13, BASE_13_SYMBOLS, sigs_13, eval_dates, label="IDEA_8A_HRP_ANCHOR_13", use_hrp_anchor=True),
        _run_1d_variant(panel_22, EXPANDED_22_MAJORS, sigs_22, eval_22, label="IDEA_8B_ADMM_FLAT_22", use_hrp_anchor=False),
        _run_1d_variant(panel_22, EXPANDED_22_MAJORS, sigs_22, eval_22, label="IDEA_8C_HRP_ANCHOR_22", use_hrp_anchor=True),
        _run_1d_variant(panel_22, EXPANDED_22_MAJORS, sigs_22, eval_22, label="IDEA_8D_HRP_22_PLUS_ACCEL", accel_map=accel_22, use_hrp_anchor=True),
        _run_1d_variant(panel_13, BASE_13_SYMBOLS, sigs_13, eval_dates, label="IDEA_11A_METALS_RESERVE", metals_sigs=sigs_metals, metals_panel=panel_metals),
        _run_1d_variant(panel_13, BASE_13_SYMBOLS, sigs_13, eval_dates, label="COMBO_1_7A_11A", ic_map=ic_13, savgol_map=savgol_13, metals_sigs=sigs_metals, metals_panel=panel_metals),
        _run_1d_variant(panel_13, BASE_13_SYMBOLS, sigs_13, eval_dates, label="COMBO_ACCEL_1_11A", ic_map=ic_13, accel_map=accel_13, metals_sigs=sigs_metals, metals_panel=panel_metals),
    ]

    rows_out: list[dict] = [{
        "label": "BASE_13_S1_S5_BENCHMARK",
        "full": base_13["metrics_full"],
        "stress": base_13["metrics_stress"],
        "fees_usdt": base_13["total_fees_usdt"],
        "turnover": base_13["turnover_multiple"],
        "avg_exposure_pct": 0.0,
        "uplift_vs_base_bps": 0.0,
        "ci_vs_base_bps": [0.0, 0.0],
    }]
    for a in arms:
        up = paired_baseline_uplift(_daily_returns_map(a["nav_by_date"]), base_rets, simulations=499, seed=42)
        ci = up.get("ci_95") or (0.0, 0.0)
        rows_out.append({
            "label": a["label"],
            "full": a["full"],
            "stress": a["stress"],
            "fees_usdt": a["fees_usdt"],
            "turnover": a["turnover"],
            "avg_exposure_pct": a["avg_exposure_pct"],
            "uplift_vs_base_bps": round(float(up.get("mean_uplift", 0.0)) * 10000.0, 2),
            "ci_vs_base_bps": [round(ci[0] * 10000.0, 2), round(ci[1] * 10000.0, 2)],
        })

    payload = {"generated_at": datetime.now(UTC).isoformat(), "arms": rows_out}
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    lines = [
        "# Track I Ablations — 1d Core Signal Geometry, HRP Anchoring & Multi-Issuer Defensive Metals",
        "",
        f"- **Generated:** `{p['generated_at']}`",
        "- **Causality:** Strict next-bar open `SelfFinancingLedger` (`13 bps` fee, `1,638` days `2022–2026`, zero fitted ML parameters).",
        "",
        "| Arm | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Fees ($) | Turnover | Avg Exp% | Uplift vs Base (bps/d, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in p["arms"]:
        lines.append(
            f"| `{r['label']}` | `${r['full']['ending_nav']:.2f}` | `{r['full']['ret_pct']:+.2f}%` | `{r['stress']['ret_pct']:+.2f}%` | "
            f"`{r['full']['ann_sharpe']:.3f}` | `{r['full']['max_dd_pct']:.2f}%` | `${r['fees_usdt']:.2f}` | `{r['turnover']:.1f}x` | "
            f"`{r['avg_exposure_pct']:.1f}%` | `{r['uplift_vs_base_bps']:+.2f} [{r['ci_vs_base_bps'][0]:+.2f}, {r['ci_vs_base_bps'][1]:+.2f}]` |"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
