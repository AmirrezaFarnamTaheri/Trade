"""Comprehensive 6-Finding Multi-Horizon Adaptive Portfolio & Execution Study (v3.5 / v4).

Tests every structural fix incrementally on the exact same 1,085d (2024-2026) causal ledger
against frozen V2_CHAMPION, plus live book_top audits for Tehran Liquidity Clock & TMN Triangles:
- F1: True Multi-Horizon Lot-Scoped Book (untouched slow Spot + real isolated Margin overlay + zero-borrow internal short)
- F2: Tehran Liquidity-Clock slow rebalance (10:00 UTC vs 00:00 UTC) + OCO passive maker profit targets
- F3: Zero-bucket unified capital pool + causal OnlineICTracker (eliminating static 60/40 & ic_prior=0.08)
- F4: Walk-forward InPositionContinuationModel (bar-by-bar EARLY_SELL + FREE_ROLL_PYRAMID)
- F5: Live Asset/TMN <-> USDTTMN synthetic triangle routing audit & dynamic USDT vs TMN borrow-currency audit
- F6: Moment-scoped Beta-Neutral RV Laggard Hedge on fragile-breadth 2h breakouts
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

import numpy as np

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
from ...domain.in_position_and_execution import (
    InPositionContinuationModel,
    InPositionSnapshot,
    decide_in_position_action,
    evaluate_synthetic_triangle_route,
    select_borrow_currency,
    tehran_execution_cost_bps,
)
from ...domain.instrument_resolver import (
    ResolverConfig,
    build_local_venue_offers,
)
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.multi_horizon_book import (
    MultiHorizonBook,
    OnlineICTracker,
    check_lot_intrabar_exit,
    resolve_safe_ignition_leverage,
    select_rv_laggard_hedge,
)
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from ...domain.venue_leverage_models import simulate_nobitex_margin_ignition
from .admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    extract_daily_breadth,
)
from .champion_v2_verification import _merge_twin_schedules, _run_v2_joint_shared_ledger
from .ensemble_study import STRESS_REPLAY_START, _daily_returns_map, _portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .ignition_upgrade_ablation_study import (
    _extract_11feat_coiled_spring_dataset,
    _walkforward_gru_scores,
)

ADAPTIVE_UNIVERSE: tuple[str, ...] = tuple(
    dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO + tuple(DEFENSIVE_METALS_CAPS))
)
NOBITEX_IDLE_USDT_APR = 0.0264
TRIANGLE_BASES: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP", "XAUT", "PEPE")


@dataclass(frozen=True)
class AdaptiveArmConfig:
    label: str
    max_leverage: float = 5.0
    use_online_ic: bool = False
    slow_exec_utc_hour: int = 0
    use_passive_slow: bool = False
    use_oco_maker_tp: bool = False
    use_ml_in_position: bool = False
    use_rv_hedge: bool = False
    idle_pool_apr: float = NOBITEX_IDLE_USDT_APR


def _extract_in_position_training_rows(
    panel_2h: dict[str, list[BarPoint]],
    gru_scores: dict[tuple[datetime, str], float],
) -> tuple[list[datetime], np.ndarray, np.ndarray]:
    """Build strictly causal bar-by-bar open-position snapshots & remaining 6h return targets."""
    btc_bars = panel_2h.get("BTCUSDT", [])
    btc_ret = {
        btc_bars[i].ts_avail: (btc_bars[i].close - btc_bars[i - 1].close) / btc_bars[i - 1].close
        for i in range(1, len(btc_bars))
        if btc_bars[i - 1].close > 0
    }
    dts: list[datetime] = []
    xs: list[list[float]] = []
    ys: list[float] = []

    for sym, bars in panel_2h.items():
        if sym not in IGNITION_18_CRYPTO or len(bars) < 60:
            continue
        rets = [0.0] + [
            (bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0
            for i in range(1, len(bars))
        ]
        vols = [b.volume for b in bars]
        for i in range(40, len(bars) - 16):
            g_sc = gru_scores.get((bars[i].ts_avail, sym))
            if g_sc is None or g_sc <= 0.001:
                continue
            entry_px = bars[i + 1].open
            if entry_px <= 0:
                continue
            pr = rets[i - 36 : i]
            b_vol = max(0.005, math.sqrt(sum((r - sum(pr) / 36.0) ** 2 for r in pr) / 35.0))
            mv = max(1e-9, median(vols[i - 36 : i]))
            peak = entry_px
            for k in range(1, 10):
                idx = i + k
                if idx + 3 >= len(bars):
                    break
                cur = bars[idx]
                peak = max(peak, cur.close)
                upnl = (cur.close - entry_px) / entry_px
                mfe = (peak - entry_px) / entry_px
                gb = max(0.0, (peak - cur.close) / max(peak, 1e-9))
                snap = InPositionSnapshot(
                    age_bars=k,
                    unrealized_ret=upnl,
                    peak_mfe=mfe,
                    giveback_from_peak=gb,
                    last_bar_ret_z=rets[idx] / b_vol,
                    volume_follow_ratio=cur.volume / mv,
                    rel_btc_ret=rets[idx] - btc_ret.get(cur.ts_avail, 0.0),
                    entry_gru_score=g_sc,
                )
                fwd_px = bars[idx + 3].open
                cur_open = bars[idx + 1].open
                if fwd_px > 0 and cur_open > 0:
                    dts.append(cur.ts_avail)
                    xs.append(snap.to_vector())
                    ys.append((fwd_px - cur_open) / cur_open)

    if not xs:
        return [], np.zeros((0, 8)), np.zeros((0,))
    return dts, np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)


def _train_walkforward_continuation_models(
    dts: list[datetime],
    x_mat: np.ndarray,
    y_vec: np.ndarray,
) -> list[tuple[datetime, datetime, InPositionContinuationModel]]:
    """Train strictly purged walk-forward continuation models matching the 3 OOS folds."""
    folds = [
        (datetime(2024, 9, 1, tzinfo=UTC), datetime(2025, 4, 1, tzinfo=UTC)),
        (datetime(2025, 4, 1, tzinfo=UTC), datetime(2025, 11, 24, tzinfo=UTC)),
        (datetime(2025, 11, 24, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),
    ]
    purge = timedelta(hours=48)
    out: list[tuple[datetime, datetime, InPositionContinuationModel]] = []
    for te_s, te_e in folds:
        tr = [k for k, dt in enumerate(dts) if dt < te_s - purge]
        m = InPositionContinuationModel(l2_alpha=35.0)
        if len(tr) >= 40:
            m.fit(x_mat[tr], y_vec[tr])
        out.append((te_s, te_e, m))
    return out


def _active_cont_model(
    ts: datetime,
    models: list[tuple[datetime, datetime, InPositionContinuationModel]],
) -> InPositionContinuationModel | None:
    for s, e, m in models:
        if s <= ts < e:
            return m
    return None


def _compute_2h_bar_stats(panel_2h: dict[str, list[BarPoint]]) -> tuple[
    dict[str, dict[datetime, float]],
    dict[str, dict[datetime, float]],
    dict[str, dict[datetime, float]],
    dict[str, dict[datetime, float]],
]:
    """Precompute causal per-bar volatility, 24h return, volume ratio, and bar return per symbol."""
    bvol_map: dict[str, dict[datetime, float]] = {}
    ret24_map: dict[str, dict[datetime, float]] = {}
    vrat_map: dict[str, dict[datetime, float]] = {}
    bret_map: dict[str, dict[datetime, float]] = {}
    for sym, bars in panel_2h.items():
        bv, r24, vr, br = {}, {}, {}, {}
        rets = [0.0] + [
            (bars[i].close - bars[i - 1].close) / bars[i - 1].close if bars[i - 1].close > 0 else 0.0
            for i in range(1, len(bars))
        ]
        vols = [b.volume for b in bars]
        for i, b in enumerate(bars):
            br[b.ts_avail] = rets[i]
            if i >= 12 and bars[i - 12].close > 0:
                r24[b.ts_avail] = (b.close - bars[i - 12].close) / bars[i - 12].close
            if i >= 36:
                pr = rets[i - 36 : i]
                mr = sum(pr) / 36.0
                bv[b.ts_avail] = max(0.006, math.sqrt(sum((r - mr) ** 2 for r in pr) / 35.0))
                mv = median(vols[i - 36 : i])
                vr[b.ts_avail] = (b.volume / mv) if mv > 0 else 1.0
        bvol_map[sym], ret24_map[sym], vrat_map[sym], bret_map[sym] = bv, r24, vr, br
    return bvol_map, ret24_map, vrat_map, bret_map


def _solve_slow_targets_for_day(
    active_slow: tuple[str, ...],
    day_sigs: dict,
    day_acc: dict,
    cur_slow_w: tuple[float, ...],
    cov_h: tuple[tuple[float, ...], ...],
    day_sigs_metals: dict,
    exec_px: dict[str, float],
    ic_val: float,
    fee_bps: float,
) -> dict[str, float]:
    """Solve slow Spot targets using dynamic online IC + defensive metals reserve (zero hard sleeve cap)."""
    sqrt_h = math.sqrt(20.0)
    mu_gross = []
    for sym in active_slow:
        sig = day_sigs[sym]
        s1_v = sig.s1_trend
        if s1_v is not None:
            s1_v = max(-1.0, min(1.0, 0.80 * s1_v + 0.20 * day_acc.get(sym, 0.0)))
        parts = [v for v in (s1_v, sig.s5_defensive_gold) if v is not None]
        raw = sum(parts) / len(parts) if parts else 0.0
        vol_h_bps = sig.yang_zhang_vol * sqrt_h * 10_000.0
        mu_gross.append(forecast_to_expected_return_bps(raw * 20.0, ic_prior=ic_val, horizon_vol_bps=vol_h_bps) / 10_000.0)

    prob = OptimizationProblem(
        symbols=active_slow, expected_returns=tuple(mu_gross), current_weights=cur_slow_w,
        covariance=cov_h, l1_fee_costs=(fee_bps / 10_000.0,) * len(active_slow),
        l2_impact_costs=(0.0020,) * len(active_slow), risk_aversion=2.0,
        max_weight=0.28, cash_buffer=0.20,
        underlying_groups=_build_cluster_groups(active_slow), max_underlying_weight=0.40,
    )
    solved = solve_convex_portfolio(prob).weights
    targets = {s: w for s, w in zip(active_slow, solved, strict=True)}
    day_br = next((s.crypto_breadth for s in day_sigs.values() if s.crypto_breadth is not None), None)
    res_w = compute_defensive_metals_reserve(day_sigs_metals, day_br)
    free_cap = max(0.0, 0.80 - sum(targets.values()))
    for ms, mw in res_w.items():
        if ms in exec_px and mw > 0:
            take = min(max(0.0, mw - targets.get(ms, 0.0)), free_cap)
            targets[ms] = targets.get(ms, 0.0) + take
            free_cap -= take
    return targets


def _manage_fast_lots_bar(
    book: MultiHorizonBook,
    by_avail: dict[str, dict[datetime, BarPoint]],
    exec_px: dict[str, float],
    tradable: set[str],
    ts: datetime,
    bret_map: dict[str, dict[datetime, float]],
    vrat_map: dict[str, dict[datetime, float]],
    cont_model: InPositionContinuationModel | None,
    arm: AdaptiveArmConfig,
    taker_bps: float,
    oco_maker_bps: float,
) -> None:
    """Step every open fast lot (ignition_2h / rv_hedge): intrabar liq/stop/OCO-TP, ML exit, pyramid, trail."""
    btc_r = bret_map.get("BTCUSDT", {}).get(ts, 0.0)
    for key in list(book.lots):
        lot = book.lots[key]
        if lot.thesis_id == "slow_core":
            continue
        lot.age_bars += 1
        bar = by_avail.get(lot.symbol, {}).get(ts)
        if bar is not None:
            evt, px, fee_bps = check_lot_intrabar_exit(
                lot, bar, taker_exit_bps=taker_bps, oco_maker_exit_bps=oco_maker_bps,
                use_oco_maker_tp=arm.use_oco_maker_tp,
            )
            if evt == "LIQ":
                book.liquidations += 1
                del book.lots[key]
                continue
            if evt in {"STOP", "OCO_TP"}:
                book.close_lot(key, px, fee_bps)
                if evt == "STOP":
                    book.stop_outs += 1
                else:
                    book.oco_profit_exits += 1
                continue
            lot.peak_price = max(lot.peak_price, bar.close) if lot.direction > 0 else min(lot.peak_price, bar.close)

        if lot.symbol not in tradable or lot.symbol not in exec_px:
            continue
        px_now = exec_px[lot.symbol]
        # Trailing stop or max-hold timeout
        trail_hit = False
        if bar is not None:
            if lot.direction > 0:
                trail_hit = bar.close < lot.peak_price * (1.0 - 2.6 * lot.entry_bar_vol)
            else:
                trail_hit = bar.close > lot.peak_price * (1.0 + 2.6 * lot.entry_bar_vol)
        max_bars = 18 if lot.pyramided else 12
        if lot.age_bars >= max_bars or trail_hit:
            book.close_lot(key, px_now, taker_bps)
            continue

        # Finding #4: In-Position ML Continuation / Early-Sell / House-Money Pyramid
        if arm.use_ml_in_position and lot.thesis_id == "ignition_2h" and cont_model is not None and bar is not None:
            upnl = (bar.close - lot.entry_price) / max(lot.entry_price, 1e-9)
            mfe = max(0.0, (lot.peak_price - lot.entry_price) / max(lot.entry_price, 1e-9))
            gb = max(0.0, (lot.peak_price - bar.close) / max(lot.peak_price, 1e-9))
            snap = InPositionSnapshot(
                age_bars=lot.age_bars, unrealized_ret=upnl, peak_mfe=mfe, giveback_from_peak=gb,
                last_bar_ret_z=bret_map.get(lot.symbol, {}).get(ts, 0.0) / max(lot.entry_bar_vol, 1e-4),
                volume_follow_ratio=vrat_map.get(lot.symbol, {}).get(ts, 1.0),
                rel_btc_ret=bret_map.get(lot.symbol, {}).get(ts, 0.0) - btc_r,
                entry_gru_score=lot.entry_gru_score,
            )
            pred_rem = cont_model.predict_remaining_return(snap)
            act = decide_in_position_action(pred_rem, snap, already_pyramided=lot.pyramided)
            if act == "EARLY_SELL":
                book.close_lot(key, px_now, taker_bps)
                book.early_ml_exits += 1
            elif act == "FREE_ROLL_PYRAMID":
                book.pyramid_lot_on_house_money(key, px_now, add_fraction=0.45, entry_fee_bps=taker_bps)


def _try_open_ignition_entries(
    book: MultiHorizonBook,
    ts: datetime,
    equity: float,
    dd_pct: float,
    exec_px: dict[str, float],
    tradable: set[str],
    day_sigs_now: dict,
    breadth: float,
    gru_scores: dict[tuple[datetime, str], float],
    recent_gru: list[float],
    bvol_map: dict[str, dict[datetime, float]],
    ret24_map: dict[str, dict[datetime, float]],
    offers_by_sym: dict,
    cfg: ResolverConfig,
    arm: AdaptiveArmConfig,
) -> int:
    """Open isolated 2h ignition Margin lots + optional moment-scoped RV laggard hedge from free cash."""
    active_ign = sum(1 for k in book.lots if k[1] == "ignition_2h")
    if active_ign >= 3 or book.free_cash < 40.0:
        return 0
    r24_now = {s: ret24_map.get(s, {}).get(ts, 0.0) for s in ADAPTIVE_UNIVERSE}
    opened = 0
    for sym in IGNITION_18_CRYPTO:
        if active_ign >= 3 or sym not in tradable or (sym, "ignition_2h") in book.lots:
            continue
        g_sc = gru_scores.get((ts, sym))
        if g_sc is None:
            continue
        rank = (
            sum(1 for x in recent_gru if x <= g_sc) / len(recent_gru)
            if len(recent_gru) >= 25
            else 0.55
        )
        recent_gru.append(g_sc)
        if len(recent_gru) > 120:
            del recent_gru[:-120]
        if g_sc <= 0.002 or rank < 0.45:
            continue
        b_vol = bvol_map.get(sym, {}).get(ts, 0.02)
        stop_bps = max(180.0, min(650.0, 2.5 * b_vol * 10_000.0))
        tp_bps = (3.4 * b_vol * 10_000.0) if arm.use_oco_maker_tp else 0.0
        nbx_long = [o for o in offers_by_sym[sym] if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == 1]
        offer = nbx_long[0] if nbx_long else offers_by_sym[sym][0]
        lev = resolve_safe_ignition_leverage(offer, stop_bps, rank, dd_pct, cfg)
        stop_frac = max(0.015, (stop_bps + 35.0) / 10_000.0)
        tgt_col = min(0.16 * equity, (0.014 * equity / stop_frac) / lev, max(0.0, book.free_cash - 10.0))
        if not book.open_fast_margin_lot(
            symbol=sym, thesis_id="ignition_2h", direction=1, leverage=lev,
            target_collateral=tgt_col, entry_px=exec_px[sym], stop_bps=stop_bps,
            take_profit_bps=tp_bps, offer=offer, ts=ts, entry_bar_vol=b_vol, entry_gru_score=g_sc,
        ):
            continue
        active_ign += 1
        opened += 1
        if arm.use_rv_hedge and breadth < 0.45:
            hed = select_rv_laggard_hedge(sym, day_sigs_now, r24_now, breadth)
            if hed is not None and hed[0] in tradable and hed[0] in exec_px:
                hsym = hed[0]
                nbx_sh = [o for o in offers_by_sym[hsym] if o.venue == "nobitex" and o.instrument_type == "ISOLATED_MARGIN" and o.direction == -1]
                if nbx_sh:
                    h_vol = bvol_map.get(hsym, {}).get(ts, 0.025)
                    h_stop = max(220.0, min(650.0, 2.4 * h_vol * 10_000.0))
                    book.open_fast_margin_lot(
                        symbol=hsym, thesis_id="rv_hedge", direction=-1, leverage=1.5,
                        target_collateral=min(0.5 * tgt_col, 0.08 * equity),
                        entry_px=exec_px[hsym], stop_bps=h_stop, take_profit_bps=0.0,
                        offer=nbx_sh[0], ts=ts, entry_bar_vol=h_vol, entry_gru_score=0.0,
                        allow_internal_short_offset=True,
                    )
    return opened


def _simulate_adaptive_phase(
    panel_2h: dict[str, list[BarPoint]],
    sigs_13: dict,
    accel_13: dict,
    sigs_metals: dict,
    cov_h_by_ts: dict,
    daily_breadth: dict[str, float],
    gru_scores: dict[tuple[datetime, str], float],
    cont_models: list[tuple[datetime, datetime, InPositionContinuationModel]],
    bar_stats: tuple,
    arm: AdaptiveArmConfig,
) -> tuple[dict, dict[str, float]]:
    """Run one phase (0h or 1h) of the unified Multi-Horizon Adaptive Engine."""
    bvol_map, ret24_map, vrat_map, bret_map = bar_stats
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in ADAPTIVE_UNIVERSE}
    all_ts = sorted({t for s in IGNITION_18_CRYPTO for t in by_avail[s]})

    offers_by_sym = {s: build_local_venue_offers(s, idle_pool_apr=arm.idle_pool_apr) for s in ADAPTIVE_UNIVERSE}
    cfg = ResolverConfig(max_venue_leverage=arm.max_leverage, idle_pool_apr=arm.idle_pool_apr)

    book = MultiHorizonBook(free_cash=1000.0)
    ic_slow = OnlineICTracker(prior_ic=0.065, prior_weight=30.0, decay=0.97, ic_floor=0.02, ic_cap=0.11)
    prev_day_forecasts: dict[str, tuple[float, float]] = {}
    pending_slow_targets: dict[str, float] | None = None
    last_px: dict[str, float] = {}
    recent_gru: list[float] = []
    peak_nav = 1000.0
    nav_by_date: dict[str, float] = {}
    slow_fills, ign_entries = 0, 0

    sig_dates = sorted(sigs_13)
    last_sig_applied: datetime | None = None
    sig_ptr = 0

    for ts in all_ts:
        book.accrue_pool_and_borrow(ts, 2.0, idle_pool_apr=arm.idle_pool_apr, eod_borrow_bps=5.0)
        exec_px: dict[str, float] = {}
        tradable: set[str] = set()
        for sym in ADAPTIVE_UNIVERSE:
            nxt, cur = by_start[sym].get(ts), by_avail[sym].get(ts)
            if nxt is not None and nxt.open > 0:
                exec_px[sym] = nxt.open
                last_px[sym] = nxt.open
                if nxt.entry_eligible and cur is not None and cur.entry_eligible:
                    tradable.add(sym)
            elif cur is not None and cur.close > 0:
                exec_px[sym] = cur.close
                last_px[sym] = cur.close
            elif sym in last_px:
                exec_px[sym] = last_px[sym]

        taker_bps = tehran_execution_cost_bps(ts.hour) if arm.slow_exec_utc_hour != 0 else 16.0
        _manage_fast_lots_bar(
            book, by_avail, exec_px, tradable, ts, bret_map, vrat_map,
            _active_cont_model(ts, cont_models), arm, taker_bps, 4.5,
        )

        equity = book.mark_equity(exec_px)
        peak_nav = max(peak_nav, equity)
        dd_pct = ((peak_nav - equity) / peak_nav * 100.0) if peak_nav > 0 else 0.0
        if equity < 20.0:
            nav_by_date[ts.date().isoformat()] = equity
            continue

        while sig_ptr + 1 < len(sig_dates) and sig_dates[sig_ptr + 1] <= ts:
            sig_ptr += 1
        cur_sig_ts = sig_dates[sig_ptr] if (sig_dates and sig_dates[sig_ptr] <= ts) else None
        if cur_sig_ts is not None and cur_sig_ts != last_sig_applied and cur_sig_ts in cov_h_by_ts:
            last_sig_applied = cur_sig_ts
            for sym, (prev_raw, prev_px) in prev_day_forecasts.items():
                if sym in exec_px and prev_px > 0:
                    ic_slow.update(prev_raw, (exec_px[sym] - prev_px) / prev_px)
            active_slow, cov_h = cov_h_by_ts[cur_sig_ts]
            day_sigs = sigs_13[cur_sig_ts]
            prev_day_forecasts = {
                s: (day_sigs[s].s1_trend, exec_px[s])
                for s in active_slow
                if day_sigs[s].s1_trend is not None and s in exec_px
            }
            cur_slow_w = tuple(
                (book.lots[(s, "slow_core")].qty * exec_px.get(s, 0.0) / equity) if (s, "slow_core") in book.lots else 0.0
                for s in active_slow
            )
            ic_use = ic_slow.shrunk_ic if arm.use_online_ic else 0.08
            slow_fee = tehran_execution_cost_bps(arm.slow_exec_utc_hour, use_passive_maker=arm.use_passive_slow)
            pending_slow_targets = _solve_slow_targets_for_day(
                active_slow, day_sigs, accel_13.get(cur_sig_ts, {}), cur_slow_w, cov_h,
                sigs_metals.get(cur_sig_ts, {}), exec_px, ic_use, slow_fee,
            )

        if pending_slow_targets is not None and (ts.hour >= arm.slow_exec_utc_hour or arm.slow_exec_utc_hour == 0):
            slow_exec_fee = (
                tehran_execution_cost_bps(ts.hour, use_passive_maker=arm.use_passive_slow)
                if (arm.slow_exec_utc_hour != 0 or arm.use_passive_slow)
                else 16.0
            )
            slow_fills += book.rebalance_slow_spot_targets(
                pending_slow_targets, exec_px, tradable, ts, leg_fee_bps=slow_exec_fee,
            )
            pending_slow_targets = None

        ign_entries += _try_open_ignition_entries(
            book, ts, equity, dd_pct, exec_px, tradable,
            sigs_13.get(cur_sig_ts, {}) if cur_sig_ts else {},
            daily_breadth.get(ts.date().isoformat(), 0.5),
            gru_scores, recent_gru, bvol_map, ret24_map, offers_by_sym, cfg, arm,
        )
        nav_by_date[ts.date().isoformat()] = book.mark_equity(exec_px)

    return {
        "fees": round(book.total_fees, 2),
        "borrow": round(book.total_borrow, 2),
        "pool_yield": round(book.total_pool_yield, 2),
        "liqs": book.liquidations,
        "stops": book.stop_outs,
        "oco_tp": book.oco_profit_exits,
        "early_ml": book.early_ml_exits,
        "pyramids": book.pyramids,
        "internal_shorts": book.internal_short_offsets,
        "rv_hedges": book.rv_hedges_opened,
        "max_lev": round(book.max_leverage_used, 2),
        "slow_fills": slow_fills,
        "ign_entries": ign_entries,
        "final_online_ic": round(ic_slow.shrunk_ic, 4),
    }, nav_by_date


def _audit_live_tehran_clock_and_triangles(db_path: Path) -> dict:
    """Empirical audit of live book_top spreads by UTC hour, TMN/USDT triangles, and USDTTMN borrow carry."""
    con = open_readonly_market_db(db_path)
    try:
        # 1. Sampled hourly spread profile across major USDT pairs
        hr_rows = con.execute(
            "SELECT substr(ts_avail, 12, 2) AS h, COUNT(*), "
            "AVG((CAST(ask AS REAL)-CAST(bid AS REAL))/((CAST(ask AS REAL)+CAST(bid AS REAL))/2.0)*10000.0) "
            "FROM book_top "
            "WHERE instrument_id IN ('wallex:BTCUSDT','wallex:ETHUSDT','wallex:SOLUSDT','wallex:XRPUSDT','wallex:XAUTUSDT') "
            "AND CAST(bid AS REAL)>0 AND CAST(ask AS REAL)>CAST(bid AS REAL) "
            "GROUP BY h ORDER BY h"
        ).fetchall()
        hourly_spreads = [
            {"utc_hour": int(h), "tehran_approx": f"{(int(h) + 3) % 24:02d}:30", "ticks": int(n), "avg_spread_bps": round(float(sp), 2)}
            for h, n, sp in hr_rows
        ]

        # 2. Live TMN vs USDT triangle routing audit on synchronized 1-minute snapshots
        # Grab last 3,000 minute buckets from book_top for USDTTMN + 6 triangle pairs
        tri_audit: list[dict] = []
        usdt_tmn_rows = con.execute(
            "SELECT substr(ts_avail, 1, 16) AS m, AVG(CAST(bid AS REAL)), AVG(CAST(ask AS REAL)) "
            "FROM book_top WHERE instrument_id='wallex:USDTTMN' AND CAST(bid AS REAL)>0 "
            "GROUP BY m ORDER BY m DESC LIMIT 2000"
        ).fetchall()
        fx_by_min = {m: (float(b), float(a)) for m, b, a in usdt_tmn_rows if b and a}

        for base in TRIANGLE_BASES:
            u_rows = con.execute(
                "SELECT substr(ts_avail, 1, 16) AS m, AVG(CAST(bid AS REAL)), AVG(CAST(ask AS REAL)) "
                "FROM book_top WHERE instrument_id=? AND CAST(bid AS REAL)>0 "
                "GROUP BY m ORDER BY m DESC LIMIT 2000",
                (f"wallex:{base}USDT",),
            ).fetchall()
            t_rows = con.execute(
                "SELECT substr(ts_avail, 1, 16) AS m, AVG(CAST(bid AS REAL)), AVG(CAST(ask AS REAL)) "
                "FROM book_top WHERE instrument_id=? AND CAST(bid AS REAL)>0 "
                "GROUP BY m ORDER BY m DESC LIMIT 2000",
                (f"wallex:{base}TMN",),
            ).fetchall()
            u_map = {m: (float(b), float(a)) for m, b, a in u_rows if b and a}
            t_map = {m: (float(b), float(a)) for m, b, a in t_rows if b and a}
            shared = sorted(set(u_map) & set(t_map) & set(fx_by_min))
            buy_wins, sell_wins = 0, 0
            buy_savings, sell_savings = [], []
            for m in shared:
                ub, ua = u_map[m]
                tb, ta = t_map[m]
                fb, fa = fx_by_min[m]
                dbuy = evaluate_synthetic_triangle_route(
                    f"{base}USDT", "BUY", direct_usdt_bid=ub, direct_usdt_ask=ua,
                    tmn_bid=tb, tmn_ask=ta, usdttmn_bid=fb, usdttmn_ask=fa,
                    usdt_fee_bps=13.0, tmn_fee_bps=25.0,
                )
                dsell = evaluate_synthetic_triangle_route(
                    f"{base}USDT", "SELL", direct_usdt_bid=ub, direct_usdt_ask=ua,
                    tmn_bid=tb, tmn_ask=ta, usdttmn_bid=fb, usdttmn_ask=fa,
                    usdt_fee_bps=13.0, tmn_fee_bps=25.0,
                )
                if dbuy.chosen_route == "SYNTHETIC_TMN":
                    buy_wins += 1
                    buy_savings.append(dbuy.saving_bps)
                if dsell.chosen_route == "SYNTHETIC_TMN":
                    sell_wins += 1
                    sell_savings.append(dsell.saving_bps)
            tri_audit.append({
                "symbol": f"{base}USDT",
                "matched_minutes": len(shared),
                "buy_synth_win_pct": round(100.0 * buy_wins / max(1, len(shared)), 2),
                "buy_avg_saving_bps": round(sum(buy_savings) / max(1, len(buy_savings)), 2) if buy_savings else 0.0,
                "sell_synth_win_pct": round(100.0 * sell_wins / max(1, len(shared)), 2),
                "sell_avg_saving_bps": round(sum(sell_savings) / max(1, len(sell_savings)), 2) if sell_savings else 0.0,
            })

        # 3. Historical USDTTMN dynamic borrow-currency regime audit (2022-2026)
        fx_bars = load_keyed_candles(con, "USDTTMN", "1d", limit=1800)
        tmn_days, usdt_days, tmn_advs = 0, 0, []
        for i in range(60, len(fx_bars)):
            c0, c60 = fx_bars[i].close, fx_bars[i - 60].close
            if c0 <= 0 or c60 <= 0:
                continue
            drift_bps_day = ((c0 / c60) ** (1.0 / 60.0) - 1.0) * 10_000.0
            trend_sc = max(-1.0, min(1.0, (c0 / c60 - 1.0) / 0.08))
            dec_b = select_borrow_currency(
                expected_usdttmn_drift_bps_per_day=drift_bps_day, usdttmn_trend_score=trend_sc,
            )
            if dec_b.chosen_currency == "TMN":
                tmn_days += 1
                tmn_advs.append(dec_b.net_carry_advantage_bps_per_day)
            else:
                usdt_days += 1
    finally:
        con.close()

    tightest = min(hourly_spreads, key=lambda x: x["avg_spread_bps"]) if hourly_spreads else {}
    widest = max(hourly_spreads, key=lambda x: x["avg_spread_bps"]) if hourly_spreads else {}
    return {
        "tehran_clock": {"tightest_hour": tightest, "widest_hour": widest, "hourly_profile": hourly_spreads},
        "tmn_triangle_routing": tri_audit,
        "dynamic_borrow_currency": {
            "total_days": tmn_days + usdt_days,
            "tmn_preferred_days": tmn_days,
            "tmn_preferred_pct": round(100.0 * tmn_days / max(1, tmn_days + usdt_days), 1),
            "avg_tmn_carry_advantage_bps_day": round(sum(tmn_advs) / max(1, len(tmn_advs)), 2) if tmn_advs else 0.0,
        },
    }


def run_multi_horizon_adaptive_study(
    db_path: Path,
    *,
    report_md: Path | None = None,
    report_json: Path | None = None,
) -> dict:
    """Execute the full 6-finding incremental ablation study + live Tehran-clock & TMN triangle audits."""
    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in ADAPTIVE_UNIVERSE}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in ADAPTIVE_UNIVERSE}
    finally:
        con.close()

    panel_13 = {s: panel_1d[s] for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    accel_13 = compute_second_order_trend_map(sigs_13, BASE_13_SYMBOLS)
    metal_syms = tuple(DEFENSIVE_METALS_CAPS)
    sigs_metals = compute_slow_sleeves({s: panel_1d[s] for s in metal_syms}, metal_syms)
    daily_breadth = extract_daily_breadth(sigs_13)

    dated_13 = build_dated_returns_index(panel_13, BASE_13_SYMBOLS)
    cov_h_by_ts: dict[datetime, tuple[tuple[str, ...], tuple[tuple[float, ...], ...]]] = {}
    for t_day in sorted(sigs_13):
        if t_day < datetime(2024, 1, 1, tzinfo=UTC):
            continue
        act_s = tuple(s for s in BASE_13_SYMBOLS if s in sigs_13[t_day])
        if len(act_s) >= 2:
            cov_h_by_ts[t_day] = (act_s, build_shrunk_horizon_cov(dated_13, act_s, t_day))

    p2_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in ADAPTIVE_UNIVERSE if panel_1h[s]}
    p2_1 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=1) for s in ADAPTIVE_UNIVERSE if panel_1h[s]}

    d0, s0, x0, yb0, yp0 = _extract_11feat_coiled_spring_dataset(p2_0, IGNITION_18_CRYPTO, daily_breadth)
    d1, s1, x1, yb1, yp1 = _extract_11feat_coiled_spring_dataset(p2_1, IGNITION_18_CRYPTO, daily_breadth)
    sc11_0, auc11_0, _ = _walkforward_gru_scores(d0, s0, x0, yp0, yb0, task="regression")
    sc11_1, auc11_1, _ = _walkforward_gru_scores(d1, s1, x1, yp1, yb1, task="regression")

    # Train strictly causal walk-forward in-position continuation models (Finding #4)
    c_d0, c_x0, c_y0 = _extract_in_position_training_rows(p2_0, sc11_0)
    c_d1, c_x1, c_y1 = _extract_in_position_training_rows(p2_1, sc11_1)
    cont_0 = _train_walkforward_continuation_models(c_d0, c_x0, c_y0)
    cont_1 = _train_walkforward_continuation_models(c_d1, c_x1, c_y1)
    stats_0 = _compute_2h_bar_stats(p2_0)
    stats_1 = _compute_2h_bar_stats(p2_1)

    # Benchmark: Frozen V2_CHAMPION (NBX16)
    _, _, sch0 = simulate_nobitex_margin_ignition(
        p2_0, IGNITION_18_CRYPTO, daily_breadth, sc11_0,
        label="V2_IGN_0H", offset_hours=0, score_is_return=True, base_prob=0.46,
        top_tercile_leverage=1.5, leg_cost=0.0016, borrow_mode="eod_utc", borrow_rate=0.0005,
    )
    _, _, sch1 = simulate_nobitex_margin_ignition(
        p2_1, IGNITION_18_CRYPTO, daily_breadth, sc11_1,
        label="V2_IGN_1H", offset_hours=1, score_is_return=True, base_prob=0.46,
        top_tercile_leverage=1.5, leg_cost=0.0016, borrow_mode="eod_utc", borrow_rate=0.0005,
    )
    v2_run = _run_v2_joint_shared_ledger(
        panel_1h, ADAPTIVE_UNIVERSE, sigs_13, accel_13, sigs_metals, cov_h_by_ts,
        _merge_twin_schedules(sch0, sch1), slow_budget=0.60, ign_budget=0.40,
        fee_rate=Decimal("0.0016"), use_metals_reserve=True,
    )
    v2_nav = v2_run["nav_by_date"]
    v2_rets = _daily_returns_map(v2_nav)
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    v2_ref = {
        "label": "V2_CHAMPION_60_40_NBX16_REF",
        "full": _portfolio_metrics(v2_nav),
        "stress": _portfolio_metrics({k: v for k, v in v2_nav.items() if k >= stress_iso}),
        "fills": v2_run["fills"],
        "fees_usdt": v2_run["total_fees_usdt"],
    }

    arms = [
        AdaptiveArmConfig("F1_LOT_BOOK_TRUE_MARGIN_5X", max_leverage=5.0),
        AdaptiveArmConfig("F1_F3_ONLINE_IC_ZERO_BUCKET_5X", max_leverage=5.0, use_online_ic=True),
        AdaptiveArmConfig("F1_F3_F2_TEHRAN_CLOCK_OCO_5X", max_leverage=5.0, use_online_ic=True, slow_exec_utc_hour=10, use_passive_slow=True, use_oco_maker_tp=True),
        AdaptiveArmConfig("F1_F3_F2_F4_ML_EXIT_PYRAMID_5X", max_leverage=5.0, use_online_ic=True, slow_exec_utc_hour=10, use_passive_slow=True, use_oco_maker_tp=True, use_ml_in_position=True),
        AdaptiveArmConfig("F1_TO_F6_FULL_WITH_RV_HEDGE_5X", max_leverage=5.0, use_online_ic=True, slow_exec_utc_hour=10, use_passive_slow=True, use_oco_maker_tp=True, use_ml_in_position=True, use_rv_hedge=True),
        AdaptiveArmConfig("F1_TO_F6_FULL_WITH_RV_HEDGE_2X", max_leverage=2.0, use_online_ic=True, slow_exec_utc_hour=10, use_passive_slow=True, use_oco_maker_tp=True, use_ml_in_position=True, use_rv_hedge=True),
        AdaptiveArmConfig("WINNERS_ONLY_F1_F2CLOCK_F4_5X", max_leverage=5.0, use_online_ic=False, slow_exec_utc_hour=10, use_passive_slow=True, use_oco_maker_tp=False, use_ml_in_position=True, use_rv_hedge=False),
    ]

    arm_rows: list[dict] = []
    for arm in arms:
        m0, n0 = _simulate_adaptive_phase(p2_0, sigs_13, accel_13, sigs_metals, cov_h_by_ts, daily_breadth, sc11_0, cont_0, stats_0, arm)
        m1, n1 = _simulate_adaptive_phase(p2_1, sigs_13, accel_13, sigs_metals, cov_h_by_ts, daily_breadth, sc11_1, cont_1, stats_1, arm)
        shared = sorted(set(n0) & set(n1))
        tn = {d: 0.5 * (n0[d] + n1[d]) for d in shared}
        fm = _portfolio_metrics(tn)
        sm = _portfolio_metrics({d: v for d, v in tn.items() if d >= stress_iso})
        s0_m = _portfolio_metrics(n0)
        s1_m = _portfolio_metrics(n1)
        up = paired_baseline_uplift(_daily_returns_map(tn), v2_rets, simulations=499, seed=42)
        ci = up.get("ci_95") or (0.0, 0.0)
        arm_rows.append({
            "label": arm.label,
            "days": len(tn),
            "ending_nav": fm["ending_nav"],
            "ret_pct": fm["ret_pct"],
            "stress_ret_pct": sm["ret_pct"],
            "ann_sharpe": fm["ann_sharpe"],
            "max_dd_pct": fm["max_dd_pct"],
            "sharpe_0h": s0_m["ann_sharpe"],
            "sharpe_1h": s1_m["ann_sharpe"],
            "liquidations_sum": m0["liqs"] + m1["liqs"],
            "fees_usdt_avg": round(0.5 * (m0["fees"] + m1["fees"]), 2),
            "borrow_usdt_avg": round(0.5 * (m0["borrow"] + m1["borrow"]), 2),
            "pool_yield_usdt_avg": round(0.5 * (m0["pool_yield"] + m1["pool_yield"]), 2),
            "oco_tp_avg": round(0.5 * (m0["oco_tp"] + m1["oco_tp"]), 1),
            "early_ml_avg": round(0.5 * (m0["early_ml"] + m1["early_ml"]), 1),
            "pyramids_avg": round(0.5 * (m0["pyramids"] + m1["pyramids"]), 1),
            "internal_shorts_avg": round(0.5 * (m0["internal_shorts"] + m1["internal_shorts"]), 1),
            "rv_hedges_avg": round(0.5 * (m0["rv_hedges"] + m1["rv_hedges"]), 1),
            "max_leverage_used": max(m0["max_lev"], m1["max_lev"]),
            "vs_v2_bps": round(float(up.get("mean_uplift", 0.0)) * 10_000.0, 2),
            "vs_v2_ci": [round(ci[0] * 10_000.0, 2), round(ci[1] * 10_000.0, 2)],
        })

    live_audits = _audit_live_tehran_clock_and_triangles(db_path)
    best_arm = max(arm_rows, key=lambda r: (r["liquidations_sum"] == 0, r["ann_sharpe"]))
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "gru11_oos_auc": {"phase_0h": round(auc11_0, 4), "phase_1h": round(auc11_1, 4)},
        "in_position_training_rows": {"phase_0h": len(c_d0), "phase_1h": len(c_d1)},
        "v2_reference": v2_ref,
        "ablation_arms": arm_rows,
        "best_arm": best_arm,
        "live_audits": live_audits,
    }
    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if report_md is not None:
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text(_render_report_md(payload), encoding="utf-8")
    return payload


def _render_report_md(p: dict) -> str:
    v2 = p["v2_reference"]
    best = p["best_arm"]
    la = p["live_audits"]
    tc = la["tehran_clock"]
    bc = la["dynamic_borrow_currency"]
    lines = [
        "# Multi-Horizon Adaptive Engine (Findings F1–F6) — Incremental Ablation & Live Venue Audit",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`PAPER_ONLY`)",
        f"- **Frozen v2 Champion Reference:** NAV `${v2['full']['ending_nav']:.2f}` (`{v2['full']['ret_pct']:+.2f}%`), Bear `{v2['stress']['ret_pct']:+.2f}%`, Sharpe `{v2['full']['ann_sharpe']:.3f}`, MaxDD `{v2['full']['max_dd_pct']:.2f}%`, Fees `${v2['fees_usdt']:.2f}`",
        f"- **Best Adaptive Arm:** `{best['label']}` — NAV `${best['ending_nav']:.2f}` (`{best['ret_pct']:+.2f}%`), Bear `{best['stress_ret_pct']:+.2f}%`, Sharpe `{best['ann_sharpe']:.3f}` (`0h={best['sharpe_0h']:.3f}` / `1h={best['sharpe_1h']:.3f}`), MaxDD `{best['max_dd_pct']:.2f}%`, Liqs `{best['liquidations_sum']}`, vs v2 `{best['vs_v2_bps']:+.2f} bps/d` `[{best['vs_v2_ci'][0]:+.2f}, {best['vs_v2_ci'][1]:+.2f}]`",
        "",
        "## 1. Incremental Ablation Stack (F1 → F6, `1,085d` `2024–2026`, Twin `0h + 1h` Phase)",
        "",
        "| Arm | Ending NAV | Full Ret | Bear Stress | Sharpe (`0h`/`1h`) | MaxDD | Liqs | MaxLev | Fees / Borrow / Pool ($) | OCO / ML-Exit / Pyr / IntSh / RV | vs v2 (bps/d, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for r in p["ablation_arms"]:
        fbp = f"${r['fees_usdt_avg']:.1f} / ${r['borrow_usdt_avg']:.1f} / +${r['pool_yield_usdt_avg']:.1f}"
        ops = f"{r['oco_tp_avg']:.0f} / {r['early_ml_avg']:.0f} / {r['pyramids_avg']:.0f} / {r['internal_shorts_avg']:.0f} / {r['rv_hedges_avg']:.0f}"
        ci = r["vs_v2_ci"]
        lines.append(
            f"| `{r['label']}` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` "
            f"| `{r['ann_sharpe']:.3f}` (`{r['sharpe_0h']:.3f}`/`{r['sharpe_1h']:.3f}`) | `{r['max_dd_pct']:.2f}%` "
            f"| `{r['liquidations_sum']}` | `{r['max_leverage_used']:.1f}×` | `{fbp}` | `{ops}` "
            f"| `{r['vs_v2_bps']:+.2f}` `[{ci[0]:+.2f}, {ci[1]:+.2f}]` |"
        )
    lines += [
        "",
        "## 2. Live Iranian Venue Audits (F2 Tehran Clock & F5 Synthetic TMN Triangles + Borrow Currency)",
        "",
        f"- **Live Tehran Liquidity Clock (`book_top`):** Tightest hour = `UTC {tc['tightest_hour'].get('utc_hour')}h` (`{tc['tightest_hour'].get('tehran_approx')} Tehran`, `{tc['tightest_hour'].get('avg_spread_bps')} bps`) vs. Widest hour = `UTC {tc['widest_hour'].get('utc_hour')}h` (`{tc['widest_hour'].get('tehran_approx')} Tehran`, `{tc['widest_hour'].get('avg_spread_bps')} bps`).",
        f"- **Dynamic Borrow Currency (`USDTTMN`, `{bc['total_days']}` days):** `TMN` debt strictly cheaper than `USDT` debt on **`{bc['tmn_preferred_days']}` days (`{bc['tmn_preferred_pct']}%`)** with mean net carry advantage **`+{bc['avg_tmn_carry_advantage_bps_day']} bps/day`** during confirmed USDTTMN uptrends.",
        "",
        "| Triangle Pair | Matched Mins | Synthetic TMN BUY Win% (Avg Save) | Synthetic TMN SELL Win% (Avg Save) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for t in la["tmn_triangle_routing"]:
        lines.append(
            f"| `{t['symbol']}` | `{t['matched_minutes']}` | `{t['buy_synth_win_pct']}%` (`+{t['buy_avg_saving_bps']} bps`) "
            f"| `{t['sell_synth_win_pct']}%` (`+{t['sell_avg_saving_bps']} bps`) |"
        )
    lines.append("")
    return "\n".join(lines)
