"""Study comparing 18-asset macro core, 3h/6h/2h crash breakers (+1h offset), family-differentiated 33 assets, and rare 1h/2h/3h ignition."""
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
from ...domain.family_and_ignition import (
    FAMILY_POLICIES,
    MACRO_18_SYMBOLS,
    SATELLITE_ALT_15,
    compute_family_differentiated_sleeves,
    compute_intraday_crash_exit_dates,
    family_of_symbol,
    simulate_rare_momentum_ignition,
)
from ...domain.multi_asset_research import (
    BASE_13_SYMBOLS,
    DEFENSIVE_GOLD_SYMBOLS,
    EXPANDED_33_SYMBOLS,
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


def _dated_returns_indexed(panel: dict[str, list[BarPoint]], symbols: tuple[str, ...]) -> dict[str, tuple[list[datetime], list[float]]]:
    out: dict[str, tuple[list[datetime], list[float]]] = {}
    for s in symbols:
        bars = panel.get(s, [])
        dts, rets = [], []
        for i in range(1, len(bars)):
            if bars[i - 1].close > 0:
                dts.append(bars[i].ts_avail)
                rets.append((bars[i].close - bars[i - 1].close) / bars[i - 1].close)
        out[s] = (dts, rets)
    return out


def _apply_family_caps_and_crash(
    active_syms: tuple[str, ...],
    solved: list[float],
    *,
    in_crash: bool,
    use_family_rules: bool,
    satellite_family_cap: float,
) -> list[float]:
    if use_family_rules:
        sat_indices = []
        for i, sym in enumerate(active_syms):
            pol = FAMILY_POLICIES[family_of_symbol(sym)]
            if in_crash and pol.exit_on_crypto_crash:
                solved[i] = 0.0
            else:
                solved[i] = min(solved[i], pol.max_weight)
            if sym in SATELLITE_ALT_15:
                sat_indices.append(i)
        sat_sum = sum(solved[i] for i in sat_indices)
        if sat_sum > satellite_family_cap and sat_sum > 0:
            scale = satellite_family_cap / sat_sum
            for i in sat_indices:
                solved[i] *= scale
    elif in_crash:
        for i, sym in enumerate(active_syms):
            if sym not in DEFENSIVE_GOLD_SYMBOLS:
                solved[i] = 0.0
    return solved


def _family_expected_returns(
    active_syms: tuple[str, ...],
    cur_w: tuple[float, ...],
    day_sigs: dict[str, SleeveSignal],
    *,
    in_crash: bool,
    use_family_rules: bool,
    sqrt_h: float,
) -> tuple[float, ...]:
    mu_gross = []
    for sym, cw in zip(active_syms, cur_w, strict=True):
        sig = day_sigs[sym]
        fam = family_of_symbol(sym)
        pol = FAMILY_POLICIES[fam]
        parts = [v for v in (sig.s1_trend, sig.s5_defensive_gold) if v is not None]
        raw_score = sum(parts) / len(parts) if parts else 0.0
        if in_crash and pol.exit_on_crypto_crash:
            raw_score = -1.0
        elif use_family_rules and fam == "ALT_SATELLITES":
            br = sig.crypto_breadth if sig.crypto_breadth is not None else 0.0
            is_held = cw > 0.005
            if (not is_held and (br < pol.min_breadth_for_entry or raw_score < pol.min_s1_entry)) or (
                is_held and br < pol.breadth_exit_floor
            ):
                raw_score = 0.0
        ic = pol.ic_prior if use_family_rules else 0.08
        vol_h_bps = sig.yang_zhang_vol * sqrt_h * 10000.0
        mu_gross.append(forecast_to_expected_return_bps(raw_score * 20.0, ic_prior=ic, horizon_vol_bps=vol_h_bps) / 10000.0)
    return tuple(mu_gross)


def _run_family_admm_arm(
    panel: dict[str, list[BarPoint]],
    signals: dict[datetime, dict[str, SleeveSignal]],
    eval_dates: list[datetime],
    symbols: tuple[str, ...],
    *,
    fee_rate: Decimal = Decimal("0.0013"),
    holding_horizon_days: float = 20.0,
    crash_exit_dates: set[str] | None = None,
    use_family_rules: bool = True,
    satellite_family_cap: float = 0.25,
    cov_cache: dict[tuple[datetime, tuple[str, ...]], tuple[tuple[float, ...], ...]] | None = None,
) -> dict:
    """Self-financing ADMM replay with family-differentiated signal gates, caps, and non-crypto crash immunity."""
    by_start = {s: {b.ts_start: b for b in panel.get(s, [])} for s in symbols}
    by_avail = {s: {b.ts_avail: b for b in panel.get(s, [])} for s in symbols}
    dated_rets = _dated_returns_indexed(panel, symbols)
    cache = cov_cache if cov_cache is not None else {}

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    nav_by_date: dict[str, float] = {}
    sqrt_h = math.sqrt(holding_horizon_days)

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
                if nxt.entry_eligible and cur is not None and cur.entry_eligible:
                    tradable.add(sym)
            elif cur is not None and cur.close > 0:
                exec_prices[sym] = Decimal(str(cur.close))
                last_mark[sym] = exec_prices[sym]
            elif sym in last_mark:
                exec_prices[sym] = last_mark[sym]

        in_crash = crash_exit_dates is not None and t_avail.date().isoformat() in crash_exit_dates
        active_syms = tuple(s for s in symbols if s in day_sigs and s in exec_prices and s in tradable)

        if len(active_syms) < 2:
            targets = {s: 0.0 for s in symbols}
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

            mu_gross = _family_expected_returns(
                active_syms,
                cur_w,
                day_sigs,
                in_crash=in_crash,
                use_family_rules=use_family_rules,
                sqrt_h=sqrt_h,
            )
            prob = OptimizationProblem(
                symbols=active_syms,
                expected_returns=mu_gross,
                current_weights=cur_w,
                covariance=cov_h,
                l1_fee_costs=(float(fee_rate),) * len(active_syms),
                l2_impact_costs=(0.0020,) * len(active_syms),
                risk_aversion=2.0,
                max_weight=0.30,
                cash_buffer=0.05,
            )
            solved = _apply_family_caps_and_crash(
                active_syms,
                list(solve_convex_portfolio(prob).weights),
                in_crash=in_crash,
                use_family_rules=use_family_rules,
                satellite_family_cap=satellite_family_cap,
            )

            targets = {s: 0.0 for s in symbols}
            for s, w in zip(active_syms, solved, strict=True):
                targets[s] = w

        ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
        nav_by_date[t_avail.date().isoformat()] = float(ledger.mark_nav(exec_prices))

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    return {
        "nav_by_date": nav_by_date,
        "metrics_full": _portfolio_metrics(nav_by_date),
        "metrics_stress": _portfolio_metrics({k: v for k, v in nav_by_date.items() if k >= stress_iso}),
        "total_fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "turnover_multiple": round(float(ledger.cumulative_turnover_quote / ledger.starting_cash), 2),
    }


def run_family_and_timeframe_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Execute 18-asset macro core, 2h/3h/6h crash-breaker comparison (+1h shift), family-gated 33 assets, and 1h/2h/3h ignition."""
    core_8 = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT")
    con = open_readonly_market_db(db_path)
    try:
        panel_33_1d = {sym: load_keyed_candles(con, sym, "1d", limit=2500) for sym in EXPANDED_33_SYMBOLS}
        panel_8_1h = {sym: load_keyed_candles(con, sym, "1h", limit=25000) for sym in core_8}
    finally:
        con.close()

    panel_13 = {s: panel_33_1d[s] for s in BASE_13_SYMBOLS}
    panel_18 = {s: panel_33_1d[s] for s in MACRO_18_SYMBOLS}

    sigs_13 = compute_slow_sleeves(panel_13, BASE_13_SYMBOLS)
    sigs_18 = compute_family_differentiated_sleeves(panel_18, MACRO_18_SYMBOLS)
    sigs_33_fam = compute_family_differentiated_sleeves(panel_33_1d, EXPANDED_33_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]

    # Build strictly causal daily breadth map for the low-timeframe ignition sleeve
    daily_breadth = {}
    for ts, d in sigs_13.items():
        first = next(iter(d.values()), None)
        if first and first.crypto_breadth is not None:
            daily_breadth[ts.date().isoformat()] = first.crypto_breadth

    # Build 2h, 3h (0h & +1h), and 6h (0h & +1h) intraday crash exit sets
    p_2h_0 = {s: resample_hourly_to_bucket(panel_8_1h[s], 2, offset_hours=0) for s in core_8}
    p_3h_0 = {s: resample_hourly_to_bucket(panel_8_1h[s], 3, offset_hours=0) for s in core_8}
    p_3h_1 = {s: resample_hourly_to_bucket(panel_8_1h[s], 3, offset_hours=1) for s in core_8}
    p_6h_0 = {s: resample_hourly_to_bucket(panel_8_1h[s], 6, offset_hours=0) for s in core_8}
    p_6h_1 = {s: resample_hourly_to_bucket(panel_8_1h[s], 6, offset_hours=1) for s in core_8}

    crash_2h_0 = compute_intraday_crash_exit_dates(p_2h_0, core_8, bucket_hours=2)
    crash_3h_0 = compute_intraday_crash_exit_dates(p_3h_0, core_8, bucket_hours=3)
    crash_3h_1 = compute_intraday_crash_exit_dates(p_3h_1, core_8, bucket_hours=3)
    crash_6h_0 = compute_intraday_crash_exit_dates(p_6h_0, core_8, bucket_hours=6)
    crash_6h_1 = compute_intraday_crash_exit_dates(p_6h_1, core_8, bucket_hours=6)

    # Baseline 13-asset leader
    base_13 = _run_self_financing_arm("DROP_S2", panel_13, sigs_13, eval_dates)
    base_rets = _daily_returns_map(base_13["nav_by_date"])

    c13: dict = {}
    c18: dict = {}
    c33: dict = {}

    arms = [
        ("BASE_13_S1_S5", base_13, True),
        ("CORE_13_CRASH_2H_0H", _run_family_admm_arm(panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, crash_exit_dates=crash_2h_0, use_family_rules=False, cov_cache=c13), False),
        ("CORE_13_CRASH_3H_0H", _run_family_admm_arm(panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, crash_exit_dates=crash_3h_0, use_family_rules=False, cov_cache=c13), False),
        ("CORE_13_CRASH_3H_1H_SHIFT", _run_family_admm_arm(panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, crash_exit_dates=crash_3h_1, use_family_rules=False, cov_cache=c13), False),
        ("CORE_13_CRASH_6H_0H", _run_family_admm_arm(panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, crash_exit_dates=crash_6h_0, use_family_rules=False, cov_cache=c13), False),
        ("CORE_13_CRASH_6H_1H_SHIFT", _run_family_admm_arm(panel_13, sigs_13, eval_dates, BASE_13_SYMBOLS, crash_exit_dates=crash_6h_1, use_family_rules=False, cov_cache=c13), False),
        ("MACRO_18_FAMILY_ONLY", _run_family_admm_arm(panel_18, sigs_18, eval_dates, MACRO_18_SYMBOLS, use_family_rules=True, cov_cache=c18), False),
        ("MACRO_18_FAMILY_CRASH_3H", _run_family_admm_arm(panel_18, sigs_18, eval_dates, MACRO_18_SYMBOLS, crash_exit_dates=crash_3h_0, use_family_rules=True, cov_cache=c18), False),
        ("MACRO_18_FAMILY_CRASH_6H", _run_family_admm_arm(panel_18, sigs_18, eval_dates, MACRO_18_SYMBOLS, crash_exit_dates=crash_6h_0, use_family_rules=True, cov_cache=c18), False),
        ("MACRO_18_CRASH_3H_NOBITEX_FEE", _run_family_admm_arm(panel_18, sigs_18, eval_dates, MACRO_18_SYMBOLS, fee_rate=Decimal("0.00091"), crash_exit_dates=crash_3h_0, use_family_rules=True, cov_cache=c18), False),
        ("FAMILY_GATED_33_ASSETS_PLAIN", _run_family_admm_arm(panel_33_1d, sigs_33_fam, eval_dates, EXPANDED_33_SYMBOLS, use_family_rules=True, cov_cache=c33), False),
        ("FAMILY_GATED_33_ASSETS_CRASH_3H", _run_family_admm_arm(panel_33_1d, sigs_33_fam, eval_dates, EXPANDED_33_SYMBOLS, crash_exit_dates=crash_3h_0, use_family_rules=True, cov_cache=c33), False),
        ("FAMILY_GATED_33_ASSETS_CRASH_6H", _run_family_admm_arm(panel_33_1d, sigs_33_fam, eval_dates, EXPANDED_33_SYMBOLS, crash_exit_dates=crash_6h_0, use_family_rules=True, cov_cache=c33), False),
    ]

    portfolio_rows = []
    for name, res, is_base in arms:
        up = (
            {"status": "BASELINE", "mean_uplift": 0.0, "ci_95": [0.0, 0.0]}
            if is_base
            else paired_baseline_uplift(_daily_returns_map(res["nav_by_date"]), base_rets, simulations=499, seed=42)
        )
        portfolio_rows.append({
            "name": name,
            "full": res["metrics_full"],
            "stress": res["metrics_stress"],
            "fees_usdt": res["total_fees_usdt"],
            "turnover": res["turnover_multiple"],
            "uplift_vs_base13": up,
        })

    # Part 4: Rare Ultra-Strong High-Momentum Ignition Sleeve on 1h, 2h, and 3h bars (+1h offset & Nobitex fee)
    ignition_rows = [
        asdict(simulate_rare_momentum_ignition(panel_8_1h, core_8, daily_breadth, label="IGNITION_1H_WALLEX", bucket_hours=1, offset_hours=0, fee_rate=Decimal("0.0013"))),
        asdict(simulate_rare_momentum_ignition(panel_8_1h, core_8, daily_breadth, label="IGNITION_1H_NOBITEX", bucket_hours=1, offset_hours=0, fee_rate=Decimal("0.00091"))),
        asdict(simulate_rare_momentum_ignition(p_2h_0, core_8, daily_breadth, label="IGNITION_2H_0H_WALLEX", bucket_hours=2, offset_hours=0, fee_rate=Decimal("0.0013"))),
        asdict(simulate_rare_momentum_ignition(p_3h_0, core_8, daily_breadth, label="IGNITION_3H_0H_WALLEX", bucket_hours=3, offset_hours=0, fee_rate=Decimal("0.0013"))),
        asdict(simulate_rare_momentum_ignition(p_3h_1, core_8, daily_breadth, label="IGNITION_3H_1H_SHIFT_WALLEX", bucket_hours=3, offset_hours=1, fee_rate=Decimal("0.0013"))),
        asdict(simulate_rare_momentum_ignition(p_3h_0, core_8, daily_breadth, label="IGNITION_3H_0H_NOBITEX", bucket_hours=3, offset_hours=0, fee_rate=Decimal("0.00091"))),
    ]

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "eval_days": len(eval_dates),
        "crash_days_triggered": {
            "2h_0h": len(crash_2h_0),
            "3h_0h": len(crash_3h_0),
            "3h_1h": len(crash_3h_1),
            "6h_0h": len(crash_6h_0),
            "6h_1h": len(crash_6h_1),
        },
        "portfolio_arms": portfolio_rows,
        "ignition_sleeves": ignition_rows,
    }

    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, summary)
    return summary


def _write_markdown(report_path: Path, summary: dict) -> None:
    cd = summary["crash_days_triggered"]
    lines = [
        "# Multi-Timeframe (2h/3h/6h), Asset-Family Architecture (13 vs 18 vs 33), and Rare High-Momentum Ignition",
        "",
        f"- **Generated:** `{summary['generated_at']}`",
        f"- **Eval Days:** `{summary['eval_days']}` (`2022-06-01..2026-11-24`, `$1,000` start, exact `SelfFinancingLedger`)",
        f"- **Intraday Crash Days Triggered:** `2h={cd['2h_0h']}`, `3h(0h)={cd['3h_0h']}`, `3h(+1h)={cd['3h_1h']}`, `6h(0h)={cd['6h_0h']}`, `6h(+1h)={cd['6h_1h']}`",
        "- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`",
        "",
        "## 1. Portfolio Arms: 2h/3h/6h Crash Breakers (+1h Clock-Shift Check) & Family-Differentiated 18/33-Asset Cores",
        "",
        "| Arm | Ending NAV | Full Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Fees ($) | Turnover | Uplift vs Base 13 (bps/day, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in summary["portfolio_arms"]:
        mf, ms = r["full"], r["stress"]
        up = r["uplift_vs_base13"]
        up_bps = float(up.get("mean_uplift", 0.0)) * 10000.0
        ci = up.get("ci_95", [0.0, 0.0])
        lines.append(
            f"| `{r['name']}` | `${mf['ending_nav']:.2f}` | `{mf['ret_pct']:+.2f}%` | `{mf['ann_sharpe']:.3f}` | "
            f"`{mf['max_dd_pct']:.2f}%` | `{ms['ret_pct']:+.2f}%` | `${r['fees_usdt']:.2f}` | `{r['turnover']:.1f}x` | "
            f"`{up_bps:+.2f}` `[{ci[0]*10000:+.2f}, {ci[1]*10000:+.2f}]` (`{up.get('status')}`) |"
        )

    lines.extend([
        "",
        "## 2. Rare Ultra-Strong High-Momentum Ignition Sleeve (`1h`, `2h`, `3h` + `+1h` Clock-Shift & Nobitex Counterfactual)",
        "",
        "| Sleeve | Bar | Offset | Fee (bps) | Days | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Entries | Win % | Fees ($) |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for ig in summary["ignition_sleeves"]:
        lines.append(
            f"| `{ig['label']}` | `{ig['bucket_hours']}h` | `+{ig['offset_hours']}h` | `{ig['fee_bps']:.1f}` | `{ig['days']}` | "
            f"`${ig['ending_nav']:.2f}` | `{ig['ret_pct']:+.2f}%` | `{ig['ann_sharpe']:.3f}` | `{ig['max_dd_pct']:.2f}%` | "
            f"`{ig['entries']}` | `{ig['win_rate_pct']:.1f}%` | `${ig['fees_usdt']:.2f}` |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
