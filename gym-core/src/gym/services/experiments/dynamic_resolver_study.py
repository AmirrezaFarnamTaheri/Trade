"""Head-to-head strictly causal evaluation of all 4 v3 Per-Moment Instrument Resolvers.

Evaluates Approach 1 (A1_UTILITY), Approach 2 (A2_SIGNED_ADMM), Approach 3 (A3_STATE_MACHINE),
and Hybrid (H12_HYBRID) on the exact same 2024-2026 2h twin-phase (0h + 1h) overlap panel,
with exact Nobitex EOD borrow, Wallex 4h borrow, idle USDT pool (+2.64% APR), tight-stop 5x
vs. 2x leverage ablation, and a pluggable Hyperliquid Perp funding-rate readiness check.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.core_signal_geometry import (
    DEFENSIVE_METALS_CAPS,
    compute_defensive_metals_reserve,
)
from ...domain.dynamic_resolver_ledger import (
    DynamicResolverSummary,
    ResolverFn,
    simulate_dynamic_resolver,
)
from ...domain.higher_order_and_sparse import compute_second_order_trend_map
from ...domain.instrument_resolver import (
    MarketView,
    ResolverConfig,
    build_local_venue_offers,
    resolve_a1_utility,
    resolve_a2_signed_admm,
    resolve_a3_state_machine,
    resolve_h12_hybrid,
)
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
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

RESOLVER_UNIVERSE: tuple[str, ...] = tuple(
    dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO + ("PAXGUSDT", "SLVONUSDT"))
)
NOBITEX_IDLE_USDT_APR = 0.0264


def _daily_atr_bps_map(bars: list[BarPoint], window: int = 14) -> dict[datetime, float]:
    out: dict[datetime, float] = {}
    trs: list[float] = []
    for i in range(1, len(bars)):
        prev_c = bars[i - 1].close
        if prev_c <= 0:
            continue
        tr = max(bars[i].high - bars[i].low, abs(bars[i].high - prev_c), abs(bars[i].low - prev_c))
        trs.append(tr / prev_c * 10_000.0)
        if len(trs) >= window:
            out[bars[i].ts_avail] = sum(trs[-window:]) / window
    return out


def _bar_2h_features(bars: list[BarPoint]) -> tuple[dict[datetime, float], dict[datetime, float], dict[datetime, float]]:
    """Compute causal 2h ATR bps, annualized vol, and 20-bar breakdown z-score per ts_avail."""
    atr_map: dict[datetime, float] = {}
    vol_map: dict[datetime, float] = {}
    z_map: dict[datetime, float] = {}
    trs: list[float] = []
    rets: list[float] = []
    closes: list[float] = []
    for i, b in enumerate(bars):
        closes.append(b.close)
        if i == 0 or bars[i - 1].close <= 0:
            continue
        pc = bars[i - 1].close
        r = (b.close - pc) / pc
        rets.append(r)
        tr = max(b.high - b.low, abs(b.high - pc), abs(b.low - pc)) / pc * 10_000.0
        trs.append(tr)
        if len(trs) >= 14:
            atr_map[b.ts_avail] = sum(trs[-14:]) / 14.0
        if len(rets) >= 24:
            w = rets[-24:]
            m = sum(w) / len(w)
            sd = math.sqrt(sum((x - m) ** 2 for x in w) / max(1, len(w) - 1))
            vol_map[b.ts_avail] = max(0.15, sd * math.sqrt(12.0 * 365.0))
        if len(closes) >= 20:
            cw = closes[-20:]
            cm = sum(cw) / len(cw)
            csd = math.sqrt(sum((x - cm) ** 2 for x in cw) / max(1, len(cw) - 1))
            z_map[b.ts_avail] = (b.close - cm) / csd if csd > 1e-12 else 0.0
    return atr_map, vol_map, z_map


def _build_causal_market_views(
    panel_1d: dict[str, list[BarPoint]],
    panel_2h: dict[str, list[BarPoint]],
    sigs_1d: dict,
    accel_1d: dict,
    daily_breadth: dict[str, float],
    gru_scores: dict[tuple[datetime, str], float],
) -> tuple[
    dict[datetime, dict[str, MarketView]],
    dict[datetime, dict[tuple[str, str], float]],
    list[datetime],
]:
    """Synthesize strictly causal venue-agnostic MarketView objects at every 2h bar close."""
    atr_1d = {s: _daily_atr_bps_map(panel_1d.get(s, [])) for s in RESOLVER_UNIVERSE}
    feats_2h = {s: _bar_2h_features(panel_2h.get(s, [])) for s in RESOLVER_UNIVERSE}
    dated_rets = build_dated_returns_index(panel_1d, RESOLVER_UNIVERSE)

    # All strictly available 2h timestamps across core/ignition symbols
    all_ts_set: set[datetime] = set()
    for sym in IGNITION_18_CRYPTO:
        for b in panel_2h.get(sym, []):
            all_ts_set.add(b.ts_avail)
    eval_ts = sorted(all_ts_set)

    # Pre-index latest closed 1d signal timestamp <= ts
    sig_dates = sorted(sigs_1d)
    sig_ptr = 0
    recent_gru: list[float] = []
    cov_cache: dict[str, dict[tuple[str, str], float]] = {}

    views_by_ts: dict[datetime, dict[str, MarketView]] = {}
    cov_by_ts: dict[datetime, dict[tuple[str, str], float]] = {}

    for ts in eval_ts:
        while sig_ptr + 1 < len(sig_dates) and sig_dates[sig_ptr + 1] <= ts:
            sig_ptr += 1
        cur_sig_ts = sig_dates[sig_ptr] if (sig_dates and sig_dates[sig_ptr] <= ts) else None
        day_sigs = sigs_1d.get(cur_sig_ts, {}) if cur_sig_ts else {}
        day_acc = accel_1d.get(cur_sig_ts, {}) if cur_sig_ts else {}
        day_key = (cur_sig_ts.date().isoformat() if cur_sig_ts else ts.date().isoformat())
        breadth = daily_breadth.get(day_key, 0.0)

        # Metals defensive reserve weights (purely causal on closed 1d bar)
        metals_w = compute_defensive_metals_reserve(day_sigs, breadth) if day_sigs else {}

        # Daily covariance cache (recomputed once per UTC day)
        if day_key not in cov_cache and cur_sig_ts is not None:
            active_cov_syms = tuple(s for s in RESOLVER_UNIVERSE if s in dated_rets)
            cov_m = build_shrunk_horizon_cov(dated_rets, active_cov_syms, cur_sig_ts)
            cov_dict: dict[tuple[str, str], float] = {}
            for i, si in enumerate(active_cov_syms):
                for j, sj in enumerate(active_cov_syms):
                    cov_dict[(si, sj)] = float(cov_m[i][j])
            cov_cache[day_key] = cov_dict
        cov_by_ts[ts] = cov_cache.get(day_key, {})

        ts_views: dict[str, MarketView] = {}
        for sym in RESOLVER_UNIVERSE:
            atr2, vol2, z2 = feats_2h[sym]
            vol_ann = vol2.get(ts, 0.65)
            atr2_bps = atr2.get(ts, 220.0)
            atr1_bps = atr_1d[sym].get(cur_sig_ts, 420.0) if cur_sig_ts else 420.0
            z_now = z2.get(ts, 0.0)

            # 1) Check 2h GRU-Ignition event (highest priority short-horizon tight-stop signal)
            g_pred = gru_scores.get((ts, sym))
            if g_pred is not None:
                rank = (
                    sum(1 for x in recent_gru if x <= g_pred) / len(recent_gru)
                    if len(recent_gru) >= 20
                    else 0.55
                )
                recent_gru.append(g_pred)
                if len(recent_gru) > 120:
                    recent_gru = recent_gru[-120:]
                if g_pred > 0.002 and rank >= 0.45:
                    exp_bps = min(280.0, max(30.0, g_pred * 10_000.0 * 1.15))
                    stop_bps = max(170.0, min(620.0, 2.2 * atr2_bps))
                    ts_views[sym] = MarketView(
                        symbol=sym, ts_avail=ts, expected_return_bps=exp_bps,
                        horizon_hours=16.0, stop_distance_bps=stop_bps,
                        realized_vol_ann=vol_ann, confidence=min(0.98, rank),
                        regime_breadth=breadth, source_tag="2h_gru_ignition",
                    )
                    continue

            # 2) Metals defensive reserve view
            if sym in DEFENSIVE_METALS_CAPS and metals_w.get(sym, 0.0) > 0.02:
                ts_views[sym] = MarketView(
                    symbol=sym, ts_avail=ts, expected_return_bps=75.0,
                    horizon_hours=240.0, stop_distance_bps=max(320.0, min(900.0, 2.6 * atr1_bps)),
                    realized_vol_ann=min(vol_ann, 0.28), confidence=0.68,
                    regime_breadth=breadth, source_tag="1d_metals_reserve",
                )
                continue

            # 3) Slow 1d Core Trend + 2nd-order Accel OR Causal Breakdown Short
            sig = day_sigs.get(sym)
            if sig is None or sig.s1_trend is None:
                continue
            score_1d = max(-1.0, min(1.0, 0.80 * sig.s1_trend + 0.20 * day_acc.get(sym, 0.0)))

            if score_1d > 0.12 and breadth >= 0.25:
                exp_bps = min(190.0, max(25.0, score_1d * 175.0))
                conf = min(0.82, 0.45 + 0.40 * score_1d)
                stop_bps = max(450.0, min(1400.0, 2.6 * atr1_bps))
                ts_views[sym] = MarketView(
                    symbol=sym, ts_avail=ts, expected_return_bps=exp_bps,
                    horizon_hours=168.0, stop_distance_bps=stop_bps,
                    realized_vol_ann=vol_ann, confidence=conf,
                    regime_breadth=breadth, source_tag="1d_core_accel",
                )
            elif score_1d < -0.45 and breadth <= 0.25 and z_now <= -2.0:
                exp_short_bps = -min(125.0, max(45.0, abs(score_1d) * 95.0 + abs(z_now) * 12.0))
                conf = min(0.88, 0.58 + 0.08 * min(3.0, abs(z_now)))
                stop_bps = max(260.0, min(680.0, 2.4 * atr2_bps))
                ts_views[sym] = MarketView(
                    symbol=sym, ts_avail=ts, expected_return_bps=exp_short_bps,
                    horizon_hours=36.0, stop_distance_bps=stop_bps,
                    realized_vol_ann=vol_ann, confidence=conf,
                    regime_breadth=breadth, source_tag="causal_breakdown_short",
                )
        views_by_ts[ts] = ts_views

    return views_by_ts, cov_by_ts, eval_ts


def _combine_twin_nav(nav0: dict[str, float], nav1: dict[str, float]) -> dict[str, float]:
    dates = sorted(set(nav0) & set(nav1))
    if len(dates) < 2:
        return nav0 or nav1
    return {d: 0.5 * (nav0[d] + nav1[d]) for d in dates}


def _avg_summary(label: str, r0: DynamicResolverSummary, r1: DynamicResolverSummary, twin_nav: dict[str, float]) -> dict:
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    full_m = _portfolio_metrics(twin_nav)
    stress_m = _portfolio_metrics({k: v for k, v in twin_nav.items() if k >= stress_iso})
    return {
        "label": label,
        "days": len(twin_nav),
        "ending_nav": full_m["ending_nav"],
        "ret_pct": full_m["ret_pct"],
        "stress_ret_pct": stress_m["ret_pct"],
        "ann_sharpe": full_m["ann_sharpe"],
        "max_dd_pct": full_m["max_dd_pct"],
        "sharpe_0h": r0.ann_sharpe,
        "sharpe_1h": r1.ann_sharpe,
        "liquidations_sum": r0.liquidations + r1.liquidations,
        "stop_outs_avg": round(0.5 * (r0.stop_outs + r1.stop_outs), 1),
        "fees_usdt_avg": round(0.5 * (r0.total_fees_usdt + r1.total_fees_usdt), 2),
        "borrow_usdt_avg": round(0.5 * (r0.total_borrow_usdt + r1.total_borrow_usdt), 2),
        "funding_net_usdt_avg": round(0.5 * (r0.total_funding_net_usdt + r1.total_funding_net_usdt), 2),
        "pool_yield_usdt_avg": round(0.5 * (r0.total_pool_yield_usdt + r1.total_pool_yield_usdt), 2),
        "spot_entries_avg": round(0.5 * (r0.spot_entries + r1.spot_entries), 1),
        "margin_long_entries_avg": round(0.5 * (r0.margin_long_entries + r1.margin_long_entries), 1),
        "margin_short_entries_avg": round(0.5 * (r0.margin_short_entries + r1.margin_short_entries), 1),
        "perp_long_entries_avg": round(0.5 * (r0.perp_long_entries + r1.perp_long_entries), 1),
        "perp_short_entries_avg": round(0.5 * (r0.perp_short_entries + r1.perp_short_entries), 1),
        "switches_avg": round(0.5 * (r0.switches + r1.switches), 1),
        "max_leverage_used": max(r0.max_leverage_used, r1.max_leverage_used),
        "avg_leverage_when_levered": round(0.5 * (r0.avg_leverage_when_levered + r1.avg_leverage_when_levered), 2),
    }


def _wrap_no_cov(fn) -> ResolverFn:
    return lambda v, o, p, eq, h, dd, _cov, cfg: fn(v, o, p, eq, h, dd, cfg)


def run_dynamic_resolver_study(
    db_path: Path,
    *,
    report_md: Path | None = None,
    report_json: Path | None = None,
) -> dict:
    """Execute the full 4-way v3 Dynamic Per-Moment Instrument Resolver head-to-head study."""
    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in RESOLVER_UNIVERSE}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in RESOLVER_UNIVERSE}
    finally:
        con.close()

    sigs_1d = compute_slow_sleeves(panel_1d, RESOLVER_UNIVERSE)
    accel_1d = compute_second_order_trend_map(sigs_1d, RESOLVER_UNIVERSE)
    daily_breadth = extract_daily_breadth(sigs_1d)

    p2_0 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in RESOLVER_UNIVERSE if panel_1h[s]}
    p2_1 = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=1) for s in RESOLVER_UNIVERSE if panel_1h[s]}

    d0, s0, x0, yb0, yp0 = _extract_11feat_coiled_spring_dataset(p2_0, IGNITION_18_CRYPTO, daily_breadth)
    d1, s1, x1, yb1, yp1 = _extract_11feat_coiled_spring_dataset(p2_1, IGNITION_18_CRYPTO, daily_breadth)
    sc11_0, auc11_0, _ = _walkforward_gru_scores(d0, s0, x0, yp0, yb0, task="regression")
    sc11_1, auc11_1, _ = _walkforward_gru_scores(d1, s1, x1, yp1, yb1, task="regression")

    views_0, cov_0, ts_0 = _build_causal_market_views(panel_1d, p2_0, sigs_1d, accel_1d, daily_breadth, sc11_0)
    views_1, cov_1, ts_1 = _build_causal_market_views(panel_1d, p2_1, sigs_1d, accel_1d, daily_breadth, sc11_1)

    # Static local offers (Nobitex + Wallex) and optional Hyperliquid Perp readiness offers
    local_offers = {s: build_local_venue_offers(s, idle_pool_apr=NOBITEX_IDLE_USDT_APR) for s in RESOLVER_UNIVERSE}
    perp_offers = {
        s: build_local_venue_offers(s, idle_pool_apr=NOBITEX_IDLE_USDT_APR, include_perp_future=True)
        for s in RESOLVER_UNIVERSE
    }
    offers_local_0 = {ts: local_offers for ts in ts_0}
    offers_local_1 = {ts: local_offers for ts in ts_1}
    offers_perp_0 = {ts: perp_offers for ts in ts_0}
    offers_perp_1 = {ts: perp_offers for ts in ts_1}

    # Benchmark: frozen V2_CHAMPION (NBX16, 60/40 slow+ignition, 1.5x twin-phase GRU11 Path-PnL + Joint ADMM)
    from ...domain.venue_leverage_models import simulate_nobitex_margin_ignition

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
    v2_sched = _merge_twin_schedules(sch0, sch1)
    panel_13 = {s: panel_1d[s] for s in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    accel_13 = compute_second_order_trend_map(sigs_13, BASE_13_SYMBOLS)
    metal_syms = tuple(DEFENSIVE_METALS_CAPS)
    sigs_metals = compute_slow_sleeves({s: panel_1d[s] for s in metal_syms}, metal_syms)
    dated_13 = build_dated_returns_index(panel_13, BASE_13_SYMBOLS)
    cov_h_by_ts: dict[datetime, tuple[tuple[str, ...], tuple[tuple[float, ...], ...]]] = {}
    for t_day in sorted(sigs_13):
        if t_day < datetime(2024, 1, 1, tzinfo=UTC):
            continue
        active_s = tuple(s for s in BASE_13_SYMBOLS if s in sigs_13[t_day])
        if len(active_s) >= 2:
            cov_h_by_ts[t_day] = (active_s, build_shrunk_horizon_cov(dated_13, active_s, t_day))
    v2_run = _run_v2_joint_shared_ledger(
        panel_1h, RESOLVER_UNIVERSE, sigs_13, accel_13, sigs_metals, cov_h_by_ts, v2_sched,
        slow_budget=0.60, ign_budget=0.40, fee_rate=Decimal("0.0016"), use_metals_reserve=True,
    )
    v2_nav = v2_run["nav_by_date"]
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    v2_ref = {
        "name": "V2_CHAMPION_60_40_NBX16_REF",
        "full": _portfolio_metrics(v2_nav),
        "stress": _portfolio_metrics({k: v for k, v in v2_nav.items() if k >= stress_iso}),
        "fills": v2_run["fills"],
        "fees_usdt": v2_run["total_fees_usdt"],
    }
    v2_rets = _daily_returns_map(v2_nav)

    resolvers: tuple[tuple[str, ResolverFn], ...] = (
        ("A1_UTILITY", _wrap_no_cov(resolve_a1_utility)),
        ("A2_SIGNED_ADMM", resolve_a2_signed_admm),
        ("A3_STATE_MACHINE", _wrap_no_cov(resolve_a3_state_machine)),
        ("H12_HYBRID", resolve_h12_hybrid),
    )

    local_5x_rows: list[dict] = []
    local_2x_rows: list[dict] = []
    perp_ready_rows: list[dict] = []
    twin_navs: dict[str, dict[str, float]] = {"V2_CHAMPION_NBX16_REF": v2_nav}

    # 1. Local Venues (5x max ceiling on tight stops)
    cfg_5x = ResolverConfig(max_venue_leverage=5.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR)
    for name, fn in resolvers:
        lbl = f"{name}_LOCAL_5X"
        r0, n0 = simulate_dynamic_resolver(p2_0, views_0, offers_local_0, cov_0, fn, label=f"{lbl}_0H", cfg=cfg_5x)
        r1, n1 = simulate_dynamic_resolver(p2_1, views_1, offers_local_1, cov_1, fn, label=f"{lbl}_1H", cfg=cfg_5x)
        tn = _combine_twin_nav(n0, n1)
        twin_navs[lbl] = tn
        row = _avg_summary(lbl, r0, r1, tn)
        up = paired_baseline_uplift(_daily_returns_map(tn), v2_rets, simulations=499, seed=42)
        ci = up.get("ci_95") or (0.0, 0.0)
        row["vs_v2_bps"] = round(float(up.get("mean_uplift", 0.0)) * 10_000.0, 2)
        row["vs_v2_ci"] = [round(ci[0] * 10_000.0, 2), round(ci[1] * 10_000.0, 2)]
        local_5x_rows.append(row)

    # 2. Local Venues (2x ceiling ablation + H12 long-only local ablation)
    cfg_2x = ResolverConfig(max_venue_leverage=2.0, idle_pool_apr=NOBITEX_IDLE_USDT_APR)
    for name, fn in resolvers:
        lbl = f"{name}_LOCAL_2X"
        r0, n0 = simulate_dynamic_resolver(p2_0, views_0, offers_local_0, cov_0, fn, label=f"{lbl}_0H", cfg=cfg_2x)
        r1, n1 = simulate_dynamic_resolver(p2_1, views_1, offers_local_1, cov_1, fn, label=f"{lbl}_1H", cfg=cfg_2x)
        tn = _combine_twin_nav(n0, n1)
        twin_navs[lbl] = tn
        row = _avg_summary(lbl, r0, r1, tn)
        up = paired_baseline_uplift(_daily_returns_map(tn), v2_rets, simulations=499, seed=42)
        ci = up.get("ci_95") or (0.0, 0.0)
        row["vs_v2_bps"] = round(float(up.get("mean_uplift", 0.0)) * 10_000.0, 2)
        row["vs_v2_ci"] = [round(ci[0] * 10_000.0, 2), round(ci[1] * 10_000.0, 2)]
        local_2x_rows.append(row)

    for max_lev_lo in (5.0, 2.0):
        cfg_lo = ResolverConfig(max_venue_leverage=max_lev_lo, idle_pool_apr=NOBITEX_IDLE_USDT_APR, allow_shorts=False)
        lbl = f"H12_HYBRID_LOCAL_{int(max_lev_lo)}X_LONG_ONLY"
        r0, n0 = simulate_dynamic_resolver(p2_0, views_0, offers_local_0, cov_0, resolve_h12_hybrid, label=f"{lbl}_0H", cfg=cfg_lo)
        r1, n1 = simulate_dynamic_resolver(p2_1, views_1, offers_local_1, cov_1, resolve_h12_hybrid, label=f"{lbl}_1H", cfg=cfg_lo)
        tn = _combine_twin_nav(n0, n1)
        twin_navs[lbl] = tn
        row = _avg_summary(lbl, r0, r1, tn)
        up = paired_baseline_uplift(_daily_returns_map(tn), v2_rets, simulations=499, seed=42)
        ci = up.get("ci_95") or (0.0, 0.0)
        row["vs_v2_bps"] = round(float(up.get("mean_uplift", 0.0)) * 10_000.0, 2)
        row["vs_v2_ci"] = [round(ci[0] * 10_000.0, 2), round(ci[1] * 10_000.0, 2)]
        local_2x_rows.append(row)

    # 3. Future Hyperliquid Perp Plug-In Readiness (top two architectures: A1 & H12)
    for name, fn in (("A1_UTILITY", _wrap_no_cov(resolve_a1_utility)), ("H12_HYBRID", resolve_h12_hybrid)):
        lbl = f"{name}_PLUS_PERP_5X"
        r0, n0 = simulate_dynamic_resolver(p2_0, views_0, offers_perp_0, cov_0, fn, label=f"{lbl}_0H", cfg=cfg_5x)
        r1, n1 = simulate_dynamic_resolver(p2_1, views_1, offers_perp_1, cov_1, fn, label=f"{lbl}_1H", cfg=cfg_5x)
        tn = _combine_twin_nav(n0, n1)
        row = _avg_summary(lbl, r0, r1, tn)
        up = paired_baseline_uplift(_daily_returns_map(tn), v2_rets, simulations=499, seed=42)
        ci = up.get("ci_95") or (0.0, 0.0)
        row["vs_v2_bps"] = round(float(up.get("mean_uplift", 0.0)) * 10_000.0, 2)
        row["vs_v2_ci"] = [round(ci[0] * 10_000.0, 2), round(ci[1] * 10_000.0, 2)]
        perp_ready_rows.append(row)

    best_local = max(local_5x_rows + local_2x_rows, key=lambda r: (r["liquidations_sum"] == 0, r["ann_sharpe"]))
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "gru11_oos_auc": {"phase_0h": round(auc11_0, 4), "phase_1h": round(auc11_1, 4)},
        "v2_reference": {
            "label": v2_ref["name"],
            "full": v2_ref["full"],
            "stress": v2_ref["stress"],
            "fills": v2_ref["fills"],
            "fees_usdt": v2_ref["fees_usdt"],
        },
        "local_5x_arms": local_5x_rows,
        "local_2x_arms": local_2x_rows,
        "perp_plugin_readiness_arms": perp_ready_rows,
        "best_local_arm": best_local,
    }

    if report_json is not None:
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if report_md is not None:
        report_md.parent.mkdir(parents=True, exist_ok=True)
        report_md.write_text(_render_markdown_report(payload), encoding="utf-8")
    return payload


def _md_table(rows: list[dict]) -> list[str]:
    lines = [
        "| Arm | Ending NAV | Full Ret | Bear Stress | Ann. Sharpe (0h / 1h) | MaxDD | Liqs | Max Lev | Spot / MLong / MShort / PerpS | Borrow / Pool ($) | vs v2 (bps/d, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for r in rows:
        mix = f"{r['spot_entries_avg']:.0f} / {r['margin_long_entries_avg']:.0f} / {r['margin_short_entries_avg']:.0f} / {r['perp_short_entries_avg']:.0f}"
        bp = f"${r['borrow_usdt_avg']:.2f} / +${r['pool_yield_usdt_avg']:.2f}"
        ci = r["vs_v2_ci"]
        lines.append(
            f"| `{r['label']}` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` "
            f"| `{r['ann_sharpe']:.3f}` (`{r['sharpe_0h']:.3f}`/`{r['sharpe_1h']:.3f}`) | `{r['max_dd_pct']:.2f}%` "
            f"| `{r['liquidations_sum']}` | `{r['max_leverage_used']:.1f}×` | `{mix}` | `{bp}` "
            f"| `{r['vs_v2_bps']:+.2f}` `[{ci[0]:+.2f}, {ci[1]:+.2f}]` |"
        )
    return lines


def _render_markdown_report(p: dict) -> str:
    v2 = p["v2_reference"]
    best = p["best_local_arm"]
    lines = [
        "# v3 Dynamic Per-Moment Instrument Resolver — 4-Way Head-to-Head Study",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`PAPER_ONLY`)",
        f"- **Purged Walk-Forward 11-feat Path-PnL GRU OOS AUC:** `0h = {p['gru11_oos_auc']['phase_0h']}` · `+1h = {p['gru11_oos_auc']['phase_1h']}`",
        f"- **Frozen v2 Champion Reference (`{v2['label']}`):** NAV `${v2['full']['ending_nav']:.2f}` (`{v2['full']['ret_pct']:+.2f}%`), Bear `{v2['stress']['ret_pct']:+.2f}%`, Sharpe `{v2['full']['ann_sharpe']:.3f}`, MaxDD `{v2['full']['max_dd_pct']:.2f}%`",
        f"- **Top Local Dynamic Resolver:** `{best['label']}` — NAV `${best['ending_nav']:.2f}` (`{best['ret_pct']:+.2f}%`), Bear `{best['stress_ret_pct']:+.2f}%`, Sharpe `{best['ann_sharpe']:.3f}`, MaxDD `{best['max_dd_pct']:.2f}%`, Liqs `{best['liquidations_sum']}`",
        "",
        "## 1. Local Venues (`Nobitex + Wallex`, Asymmetric Tight-Stop Cap up to `5.0×`)",
        "",
        *_md_table(p["local_5x_arms"]),
        "",
        "## 2. Local Venues Leverage Ceiling Ablation (`2.0×` Cap)",
        "",
        *_md_table(p["local_2x_arms"]),
        "",
        "## 3. Pluggable Hyperliquid Perp Readiness Check (`5 bps` leg, `+1 bps/8h` funding paid to shorts)",
        "",
        *_md_table(p["perp_plugin_readiness_arms"]),
        "",
        "## 4. Key Takeaways",
        "",
        "- Every arm consumed the exact same causal `MarketView` stream and ran through one shared multi-instrument ledger (`0h` + `+1h` twin-phase average, exact Nobitex `0.05%/d` EOD UTC borrow, `$0` intraday, `+2.64%` idle USDT pool, exact intra-bar high/low stops & liquidations).",
        "- Comparing `A1_UTILITY`, `A2_SIGNED_ADMM`, `A3_STATE_MACHINE`, and `H12_HYBRID` directly reveals whether per-moment instrument pre-pricing + covariance netting beats standalone utility, post-solve routing, or discrete state ladders.",
        "- Frozen v1 and v2 forward shadow journals remain untouched.",
        "",
    ]
    return "\n".join(lines)
