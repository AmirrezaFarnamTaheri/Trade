"""Track II rigorous zero-lookahead ablations for 2h Ignition & GRU-Ignition:
- #2 Amended: 50/50 Phase-Averaged Twin Book (0h + 1h) on IGN18 & IGN38_TIERED
- #3 Amended: Vol-normalized Two-Tranche Exit (50% profit-lock + breakeven stop + unlocked 96h runner)
- #4 Amended: 11-feature Cross-Sectional Coiled-Spring GRU trained on exact path-dependent net trade P&L
- #10: Eigenvalue Absorption-Ratio single-factor slot throttle
- #12: Online Conformal Quantile calibration + equity-curve drawdown leverage governor
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

import numpy as np

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.higher_order_and_sparse import simulate_tiered_sparse_ignition
from ...domain.ignition_upgrades import (
    combine_twin_phase_navs,
    compute_absorption_ratio_map,
    compute_cross_sectional_2h_context,
    simulate_episode_path_pnl,
    simulate_upgraded_ignition,
)
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import extract_daily_breadth
from .gru_engine import EnsembleGRU
from .gru_prototypes_study import _roc_auc
from .higher_order_and_sparse_study import SATELLITE_20_CRYPTO
from .ignition_expansion_study import IGNITION_18_CRYPTO


def _extract_11feat_coiled_spring_dataset(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth: dict[str, float],
    *,
    seq_len: int = 36,
) -> tuple[list[datetime], list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Extract 11-channel pre-breakout sequences with both binary 24h labels and exact path-dependent net trade P&L."""
    wave_by_ts, rank_by_ts_sym = compute_cross_sectional_2h_context(panel_2h, symbols)
    btc_bars = panel_2h.get("BTCUSDT", [])
    btc_ret = {
        btc_bars[i].ts_avail: (btc_bars[i].close - btc_bars[i - 1].close) / btc_bars[i - 1].close
        for i in range(1, len(btc_bars))
        if btc_bars[i - 1].close > 0
    }

    dts, syms, xs, y_bin, y_path = [], [], [], [], []
    af, as_ = 2.0 / 5.0, 2.0 / 13.0

    for sym in symbols:
        bars = panel_2h.get(sym, [])
        if len(bars) < 105:
            continue
        rets = [0.0] + [
            (bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0
            for i in range(1, len(bars))
        ]
        vols = [b.volume for b in bars]
        highs = [b.high for b in bars]
        hls = [(b.high - b.low) / max(b.close, 1e-9) for b in bars]

        for i in range(max(72, seq_len), len(bars) - 26):
            b = bars[i]
            if not b.entry_eligible or not bars[i + 1].entry_eligible or bars[i + 1].open <= 0:
                continue
            pr, pv, ph = rets[i - 36 : i], vols[i - 36 : i], highs[i - 72 : i]
            mr = sum(pr) / 36.0
            sr = math.sqrt(sum((r - mr) ** 2 for r in pr) / 35.0)
            mv = median(pv)
            z = (rets[i] - mr) / max(sr, 1e-4)
            if z < 2.0 or mv <= 0 or b.volume < 1.8 * mv or b.close <= max(ph):
                continue

            seq = []
            ef_r, es_r, ef_v, es_v = 0.0, 0.0, 0.0, 0.0
            for idx_j, j in enumerate(range(i - seq_len + 1, i + 1)):
                bj = bars[j]
                rj = rets[j]
                zr = rj / max(sr, 1e-4)
                vr = math.log1p(bj.volume / max(mv, 1e-9))
                if idx_j == 0:
                    ef_r, es_r, ef_v, es_v = zr, zr, vr, vr
                else:
                    ef_r, es_r = (1.0 - af) * ef_r + af * zr, (1.0 - as_) * es_r + as_ * zr
                    ef_v, es_v = (1.0 - af) * ef_v + af * vr, (1.0 - as_) * es_v + as_ * vr
                rel_btc = rj - btc_ret.get(bj.ts_avail, 0.0)
                br_d = daily_breadth.get(bj.ts_avail.date().isoformat(), 0.5)
                hl_12 = sum(hls[max(0, j - 5) : j + 1]) / max(1, min(6, j + 1))
                hl_72 = sum(hls[max(0, j - 35) : j + 1]) / max(1, min(36, j + 1))
                vol_comp = min(3.0, hl_12 / max(hl_72, 1e-4))
                wave = wave_by_ts.get(bj.ts_avail, 0.0)
                cs_rk = rank_by_ts_sym.get((bj.ts_avail, sym), 0.5)
                seq.append([
                    zr, hls[j], vr, rel_btc, br_d, 1.0 if bj.close > bj.open else -1.0,
                    ef_r - es_r, ef_v - es_v, vol_comp, wave, cs_rk,
                ])

            ret_24h = (bars[i + 13].open - bars[i + 1].open) / bars[i + 1].open
            path_pnl = simulate_episode_path_pnl(bars, i, sr, leg_cost=0.0016, max_hold_bars=24)
            dts.append(b.ts_avail)
            syms.append(sym)
            xs.append(seq)
            y_bin.append(1.0 if ret_24h > 0.0032 else 0.0)
            y_path.append(path_pnl)

    return (
        dts, syms,
        np.asarray(xs, dtype=np.float64),
        np.asarray(y_bin, dtype=np.float64),
        np.asarray(y_path, dtype=np.float64),
    )


def _walkforward_gru_scores(
    dts: list[datetime],
    syms: list[str],
    x_mat: np.ndarray,
    y_target: np.ndarray,
    y_bin_eval: np.ndarray,
    *,
    task: str,
) -> tuple[dict[tuple[datetime, str], float], float, float]:
    """Run purged 3-fold walk-forward 3-seed EnsembleGRU and return (score_map, oos_auc_vs_bin, base_rate)."""
    folds = [
        (datetime(2024, 9, 1, tzinfo=UTC), datetime(2025, 4, 1, tzinfo=UTC)),
        (datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 11, 24, tzinfo=UTC)),
        (datetime(2025, 11, 24, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    ]
    purge = timedelta(hours=48)
    score_map: dict[tuple[datetime, str], float] = {}
    oos_y, oos_s = [], []
    for te_s, te_e in folds:
        tr_i = [k for k, dt in enumerate(dts) if dt < te_s - purge]
        te_i = [k for k, dt in enumerate(dts) if te_s <= dt < te_e]
        if len(tr_i) < 80 or not te_i:
            continue
        m = EnsembleGRU(input_dim=x_mat.shape[2], hidden_dim=12, task=task, seeds=(42, 101, 202))
        m.fit(x_mat[tr_i], y_target[tr_i], epochs=24, batch_size=64, lr=4e-3, l2_reg=5e-3)
        pr = m.predict(x_mat[te_i])
        for kp, rk in enumerate(te_i):
            val = float(pr[kp])
            score_map[(dts[rk], syms[rk])] = val
            oos_y.append(int(y_bin_eval[rk]))
            oos_s.append(val)
    auc = _roc_auc(oos_y, oos_s)
    base_r = sum(oos_y) / max(1, len(oos_y))
    return score_map, auc, base_r


def run_ignition_upgrade_ablation_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Execute Track II ablations (#2 Amended, #3 Amended, #4 Amended, #10, #12) strictly zero-lookahead."""
    all_1h = tuple(dict.fromkeys(IGNITION_18_CRYPTO + SATELLITE_20_CRYPTO))
    con = open_readonly_market_db(db_path)
    try:
        panel_13 = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in all_1h}
    finally:
        con.close()

    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    daily_breadth = extract_daily_breadth(sigs_13)

    p18_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    p18_1 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=1) for s in IGNITION_18_CRYPTO}
    p38_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in all_1h}
    p38_1 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=1) for s in all_1h}

    # Part A: Idea #2 Amended (50/50 Phase-Invariant Twin Book) on IGN18 & IGN38_TIERED
    twin_rows: list[dict] = []
    for tag, cost in (("NBX16", 0.0016), ("WLX25", 0.0025)):
        r18_0, n18_0 = simulate_upgraded_ignition(p18_0, IGNITION_18_CRYPTO, daily_breadth, label=f"IGN18_0H_{tag}", offset_hours=0, leg_cost=cost)
        r18_1, n18_1 = simulate_upgraded_ignition(p18_1, IGNITION_18_CRYPTO, daily_breadth, label=f"IGN18_1H_{tag}", offset_hours=1, leg_cost=cost)
        tw18 = combine_twin_phase_navs(f"IDEA_2_TWIN_IGN18_{tag}", n18_0, n18_1, r18_0, r18_1)
        tw18.pop("nav_by_date", None)
        twin_rows.extend([asdict(r18_0), asdict(r18_1), tw18])

        t38_0, n38_0, _ = simulate_tiered_sparse_ignition(
            p38_0, IGNITION_18_CRYPTO, SATELLITE_20_CRYPTO, daily_breadth,
            label=f"IGN38_TIER_0H_{tag}", offset_hours=0, core_leg_cost=cost, sat_extra_leg_cost=0.0010,
        )
        t38_1, n38_1, _ = simulate_tiered_sparse_ignition(
            p38_1, IGNITION_18_CRYPTO, SATELLITE_20_CRYPTO, daily_breadth,
            label=f"IGN38_TIER_1H_{tag}", offset_hours=1, core_leg_cost=cost, sat_extra_leg_cost=0.0010,
        )
        tw38 = combine_twin_phase_navs(f"IDEA_2_TWIN_IGN38_TIER_{tag}", n38_0, n38_1, t38_0.base, t38_1.base)
        tw38.pop("nav_by_date", None)
        twin_rows.append(tw38)

    # Part B: Ideas #3 (Two-Tranche Exit), #4 (11-feat Coiled-Spring + Path P&L GRU), #10 (Absorption Ratio), #12 (Conformal + DD Gov)
    ar_0 = compute_absorption_ratio_map(p18_0, IGNITION_18_CRYPTO)
    dts, syms, xs11, y_bin, y_path = _extract_11feat_coiled_spring_dataset(p18_0, IGNITION_18_CRYPTO, daily_breadth)

    sc_gru8_bin, auc8_bin, br8 = _walkforward_gru_scores(dts, syms, xs11[:, :, :8], y_bin, y_bin, task="binary")
    sc_gru11_bin, auc11_bin, br11 = _walkforward_gru_scores(dts, syms, xs11, y_bin, y_bin, task="binary")
    sc_gru11_pnl, auc11_pnl, _ = _walkforward_gru_scores(dts, syms, xs11, y_path, y_bin, task="regression")

    ablation_rows: list[dict] = []
    for tag, cost in (("NBX16", 0.0016), ("WLX25", 0.0025)):
        configs = [
            (f"BENCH_PLAIN_IGN18_{tag}", None, False, br8, False, None, False),
            (f"BENCH_GRU8_BCE_{tag}", sc_gru8_bin, False, br8, False, None, False),
            (f"IDEA_3_TWO_TRANCHE_PLAIN_{tag}", None, False, br8, True, None, False),
            (f"IDEA_3_TWO_TRANCHE_GRU8_{tag}", sc_gru8_bin, False, br8, True, None, False),
            (f"IDEA_4A_GRU11_COIL_BCE_{tag}", sc_gru11_bin, False, br11, False, None, False),
            (f"IDEA_4B_GRU11_COIL_PATHPNL_{tag}", sc_gru11_pnl, True, br11, False, None, False),
            (f"IDEA_10_AR_THROTTLE_GRU8_{tag}", sc_gru8_bin, False, br8, False, ar_0, False),
            (f"IDEA_12_CONFORMAL_DD_GRU8_{tag}", sc_gru8_bin, False, br8, False, None, True),
            (f"COMBO_GRU11PNL_3_10_12_{tag}", sc_gru11_pnl, True, br11, True, ar_0, True),
            (f"COMBO_GRU8_3_10_12_{tag}", sc_gru8_bin, False, br8, True, ar_0, True),
        ]
        for lbl, smap, is_ret, bp, two_t, ar_m, conf_dd in configs:
            res, _ = simulate_upgraded_ignition(
                p18_0, IGNITION_18_CRYPTO, daily_breadth, label=lbl, leg_cost=cost,
                score_map=smap, score_is_return=is_ret, base_prob=bp,
                use_two_tranche_exit=two_t, absorption_map=ar_m, use_conformal_and_dd_gov=conf_dd,
            )
            ablation_rows.append(asdict(res))

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "gru_model_auc": {
            "episodes_total": len(dts),
            "gru8_bce_oos_auc": auc8_bin,
            "gru11_coiled_bce_oos_auc": auc11_bin,
            "gru11_coiled_pathpnl_oos_auc": auc11_pnl,
        },
        "twin_phase_arms": twin_rows,
        "ablation_arms": ablation_rows,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    auc = p["gru_model_auc"]
    lines = [
        "# Track II Ablations — Phase-Invariant Twin Book, Two-Tranche Exit, 11-Feat Coiled-Spring GRU, Absorption Throttle & Conformal DD Governor",
        "",
        f"- **Generated:** `{p['generated_at']}`",
        f"- **Purged Walk-Forward GRU OOS AUC (`N={auc['episodes_total']}` total episodes):** `GRU8 BCE = {auc['gru8_bce_oos_auc']:.4f}` · `GRU11 Coiled BCE = {auc['gru11_coiled_bce_oos_auc']:.4f}` · `GRU11 Coiled Path-PnL = {auc['gru11_coiled_pathpnl_oos_auc']:.4f}`",
        "",
        "## Part A — Idea #2 Amended: 50/50 Phase-Invariant Twin Book (0h + 1h)",
        "",
        "| Arm | Cost | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Entries | Win% |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in p["twin_phase_arms"]:
        lines.append(
            f"| `{r['label']}` | `{r['cost_bps']:.1f}bp` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['entries']}` | `{r['win_rate_pct']:.1f}%` |"
        )
    lines.extend([
        "",
        "## Part B — Single-Factor & Combo Ablations (#3 Two-Tranche, #4 Coiled-Spring Path-PnL GRU, #10 Absorption Ratio, #12 Conformal + DD Gov)",
        "",
        "| Arm | Cost | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Entries | Win% | Liqs | Borrow ($) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in p["ablation_arms"]:
        lines.append(
            f"| `{r['label']}` | `{r['cost_bps']:.1f}bp` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['entries']}` | `{r['win_rate_pct']:.1f}%` | `{r['liquidations']}` | `${r['total_borrow_usdt']:.2f}` |"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
