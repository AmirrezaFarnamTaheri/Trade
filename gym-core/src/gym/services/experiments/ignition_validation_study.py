"""Three-part validation: (1) Ignition live-spread stress + 2h shift, (2) Shared-ledger 70/30 blend, (3) True intraday 3h exit."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.ignition_and_intraday_exit import (
    compute_intraday_crash_timestamps,
    pearson_correlation,
    run_shared_ledger_1h_blend,
    run_true_intraday_3h_exit,
    simulate_ignition_detailed,
)
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import (
    build_dated_returns_index,
    build_shrunk_horizon_cov,
    solve_s1_s5_admm_weights,
)
from .ensemble_study import STRESS_REPLAY_START, _daily_returns_map, _portfolio_metrics

CORE_8_IGNITION = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT")


def _extract_daily_s1_s5_targets(
    panel_1d: dict[str, list[BarPoint]],
    signals_1d: dict,
    eval_dates: list[datetime],
    symbols: tuple[str, ...],
    *,
    fee_rate: Decimal = Decimal("0.0013"),
    holding_horizon_days: float = 20.0,
) -> dict[datetime, dict[str, float]]:
    """Compute exact daily DROP_S2 (S1+S5) ADMM target weight schedule keyed by causal ts_avail (00:00Z)."""
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in symbols}
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in symbols}
    dated_rets = build_dated_returns_index(panel_1d, symbols)

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    schedule: dict[datetime, dict[str, float]] = {}

    for t_avail in eval_dates[:-1]:
        day_sigs = signals_1d.get(t_avail, {})
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

        active = tuple(s for s in symbols if s in day_sigs and s in exec_prices)
        if len(active) < 2:
            targets = {s: 0.0 for s in symbols}
        else:
            cur_w = ledger.current_weights(active, exec_prices)
            cov_h = build_shrunk_horizon_cov(dated_rets, active, t_avail, holding_horizon_days=holding_horizon_days)
            solved = solve_s1_s5_admm_weights(
                active, day_sigs, cur_w, cov_h,
                fee_rate=float(fee_rate), holding_horizon_days=holding_horizon_days,
            )
            targets = {s: 0.0 for s in symbols}
            for s, w in zip(active, solved, strict=True):
                targets[s] = w
        ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
        schedule[t_avail] = targets
    return schedule


def _pack_arm(name: str, res: dict, base_rets: dict[str, float] | None, *, stress_iso: str) -> dict:
    nav = res["nav_by_date"]
    rets = _daily_returns_map(nav)
    up = (
        {"status": "BASELINE", "mean_uplift": 0.0, "ci_95": [0.0, 0.0]}
        if base_rets is None
        else paired_baseline_uplift(rets, base_rets, simulations=499, seed=42)
    )
    return {
        "name": name,
        "full": _portfolio_metrics(nav),
        "stress": _portfolio_metrics({k: v for k, v in nav.items() if k >= stress_iso}),
        "fills": res.get("fills", 0),
        "fees_usdt": res.get("total_fees_usdt", 0.0),
        "turnover": res.get("turnover_multiple", 0.0),
        "intraday_exits": res.get("intraday_exits", 0),
        "uplift_vs_baseline": up,
    }


def run_ignition_validation_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Execute all 3 requested validations read-only against data/live/market.db."""
    con = open_readonly_market_db(db_path)
    try:
        panel_13_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_13_1h = {s: load_keyed_candles(con, s, "1h", limit=25000) for s in BASE_13_SYMBOLS}
    finally:
        con.close()

    sigs_13_1d = compute_slow_sleeves(panel_13_1d, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13_1d) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_breadth = {}
    for ts, d in sigs_13_1d.items():
        first = next(iter(d.values()), None)
        if first and first.crypto_breadth is not None:
            daily_breadth[ts.date().isoformat()] = first.crypto_breadth

    # Part 1: Realistic Live-Spread Stress Test on IGNITION_1H & IGNITION_2H (+1h offset check)
    p_8_1h = {s: panel_13_1h[s] for s in CORE_8_IGNITION}
    p_8_2h_0 = {s: resample_hourly_to_bucket(panel_13_1h[s], 2, offset_hours=0) for s in CORE_8_IGNITION}
    p_8_2h_1 = {s: resample_hourly_to_bucket(panel_13_1h[s], 2, offset_hours=1) for s in CORE_8_IGNITION}

    ig_1h_13, nav_ig1h_13, targets_ig1h_13 = simulate_ignition_detailed(
        p_8_1h, CORE_8_IGNITION, daily_breadth, label="IGNITION_1H_FEE13", bucket_hours=1, fee_rate=Decimal("0.0013")
    )
    ig_1h_16, nav_ig1h_16, targets_ig1h_16 = simulate_ignition_detailed(
        p_8_1h, CORE_8_IGNITION, daily_breadth, label="IGNITION_1H_NOBITEX_ALLIN_16BPS", bucket_hours=1, fee_rate=Decimal("0.0016")
    )
    ig_1h_25, nav_ig1h_25, targets_ig1h_25 = simulate_ignition_detailed(
        p_8_1h, CORE_8_IGNITION, daily_breadth, label="IGNITION_1H_WALLEX_ALLIN_25BPS", bucket_hours=1, fee_rate=Decimal("0.0025")
    )
    ig_2h_0_16, _, _ = simulate_ignition_detailed(
        p_8_2h_0, CORE_8_IGNITION, daily_breadth, label="IGNITION_2H_0H_NOBITEX_16BPS", bucket_hours=2, offset_hours=0, fee_rate=Decimal("0.0016")
    )
    ig_2h_1_16, _, _ = simulate_ignition_detailed(
        p_8_2h_1, CORE_8_IGNITION, daily_breadth, label="IGNITION_2H_1H_SHIFT_NOBITEX_16BPS", bucket_hours=2, offset_hours=1, fee_rate=Decimal("0.0016")
    )
    ig_2h_0_25, _, _ = simulate_ignition_detailed(
        p_8_2h_0, CORE_8_IGNITION, daily_breadth, label="IGNITION_2H_0H_WALLEX_25BPS", bucket_hours=2, offset_hours=0, fee_rate=Decimal("0.0025")
    )
    ig_2h_1_25, _, _ = simulate_ignition_detailed(
        p_8_2h_1, CORE_8_IGNITION, daily_breadth, label="IGNITION_2H_1H_SHIFT_WALLEX_25BPS", bucket_hours=2, offset_hours=1, fee_rate=Decimal("0.0025")
    )

    stress_iso = STRESS_REPLAY_START.date().isoformat()

    # Part 2: Exact Shared-Ledger 1h Blend (70% BASE_13_S1_S5 + 30% IGNITION_1H) vs 100% BASE_13 on identical 1h clock
    daily_sched_13 = _extract_daily_s1_s5_targets(panel_13_1d, sigs_13_1d, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0013"))
    empty_ign: dict[datetime, dict[str, float]] = {}

    solo_13 = run_shared_ledger_1h_blend(panel_13_1h, BASE_13_SYMBOLS, daily_sched_13, empty_ign, slow_weight=1.0, ignition_weight=0.0, fee_rate=Decimal("0.0013"))
    blend_70_30_13 = run_shared_ledger_1h_blend(panel_13_1h, BASE_13_SYMBOLS, daily_sched_13, targets_ig1h_13, slow_weight=0.70, ignition_weight=0.30, fee_rate=Decimal("0.0013"))
    blend_80_20_13 = run_shared_ledger_1h_blend(panel_13_1h, BASE_13_SYMBOLS, daily_sched_13, targets_ig1h_13, slow_weight=0.80, ignition_weight=0.20, fee_rate=Decimal("0.0013"))

    solo_16 = run_shared_ledger_1h_blend(panel_13_1h, BASE_13_SYMBOLS, daily_sched_13, empty_ign, slow_weight=1.0, ignition_weight=0.0, fee_rate=Decimal("0.0016"))
    blend_70_30_16 = run_shared_ledger_1h_blend(panel_13_1h, BASE_13_SYMBOLS, daily_sched_13, targets_ig1h_16, slow_weight=0.70, ignition_weight=0.30, fee_rate=Decimal("0.0016"))

    solo_25 = run_shared_ledger_1h_blend(panel_13_1h, BASE_13_SYMBOLS, daily_sched_13, empty_ign, slow_weight=1.0, ignition_weight=0.0, fee_rate=Decimal("0.0025"))
    blend_70_30_25 = run_shared_ledger_1h_blend(panel_13_1h, BASE_13_SYMBOLS, daily_sched_13, targets_ig1h_25, slow_weight=0.70, ignition_weight=0.30, fee_rate=Decimal("0.0025"))

    solo_rets_13 = _daily_returns_map(solo_13["nav_by_date"])
    ig_rets_13 = _daily_returns_map(nav_ig1h_13)
    corr_full = pearson_correlation(solo_rets_13, ig_rets_13)
    corr_stress = pearson_correlation(
        {k: v for k, v in solo_rets_13.items() if k >= stress_iso},
        {k: v for k, v in ig_rets_13.items() if k >= stress_iso},
    )

    blend_rows = [
        _pack_arm("SOLO_100_S1_S5_FEE13", solo_13, None, stress_iso=stress_iso),
        _pack_arm("BLEND_70_30_S1S5_IGN1H_FEE13", blend_70_30_13, solo_rets_13, stress_iso=stress_iso),
        _pack_arm("BLEND_80_20_S1S5_IGN1H_FEE13", blend_80_20_13, solo_rets_13, stress_iso=stress_iso),
        _pack_arm("SOLO_100_S1_S5_NOBITEX_16BPS", solo_16, None, stress_iso=stress_iso),
        _pack_arm("BLEND_70_30_NOBITEX_16BPS", blend_70_30_16, _daily_returns_map(solo_16["nav_by_date"]), stress_iso=stress_iso),
        _pack_arm("SOLO_100_S1_S5_WALLEX_25BPS", solo_25, None, stress_iso=stress_iso),
        _pack_arm("BLEND_70_30_WALLEX_25BPS", blend_70_30_25, _daily_returns_map(solo_25["nav_by_date"]), stress_iso=stress_iso),
    ]

    # Part 3: True Intraday 3h Execution Exit (Immediate next-3h-bar-open exit on crash, 0h & +1h offset)
    p_13_3h_0 = {s: resample_hourly_to_bucket(panel_13_1h[s], 3, offset_hours=0) for s in BASE_13_SYMBOLS}
    p_13_3h_1 = {s: resample_hourly_to_bucket(panel_13_1h[s], 3, offset_hours=1) for s in BASE_13_SYMBOLS}
    crash_ts_3h_0 = compute_intraday_crash_timestamps({s: p_13_3h_0[s] for s in CORE_8_IGNITION}, CORE_8_IGNITION, bucket_hours=3)
    crash_ts_3h_1 = compute_intraday_crash_timestamps({s: p_13_3h_1[s] for s in CORE_8_IGNITION}, CORE_8_IGNITION, bucket_hours=3)

    intraday_base_3h = run_true_intraday_3h_exit(p_13_3h_0, BASE_13_SYMBOLS, daily_sched_13, set(), fee_rate=Decimal("0.0013"))
    intraday_exit_3h_0 = run_true_intraday_3h_exit(p_13_3h_0, BASE_13_SYMBOLS, daily_sched_13, crash_ts_3h_0, fee_rate=Decimal("0.0013"))
    intraday_exit_3h_1 = run_true_intraday_3h_exit(p_13_3h_1, BASE_13_SYMBOLS, daily_sched_13, crash_ts_3h_1, fee_rate=Decimal("0.0013"))
    intraday_exit_3h_16 = run_true_intraday_3h_exit(p_13_3h_0, BASE_13_SYMBOLS, daily_sched_13, crash_ts_3h_0, fee_rate=Decimal("0.0016"))

    base_3h_rets = _daily_returns_map(intraday_base_3h["nav_by_date"])
    intraday_rows = [
        _pack_arm("BASE_3H_CLOCK_NO_EXIT_FEE13", intraday_base_3h, None, stress_iso=stress_iso),
        _pack_arm("TRUE_INTRADAY_3H_EXIT_0H_FEE13", intraday_exit_3h_0, base_3h_rets, stress_iso=stress_iso),
        _pack_arm("TRUE_INTRADAY_3H_EXIT_1H_SHIFT_FEE13", intraday_exit_3h_1, base_3h_rets, stress_iso=stress_iso),
        _pack_arm("TRUE_INTRADAY_3H_EXIT_0H_NOBITEX_16BPS", intraday_exit_3h_16, base_3h_rets, stress_iso=stress_iso),
    ]

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "correlation_s1s5_vs_ignition1h": {"full_1043d": corr_full, "bear_stress_366d": corr_stress},
        "part1_ignition_spread_stress": [
            asdict(ig_1h_13),
            asdict(ig_1h_16),
            asdict(ig_1h_25),
            asdict(ig_2h_0_16),
            asdict(ig_2h_1_16),
            asdict(ig_2h_0_25),
            asdict(ig_2h_1_25),
        ],
        "part2_shared_ledger_blend": blend_rows,
        "part3_true_intraday_3h_exit": intraday_rows,
        "crash_3h_bar_triggers": {"offset_0h": len(crash_ts_3h_0), "offset_1h": len(crash_ts_3h_1)},
    }

    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, summary)
    return summary


