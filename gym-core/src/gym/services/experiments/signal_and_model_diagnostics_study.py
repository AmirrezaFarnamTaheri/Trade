"""Post-Repair Signal & Model Diagnostics Study (Menu Ideas 2, 3, 4, 5, and 15).

Implements five post-repair paper diagnostics from
docs/architecture/2026-11-25-last-42-commits-review.md:
  - Idea 2: Sleeve disagreement netting vs. 1-bar residual delay (virtual opp-cost accounting).
  - Idea 3: Cheap static BTC/XAUT/USDT replica benchmark vs. sophisticated sleeves.
  - Idea 4: Event-clustered episode leave-one-out concentration analysis.
  - Idea 5: Narrow ML job — execute-now vs. wait-1-bar only (direction & size frozen).
  - Idea 15: Shallow rule distillation of the frozen 11-feat GRU and disagreement pricing.

Strictly read-only against market.db; DISARMED ($0 funded budget).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeRegressor

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import extract_daily_breadth
from .champion_v2_verification import _extract_daily_s1_s5_targets
from .ensemble_study import (
    STRESS_REPLAY_START,
    daily_returns_map,
    portfolio_metrics,
)
from .gru_engine import EnsembleGRU
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .ignition_upgrade_ablation_study import _extract_11feat_coiled_spring_dataset
from .unified_book_helpers import (
    WALKFORWARD_FOLDS,
    latest_signal_date,
    resolve_bar_prices,
)


def _run_idea_2_sleeve_disagreement(
    panel_2h: dict[str, list[BarPoint]],
    daily_targets: dict[datetime, dict[str, float]],
    dts_ign: list[datetime],
    syms_ign: list[str],
    *,
    leg_fee_bps: float = 16.0,
) -> dict:
    """Idea 2: Find opposite-signed slow-sell vs fast-buy intents and compare netting vs 1-bar residual delay."""
    sig_dates = sorted(daily_targets)
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    ts_lists = {s: sorted(by_start[s]) for s in IGNITION_18_CRYPTO}
    ts_idx = {s: {t: i for i, t in enumerate(ts_lists[s])} for s in IGNITION_18_CRYPTO}

    prev_slow_w: dict[datetime, dict[str, float]] = {}
    for k in range(1, len(sig_dates)):
        prev_slow_w[sig_dates[k]] = daily_targets[sig_dates[k - 1]]

    events = 0
    netted_notional = 0.0
    fees_saved_usdt = 0.0
    delay_bps: list[float] = []
    relinquish_opp_bps: list[float] = []

    for dt, sym in zip(dts_ign, syms_ign, strict=True):
        cur_sig = latest_signal_date(sig_dates, dt)
        if cur_sig is None or cur_sig not in prev_slow_w:
            continue
        w_prev = prev_slow_w[cur_sig].get(sym, 0.0)
        w_now = daily_targets[cur_sig].get(sym, 0.0)
        slow_sell_w = max(0.0, w_prev - w_now)
        if slow_sell_w < 0.01:
            continue
        i_bar = ts_idx.get(sym, {}).get(dt)
        if i_bar is None or i_bar + 12 >= len(ts_lists[sym]):
            continue
        b0 = by_start[sym][ts_lists[sym][i_bar]]
        b1 = by_start[sym][ts_lists[sym][i_bar + 1]]
        b12 = by_start[sym][ts_lists[sym][i_bar + 12]]
        if b0.open <= 0 or b1.open <= 0:
            continue
        events += 1
        fast_buy_notional = 100.0  # $100 reference fast buy on $1,000 book
        slow_sell_notional = slow_sell_w * 700.0
        net_n = min(fast_buy_notional, slow_sell_notional)
        netted_notional += net_n
        fees_saved_usdt += 2.0 * net_n * (leg_fee_bps / 10_000.0)
        # Positive means waiting 1 bar got a cheaper buy price; negative means adverse drift
        delay_bps.append(((b0.open - b1.open) / b0.open) * 10_000.0)
        # Opportunity cost to slow sleeve that relinquished short/trim exposure over next 24h
        relinquish_opp_bps.append(((b12.open - b0.open) / b0.open) * 10_000.0)

    return {
        "disagreement_events": events,
        "total_netted_notional_usdt": round(netted_notional, 2),
        "fees_saved_immediate_netting_usdt": round(fees_saved_usdt, 2),
        "mean_1bar_residual_delay_saving_bps": round(mean(delay_bps), 2) if delay_bps else 0.0,
        "mean_24h_relinquish_opp_cost_bps": round(mean(relinquish_opp_bps), 2) if relinquish_opp_bps else 0.0,
    }


def _project_simplex_bounded(w: np.ndarray) -> tuple[float, float, float]:
    """Project (w_btc, w_xaut) onto {w >= 0, sum(w) <= 1} with residual in USDT cash."""
    w_pos = np.maximum(0.0, w)
    s = float(np.sum(w_pos))
    if s > 1.0:
        w_pos = w_pos / s
    return round(float(w_pos[0]), 4), round(float(w_pos[1]), 4), round(max(0.0, 1.0 - float(np.sum(w_pos))), 4)


def _run_idea_3_cheap_replica(
    panel_1d: dict[str, list[BarPoint]],
    daily_targets: dict[datetime, dict[str, float]],
    *,
    fee_rate: Decimal = Decimal("0.0016"),
) -> dict:
    """Idea 3: Fit a static BTC/XAUT/USDT replica on dev (<2025-11-24) and test residual alpha OOS."""
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    dates = sorted(daily_targets)
    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    nav_strat: dict[str, float] = {}
    last_px: dict[str, float] = {}
    for ts in dates:
        ef, tr = resolve_bar_prices(BASE_13_SYMBOLS, by_start, by_avail, ts, last_px)
        ep = {s: Decimal(str(p)) for s, p in ef.items()}
        ledger.rebalance_to_targets(ts, daily_targets[ts], ep, tradable_symbols=tr)
        nav_strat[ts.date().isoformat()] = float(ledger.mark_nav(ep))

    r_strat = daily_returns_map(nav_strat)
    r_btc = daily_returns_map({b.ts_avail.date().isoformat(): b.close for b in panel_1d.get("BTCUSDT", [])})
    r_gold = daily_returns_map({b.ts_avail.date().isoformat(): b.close for b in panel_1d.get("XAUTUSDT", [])})
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    dev_days = sorted(d for d in (set(r_strat) & set(r_btc) & set(r_gold)) if d < stress_iso)
    oos_days = sorted(d for d in (set(r_strat) & set(r_btc) & set(r_gold)) if d >= stress_iso)

    x_dev = np.asarray([[r_btc[d], r_gold[d]] for d in dev_days], dtype=np.float64)
    y_dev = np.asarray([r_strat[d] for d in dev_days], dtype=np.float64)
    coef, *_ = np.linalg.lstsq(x_dev, y_dev, rcond=None)
    w_btc, w_xaut, w_cash = _project_simplex_bounded(coef)

    # Simulate frozen cheap replica OOS (with initial 16 bps entry fee + monthly rebalance)
    rep_nav_oos: dict[str, float] = {}
    strat_nav_oos: dict[str, float] = {}
    cur_rep = 1000.0 * (1.0 - (w_btc + w_xaut) * float(fee_rate))
    cur_str = 1000.0
    for d in oos_days:
        cur_rep *= 1.0 + w_btc * r_btc[d] + w_xaut * r_gold[d]
        cur_str *= 1.0 + r_strat[d]
        rep_nav_oos[d] = cur_rep
        strat_nav_oos[d] = cur_str

    m_str = portfolio_metrics(strat_nav_oos, starting_nav=1000.0)
    m_rep = portfolio_metrics(rep_nav_oos, starting_nav=1000.0)
    return {
        "fitted_dev_weights": {"BTCUSDT": w_btc, "XAUTUSDT": w_xaut, "USDT_CASH": w_cash},
        "strategy_oos": m_str,
        "cheap_replica_oos": m_rep,
        "oos_residual_ret_pct": round(m_str["ret_pct"] - m_rep["ret_pct"], 2),
        "oos_maxdd_diff_pct": round(m_str["max_dd_pct"] - m_rep["max_dd_pct"], 2),
    }


def _run_idea_4_episode_concentration(
    dts: list[datetime],
    y_path: np.ndarray,
    *,
    cluster_gap_hours: int = 6,
) -> dict:
    """Idea 4: Group simultaneous 2h entries into episodes and compute leave-one-out P&L concentration."""
    if len(dts) == 0:
        return {"episodes": 0, "independent_entry_days": 0}
    order = sorted(range(len(dts)), key=lambda i: dts[i])
    episodes: list[list[float]] = []
    cur_ep: list[float] = []
    last_dt: datetime | None = None
    for idx in order:
        dt = dts[idx]
        if last_dt is not None and (dt - last_dt) > timedelta(hours=cluster_gap_hours):
            episodes.append(cur_ep)
            cur_ep = []
        cur_ep.append(float(y_path[idx]) * 100.0)
        last_dt = dt
    if cur_ep:
        episodes.append(cur_ep)

    ep_pnls = sorted([sum(ep) for ep in episodes], reverse=True)
    total_pnl = sum(ep_pnls)
    top3_sum = sum(ep_pnls[:3])
    return {
        "total_raw_entries": len(dts),
        "clustered_episodes": len(episodes),
        "independent_entry_days": len({d.date() for d in dts}),
        "total_net_pnl_pct_pts": round(total_pnl, 2),
        "top1_episode_pnl_pct_pts": round(ep_pnls[0], 2) if ep_pnls else 0.0,
        "top3_episodes_pnl_pct_pts": round(top3_sum, 2),
        "top3_share_of_total_pct": round((top3_sum / total_pnl * 100.0), 1) if abs(total_pnl) > 1e-9 else 0.0,
        "pnl_without_top3_pct_pts": round(total_pnl - top3_sum, 2),
    }


def _run_idea_5_narrow_ml_execute_or_wait(
    panel_2h: dict[str, list[BarPoint]],
    dts: list[datetime],
    syms: list[str],
    xs11: np.ndarray,
    y_path: np.ndarray,
) -> dict:
    """Idea 5: Freeze direction/size; let ML choose ONLY execute-now vs wait-1-bar vs simple baselines."""
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    ts_lists = {s: sorted(by_start[s]) for s in IGNITION_18_CRYPTO}
    ts_idx = {s: {t: i for i, t in enumerate(ts_lists[s])} for s in IGNITION_18_CRYPTO}

    feats_dev, y_wait_dev = [], []
    oos_rows: list[tuple[np.ndarray, float, float, float]] = []  # (feat, wait_save_bps, bar_hl, path_bps)
    for k, (dt, sym) in enumerate(zip(dts, syms, strict=True)):
        i_bar = ts_idx.get(sym, {}).get(dt)
        if i_bar is None or i_bar + 1 >= len(ts_lists[sym]):
            continue
        b0 = by_start[sym][ts_lists[sym][i_bar]]
        b1 = by_start[sym][ts_lists[sym][i_bar + 1]]
        if b0.open <= 0 or b1.open <= 0:
            continue
        wait_save_bps = ((b0.open - b1.open) / b0.open) * 10_000.0
        f_last = xs11[k, -1, :6]
        if dt < STRESS_REPLAY_START:
            feats_dev.append(f_last)
            y_wait_dev.append(1 if wait_save_bps > 0 else 0)
        else:
            oos_rows.append((f_last, wait_save_bps, float(f_last[1]), float(y_path[k]) * 10_000.0))

    if len(feats_dev) < 40 or not oos_rows:
        return {"status": "INSUFFICIENT_DATA"}

    clf = LogisticRegression(C=0.2, max_iter=300)
    clf.fit(np.asarray(feats_dev), np.asarray(y_wait_dev))
    med_hl = float(np.median([f[1] for f in feats_dev]))

    always_now = [0.0 for _ in oos_rows]
    always_wait = [r[1] for r in oos_rows]
    hl_rule = [r[1] if r[2] > med_hl else 0.0 for r in oos_rows]
    ml_preds = clf.predict_proba(np.asarray([r[0] for r in oos_rows]))[:, 1]
    ml_gate = [r[1] if p >= 0.55 else 0.0 for r, p in zip(oos_rows, ml_preds, strict=True)]

    return {
        "oos_orders": len(oos_rows),
        "always_now_mean_saving_bps": round(mean(always_now), 2),
        "always_wait_1b_mean_saving_bps": round(mean(always_wait), 2),
        "simple_range_threshold_mean_saving_bps": round(mean(hl_rule), 2),
        "ml_wait_gate_mean_saving_bps": round(mean(ml_gate), 2),
        "ml_wait_rate_pct": round(sum(1 for p in ml_preds if p >= 0.55) / len(ml_preds) * 100.0, 1),
    }


def _run_idea_15_gru_distillation(
    dts: list[datetime],
    xs11: np.ndarray,
    y_path: np.ndarray,
) -> dict:
    """Idea 15: Distill the frozen GRU into a depth-3 decision tree and price their OOS disagreements."""
    purge = timedelta(hours=48)
    agree_n = disagree_n = 0
    gru_only_bps: list[float] = []
    tree_only_bps: list[float] = []
    both_hi_bps: list[float] = []

    for te_s, te_e in WALKFORWARD_FOLDS:
        tr_i = [k for k, dt in enumerate(dts) if dt < te_s - purge]
        te_i = [k for k, dt in enumerate(dts) if te_s <= dt < te_e]
        if len(tr_i) < 80 or not te_i:
            continue
        gru = EnsembleGRU(input_dim=xs11.shape[2], hidden_dim=12, task="regression", seeds=(42, 101, 202))
        gru.fit(xs11[tr_i], y_path[tr_i], epochs=24, batch_size=64, lr=4e-3, l2_reg=5e-3)
        gru_tr = gru.predict(xs11[tr_i])
        gru_te = gru.predict(xs11[te_i])

        # Shallow depth-3 tree imitating frozen GRU's predictions (strictly no oracle labels!)
        tree = DecisionTreeRegressor(max_depth=3, min_samples_leaf=15, random_state=42)
        tree.fit(xs11[tr_i, -1, :], gru_tr)
        tree_te = tree.predict(xs11[te_i, -1, :])

        thr_g = float(np.quantile(gru_tr, 0.67))
        thr_t = float(np.quantile(tree.predict(xs11[tr_i, -1, :]), 0.67))
        for k_loc, rk in enumerate(te_i):
            g_hi = float(gru_te[k_loc]) >= thr_g
            t_hi = float(tree_te[k_loc]) >= thr_t
            net_bps = float(y_path[rk]) * 10_000.0
            if g_hi == t_hi:
                agree_n += 1
                if g_hi:
                    both_hi_bps.append(net_bps)
            else:
                disagree_n += 1
                if g_hi:
                    gru_only_bps.append(net_bps)
                else:
                    tree_only_bps.append(net_bps)

    tot = max(1, agree_n + disagree_n)
    g_m = mean(gru_only_bps) if gru_only_bps else 0.0
    t_m = mean(tree_only_bps) if tree_only_bps else 0.0
    return {
        "oos_total": agree_n + disagree_n,
        "agreement_rate_pct": round(agree_n / tot * 100.0, 1),
        "disagreement_count": disagree_n,
        "both_top_tercile_mean_bps": round(mean(both_hi_bps), 2) if both_hi_bps else 0.0,
        "gru_only_top_count": len(gru_only_bps),
        "gru_only_mean_bps": round(g_m, 2),
        "shallow_tree_only_count": len(tree_only_bps),
        "shallow_tree_only_mean_bps": round(t_m, 2),
        "gru_minus_tree_disagreement_bps": round(g_m - t_m, 2),
    }


def run_signal_and_model_diagnostics_study(
    wallex_db: Path,
    report_path: Path,
    receipt_path: Path,
) -> dict:
    """Execute Menu Ideas 2, 3, 4, 5, and 15 on the corrected zero-lookahead engine."""
    all_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    con = open_readonly_market_db(wallex_db)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in all_syms}
    finally:
        con.close()

    sigs_13 = compute_slow_sleeves(panel_1d, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_breadth = extract_daily_breadth(sigs_13)
    daily_targets = _extract_daily_s1_s5_targets(panel_1d, sigs_13, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0016"))
    panel_2h = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in all_syms if panel_1h[s]}

    dts, syms, xs11, _, y_path = _extract_11feat_coiled_spring_dataset(panel_2h, IGNITION_18_CRYPTO, daily_breadth)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "idea_2_sleeve_disagreement": _run_idea_2_sleeve_disagreement(panel_2h, daily_targets, dts, syms),
        "idea_3_cheap_replica": _run_idea_3_cheap_replica(panel_1d, daily_targets),
        "idea_4_episode_concentration": _run_idea_4_episode_concentration(dts, y_path),
        "idea_5_narrow_ml_wait": _run_idea_5_narrow_ml_execute_or_wait(panel_2h, dts, syms, xs11, y_path),
        "idea_15_gru_distillation": _run_idea_15_gru_distillation(dts, xs11, y_path),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    i2, i3, i4 = p["idea_2_sleeve_disagreement"], p["idea_3_cheap_replica"], p["idea_4_episode_concentration"]
    i5, i15 = p["idea_5_narrow_ml_wait"], p["idea_15_gru_distillation"]
    lines = [
        "# Post-Repair Signal & Model Diagnostics Study (Menu Ideas 2, 3, 4, 5, and 15)",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`$0` funded budget)",
        "",
        "## Idea 2 — Sleeve Disagreement (Immediate Netting vs. 1-Bar Residual Delay)",
        f"- **Opposite-Signed Events (Slow Sell vs Fast Buy):** `{i2['disagreement_events']}` · **Netted Notional:** `${i2['total_netted_notional_usdt']:.2f}` · **Immediate Netting Fee Savings:** `${i2['fees_saved_immediate_netting_usdt']:.2f}`",
        f"- **1-Bar Residual Delay Price Saving:** `{i2['mean_1bar_residual_delay_saving_bps']:+.2f} bps` · **24h Relinquishing-Sleeve Opp. Cost:** `{i2['mean_24h_relinquish_opp_cost_bps']:+.2f} bps`",
        "",
        "## Idea 3 — Cheap Static BTC/XAUT/USDT Replica Benchmark (OOS `>= 2025-11-24`)",
        f"- **Dev-Fitted Static Replica Weights:** `{i3['fitted_dev_weights']}`",
        f"- **Slow `S1+S5` OOS:** Ret `{i3['strategy_oos']['ret_pct']:+.2f}%`, Sharpe `{i3['strategy_oos']['ann_sharpe']:.3f}`, MaxDD `{i3['strategy_oos']['max_dd_pct']:.2f}%`",
        f"- **Cheap Replica OOS:** Ret `{i3['cheap_replica_oos']['ret_pct']:+.2f}%`, Sharpe `{i3['cheap_replica_oos']['ann_sharpe']:.3f}`, MaxDD `{i3['cheap_replica_oos']['max_dd_pct']:.2f}%`",
        f"- **OOS Residual Alpha vs Replica:** `{i3['oos_residual_ret_pct']:+.2f}%` · **MaxDD Diff:** `{i3['oos_maxdd_diff_pct']:+.2f}%`",
        "",
        "## Idea 4 — Event-Clustered Episode Leave-One-Out Concentration (`<=6h` Clusters)",
        f"- **Raw Entries:** `{i4['total_raw_entries']}` → **Clustered Episodes:** `{i4['clustered_episodes']}` (`{i4['independent_entry_days']}` independent entry days)",
        f"- **Total Net Path P&L:** `{i4['total_net_pnl_pct_pts']:+.2f}` pct-pts · **Top-1 Episode:** `{i4['top1_episode_pnl_pct_pts']:+.2f}` · **Top-3 Share:** `{i4['top3_share_of_total_pct']:.1f}%` · **P&L Without Top-3:** `{i4['pnl_without_top3_pct_pts']:+.2f}`",
        "",
        "## Idea 5 — Narrow ML Job (Execute-Now vs. Wait-1-Bar Only, OOS `>= 2025-11-24`)",
        f"- **OOS Orders:** `{i5.get('oos_orders', 0)}` · **Always Now:** `{i5.get('always_now_mean_saving_bps', 0):+.2f} bps` · **Always Wait 1b:** `{i5.get('always_wait_1b_mean_saving_bps', 0):+.2f} bps`",
        f"- **Simple Range Threshold:** `{i5.get('simple_range_threshold_mean_saving_bps', 0):+.2f} bps` · **ML Wait Gate:** `{i5.get('ml_wait_gate_mean_saving_bps', 0):+.2f} bps` (`wait_rate={i5.get('ml_wait_rate_pct', 0):.1f}%`)",
        "",
        "## Idea 15 — Shallow Depth-3 Tree Distillation of Frozen GRU & Disagreement Pricing",
        f"- **OOS Samples:** `{i15['oos_total']}` · **Agreement Rate:** `{i15['agreement_rate_pct']:.1f}%` · **Disagreements:** `{i15['disagreement_count']}`",
        f"- **Both Top-Tercile:** `{i15['both_top_tercile_mean_bps']:+.2f} bps` · **GRU-Only Top (`N={i15['gru_only_top_count']}`):** `{i15['gru_only_mean_bps']:+.2f} bps` · **Tree-Only Top (`N={i15['shallow_tree_only_count']}`):** `{i15['shallow_tree_only_mean_bps']:+.2f} bps`",
        f"- **GRU Minus Shallow Tree on Disagreements:** `{i15['gru_minus_tree_disagreement_bps']:+.2f} bps`",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
