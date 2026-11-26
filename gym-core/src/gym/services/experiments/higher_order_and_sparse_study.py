"""Four-part quantitative study:
1. 2nd-order momentum (trend acceleration/deceleration) on 1d BASE_13_S1_S5 + as GRU-Ignition input channels.
2. Tiered sparse universe expansion (18 -> 38 liquid crypto markets behind strict sparsity hurdle + spread penalty).
3. Walk-forward risk-parity / shrunk min-var sleeve weighting across (1d Core, 2h Ignition) on single shared ledger.
4. Multi-week structural support breakdown short on bear-market relative-strength laggards (Wallex margin vs perp counterfactual).
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.higher_order_and_sparse import (
    compute_second_order_trend_map,
    compute_walkforward_sleeve_weights,
    run_dynamic_shared_ledger_blend,
    simulate_structural_breakdown_short,
    simulate_tiered_sparse_ignition,
)
from ...domain.ignition_and_intraday_exit import pearson_correlation
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    extract_daily_breadth,
    solve_s1_s5_admm_weights,
)
from .ensemble_study import (
    STRESS_REPLAY_START,
    _daily_returns_map,
    _portfolio_metrics,
    _run_self_financing_arm,
)
from .gru_engine import EnsembleGRU
from .gru_prototypes_study import (
    _extract_2h_breakout_sequences,
    _roc_auc,
    _simulate_gru_sized_ignition,
)
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .ignition_validation_study import _extract_daily_s1_s5_targets

SATELLITE_20_CRYPTO = (
    "PEPEUSDT",
    "ARBUSDT",
    "SHIBUSDT",
    "DASHUSDT",
    "FLOKIUSDT",
    "WLDUSDT",
    "CAKEUSDT",
    "NOTUSDT",
    "GALAUSDT",
    "POLUSDT",
    "FETUSDT",
    "APEUSDT",
    "CHZUSDT",
    "XLMUSDT",
    "SANDUSDT",
    "ETCUSDT",
    "SUSDT",
    "SEIUSDT",
    "BONKUSDT",
    "WIFUSDT",
)


def _run_second_order_1d_arms(
    panel_13: dict[str, list[BarPoint]],
    sigs_13: dict,
    eval_dates: list[datetime],
    base_13: dict,
) -> dict:
    """Part 1A: Evaluate 3 disciplined 2nd-order trend acceleration variants on BASE_13_S1_S5."""
    accel_map = compute_second_order_trend_map(sigs_13, BASE_13_SYMBOLS)
    by_start = {s: {b.ts_start: b for b in panel_13.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_13.get(s, [])} for s in BASE_13_SYMBOLS}
    dated_rets = build_dated_returns_index(panel_13, BASE_13_SYMBOLS)
    base_rets = _daily_returns_map(base_13["nav_by_date"])
    stress_iso = STRESS_REPLAY_START.date().isoformat()

    def _sim(mode: str) -> dict:
        ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=Decimal("0.0013"), fee_in_received_asset=True)
        nav_by_date: dict[str, float] = {}
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
                s1_ovr: dict[str, float | None] = {}
                for sym in active:
                    s1_v = day_sigs[sym].s1_trend
                    acc = day_acc.get(sym, 0.0)
                    if s1_v is not None:
                        if mode == "ACCEL_BLEND_20":
                            s1_v = max(-1.0, min(1.0, 0.80 * s1_v + 0.20 * acc))
                        elif mode == "ACCEL_DECEL_BRAKE" and s1_v > 0.50 and acc < -0.25:
                            s1_v *= 0.70
                        elif mode == "ACCEL_EARLY_BOOST":
                            if s1_v > 0.0 and acc > 0.25:
                                s1_v = min(1.0, s1_v * 1.25)
                            elif s1_v > 0.50 and acc < -0.25:
                                s1_v *= 0.75
                    s1_ovr[sym] = s1_v
                solved = solve_s1_s5_admm_weights(active, day_sigs, cur_w, cov_h, s1_override=s1_ovr)
                targets = {s: w for s, w in zip(active, solved, strict=True)}
            ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
            nav_by_date[t_avail.date().isoformat()] = float(ledger.mark_nav(exec_prices))
        return {
            "full": _portfolio_metrics(nav_by_date),
            "stress": _portfolio_metrics({k: v for k, v in nav_by_date.items() if k >= stress_iso}),
            "fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
            "uplift_vs_base": paired_baseline_uplift(_daily_returns_map(nav_by_date), base_rets, simulations=499, seed=42),
        }

    return {
        "baseline_13": {"full": base_13["metrics_full"], "stress": base_13["metrics_stress"], "fees_usdt": base_13["total_fees_usdt"]},
        "ACCEL_BLEND_20": _sim("ACCEL_BLEND_20"),
        "ACCEL_DECEL_BRAKE": _sim("ACCEL_DECEL_BRAKE"),
        "ACCEL_EARLY_BOOST": _sim("ACCEL_EARLY_BOOST"),
    }


def _extract_8feat_2h_sequences(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth: dict[str, float],
    *,
    seq_len: int = 36,
) -> tuple[list[datetime], list[str], np.ndarray, np.ndarray]:
    """Extract 8-channel 2h pre-breakout sequences: 6 baseline + 2nd-order velocity accel + volume accel."""
    dts6, syms6, xs6, ys6 = _extract_2h_breakout_sequences(panel_2h, symbols, daily_breadth, seq_len=seq_len)
    if len(dts6) == 0:
        return dts6, syms6, np.empty((0, seq_len, 8)), ys6
    # Build causal 2nd-order velocity acceleration & volume acceleration directly from sequence channels 0 (z_ret) & 2 (log_vol)
    n, t_len, _ = xs6.shape
    xs8 = np.zeros((n, t_len, 8), dtype=np.float64)
    xs8[:, :, :6] = xs6
    af, as_ = 2.0 / 5.0, 2.0 / 13.0
    for k in range(n):
        ef_r, es_r = xs6[k, 0, 0], xs6[k, 0, 0]
        ef_v, es_v = xs6[k, 0, 2], xs6[k, 0, 2]
        for t in range(t_len):
            r_t, v_t = xs6[k, t, 0], xs6[k, t, 2]
            ef_r = (1.0 - af) * ef_r + af * r_t
            es_r = (1.0 - as_) * es_r + as_ * r_t
            ef_v = (1.0 - af) * ef_v + af * v_t
            es_v = (1.0 - as_) * es_v + as_ * v_t
            xs8[k, t, 6] = ef_r - es_r
            xs8[k, t, 7] = ef_v - es_v
    return dts6, syms6, xs8, ys6


def _run_gru_ignition_2nd_order(
    panel_2h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
) -> dict:
    """Part 1B: Purged walk-forward 8-feature (with 2nd-order accel) vs 6-feature GRU-Ignition."""
    dts, syms, xs8, ys = _extract_8feat_2h_sequences(panel_2h, IGNITION_18_CRYPTO, daily_breadth)
    folds = [
        (datetime(2024, 9, 1, tzinfo=UTC), datetime(2025, 4, 1, tzinfo=UTC)),
        (datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 11, 24, tzinfo=UTC)),
        (datetime(2025, 11, 24, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    ]
    purge = timedelta(hours=48)

    def _eval_dim(x_mat: np.ndarray, tag: str) -> dict:
        prob_map: dict[tuple[datetime, str], float] = {}
        oos_y, oos_p = [], []
        for te_s, te_e in folds:
            tr_i = [k for k, dt in enumerate(dts) if dt < te_s - purge]
            te_i = [k for k, dt in enumerate(dts) if te_s <= dt < te_e]
            if len(tr_i) < 80 or not te_i:
                continue
            m = EnsembleGRU(input_dim=x_mat.shape[2], hidden_dim=12, task="binary", seeds=(42, 101, 202))
            m.fit(x_mat[tr_i], ys[tr_i], epochs=24, batch_size=64, lr=4e-3, l2_reg=5e-3)
            pr = m.predict(x_mat[te_i])
            for kp, rk in enumerate(te_i):
                p = float(pr[kp])
                prob_map[(dts[rk], syms[rk])] = p
                oos_y.append(int(ys[rk]))
                oos_p.append(p)
        auc = _roc_auc(oos_y, oos_p)
        base_r = sum(oos_y) / max(1, len(oos_y))
        order = sorted(range(len(oos_p)), key=lambda i: oos_p[i])
        cut = max(1, len(order) // 3)
        bot_wr = sum(oos_y[i] for i in order[:cut]) / cut * 100.0 if order else 0.0
        top_wr = sum(oos_y[i] for i in order[-cut:]) / cut * 100.0 if order else 0.0
        nbx = _simulate_gru_sized_ignition(panel_2h, IGNITION_18_CRYPTO, daily_breadth, prob_map, label=f"{tag}_NBX16", leg_cost=0.0016, base_prob=base_r)
        wlx = _simulate_gru_sized_ignition(panel_2h, IGNITION_18_CRYPTO, daily_breadth, prob_map, label=f"{tag}_WLX25", leg_cost=0.0025, base_prob=base_r)
        return {
            "oos_episodes": len(oos_y),
            "oos_roc_auc": auc,
            "bottom_tercile_wr_pct": round(bot_wr, 1),
            "top_tercile_wr_pct": round(top_wr, 1),
            "nbx16": nbx,
            "wlx25": wlx,
        }

    return {
        "gru_6feat_baseline": _eval_dim(xs8[:, :, :6], "GRU6"),
        "gru_8feat_second_order": _eval_dim(xs8, "GRU8_ACCEL"),
    }


def _run_part2_tiered_sparse(
    panel_2h_0: dict[str, list[BarPoint]],
    panel_2h_1: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
    base_rets: dict[str, float],
) -> tuple[list[dict], dict[str, float], dict[datetime, dict[str, float]]]:
    """Part 2: Compare IGN18 vs IGN38_RAW vs IGN38_TIERED_HURDLE across 0h/+1h and NBX16/WLX25."""
    rows: list[dict] = []
    ign18_nav_0: dict[str, float] = {}
    ign18_targets_0: dict[datetime, dict[str, float]] = {}

    for off, p2h in ((0, panel_2h_0), (1, panel_2h_1)):
        for tag, cost in (("NBX16", 0.0016), ("WLX25", 0.0025)):
            # 18-coin baseline
            r18, n18, t18 = simulate_tiered_sparse_ignition(
                p2h, IGNITION_18_CRYPTO, (), daily_breadth,
                label=f"IGN18_2H_{tag}_OFF{off}H", offset_hours=off, core_leg_cost=cost, sat_extra_leg_cost=0.0,
            )
            rows.append({
                **asdict(r18.base), "core_entries": r18.core_entries, "sat_entries": r18.satellite_entries,
                "corr_vs_base": round(pearson_correlation(base_rets, _daily_returns_map(n18)), 4),
            })
            if off == 0 and tag == "NBX16":
                ign18_nav_0, ign18_targets_0 = n18, t18

            # 38-coin raw uniform hurdle (same 3.0z / 2.5x vol, +10bps Tier-2 spread penalty)
            r38_raw, n38_raw, _ = simulate_tiered_sparse_ignition(
                p2h, IGNITION_18_CRYPTO, SATELLITE_20_CRYPTO, daily_breadth,
                label=f"IGN38_RAW_{tag}_OFF{off}H", offset_hours=off, core_leg_cost=cost, sat_extra_leg_cost=0.0010,
                core_z=3.0, core_vol=2.5, sat_z=3.0, sat_vol=2.5, sat_min_24h_dvol=0.0,
            )
            rows.append({
                **asdict(r38_raw.base), "core_entries": r38_raw.core_entries, "sat_entries": r38_raw.satellite_entries,
                "corr_vs_base": round(pearson_correlation(base_rets, _daily_returns_map(n38_raw)), 4),
            })

            # 38-coin strict tiered sparsity hurdle (sat_z=3.6, sat_vol=3.2, $15k 24h dvol floor, +10bps penalty)
            r38_tier, n38_tier, _ = simulate_tiered_sparse_ignition(
                p2h, IGNITION_18_CRYPTO, SATELLITE_20_CRYPTO, daily_breadth,
                label=f"IGN38_TIERED_{tag}_OFF{off}H", offset_hours=off, core_leg_cost=cost, sat_extra_leg_cost=0.0010,
                core_z=3.0, core_vol=2.5, sat_z=3.6, sat_vol=3.2, sat_min_24h_dvol=15000.0,
            )
            rows.append({
                **asdict(r38_tier.base), "core_entries": r38_tier.core_entries, "sat_entries": r38_tier.satellite_entries,
                "corr_vs_base": round(pearson_correlation(base_rets, _daily_returns_map(n38_tier)), 4),
            })

    return rows, ign18_nav_0, ign18_targets_0


def _run_part3_sleeve_weighting(
    panel_1h_union: dict[str, list[BarPoint]],
    union_syms: tuple[str, ...],
    daily_targets: dict[datetime, dict[str, float]],
    ign_targets_2h: dict[datetime, dict[str, float]],
    base_nav: dict[str, float],
    ign_nav: dict[str, float],
) -> list[dict]:
    """Part 3: Static vs Walk-Forward Risk-Parity & Shrunk Min-Var sleeve weighting on single shared ledger."""
    slow_rets = _daily_returns_map(base_nav)
    ign_rets = _daily_returns_map(ign_nav)
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    wf_rp_w = compute_walkforward_sleeve_weights(slow_rets, ign_rets, mode="WF_INV_VOL_RP", window=60)
    wf_mv_w = compute_walkforward_sleeve_weights(slow_rets, ign_rets, mode="WF_MIN_VAR_SHRUNK", window=90)

    # Overlap baseline (100% slow on exact same 1h calendar)
    results: list[dict] = []
    for tag, fee in (("NBX16", Decimal("0.0016")), ("WLX25", Decimal("0.0025"))):
        base_run = run_dynamic_shared_ledger_blend(
            panel_1h_union, union_syms, daily_targets, ign_targets_2h, {},
            default_weights=(1.0, 0.0), fee_rate=fee,
        )
        base_ov_rets = _daily_returns_map(base_run["nav_by_date"])
        st70_run = run_dynamic_shared_ledger_blend(
            panel_1h_union, union_syms, daily_targets, ign_targets_2h, {},
            default_weights=(0.70, 0.30), fee_rate=fee,
        )
        st70_rets = _daily_returns_map(st70_run["nav_by_date"])

        configs = [
            (f"BASE_100_0_{tag}", {}, (1.0, 0.0), base_run),
            (f"STATIC_70_30_{tag}", {}, (0.70, 0.30), st70_run),
            (f"STATIC_60_40_{tag}", {}, (0.60, 0.40), None),
            (f"STATIC_50_50_{tag}", {}, (0.50, 0.50), None),
            (f"WF_INV_VOL_RP_{tag}", wf_rp_w, (0.70, 0.30), None),
            (f"WF_MIN_VAR_SHRUNK_{tag}", wf_mv_w, (0.70, 0.30), None),
        ]
        for name, w_map, def_w, pre_run in configs:
            run = pre_run or run_dynamic_shared_ledger_blend(
                panel_1h_union, union_syms, daily_targets, ign_targets_2h, w_map,
                default_weights=def_w, fee_rate=fee,
            )
            nav = run["nav_by_date"]
            rets = _daily_returns_map(nav)
            up_base = paired_baseline_uplift(rets, base_ov_rets, simulations=499, seed=42)
            up_70 = paired_baseline_uplift(rets, st70_rets, simulations=499, seed=42)
            ci_b = up_base.get("ci_95") or (0.0, 0.0)
            ci_7 = up_70.get("ci_95") or (0.0, 0.0)
            results.append({
                "name": name,
                "avg_slow_weight": run["avg_slow_weight"],
                "full": _portfolio_metrics(nav),
                "stress": _portfolio_metrics({k: v for k, v in nav.items() if k >= stress_iso}),
                "fees_usdt": run["total_fees_usdt"],
                "uplift_vs_base_bps": round(float(up_base.get("mean_uplift", 0.0)) * 10000.0, 2),
                "ci_vs_base_bps": [round(ci_b[0] * 10000.0, 2), round(ci_b[1] * 10000.0, 2)],
                "uplift_vs_70_30_bps": round(float(up_70.get("mean_uplift", 0.0)) * 10000.0, 2),
                "ci_vs_70_30_bps": [round(ci_7[0] * 10000.0, 2), round(ci_7[1] * 10000.0, 2)],
            })
    return results


def run_higher_order_and_sparse_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Execute all 4 studies strictly read-only against archived candles."""
    all_1d_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    all_1h_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO + SATELLITE_20_CRYPTO))

    con = open_readonly_market_db(db_path)
    try:
        panel_1d_all = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in all_1d_syms}
        panel_1h_all = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in all_1h_syms}
    finally:
        con.close()

    panel_13 = {s: panel_1d_all[s] for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    base_13 = _run_self_financing_arm("DROP_S2", panel_13, sigs_13, eval_dates)
    base_rets = _daily_returns_map(base_13["nav_by_date"])

    daily_breadth = extract_daily_breadth(sigs_13)

    # Part 1A: 2nd-order momentum on 1d BASE_13_S1_S5
    part_1a = _run_second_order_1d_arms(panel_13, sigs_13, eval_dates, base_13)

    # Resample 1h -> 2h for all 38 crypto markets (0h & +1h)
    ign38_syms = tuple(dict.fromkeys(IGNITION_18_CRYPTO + SATELLITE_20_CRYPTO))
    panel_2h_0 = {s: resample_hourly_to_bucket(panel_1h_all[s], 2, offset_hours=0) for s in ign38_syms}
    panel_2h_1 = {s: resample_hourly_to_bucket(panel_1h_all[s], 2, offset_hours=1) for s in ign38_syms}

    # Part 1B: 8-feature (with 2nd-order accel) GRU-Ignition vs 6-feature baseline
    part_1b = _run_gru_ignition_2nd_order({s: panel_2h_0[s] for s in IGNITION_18_CRYPTO}, daily_breadth)

    # Part 2: Tiered sparse universe expansion (18 -> 38)
    part_2, ign18_nav_0, ign18_targets_0 = _run_part2_tiered_sparse(panel_2h_0, panel_2h_1, daily_breadth, base_rets)

    # Part 3: Walk-forward risk-parity & shrunk min-var sleeve weighting
    union_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    daily_targets = _extract_daily_s1_s5_targets(panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0013"))
    panel_1h_union = {s: panel_1h_all[s] for s in union_syms}
    part_3 = _run_part3_sleeve_weighting(panel_1h_union, union_syms, daily_targets, ign18_targets_0, base_13["nav_by_date"], ign18_nav_0)

    # Part 4: Multi-week structural support breakdown short (1d laggards, Wallex borrow vs perp counterfactual)
    sigs_18 = compute_slow_sleeves({s: panel_1d_all[s] for s in IGNITION_18_CRYPTO}, IGNITION_18_CRYPTO)
    part_4: list[dict] = []
    for label, cost, brw in (
        ("STRUCT_SHORT_1D_WALLEX_MARGIN", 0.0025, 0.0009),
        ("STRUCT_SHORT_1D_NBX16_WLXBORROW", 0.0016, 0.0009),
        ("STRUCT_SHORT_1D_PERP_ZERO_BORROW", 0.0010, 0.0),
    ):
        res, nav = simulate_structural_breakdown_short(
            {s: panel_1d_all[s] for s in IGNITION_18_CRYPTO}, IGNITION_18_CRYPTO, sigs_18,
            label=label, leg_cost=cost, borrow_per_day=brw,
        )
        part_4.append({**asdict(res), "corr_vs_base": round(pearson_correlation(base_rets, _daily_returns_map(nav)), 4)})

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "part_1a_second_order_1d": part_1a,
        "part_1b_gru_ignition_second_order": part_1b,
        "part_2_tiered_sparse_38": part_2,
        "part_3_sleeve_weighting": part_3,
        "part_4_structural_breakdown_short": part_4,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    lines = [
        "# Four-Part Quantitative Study: Higher-Order Momentum, Tiered Sparse Expansion, Sleeve Weighting & Structural Bear Shorts",
        "",
        f"- **Generated:** `{p['generated_at']}`",
        "- **Causality:** Strict next-bar open execution, 1-day lagged walk-forward sleeve weights, 48h purged GRU walk-forward, explicit `+10 bps` Tier-2 altcoin spread penalty.",
        "",
        "## Part 1A — 2nd-Order Momentum (Trend Acceleration / Deceleration) on 1d BASE_13_S1_S5",
        "",
        "| Arm | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Fees | Mean Uplift (bps/d) | 95% CI (bps/d) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    p1a = p["part_1a_second_order_1d"]
    b = p1a["baseline_13"]
    lines.append(
        f"| `BASE_13_S1_S5` | `${b['full']['ending_nav']:.2f}` | `{b['full']['ret_pct']:+.2f}%` | `{b['stress']['ret_pct']:+.2f}%` | `{b['full']['ann_sharpe']:.3f}` | `{b['full']['max_dd_pct']:.2f}%` | `${b['fees_usdt']:.2f}` | `0.00` | `baseline` |"
    )
    for key in ("ACCEL_BLEND_20", "ACCEL_DECEL_BRAKE", "ACCEL_EARLY_BOOST"):
        a = p1a[key]
        up = a["uplift_vs_base"]
        lines.append(
            f"| `{key}` | `${a['full']['ending_nav']:.2f}` | `{a['full']['ret_pct']:+.2f}%` | `{a['stress']['ret_pct']:+.2f}%` | `{a['full']['ann_sharpe']:.3f}` | `{a['full']['max_dd_pct']:.2f}%` | `${a['fees_usdt']:.2f}` | `{up['mean_uplift']*10000:+.2f}` | `[{up['ci_95'][0]*10000:+.2f}, {up['ci_95'][1]*10000:+.2f}]` |"
        )

    p1b = p["part_1b_gru_ignition_second_order"]
    lines.extend([
        "",
        "## Part 1B — 2nd-Order Acceleration Features Inside GRU-Ignition (Purged Walk-Forward)",
        "",
        "| Model | OOS Episodes | ROC AUC | Bot/Top Tercile WR | NBX16 NAV / Ret / Bear / Sharpe | WLX25 NAV / Ret / Bear / Sharpe |",
        "| --- | ---: | ---: | --- | --- | --- |",
    ])
    for key, lbl in (("gru_6feat_baseline", "GRU-Ignition (6-feat baseline)"), ("gru_8feat_second_order", "GRU-Ignition (8-feat + 2nd-order accel)")):
        g = p1b[key]
        n16, w25 = g["nbx16"], g["wlx25"]
        lines.append(
            f"| `{lbl}` | `{g['oos_episodes']}` | `{g['oos_roc_auc']:.4f}` | `{g['bottom_tercile_wr_pct']:.1f}% / {g['top_tercile_wr_pct']:.1f}%` | "
            f"`${n16['ending_nav']:.2f} ({n16['ret_pct']:+.1f}%, Bear {n16['stress_ret_pct']:+.1f}%, SR {n16['ann_sharpe']:.3f})` | "
            f"`${w25['ending_nav']:.2f} ({w25['ret_pct']:+.1f}%, Bear {w25['stress_ret_pct']:+.1f}%, SR {w25['ann_sharpe']:.3f})` |"
        )

    lines.extend([
        "",
        "## Part 2 — Tiered Sparse Universe Expansion (18 Core vs 38 Markets Behind Strict Sparsity Hurdle)",
        "",
        "| Arm | Offset | Core Cost | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Entries (Core/Sat) | Win% | Corr vs Base |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ])
    for r in p["part_2_tiered_sparse_38"]:
        lines.append(
            f"| `{r['label']}` | `+{r['offset_hours']}h` | `{r['cost_bps']:.1f}bp` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['entries']} ({r['core_entries']}/{r['sat_entries']})` | `{r['win_rate_pct']:.1f}%` | `{r['corr_vs_base']:+.3f}` |"
        )

    lines.extend([
        "",
        "## Part 3 — Walk-Forward Risk-Parity & Shrunk Min-Var Sleeve Weighting (Single Shared Ledger)",
        "",
        "| Arm | Avg Slow Wt | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Fees | vs Base (bps/d) | vs 70/30 (bps/d) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ])
    for r in p["part_3_sleeve_weighting"]:
        lines.append(
            f"| `{r['name']}` | `{r['avg_slow_weight']*100:.1f}%` | `${r['full']['ending_nav']:.2f}` | `{r['full']['ret_pct']:+.2f}%` | `{r['stress']['ret_pct']:+.2f}%` | `{r['full']['ann_sharpe']:.3f}` | `{r['full']['max_dd_pct']:.2f}%` | `${r['fees_usdt']:.2f}` | `{r['uplift_vs_base_bps']:+.2f} [{r['ci_vs_base_bps'][0]:+.2f}, {r['ci_vs_base_bps'][1]:+.2f}]` | `{r['uplift_vs_70_30_bps']:+.2f} [{r['ci_vs_70_30_bps'][0]:+.2f}, {r['ci_vs_70_30_bps'][1]:+.2f}]` |"
        )

    lines.extend([
        "",
        "## Part 4 — Multi-Week Structural Support Breakdown Short (1d Bear-Momentum Laggards)",
        "",
        "| Arm | Cost | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Entries | Win% | Liqs | Avg Hold | Borrow ($) | Corr vs Base |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in p["part_4_structural_breakdown_short"]:
        lines.append(
            f"| `{r['label']}` | `{r['cost_bps']:.1f}bp` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['entries']}` | `{r['win_rate_pct']:.1f}%` | `{r['liquidations']}` | `{r['avg_hold_hours']/24.0:.1f}d` | `${r['total_borrow_usdt']:.2f}` | `{r['corr_vs_base']:+.3f}` |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