def _write_markdown(report_path: Path, summary: dict) -> None:
    corr = summary["correlation_s1s5_vs_ignition1h"]
    lines = [
        "# 3-Part Validation: Ignition Live-Spread Stress, Shared-Ledger 70/30 Blend, and True Intraday 3h Exit",
        "",
        f"- **Generated:** `{summary['generated_at']}`",
        f"- **Daily Return Correlation (`S1+S5` vs `IGNITION_1H`):** Full `1,043d` = **`{corr['full_1043d']:+.4f}`**, Bear Stress `366d` = **`{corr['bear_stress_366d']:+.4f}`**",
        "- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`",
        "",
        "## 1. Part 1 — Realistic Live-Spread Stress Test (`IGNITION_1H` & `IGNITION_2H` + `+1h` Offset)",
        "",
        "| Sleeve | Bar | Offset | All-In Cost (bps/leg) | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Entries | Win % | Fees+Spread ($) |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in summary["part1_ignition_spread_stress"]:
        lines.append(
            f"| `{r['label']}` | `{r['bucket_hours']}h` | `+{r['offset_hours']}h` | `{r['fee_bps']:.1f}` | "
            f"`${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | "
            f"`{r['entries']}` | `{r['win_rate_pct']:.1f}%` | `${r['fees_usdt']:.2f}` |"
        )

    lines.extend([
        "",
        "## 2. Part 2 — Single Shared-Ledger Combined Portfolio (`S1+S5` + `IGNITION_1H`, Exact `1h` Overlap)",
        "",
        "| Arm | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Fees ($) | Turnover | Paired Uplift vs Matched Solo (bps/day, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for r in summary["part2_shared_ledger_blend"]:
        mf, ms, up = r["full"], r["stress"], r["uplift_vs_baseline"]
        up_bps = float(up.get("mean_uplift", 0.0)) * 10000.0
        ci = up.get("ci_95", [0.0, 0.0])
        lines.append(
            f"| `{r['name']}` | `${mf['ending_nav']:.2f}` | `{mf['ret_pct']:+.2f}%` | `{mf['ann_sharpe']:.3f}` | "
            f"`{mf['max_dd_pct']:.2f}%` | `{ms['ret_pct']:+.2f}%` | `${r['fees_usdt']:.2f}` | `{r['turnover']:.1f}x` | "
            f"`{up_bps:+.2f}` `[{ci[0]*10000:+.2f}, {ci[1]*10000:+.2f}]` (`{up.get('status')}`) |"
        )

    lines.extend([
        "",
        "## 3. Part 3 — True Intraday `3h` Execution Exit (Immediate Next-`3h`-Open Exit, Zero Lookahead)",
        "",
        "| Arm | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Intraday Exits | Fees ($) | Paired Uplift vs No-Exit (bps/day, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for r in summary["part3_true_intraday_3h_exit"]:
        mf, ms, up = r["full"], r["stress"], r["uplift_vs_baseline"]
        up_bps = float(up.get("mean_uplift", 0.0)) * 10000.0
        ci = up.get("ci_95", [0.0, 0.0])
        lines.append(
            f"| `{r['name']}` | `${mf['ending_nav']:.2f}` | `{mf['ret_pct']:+.2f}%` | `{mf['ann_sharpe']:.3f}` | "
            f"`{mf['max_dd_pct']:.2f}%` | `{ms['ret_pct']:+.2f}%` | `{r['intraday_exits']}` | `${r['fees_usdt']:.2f}` | "
            f"`{up_bps:+.2f}` `[{ci[0]*10000:+.2f}, {ci[1]*10000:+.2f}]` (`{up.get('status')}`) |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
