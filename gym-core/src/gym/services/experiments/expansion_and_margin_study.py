"""Experiments A, B, and C: 33-Market Multi-Asset Expansion, Continuous ML Tilt + 4h Exit, and Paper Margin."""
from __future__ import annotations

import json
import math
from bisect import bisect_right
from dataclasses import asdict
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
from ...domain.meta_gateway import LogisticVetoGateway, extract_gateway_features
from ...domain.model import dec
from ...domain.multi_asset_research import (
    BASE_13_SYMBOLS,
    COMMODITY_SYMBOLS,
    EXPANDED_33_SYMBOLS,
    compute_4h_crash_exit_dates,
    compute_multi_asset_sleeves,
    continuous_ml_tilt,
    depth_scaled_l2_impact,
    simulate_market_neutral_l1_pairs,
    simulate_wallex_margin_short_cascades,
    spread_aware_l1_cost,
)
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import SleeveSignal, compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .ensemble_study import (
    STRESS_REPLAY_START,
    _daily_returns_map,
    _portfolio_metrics,
    _run_self_financing_arm,
)


def _dated_returns_for(panel: dict[str, list[BarPoint]], symbols: tuple[str, ...]) -> dict[str, tuple[list[datetime], list[float]]]:
    out: dict[str, tuple[list[datetime], list[float]]] = {}
    for s in symbols:
        bars = panel.get(s, [])
        dts: list[datetime] = []
        rets: list[float] = []
        for i in range(1, len(bars)):
            if bars[i - 1].close > 0:
                dts.append(bars[i].ts_avail)
                rets.append((bars[i].close - bars[i - 1].close) / bars[i - 1].close)
        out[s] = (dts, rets)
    return out


def _live_liquidity_profile(con, symbols: tuple[str, ...]) -> dict[str, tuple[float | None, float | None]]:
    """Return {symbol: (displayed_5l_depth_usdt, half_spread_bps)} from latest live book_top."""
    prof: dict[str, tuple[float | None, float | None]] = {}
    for sym in symbols:
        row = con.execute(
            "SELECT b.bid, b.ask, b.bid_qty, b.ask_qty, b.depth "
            "FROM book_top b JOIN instruments i ON i.instrument_id = b.instrument_id "
            "WHERE i.symbol = ? AND b.bid IS NOT NULL AND b.ask IS NOT NULL "
            "ORDER BY b.rowid DESC LIMIT 1",
            (sym,),
        ).fetchone()
        if not row:
            prof[sym] = (None, None)
            continue
        bid, ask, bq, aq, depth_raw = row
        bd, ad = dec(bid), dec(ask)
        mid = (bd + ad) / Decimal(2)
        half_sp = float((ad - bd) / mid * Decimal(5000)) if mid > 0 else None
        depth_usdt: float | None = None
        if depth_raw:
            try:
                d = json.loads(depth_raw)
                if isinstance(d, list) and len(d) == 2 and d[0] and d[1]:
                    bv = sum((dec(p) * dec(q) for p, q in d[0]), Decimal(0))
                    av = sum((dec(p) * dec(q) for p, q in d[1]), Decimal(0))
                    depth_usdt = float(min(bv, av))
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        if depth_usdt is None:
            depth_usdt = float(mid * min(dec(bq or "0"), dec(aq or "0")))
        prof[sym] = (depth_usdt, half_sp)
    return prof


def _train_dev_logistic_for_tilt(
    panel: dict[str, list[BarPoint]],
    signals: dict[datetime, dict[str, SleeveSignal]],
    dev_dates: list[datetime],
    symbols: tuple[str, ...],
    *,
    fee_rate: float = 0.0013,
) -> tuple[LogisticVetoGateway, float]:
    by_start = {s: {b.ts_start: b for b in panel.get(s, [])} for s in symbols}
    gw = LogisticVetoGateway()
    feats, y_bin, y_bps = [], [], []
    for i in range(0, len(dev_dates) - 6, 5):
        t0, t5 = dev_dates[i], dev_dates[i + 5]
        day = signals.get(t0, {})
        for sym, sig in day.items():
            parts = [v for v in (sig.s1_trend, sig.s5_defensive_gold) if v is not None]
            sc = sum(parts) / len(parts) if parts else 0.0
            if sc <= 0.05:
                continue
            b0, b5 = by_start[sym].get(t0), by_start[sym].get(t5)
            if not b0 or not b5 or b0.open <= 0:
                continue
            net_bps = ((b5.open - b0.open) / b0.open - 2.0 * fee_rate) * 10000.0
            feats.append(extract_gateway_features(sig, consensus_score=sc))
            y_bin.append(1 if net_bps > 0 else 0)
            y_bps.append(net_bps)
    if len(feats) >= 60:
        gw.fit(feats, y_bps)
    base_rate = sum(y_bin) / max(1, len(y_bin))
    return gw, base_rate


