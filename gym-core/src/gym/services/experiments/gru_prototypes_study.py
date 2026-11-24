"""Strictly causal walk-forward evaluation of 3 GRU prototypes: GRU-Vol, GRU-Ignition, and GRU-Exec."""
from __future__ import annotations

import json
import math
from bisect import bisect_right
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

import numpy as np

from ...adapters.candle_reader import (
    load_book_and_trades,
    load_keyed_candles,
    open_readonly_market_db,
)
from ...domain.async_covariance import coarse_bar_shrunk_covariance_aligned
from ...domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    solve_convex_portfolio,
)
from ...domain.execution_schedule import (
    causal_spread_quantile_bps,
    compare_execution_timing_arms,
)
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.short_and_levered_ignition import (
    _breakdown_or_breakout_z,
    _check_margin_exit,
    _summarize_levered_nav,
    simulate_levered_ignition,
)
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from ...domain.venue_contracts import wallex_l1_fee_schedule
from ...domain.volatility_models import OhlcBar, yang_zhang_volatility
from .ensemble_study import (
    STRESS_REPLAY_START,
    _daily_returns_map,
    _portfolio_metrics,
    _run_self_financing_arm,
)
from .gru_engine import EnsembleGRU
from .ignition_expansion_study import IGNITION_18_CRYPTO


def _roc_auc(y_true: list[int], y_prob: list[float]) -> float:
    pairs = sorted(zip(y_prob, y_true, strict=True))
    n_pos = sum(y_true)
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    rank_sum = sum(i + 1 for i, (_, y) in enumerate(pairs) if y == 1)
    return round((rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg), 4)


# ── Prototype 1: GRU-Vol (20-day realized volatility forecaster fed into ADMM) ─────────────────────

