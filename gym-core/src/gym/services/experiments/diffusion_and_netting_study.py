"""Track III ablations:
- Idea #5: Cross-sectional BTC/ETH Lead-Lag Diffusion sleeve on 2h bars (0h/+1h, NBX16/WLX25)
- Idea #9: Joint Single-ADMM Cross-Sleeve Netting & Sector Cluster Caps vs Post-Hoc 70/30 Blend
- Idea #6: Live Nobitex <-> Wallex Dislocation Fair-Value Entry Guard & Exit Premium Rebate across 20 USDT pairs
"""
from __future__ import annotations

import json
from bisect import bisect_left
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean, median

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.diffusion_and_netting import (
    run_joint_admm_cross_sleeve_netting,
    simulate_lead_lag_diffusion,
)
from ...domain.higher_order_and_sparse import simulate_tiered_sparse_ignition
from ...domain.ignition_and_intraday_exit import (
    pearson_correlation,
    run_shared_ledger_1h_blend,
)
from ...domain.model import dec, parse_ts
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import resample_hourly_to_bucket
from .admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    extract_daily_breadth,
)
from .ensemble_study import (
    STRESS_REPLAY_START,
    _daily_returns_map,
    _portfolio_metrics,
    _run_self_financing_arm,
)
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .ignition_validation_study import _extract_daily_s1_s5_targets


def _audit_live_venue_dislocations(
    wallex_db: Path,
    multi_venue_db: Path,
    *,
    max_skew_s: float = 15.0,
    dislocation_bps: float = 15.0,
) -> list[dict]:
    """Measure live entry-trap avoidance and exit-rebate opportunities across all matched Nobitex/Wallex USDT pairs."""
    if not wallex_db.is_file() or not multi_venue_db.is_file():
        return []
    wcon = open_readonly_market_db(wallex_db)
    mcon = open_readonly_market_db(multi_venue_db)
    out: list[dict] = []
    try:
        nbx_raw = mcon.execute(
            "SELECT symbol, ts_avail, bid, ask FROM venue_quotes "
            "WHERE venue = 'nobitex' AND symbol LIKE '%USDT' ORDER BY ts_avail ASC"
        ).fetchall()
        by_sym: dict[str, list] = {}
        for rec in nbx_raw:
            by_sym.setdefault(rec[0], []).append(rec)

        for sym, n_list in sorted(by_sym.items()):
            inst = wcon.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (sym,)).fetchone()
            if inst is None:
                continue
            min_ts = (parse_ts(n_list[0][1]) - timedelta(seconds=max_skew_s)).isoformat().replace("+00:00", "Z")
            w_raw = wcon.execute(
                "SELECT ts_avail, bid, ask FROM book_top WHERE instrument_id = ? AND ts_avail >= ? "
                "AND bid IS NOT NULL AND ask IS NOT NULL ORDER BY ts_avail ASC",
                (inst[0], min_ts),
            ).fetchall()
            if not w_raw:
                continue
            w_ep = [parse_ts(r[0]).timestamp() for r in w_raw]
            buy_traps, exit_rebates = [], []
            for _, ts_s, nb_s, na_s in n_list:
                t_ep = parse_ts(ts_s).timestamp()
                pos = bisect_left(w_ep, t_ep)
                best_i, best_dt = None, max_skew_s + 1.0
                for cand in (pos - 1, pos):
                    if 0 <= cand < len(w_ep):
                        dt = abs(w_ep[cand] - t_ep)
                        if dt < best_dt:
                            best_dt, best_i = dt, cand
                if best_i is None or best_dt > max_skew_s:
                    continue
                wb, wa = float(dec(w_raw[best_i][1])), float(dec(w_raw[best_i][2]))
                nb, na = float(dec(nb_s)), float(dec(na_s))
                if wb <= 0 or wa <= 0 or nb <= 0 or na <= 0:
                    continue
                common_mid = 0.25 * (wb + wa + nb + na)
                # Entry guard saving: worse venue ask minus better venue ask (in bps)
                buy_diff_bps = abs(wa - na) / common_mid * 10000.0
                # Exit rebate: best venue bid minus worse venue bid (in bps)
                sell_rebate_bps = abs(wb - nb) / common_mid * 10000.0
                buy_traps.append(buy_diff_bps)
                exit_rebates.append(sell_rebate_bps)
            if not buy_traps:
                continue
            n = len(buy_traps)
            out.append({
                "symbol": sym,
                "matched_pairs": n,
                "buy_guard_trigger_pct": round(sum(1 for x in buy_traps if x >= dislocation_bps) / n * 100.0, 1),
                "median_buy_dislocation_bps": round(median(buy_traps), 2),
                "exit_rebate_trigger_pct": round(sum(1 for x in exit_rebates if x >= dislocation_bps) / n * 100.0, 1),
                "median_exit_rebate_bps": round(median(exit_rebates), 2),
                "mean_exit_rebate_bps": round(mean(exit_rebates), 2),
            })
    finally:
        wcon.close()
        mcon.close()
    return out