def _run_flexible_admm_arm(
    panel: dict[str, list[BarPoint]],
    signals: dict[datetime, dict[str, SleeveSignal]],
    eval_dates: list[datetime],
    symbols: tuple[str, ...],
    *,
    fee_rate: Decimal = Decimal("0.0013"),
    holding_horizon_days: float = 20.0,
    liq_profile: dict[str, tuple[float | None, float | None]] | None = None,
    use_depth_l2: bool = False,
    use_spread_l1: bool = False,
    ml_gw: LogisticVetoGateway | None = None,
    ml_base_rate: float = 0.50,
    crash_exit_dates: set[str] | None = None,
    tactical_bull_leverage: float = 1.0,
    cov_cache: dict[tuple[datetime, tuple[str, ...]], tuple[tuple[float, ...], ...]] | None = None,
) -> dict:
    """Self-financing exact-Decimal ADMM replay supporting 33-asset expansion, liquidity scaling, ML tilt & 4h exit."""
    by_start = {s: {b.ts_start: b for b in panel.get(s, [])} for s in symbols}
    by_avail = {s: {b.ts_avail: b for b in panel.get(s, [])} for s in symbols}
    dated_rets = _dated_returns_for(panel, symbols)
    cache = cov_cache if cov_cache is not None else {}

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    nav_by_date: dict[str, float] = {}
    sqrt_h = math.sqrt(holding_horizon_days)
    recent_port_rets: list[float] = []
    extra_borrow_cost = 0.0
    lev_days = 0
    prev_nav = 1000.0

    for idx in range(len(eval_dates) - 1):
        t_avail = eval_dates[idx]
        day_sigs = signals.get(t_avail, {})
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        for sym in symbols:
            nxt = by_start[sym].get(t_avail)
            cur = by_avail[sym].get(t_avail)
            if nxt is not None and nxt.open > 0:
                exec_prices[sym] = Decimal(str(nxt.open))
                last_mark[sym] = exec_prices[sym]
                if cur is not None and cur.entry_eligible:
                    tradable.add(sym)
            elif cur is not None and cur.close > 0:
                exec_prices[sym] = Decimal(str(cur.close))
                last_mark[sym] = exec_prices[sym]
            elif sym in last_mark:
                exec_prices[sym] = last_mark[sym]

        active_syms = tuple(s for s in symbols if s in day_sigs and s in exec_prices and s in tradable)
        if len(active_syms) < 2:
            targets = {s: 0.0 for s in symbols}
        elif crash_exit_dates is not None and t_avail.date().isoformat() in crash_exit_dates:
            # 4h crash circuit breaker: exit all crypto immediately, retain defensive gold only
            targets = {
                s: (0.25 if (s in ("PAXGUSDT", "XAUTUSDT") and (day_sigs.get(s) and (day_sigs[s].s5_defensive_gold or 0.0) > 0.2)) else 0.0)
                for s in symbols
            }
        else:
            cur_w = ledger.current_weights(active_syms, exec_prices)
            ckey = (t_avail, active_syms)
            cov_h = cache.get(ckey)
            if cov_h is None:
                win_trimmed = {}
                for s in active_syms:
                    dts, rts = dated_rets[s]
                    hi = bisect_right(dts, t_avail)
                    lo = max(0, hi - 60)
                    win_trimmed[s] = dict(zip(dts[lo:hi], rts[lo:hi], strict=True))
                cov_d = coarse_bar_shrunk_covariance_aligned(win_trimmed, active_syms, shrinkage=0.25)
                cov_h = tuple(tuple(v * holding_horizon_days for v in row) for row in cov_d)
                cache[ckey] = cov_h

            mu_gross, l1_costs, l2_costs = [], [], []
            for sym in active_syms:
                sig = day_sigs[sym]
                parts = [v for v in (sig.s1_trend, sig.s5_defensive_gold) if v is not None]
                raw_score = sum(parts) / len(parts) if parts else 0.0
                if ml_gw is not None and raw_score > 0.05:
                    feats = extract_gateway_features(sig, consensus_score=raw_score)
                    _, prob, _ = ml_gw.should_accept(feats, incremental_cost_bps=float(fee_rate) * 20000.0)
                    raw_score *= continuous_ml_tilt(prob, base_rate=ml_base_rate)
                vol_h_bps = sig.yang_zhang_vol * sqrt_h * 10000.0
                mu_bps = forecast_to_expected_return_bps(raw_score * 20.0, ic_prior=0.08, horizon_vol_bps=vol_h_bps)
                mu_gross.append(mu_bps / 10000.0)

                depth_u, hs_bps = (liq_profile or {}).get(sym, (None, None))
                l1_costs.append(
                    spread_aware_l1_cost(hs_bps, fee_rate=float(fee_rate)) if use_spread_l1 else float(fee_rate)
                )
                l2_costs.append(depth_scaled_l2_impact(depth_u) if use_depth_l2 else 0.0020)

            prob = OptimizationProblem(
                symbols=active_syms,
                expected_returns=tuple(mu_gross),
                current_weights=cur_w,
                covariance=cov_h,
                l1_fee_costs=tuple(l1_costs),
                l2_impact_costs=tuple(l2_costs),
                risk_aversion=2.0,
                max_weight=0.30,
                cash_buffer=0.05,
            )
            solved = solve_convex_portfolio(prob).weights
            targets = {s: 0.0 for s in symbols}
            for s, w in zip(active_syms, solved, strict=True):
                targets[s] = w

        ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
        raw_nav = float(ledger.mark_nav(exec_prices))

        # Optional tactical bull-regime leverage overlay (Experiment C3) charging exact 0.09%/day borrow on extra slice
        if tactical_bull_leverage > 1.0 and prev_nav > 0:
            day_ret = raw_nav / prev_nav - 1.0
            recent_port_rets.append(day_ret)
            sample_sig = next(iter(day_sigs.values()), None)
            br = sample_sig.crypto_breadth if sample_sig else 0.0
            ann_vol = (
                math.sqrt(sum(r * r for r in recent_port_rets[-30:]) / len(recent_port_rets[-30:])) * math.sqrt(365.0)
                if len(recent_port_rets) >= 20
                else 1.0
            )
            if br is not None and br >= 0.75 and ann_vol < 0.25:
                extra_mult = tactical_bull_leverage - 1.0
                borrow_day = prev_nav * extra_mult * 0.0009
                extra_borrow_cost += borrow_day
                lev_days += 1
                adj_nav = max(1.0, prev_nav * (1.0 + tactical_bull_leverage * day_ret) - borrow_day)
            else:
                adj_nav = max(1.0, prev_nav * (1.0 + day_ret))
            nav_by_date[t_avail.date().isoformat()] = adj_nav
            prev_nav = adj_nav
        else:
            nav_by_date[t_avail.date().isoformat()] = raw_nav
            prev_nav = raw_nav

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    return {
        "nav_by_date": nav_by_date,
        "metrics_full": _portfolio_metrics(nav_by_date),
        "metrics_stress": _portfolio_metrics({k: v for k, v in nav_by_date.items() if k >= stress_iso}),
        "total_fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "turnover_multiple": round(float(ledger.cumulative_turnover_quote / ledger.starting_cash), 2),
        "extra_borrow_usdt": round(extra_borrow_cost, 2),
        "levered_days": lev_days,
    }