def _build_daily_vol_dataset(
    panel_1d: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    *,
    seq_len: int = 20,
    horizon: int = 20,
) -> tuple[list[datetime], list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Build strictly causal (T=20) daily feature sequences and forward 20d log-vol targets."""
    btc_bars = {b.ts_avail: b for b in panel_1d.get("BTCUSDT", [])}
    btc_dates = sorted(btc_bars)
    btc_ret = {}
    for i in range(1, len(btc_dates)):
        c0, c1 = btc_bars[btc_dates[i - 1]].close, btc_bars[btc_dates[i]].close
        if c0 > 0:
            btc_ret[btc_dates[i]] = (c1 - c0) / c0

    dts_out, syms_out, x_list, y_list, yz_list = [], [], [], [], []
    for sym in symbols:
        bars = panel_1d.get(sym, [])
        if len(bars) < seq_len + horizon + 25:
            continue
        rets = [0.0] + [
            (bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0
            for i in range(1, len(bars))
        ]
        ohlcs = [OhlcBar(b.open, b.high, b.low, b.close) for b in bars]
        yzs = [yang_zhang_volatility(ohlcs[max(0, i - 19) : i + 1]) for i in range(len(bars))]

        for i in range(seq_len + 20, len(bars) - horizon):
            seq = []
            for j in range(i - seq_len + 1, i + 1):
                b = bars[j]
                hl = (b.high - b.low) / max(b.close, 1e-9)
                r = rets[j]
                br = abs(btc_ret.get(b.ts_avail, 0.0))
                seq.append([r, abs(r), hl, yzs[j], 1.0 if r < 0 else 0.0, br])
            fut = rets[i + 1 : i + 1 + horizon]
            m_f = sum(fut) / horizon
            rv = math.sqrt(sum((r - m_f) ** 2 for r in fut) / max(1, horizon - 1))
            dts_out.append(bars[i].ts_avail)
            syms_out.append(sym)
            x_list.append(seq)
            y_list.append(math.log(max(rv, 1e-4)))
            yz_list.append(yzs[i])

    return dts_out, syms_out, np.asarray(x_list, dtype=np.float64), np.asarray(y_list, dtype=np.float64), np.asarray(yz_list, dtype=np.float64)


def _run_prototype_1_gru_vol(
    panel_13: dict[str, list[BarPoint]],
    sigs_13: dict,
    eval_dates: list[datetime],
    base_13: dict,
) -> dict:
    """Expanding purged walk-forward GRU-Vol (retrained yearly) injected into BASE_13_S1_S5 ADMM."""
    dts, syms, x_all, y_all, yz_all = _build_daily_vol_dataset(panel_13, BASE_13_SYMBOLS)
    fold_bounds = [
        (datetime(2022, 6, 1, tzinfo=UTC), datetime(2023, 6, 1, tzinfo=UTC)),
        (datetime(2023, 6, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC)),
        (datetime(2024, 6, 1, tzinfo=UTC), datetime(2025, 11, 24, tzinfo=UTC)),
        (datetime(2025, 11, 24, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    ]

    pred_vol_map: dict[tuple[datetime, str], float] = {}
    oos_true, oos_gru, oos_yz = [], [], []
    purge_delta = timedelta(days=21)

    for test_start, test_end in fold_bounds:
        train_cutoff = test_start - purge_delta
        tr_idx = [k for k, dt in enumerate(dts) if dt < train_cutoff]
        te_idx = [k for k, dt in enumerate(dts) if test_start <= dt < test_end]
        if len(tr_idx) < 200 or not te_idx:
            continue
        model = EnsembleGRU(input_dim=6, hidden_dim=12, task="regression", seeds=(42, 101, 202))
        model.fit(x_all[tr_idx], y_all[tr_idx], epochs=22, batch_size=128, lr=5e-3, l2_reg=3e-3)
        log_preds = model.predict(x_all[te_idx])
        for k_pos, raw_k in enumerate(te_idx):
            pv = float(np.clip(np.exp(log_preds[k_pos]), 0.005, 0.25))
            pred_vol_map[(dts[raw_k], syms[raw_k])] = pv
            oos_true.append(float(np.exp(y_all[raw_k])))
            oos_gru.append(pv)
            oos_yz.append(float(yz_all[raw_k]))

    # Vol forecast accuracy vs static Yang-Zhang
    t_arr, g_arr, y_arr = np.asarray(oos_true), np.asarray(oos_gru), np.asarray(oos_yz)
    rmse_gru = float(np.sqrt(np.mean((g_arr - t_arr) ** 2)))
    rmse_yz = float(np.sqrt(np.mean((y_arr - t_arr) ** 2)))
    ss_tot = float(np.sum((t_arr - np.mean(t_arr)) ** 2))
    r2_gru = 1.0 - float(np.sum((g_arr - t_arr) ** 2)) / max(ss_tot, 1e-12)
    r2_yz = 1.0 - float(np.sum((y_arr - t_arr) ** 2)) / max(ss_tot, 1e-12)

    # Replay BASE_13_S1_S5 with GRU-Vol blended into ADMM covariance diagonal & mu vol scaling
    by_start = {s: {b.ts_start: b for b in panel_13.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_13.get(s, [])} for s in BASE_13_SYMBOLS}
    dated_rets = {}
    for s in BASE_13_SYMBOLS:
        bars = panel_13[s]
        dated_rets[s] = (
            [bars[i].ts_avail for i in range(1, len(bars)) if bars[i - 1].close > 0],
            [(bars[i].close - bars[i - 1].close) / bars[i - 1].close for i in range(1, len(bars)) if bars[i - 1].close > 0],
        )

    def _run_vol_arm(use_dynamic_buffer: bool) -> dict:
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
                # Scale covariance by GRU predicted vol ratio while preserving shrunk correlation structure
                gru_vols = []
                for i, sym in enumerate(active):
                    gv = pred_vol_map.get((t_avail, sym), day_sigs[sym].yang_zhang_vol)
                    gru_vols.append(gv)
                    old_v = math.sqrt(max(cov_d[i][i], 1e-8))
                    scale = max(0.5, min(2.0, gv / old_v))
                    for j in range(len(active)):
                        cov_d[i][j] *= scale
                        cov_d[j][i] *= scale
                cov_h = tuple(tuple(v * 20.0 for v in row) for row in cov_d)
                mu_gross = []
                for sym, gv in zip(active, gru_vols, strict=True):
                    sig = day_sigs[sym]
                    parts = [v for v in (sig.s1_trend, sig.s5_defensive_gold) if v is not None]
                    raw = sum(parts) / len(parts) if parts else 0.0
                    mu_gross.append(forecast_to_expected_return_bps(raw * 20.0, ic_prior=0.08, horizon_vol_bps=gv * sqrt_h * 10000.0) / 10000.0)
                avg_pred_vol = sum(gru_vols) / len(gru_vols)
                cash_buf = min(0.35, max(0.05, (avg_pred_vol - 0.035) * 6.0 + 0.05)) if use_dynamic_buffer else 0.05
                prob = OptimizationProblem(
                    symbols=active,
                    expected_returns=tuple(mu_gross),
                    current_weights=cur_w,
                    covariance=cov_h,
                    l1_fee_costs=(0.0013,) * len(active),
                    l2_impact_costs=(0.0020,) * len(active),
                    risk_aversion=2.0,
                    max_weight=0.30,
                    cash_buffer=cash_buf,
                )
                solved = solve_convex_portfolio(prob).weights
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

    arm_vol = _run_vol_arm(use_dynamic_buffer=False)
    arm_vol_buf = _run_vol_arm(use_dynamic_buffer=True)
    base_rets = _daily_returns_map(base_13["nav_by_date"])

    return {
        "oos_samples": len(oos_true),
        "rmse_gru_vol": round(rmse_gru, 5),
        "rmse_yang_zhang": round(rmse_yz, 5),
        "r2_gru_vol": round(r2_gru, 4),
        "r2_yang_zhang": round(r2_yz, 4),
        "baseline_13": {"full": base_13["metrics_full"], "stress": base_13["metrics_stress"], "fees_usdt": base_13["total_fees_usdt"]},
        "gru_vol_admm": {
            "full": arm_vol["full"],
            "stress": arm_vol["stress"],
            "fees_usdt": arm_vol["fees_usdt"],
            "uplift_vs_base": paired_baseline_uplift(_daily_returns_map(arm_vol["nav_by_date"]), base_rets, simulations=499, seed=42),
        },
        "gru_vol_admm_dynamic_cash": {
            "full": arm_vol_buf["full"],
            "stress": arm_vol_buf["stress"],
            "fees_usdt": arm_vol_buf["fees_usdt"],
            "uplift_vs_base": paired_baseline_uplift(_daily_returns_map(arm_vol_buf["nav_by_date"]), base_rets, simulations=499, seed=42),
        },
    }


# ── Prototype 2: GRU-Ignition (36-bar 2h pre-breakout sequence scorer & dynamic 0.5x/1.0x/1.5x sizer) ─

def _extract_2h_breakout_sequences(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth: dict[str, float],
    *,
    seq_len: int = 36,
    train_z: float = 2.0,
    train_vol: float = 1.8,
) -> tuple[list[datetime], list[str], np.ndarray, np.ndarray]:
    """Extract 36-bar (3-day) 2h pre-breakout sequences and forward 24h binary winner labels."""
    btc_map = {b.ts_avail: b for b in panel_2h.get("BTCUSDT", [])}
    btc_ts = sorted(btc_map)
    btc_ret = {}
    for i in range(1, len(btc_ts)):
        c0, c1 = btc_map[btc_ts[i - 1]].close, btc_map[btc_ts[i]].close
        if c0 > 0:
            btc_ret[btc_ts[i]] = (c1 - c0) / c0

    dts, syms, xs, ys = [], [], [], []
    for sym in symbols:
        bars = panel_2h.get(sym, [])
        if len(bars) < 100:
            continue
        rets = [0.0] + [
            (bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0
            for i in range(1, len(bars))
        ]
        vols = [b.volume for b in bars]
        highs = [b.high for b in bars]

        for i in range(max(72, seq_len), len(bars) - 13):
            b = bars[i]
            if not b.entry_eligible or not bars[i + 1].entry_eligible or bars[i + 1].open <= 0:
                continue
            pr = rets[i - 36 : i]
            pv = vols[i - 36 : i]
            ph = highs[i - 72 : i]
            mr = sum(pr) / len(pr)
            sr = math.sqrt(sum((r - mr) ** 2 for r in pr) / max(1, len(pr) - 1))
            mv = median(pv)
            z = (rets[i] - mr) / max(sr, 1e-4)
            if z < train_z or mv <= 0 or b.volume < train_vol * mv or b.close <= max(ph):
                continue
            seq = []
            for j in range(i - seq_len + 1, i + 1):
                bj = bars[j]
                rj = rets[j]
                hl = (bj.high - bj.low) / max(bj.close, 1e-9)
                vr = math.log1p(bj.volume / max(mv, 1e-9))
                rel_btc = rj - btc_ret.get(bj.ts_avail, 0.0)
                br_d = daily_breadth.get(bj.ts_avail.date().isoformat(), 0.5)
                seq.append([rj / max(sr, 1e-4), hl, vr, rel_btc, br_d, 1.0 if bj.close > bj.open else -1.0])
            # Label: net 24h (12-bar) forward return > 32 bps round-trip
            ret_24h = (bars[i + 13].open - bars[i + 1].open) / bars[i + 1].open
            dts.append(b.ts_avail)
            syms.append(sym)
            xs.append(seq)
            ys.append(1.0 if ret_24h > 0.0032 else 0.0)
    return dts, syms, np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)


def _simulate_gru_sized_ignition(
    panel_2h: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    daily_breadth: dict[str, float],
    prob_map: dict[tuple[datetime, str], float],
    *,
    label: str,
    leg_cost: float = 0.0016,
    base_prob: float = 0.45,
) -> dict:
    """Run IGN18_2H where each breakout's leverage is dynamically sized by OOS GRU probability (0.5x / 1.0x / 1.5x)."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    vol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    high_hist: dict[str, list[float]] = {s: [] for s in symbols}
    low_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}

    equity = 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    entries, wins, closed, liqs = 0, 0, 0, 0
    hold_h, total_borrow, total_fees = 0.0, 0.0, 0.0
    borrow_bar = 0.00015 * 0.5

    for ts in all_ts:
        cands = []
        for sym in symbols:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_close[sym]) / prev_close[sym]) if (sym in prev_close and prev_close[sym] > 0) else 0.0
            if cur.entry_eligible and nxt and nxt.entry_eligible and nxt.open > 0 and sym not in active:
                hit = _breakdown_or_breakout_z(
                    cur, r, high_hist[sym][-72:], low_hist[sym][-72:], ret_hist[sym][-36:], vol_hist[sym][-36:],
                    side="LONG", breakout_bars=72, vol_lookback=36, z_threshold=3.0, vol_mult=2.5,
                )
                if hit is not None:
                    cands.append((hit[0], sym, hit[1]))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append(r)
            prev_close[sym] = cur.close
            vol_hist[sym].append(cur.volume)
            high_hist[sym].append(cur.high)
            low_hist[sym].append(cur.low)

        for sym in list(active):
            pos = active[sym]
            is_c, is_l, pnl, brw, fee = _check_margin_exit(
                pos, by_avail[sym].get(ts), by_start[sym].get(ts),
                side="LONG", leverage=pos["lev"], max_hold_bars=24, trail_stop_mult=2.5,
                hard_stop_pct=0.04, leg_cost=leg_cost, borrow_per_bar=borrow_bar,
            )
            equity -= brw
            total_borrow += brw
            total_fees += fee
            if is_c:
                equity = max(0.0, equity + pnl)
                closed += 1
                hold_h += pos["age"] * 2.0
                if is_l:
                    liqs += 1
                elif pnl - pos["entry_fee"] > 0:
                    wins += 1
                del active[sym]

        day_br = daily_breadth.get(ts.date().isoformat(), 0.0)
        if equity > 100.0 and day_br >= 0.45 and cands and len(active) < 3:
            cands.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in cands:
                if len(active) >= 3:
                    break
                nxt = by_start[sym].get(ts)
                if not nxt or nxt.open <= 0:
                    continue
                p_win = prob_map.get((ts, sym), base_prob)
                if p_win >= base_prob + 0.05:
                    lev, col_f = 1.5, 0.30
                elif p_win >= base_prob - 0.05:
                    lev, col_f = 1.0, 0.30
                else:
                    lev, col_f = 1.0, 0.15
                free_col = max(0.0, equity - sum(p["collateral"] for p in active.values()))
                col = min(equity * col_f, free_col)
                if col < 25.0:
                    continue
                notional = col * lev
                ef = notional * leg_cost
                equity = max(0.0, equity - ef)
                total_fees += ef
                liq_px = nxt.open * max(0.0, 1.0 - (0.85 / lev)) if lev > 1.0 else 0.0
                active[sym] = {
                    "collateral": col, "notional": notional, "qty": notional / nxt.open,
                    "entry_px": nxt.open, "entry_fee": ef, "extreme": nxt.open,
                    "b_vol": b_vol, "liq_price": liq_px, "age": 0, "lev": lev,
                }
                entries += 1

        unreal = sum(
            max(-pos["collateral"], pos["qty"] * (by_avail[s][ts].close - pos["entry_px"]))
            for s, pos in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        nav_by_date[ts.date().isoformat()] = max(0.0, equity + unreal)

    res = _summarize_levered_nav(
        label, "LONG", 1.25, len(symbols), 0, leg_cost, nav_by_date, "2025-11-24",
        entries, wins, closed, liqs, hold_h, total_borrow, total_fees,
    )
    return asdict(res)


def _run_prototype_2_gru_ignition(
    panel_2h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
) -> dict:
    """Purged walk-forward GRU-Ignition scoring 36-bar 2h pre-breakout shapes."""
    dts, syms, xs, ys = _extract_2h_breakout_sequences(panel_2h, IGNITION_18_CRYPTO, daily_breadth)
    folds = [
        (datetime(2024, 9, 1, tzinfo=UTC), datetime(2025, 4, 1, tzinfo=UTC)),
        (datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 11, 24, tzinfo=UTC)),
        (datetime(2025, 11, 24, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    ]
    prob_map: dict[tuple[datetime, str], float] = {}
    oos_y: list[int] = []
    oos_p: list[float] = []
    purge = timedelta(hours=48)

    for te_start, te_end in folds:
        tr_idx = [k for k, dt in enumerate(dts) if dt < te_start - purge]
        te_idx = [k for k, dt in enumerate(dts) if te_start <= dt < te_end]
        if len(tr_idx) < 80 or not te_idx:
            continue
        model = EnsembleGRU(input_dim=6, hidden_dim=12, task="binary", seeds=(42, 101, 202))
        model.fit(xs[tr_idx], ys[tr_idx], epochs=24, batch_size=64, lr=4e-3, l2_reg=5e-3)
        preds = model.predict(xs[te_idx])
        for kp, rk in enumerate(te_idx):
            p = float(preds[kp])
            prob_map[(dts[rk], syms[rk])] = p
            oos_y.append(int(ys[rk]))
            oos_p.append(p)

    auc = _roc_auc(oos_y, oos_p)
    base_rate = sum(oos_y) / max(1, len(oos_y))
    order = sorted(range(len(oos_p)), key=lambda i: oos_p[i])
    cut = max(1, len(order) // 3)
    bot_wr = sum(oos_y[i] for i in order[:cut]) / cut * 100.0 if order else 0.0
    top_wr = sum(oos_y[i] for i in order[-cut:]) / cut * 100.0 if order else 0.0

    plain_1x_16, _ = simulate_levered_ignition(panel_2h, IGNITION_18_CRYPTO, daily_breadth, label="PLAIN_IGN18_1.0X_NBX16", side="LONG", leverage=1.0, leg_cost=0.0016)
    plain_15x_16, _ = simulate_levered_ignition(panel_2h, IGNITION_18_CRYPTO, daily_breadth, label="PLAIN_IGN18_1.5X_NBX16", side="LONG", leverage=1.5, leg_cost=0.0016)
    gru_16 = _simulate_gru_sized_ignition(panel_2h, IGNITION_18_CRYPTO, daily_breadth, prob_map, label="GRU_SIZED_IGN18_NBX16", leg_cost=0.0016, base_prob=base_rate)
    gru_25 = _simulate_gru_sized_ignition(panel_2h, IGNITION_18_CRYPTO, daily_breadth, prob_map, label="GRU_SIZED_IGN18_WLX25", leg_cost=0.0025, base_prob=base_rate)

    return {
        "total_breakout_episodes": len(dts),
        "oos_scored_episodes": len(oos_y),
        "oos_roc_auc": auc,
        "oos_base_win_rate_pct": round(base_rate * 100.0, 1),
        "bottom_tercile_win_rate_pct": round(bot_wr, 1),
        "top_tercile_win_rate_pct": round(top_wr, 1),
        "plain_1x_nbx16": asdict(plain_1x_16),
        "plain_15x_nbx16": asdict(plain_15x_16),
        "gru_dynamic_nbx16": gru_16,
        "gru_dynamic_wlx25": gru_25,
    }


# ── Prototype 3: GRU-Exec (Live Wallex book_top 5-min adverse-drift predictor & execution router) ────

def _run_prototype_3_gru_exec(con) -> dict:
    """Train pooled GRU on real Wallex book_top ticks (strict chronological 60/40 split + 10m purge)."""
    exec_syms = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XAUTUSDT", "PEPEUSDT")
    latest_row = con.execute("SELECT MAX(ts_avail) FROM book_top").fetchone()
    latest_ts = datetime.fromisoformat(latest_row[0].replace("Z", "+00:00")) if latest_row and latest_row[0] else datetime.now(UTC)
    since_iso = (latest_ts - timedelta(hours=72)).isoformat().replace("+00:00", "Z")
    sched = wallex_l1_fee_schedule("USDT")

    seq_len = 20
    tr_x, tr_y = [], []
    te_x, te_y = [], []
    sym_books: dict[str, tuple[list, list, int]] = {}

    for sym in exec_syms:
        books, trades = load_book_and_trades(con, sym, since_iso, max_books=4000, max_trades=6000)
        valid = [b for b in books if b.bid and b.ask and b.bid > 0 and b.ask > 0]
        if len(valid) < 200:
            continue
        split_i = int(len(valid) * 0.60)
        sym_books[sym] = (valid, trades, split_i)
        mids = [float((b.bid + b.ask) / Decimal(2)) for b in valid]
        eps = [b.ts_avail.timestamp() for b in valid]

        # Build tick sequences sampled every 4 ticks to keep training crisp & fast
        for i in range(seq_len + 1, len(valid) - 20, 4):
            target_ep = eps[i] + 300.0
            fut_i = bisect_right(eps, target_ep)
            if fut_i >= len(valid):
                continue
            drift_bps = (mids[fut_i] - mids[i]) / mids[i] * 10000.0
            seq = []
            for j in range(i - seq_len + 1, i + 1):
                bj = valid[j]
                mr = (mids[j] - mids[j - 1]) / mids[j - 1] * 10000.0
                sp = float(bj.spread_bps or Decimal(0))
                bq = float(bj.bid_qty or Decimal(0))
                aq = float(bj.ask_qty or Decimal(0))
                imb = (bq - aq) / max(bq + aq, 1e-9)
                dt_s = min(60.0, max(0.0, eps[j] - eps[j - 1]))
                seq.append([mr, sp, math.log1p(bq), math.log1p(aq), imb, dt_s / 10.0])
            if i < split_i - 25:
                tr_x.append(seq)
                tr_y.append(1.0 if drift_bps > 0.0 else 0.0)
            elif i >= split_i + 25:
                te_x.append(seq)
                te_y.append(1.0 if drift_bps > 0.0 else 0.0)

    if len(tr_x) < 100 or len(te_x) < 50:
        return {"status": "INSUFFICIENT_TICKS"}

    model = EnsembleGRU(input_dim=6, hidden_dim=16, task="binary", seeds=(42, 101, 202))
    model.fit(np.asarray(tr_x), np.asarray(tr_y), epochs=20, batch_size=128, lr=5e-3, l2_reg=2e-3)
    oos_probs = model.predict(np.asarray(te_x))
    oos_auc = _roc_auc([int(y) for y in te_y], [float(p) for p in oos_probs])

    # Evaluate GRU-routed execution vs IMMEDIATE vs STATIC_P35 on strictly OOS ticks (BUY & SELL)
    policy_rows = []
    for sym, (valid, trades, split_i) in sym_books.items():
        mids = [float((b.bid + b.ask) / Decimal(2)) for b in valid]
        eps = [b.ts_avail.timestamp() for b in valid]
        start_i = max(split_i + 25, seq_len + 1)
        end_i = len(valid) - 15
        step = max(1, (end_i - start_i) // 10)
        sample_idxs = list(range(start_i, end_i, step))[:10]
        if not sample_idxs:
            continue

        for side in ("BUY", "SELL"):
            imm_c, p35_c, gru_c = [], [], []
            for idx in sample_idxs:
                top = valid[idx]
                mid = (top.bid + top.ask) / Decimal(2)
                qty = (Decimal("250") / mid).quantize(Decimal("0.000001"))
                p35 = causal_spread_quantile_bps(valid, top.ts_avail)
                comp = compare_execution_timing_arms(
                    sym, side, qty, top.ts_avail, 300.0, valid, trades, sched,
                    p35_spread_bps=p35, duplicate_print_mode="adversarial_lower_bound", enforce_displayed_size=True,
                )
                seq = []
                for j in range(idx - seq_len + 1, idx + 1):
                    bj = valid[j]
                    mr = (mids[j] - mids[j - 1]) / mids[j - 1] * 10000.0
                    sp = float(bj.spread_bps or Decimal(0))
                    bq, aq = float(bj.bid_qty or Decimal(0)), float(bj.ask_qty or Decimal(0))
                    imb = (bq - aq) / max(bq + aq, 1e-9)
                    dt_s = min(60.0, max(0.0, eps[j] - eps[j - 1]))
                    seq.append([mr, sp, math.log1p(bq), math.log1p(aq), imb, dt_s / 10.0])
                p_up = float(model.predict(np.asarray([seq]))[0])
                # Cross immediately if GRU predicts adverse drift against our side; else rest opportunistically.
                adverse = (side == "BUY" and p_up > 0.55) or (side == "SELL" and p_up < 0.45)
                imm_v = float(comp.immediate.total_cost_bps)
                opp_v = float(comp.opportunistic_recovery.total_cost_bps)
                imm_c.append(imm_v)
                p35_c.append(opp_v)
                gru_c.append(imm_v if adverse else opp_v)

            n = len(sample_idxs)
            policy_rows.append({
                "symbol": sym,
                "side": side,
                "samples": n,
                "immediate_bps": round(sum(imm_c) / n, 2),
                "p35_passive_bps": round(sum(p35_c) / n, 2),
                "gru_routed_bps": round(sum(gru_c) / n, 2),
                "gru_vs_imm_saving_bps": round((sum(imm_c) - sum(gru_c)) / n, 2),
                "gru_vs_p35_saving_bps": round((sum(p35_c) - sum(gru_c)) / n, 2),
            })

    avg_imm = sum(r["immediate_bps"] for r in policy_rows) / max(1, len(policy_rows))
    avg_p35 = sum(r["p35_passive_bps"] for r in policy_rows) / max(1, len(policy_rows))
    avg_gru = sum(r["gru_routed_bps"] for r in policy_rows) / max(1, len(policy_rows))
    return {
        "train_ticks": len(tr_x),
        "oos_ticks": len(te_x),
        "oos_5m_direction_auc": oos_auc,
        "avg_immediate_bps": round(avg_imm, 2),
        "avg_p35_passive_bps": round(avg_p35, 2),
        "avg_gru_routed_bps": round(avg_gru, 2),
        "avg_gru_saving_vs_imm_bps": round(avg_imm - avg_gru, 2),
        "avg_gru_saving_vs_p35_bps": round(avg_p35 - avg_gru, 2),
        "by_symbol_side": policy_rows,
    }


def run_gru_prototypes_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Run all 3 strictly causal walk-forward GRU prototypes read-only against data/live/market.db."""
    con = open_readonly_market_db(db_path)
    try:
        panel_13 = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_18_1h = {s: load_keyed_candles(con, s, "1h", limit=25000) for s in IGNITION_18_CRYPTO}
        proto3 = _run_prototype_3_gru_exec(con)
    finally:
        con.close()

    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_breadth = {}
    for ts, d in sigs_13.items():
        first = next(iter(d.values()), None)
        if first and first.crypto_breadth is not None:
            daily_breadth[ts.date().isoformat()] = first.crypto_breadth

    base_13 = _run_self_financing_arm("DROP_S2", panel_13, sigs_13, eval_dates)
    proto1 = _run_prototype_1_gru_vol(panel_13, sigs_13, eval_dates, base_13)

    panel_18_2h = {s: resample_hourly_to_bucket(panel_18_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    proto2 = _run_prototype_2_gru_ignition(panel_18_2h, daily_breadth)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "prototype_1_gru_vol": proto1,
        "prototype_2_gru_ignition": proto2,
        "prototype_3_gru_exec": proto3,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, summary)
    return summary


def _write_markdown(report_path: Path, summary: dict) -> None:
    p1, p2, p3 = summary["prototype_1_gru_vol"], summary["prototype_2_gru_ignition"], summary["prototype_3_gru_exec"]
    lines = [
        "# GRU Prototypes Empirical Evaluation (Purged Walk-Forward, Zero Lookahead)",
        "",
        f"- **Generated:** `{summary['generated_at']}`",
        "- **Engine:** Pure-NumPy 3-seed `EnsembleGRU` (`hidden=12–16`), exact BPTT + Adam + L2 + strict chronological purged walk-forward.",
        "- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`",
        "",
        "## 1. Prototype 1 — `GRU-Vol` (20d Volatility Forecaster Fed Into ADMM on `BASE_13_S1_S5`)",
        "",
        f"- **Out-of-Sample Vol Forecast (`N={p1['oos_samples']}`):** GRU RMSE = **`{p1['rmse_gru_vol']:.5f}`** (`R² = {p1['r2_gru_vol']:+.4f}`) vs Static Yang–Zhang RMSE = **`{p1['rmse_yang_zhang']:.5f}`** (`R² = {p1['r2_yang_zhang']:+.4f}`)",
        "",
        "| Arm (`1,638` Days) | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Fees ($) | Paired Uplift vs Base (bps/day, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    b1 = p1["baseline_13"]
    lines.append(
        f"| `BASE_13_S1_S5_YANG_ZHANG` | `${b1['full']['ending_nav']:.2f}` | `{b1['full']['ret_pct']:+.2f}%` | `{b1['full']['ann_sharpe']:.3f}` | `{b1['full']['max_dd_pct']:.2f}%` | `{b1['stress']['ret_pct']:+.2f}%` | `${b1['fees_usdt']:.2f}` | Baseline |"
    )
    for key, label in (("gru_vol_admm", "GRU_VOL_ADMM"), ("gru_vol_admm_dynamic_cash", "GRU_VOL_ADMM_DYNAMIC_CASH")):
        a = p1[key]
        up = a["uplift_vs_base"]
        ci = up.get("ci_95", [0.0, 0.0])
        lines.append(
            f"| `{label}` | `${a['full']['ending_nav']:.2f}` | `{a['full']['ret_pct']:+.2f}%` | `{a['full']['ann_sharpe']:.3f}` | `{a['full']['max_dd_pct']:.2f}%` | `{a['stress']['ret_pct']:+.2f}%` | `${a['fees_usdt']:.2f}` | `{up.get('mean_uplift', 0)*10000:+.2f}` `[{ci[0]*10000:+.2f}, {ci[1]*10000:+.2f}]` (`{up.get('status')}`) |"
        )

    lines.extend([
        "",
        "## 2. Prototype 2 — `GRU-Ignition` (36-Bar `2h` Pre-Breakout Scorer & Dynamic `0.5x/1.0x/1.5x` Sizer)",
        "",
        f"- **Out-of-Sample Breakout Classification (`N={p2['oos_scored_episodes']}` of `{p2['total_breakout_episodes']}` episodes):** ROC AUC = **`{p2['oos_roc_auc']:.4f}`**, Bottom-Tercile Win Rate = **`{p2['bottom_tercile_win_rate_pct']:.1f}%`** vs Top-Tercile Win Rate = **`{p2['top_tercile_win_rate_pct']:.1f}%`** (Base = `{p2['oos_base_win_rate_pct']:.1f}%`)",
        "",
        "| Arm (`18` Markets, `2h` Ignition) | Cost (bps) | Ending NAV | Ret % | Bear Stress % | Ann. Sharpe | MaxDD % | Entries | Win % | Liq | Borrow ($) | Fees ($) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for key in ("plain_1x_nbx16", "plain_15x_nbx16", "gru_dynamic_nbx16", "gru_dynamic_wlx25"):
        r = p2[key]
        lines.append(
            f"| `{r['label']}` | `{r['cost_bps']:.1f}` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['entries']}` | `{r['win_rate_pct']:.1f}%` | `{r['liquidations']}` | `${r['total_borrow_usdt']:.2f}` | `${r['total_fees_usdt']:.2f}` |"
        )

    lines.extend([
        "",
        "## 3. Prototype 3 — `GRU-Exec` (Live Wallex `book_top` 5-Min Adverse-Drift Predictor & Execution Router)",
        "",
        f"- **OOS Tick Classification (`Train={p3.get('train_ticks', 0)}`, `OOS={p3.get('oos_ticks', 0)}`):** 5-Min Direction ROC AUC = **`{p3.get('oos_5m_direction_auc', 0.5):.4f}`**",
        f"- **Average OOS Execution Cost (12 Symbol×Side Pairs):** Immediate Taker = **`{p3.get('avg_immediate_bps', 0):.2f} bps`**, Static `p35` Passive = **`{p3.get('avg_p35_passive_bps', 0):.2f} bps`**, **`GRU-Exec` Routed = `{p3.get('avg_gru_routed_bps', 0):.2f} bps`** (Saving **`{p3.get('avg_gru_saving_vs_imm_bps', 0):+.2f} bps`** vs Immediate, **`{p3.get('avg_gru_saving_vs_p35_bps', 0):+.2f} bps`** vs Static `p35`)",
        "",
        "| Symbol | Side | N | Immediate (bps) | Static p35 (bps) | GRU-Routed (bps) | GRU vs Imm (bps) | GRU vs p35 (bps) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in p3.get("by_symbol_side", []):
        lines.append(
            f"| `{r['symbol']}` | `{r['side']}` | `{r['samples']}` | `{r['immediate_bps']:.2f}` | `{r['p35_passive_bps']:.2f}` | `{r['gru_routed_bps']:.2f}` | `{r['gru_vs_imm_saving_bps']:+.2f}` | `{r['gru_vs_p35_saving_bps']:+.2f}` |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