def run_diffusion_and_netting_study(
    wallex_db: Path,
    multi_venue_db: Path,
    report_path: Path,
    receipt_path: Path,
) -> dict:
    """Execute Track III ablations (#5 Lead-Lag Diffusion, #9 Joint ADMM Netting, #6 Live Dislocation Rebate)."""
    union_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    con = open_readonly_market_db(wallex_db)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in union_syms}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in union_syms}
    finally:
        con.close()

    panel_13 = {s: panel_1d[s] for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    base_13 = _run_self_financing_arm("DROP_S2", panel_13, sigs_13, eval_dates)
    base_rets = _daily_returns_map(base_13["nav_by_date"])
    daily_breadth = extract_daily_breadth(sigs_13)

    sigs_18 = compute_slow_sleeves({s: panel_1d[s] for s in IGNITION_18_CRYPTO}, IGNITION_18_CRYPTO)
    daily_s1: dict[str, dict[str, float]] = {}
    for ts, d in sigs_18.items():
        daily_s1[ts.date().isoformat()] = {s: (v.s1_trend or 0.0) for s, v in d.items()}

    p18_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    p18_1 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=1) for s in IGNITION_18_CRYPTO}

    # Idea #5: Cross-sectional BTC/ETH Lead-Lag Diffusion across 0h/+1h & NBX16/WLX25
    diff_rows: list[dict] = []
    for off, p2h in ((0, p18_0), (1, p18_1)):
        for tag, cost in (("NBX16", 0.0016), ("WLX25", 0.0025)):
            r_d, nav_d = simulate_lead_lag_diffusion(
                p2h, IGNITION_18_CRYPTO, daily_breadth, daily_s1,
                label=f"IDEA_5_DIFFUSION_{tag}_OFF{off}H", offset_hours=off, leg_cost=cost,
            )
            diff_rows.append({
                **asdict(r_d),
                "corr_vs_base": round(pearson_correlation(base_rets, _daily_returns_map(nav_d)), 4),
            })

    # Idea #9: Joint Single-ADMM Cross-Sleeve Netting & Sector Cluster Caps vs Post-Hoc 70/30 Blend
    _, _, ign_targets = simulate_tiered_sparse_ignition(
        p18_0, IGNITION_18_CRYPTO, (), daily_breadth,
        label="IGN18_TARGETS", offset_hours=0, core_leg_cost=0.0016, sat_extra_leg_cost=0.0,
    )
    daily_targets = _extract_daily_s1_s5_targets(panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0013"))
    dated_rets = build_dated_returns_index(panel_13, BASE_13_SYMBOLS)
    cov_h_by_ts: dict[datetime, tuple[tuple[str, ...], tuple[tuple[float, ...], ...]]] = {}
    for ts in eval_dates[:-1]:
        act = tuple(s for s in BASE_13_SYMBOLS if s in sigs_13.get(ts, {}))
        if len(act) >= 2:
            cov_h_by_ts[ts] = (act, build_shrunk_horizon_cov(dated_rets, act, ts))

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    netting_rows: list[dict] = []
    for tag, fee in (("NBX16", Decimal("0.0016")), ("WLX25", Decimal("0.0025"))):
        posthoc = run_shared_ledger_1h_blend(
            panel_1h, union_syms, daily_targets, ign_targets,
            slow_weight=0.70, ignition_weight=0.30, fee_rate=fee,
        )
        joint = run_joint_admm_cross_sleeve_netting(
            panel_1h, union_syms, BASE_13_SYMBOLS, sigs_13, cov_h_by_ts, ign_targets,
            slow_budget=0.70, ignition_budget=0.30, fee_rate=fee, max_cluster_weight=0.40,
        )
        ph_rets = _daily_returns_map(posthoc["nav_by_date"])
        jn_rets = _daily_returns_map(joint["nav_by_date"])
        up = paired_baseline_uplift(jn_rets, ph_rets, simulations=499, seed=42)
        ci = up.get("ci_95") or (0.0, 0.0)
        for name, run, u_bps, c_bps in (
            (f"BENCH_POSTHOC_70_30_{tag}", posthoc, 0.0, [0.0, 0.0]),
            (f"IDEA_9_JOINT_ADMM_NETTED_{tag}", joint, round(float(up.get("mean_uplift", 0.0)) * 10000.0, 2), [round(ci[0] * 10000.0, 2), round(ci[1] * 10000.0, 2)]),
        ):
            nav = run["nav_by_date"]
            netting_rows.append({
                "name": name,
                "full": _portfolio_metrics(nav),
                "stress": _portfolio_metrics({k: v for k, v in nav.items() if k >= stress_iso}),
                "fills": run["fills"],
                "fees_usdt": run["total_fees_usdt"],
                "turnover": run["turnover_multiple"],
                "uplift_vs_posthoc_bps": u_bps,
                "ci_vs_posthoc_bps": c_bps,
            })

    # Idea #6: Live Nobitex <-> Wallex Dislocation Fair-Value Guard & Exit Rebate across all 20 USDT pairs
    disloc_rows = _audit_live_venue_dislocations(wallex_db, multi_venue_db)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "idea_5_lead_lag_diffusion": diff_rows,
        "idea_9_joint_admm_netting": netting_rows,
        "idea_6_live_dislocation_rebate": disloc_rows,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    lines = [
        "# Track III Ablations — Lead-Lag Diffusion, Single-ADMM Cross-Sleeve Netting & Live Venue Dislocation Rebates",
        "",
        f"- **Generated:** `{p['generated_at']}`",
        "",
        "## Idea #5 — Cross-Sectional BTC/ETH Lead-Lag Diffusion Sleeve (2h Bars)",
        "",
        "| Arm | Offset | Cost | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Entries | Win% | Avg Hold | Corr vs Base |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in p["idea_5_lead_lag_diffusion"]:
        lines.append(
            f"| `{r['label']}` | `+{r['offset_hours']}h` | `{r['cost_bps']:.1f}bp` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['entries']}` | `{r['win_rate_pct']:.1f}%` | `{r['avg_hold_hours']:.1f}h` | `{r['corr_vs_base']:+.3f}` |"
        )

    lines.extend([
        "",
        "## Idea #9 — Joint Single-ADMM Cross-Sleeve Netting & Sector Cluster Caps vs. Post-Hoc 70/30 Blend",
        "",
        "| Arm | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Fills | Fees ($) | Turnover | vs Post-Hoc (bps/d, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for r in p["idea_9_joint_admm_netting"]:
        lines.append(
            f"| `{r['name']}` | `${r['full']['ending_nav']:.2f}` | `{r['full']['ret_pct']:+.2f}%` | `{r['stress']['ret_pct']:+.2f}%` | `{r['full']['ann_sharpe']:.3f}` | `{r['full']['max_dd_pct']:.2f}%` | `{r['fills']}` | `${r['fees_usdt']:.2f}` | `{r['turnover']:.1f}x` | `{r['uplift_vs_posthoc_bps']:+.2f} [{r['ci_vs_posthoc_bps'][0]:+.2f}, {r['ci_vs_posthoc_bps'][1]:+.2f}]` |"
        )

    lines.extend([
        "",
        "## Idea #6 — Live Nobitex <-> Wallex Fair-Value Entry Guard & Exit Rebate Audit (`multi_venue_quotes.sqlite3`)",
        "",
        "| Symbol | Matched Live Pairs | Entry Guard >=15bp (%) | Med Entry Gap (bps) | Exit Rebate >=15bp (%) | Med Exit Rebate (bps) | Mean Exit Rebate (bps) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in p["idea_6_live_dislocation_rebate"]:
        lines.append(
            f"| `{r['symbol']}` | `{r['matched_pairs']}` | `{r['buy_guard_trigger_pct']:.1f}%` | `{r['median_buy_dislocation_bps']:.2f}` | `{r['exit_rebate_trigger_pct']:.1f}%` | `{r['median_exit_rebate_bps']:.2f}` | `{r['mean_exit_rebate_bps']:.2f}` |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