def run_expansion_and_margin_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Execute Experiments A (33-market + liquidity), B (ML tilt + 4h exit), and C (margin shorts/pairs/leverage)."""
    con = open_readonly_market_db(db_path)
    try:
        panel_33 = {sym: load_keyed_candles(con, sym, "1d", limit=2500) for sym in EXPANDED_33_SYMBOLS}
        liq_prof = _live_liquidity_profile(con, EXPANDED_33_SYMBOLS)
        core_crypto_4h = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT")
        panel_6h = {
            sym: resample_hourly_to_bucket(load_keyed_candles(con, sym, "1h", limit=25000), 6)
            for sym in core_crypto_4h
        }
    finally:
        con.close()

    panel_13 = {sym: panel_33[sym] for sym in BASE_13_SYMBOLS}
    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    sigs_33 = compute_multi_asset_sleeves(panel_33, EXPANDED_33_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    dev_dates = [d for d in eval_dates if d < STRESS_REPLAY_START]

    # Standing Leader baseline (13-asset DROP_S2)
    base_13 = _run_self_financing_arm("DROP_S2", panel_13, sigs_13, eval_dates)
    base_rets = _daily_returns_map(base_13["nav_by_date"])

    # Experiment A: 33-Market Multi-Asset Expansion (shared causal covariance cache across 33-asset arms)
    cov_cache_33: dict[tuple[datetime, tuple[str, ...]], tuple[tuple[float, ...], ...]] = {}
    cov_cache_13: dict[tuple[datetime, tuple[str, ...]], tuple[tuple[float, ...], ...]] = {}
    exp_a_plain = _run_flexible_admm_arm(panel_33, sigs_33, eval_dates, EXPANDED_33_SYMBOLS, cov_cache=cov_cache_33)
    exp_a_depth = _run_flexible_admm_arm(
        panel_33, sigs_33, eval_dates, EXPANDED_33_SYMBOLS, liq_profile=liq_prof, use_depth_l2=True, cov_cache=cov_cache_33
    )
    exp_a_full_liq = _run_flexible_admm_arm(
        panel_33,
        sigs_33,
        eval_dates,
        EXPANDED_33_SYMBOLS,
        liq_profile=liq_prof,
        use_depth_l2=True,
        use_spread_l1=True,
        cov_cache=cov_cache_33,
    )
    exp_a_nobitex = _run_flexible_admm_arm(
        panel_33,
        sigs_33,
        eval_dates,
        EXPANDED_33_SYMBOLS,
        fee_rate=Decimal("0.00091"),
        liq_profile=liq_prof,
        use_depth_l2=True,
        cov_cache=cov_cache_33,
    )

    # Experiment B: Continuous ML Sizing Tilt + Asymmetric 4h Crash Exit (on both 13 and 33 assets)
    gw_13, br_13 = _train_dev_logistic_for_tilt(panel_13, sigs_13, dev_dates, BASE_13_SYMBOLS)
    gw_33, br_33 = _train_dev_logistic_for_tilt(panel_33, sigs_33, dev_dates, EXPANDED_33_SYMBOLS)
    crash_dates_4h = compute_4h_crash_exit_dates(panel_6h, core_crypto_4h)

    exp_b_ml_13 = _run_flexible_admm_arm(
        panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, ml_gw=gw_13, ml_base_rate=br_13, cov_cache=cov_cache_13
    )
    exp_b_4h_13 = _run_flexible_admm_arm(
        panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, crash_exit_dates=crash_dates_4h, cov_cache=cov_cache_13
    )
    exp_b_combo_33 = _run_flexible_admm_arm(
        panel_33,
        sigs_33,
        eval_dates,
        EXPANDED_33_SYMBOLS,
        liq_profile=liq_prof,
        use_depth_l2=True,
        ml_gw=gw_33,
        ml_base_rate=br_33,
        crash_exit_dates=crash_dates_4h,
        cov_cache=cov_cache_33,
    )

    # Experiment C: Paper Margin (Crash Shorts, Market-Neutral L1 Pairs, Tactical 1.35x Bull Leverage)
    exp_c_shorts = simulate_wallex_margin_short_cascades(panel_33, sigs_33, eval_dates)
    crypto_only_33 = tuple(s for s in EXPANDED_33_SYMBOLS if s not in COMMODITY_SYMBOLS)
    exp_c_pairs = simulate_market_neutral_l1_pairs(panel_33, sigs_33, eval_dates, crypto_only_33)
    exp_c_lev_13 = _run_flexible_admm_arm(
        panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, tactical_bull_leverage=1.35, cov_cache=cov_cache_13
    )

    def _pack(name: str, arm: dict, *, is_base: bool = False) -> dict:
        up = (
            {"status": "BASELINE", "mean_uplift": 0.0, "ci_95": [0.0, 0.0]}
            if is_base
            else paired_baseline_uplift(_daily_returns_map(arm["nav_by_date"]), base_rets, simulations=499, seed=42)
        )
        return {
            "name": name,
            "full": arm["metrics_full"],
            "stress": arm["metrics_stress"],
            "fees_usdt": arm["total_fees_usdt"],
            "turnover": arm["turnover_multiple"],
            "extra_borrow_usdt": arm.get("extra_borrow_usdt", 0.0),
            "levered_days": arm.get("levered_days", 0),
            "uplift_vs_base13": up,
        }

    spot_arms = [
        _pack("BASE_13_S1_S5_LEADER", base_13, is_base=True),
        _pack("EXP_A1_33_ASSETS_PLAIN", exp_a_plain),
        _pack("EXP_A2_33_ASSETS_DEPTH_L2", exp_a_depth),
        _pack("EXP_A3_33_ASSETS_DEPTH_L2_SPREAD_L1", exp_a_full_liq),
        _pack("EXP_A4_33_ASSETS_NOBITEX_FEE", exp_a_nobitex),
        _pack("EXP_B1_13_ASSETS_ML_CONTINUOUS_TILT", exp_b_ml_13),
        _pack("EXP_B2_13_ASSETS_4H_CRASH_EXIT", exp_b_4h_13),
        _pack("EXP_B3_33_ASSETS_DEPTH_ML_4H_COMBO", exp_b_combo_33),
        _pack("EXP_C3_13_ASSETS_TACTICAL_1.35X_BULL", exp_c_lev_13),
    ]

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "eval_days": len(eval_dates),
        "crash_exit_4h_days_triggered": len(crash_dates_4h),
        "spot_and_overlay_arms": spot_arms,
        "margin_standalone_arms": [asdict(exp_c_shorts), asdict(exp_c_pairs)],
    }

    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, summary)
    return summary


def _write_markdown(report_path: Path, summary: dict) -> None:
    lines = [
        "# Experiments A, B, and C: 33-Market Multi-Asset Expansion, ML Tilt + 4h Exit, and Paper Margin",
        "",
        f"- **Generated:** `{summary['generated_at']}`",
        f"- **Eval Days:** `{summary['eval_days']}` (`2022-06-01..2026-11-24`, `$1,000` start, exact `SelfFinancingLedger`)",
        f"- **4h Crash Circuit-Breaker Days Triggered:** `{summary['crash_exit_4h_days_triggered']}`",
        "- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`",
        "",
        "## 1. Spot Multi-Asset, Liquidity-Scaled ADMM, ML Tilt, 4h Exit & Tactical Leverage",
        "",
        "| Arm | Ending NAV | Full Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Fees ($) | Borrow ($) | Turnover | Uplift vs 13-Asset Leader (bps/day, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in summary["spot_and_overlay_arms"]:
        mf, ms = r["full"], r["stress"]
        up = r["uplift_vs_base13"]
        up_bps = float(up.get("mean_uplift", 0.0)) * 10000.0
        ci = up.get("ci_95", [0.0, 0.0])
        lines.append(
            f"| `{r['name']}` | `${mf['ending_nav']:.2f}` | `{mf['ret_pct']:+.2f}%` | `{mf['ann_sharpe']:.3f}` | "
            f"`{mf['max_dd_pct']:.2f}%` | `{ms['ret_pct']:+.2f}%` | `${r['fees_usdt']:.2f}` | `${r['extra_borrow_usdt']:.2f}` | "
            f"`{r['turnover']:.1f}x` | `{up_bps:+.2f}` `[{ci[0]*10000:+.2f}, {ci[1]*10000:+.2f}]` (`{up.get('status')}`) |"
        )

    lines.extend([
        "",
        "## 2. Standalone Paper Margin Strategies (Exact Wallex `0.015%/4h` = `32.85%/yr` Borrow + Bar-High Liquidations)",
        "",
        "| Strategy | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Trades | Liquidations | Borrow ($) | Fees+Slip ($) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for m in summary["margin_standalone_arms"]:
        lines.append(
            f"| `{m['name']}` | `${m['ending_nav']:.2f}` | `{m['ret_pct']:+.2f}%` | `{m['ann_sharpe']:.3f}` | "
            f"`{m['max_dd_pct']:.2f}%` | `{m['trades']}` | `{m['liquidations']}` | `${m['total_borrow_usdt']:.2f}` | `${m['total_fees_usdt']:.2f}` |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
