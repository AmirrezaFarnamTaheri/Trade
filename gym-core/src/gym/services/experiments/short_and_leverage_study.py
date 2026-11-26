"""Study unlocking short-selling and event-scoped leverage via rare 2h ignition + 3-engine all-weather blend."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.ignition_and_intraday_exit import (
    pearson_correlation,
    run_shared_ledger_1h_blend,
)
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.short_and_levered_ignition import simulate_levered_ignition
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import resample_hourly_to_bucket
from .ensemble_study import STRESS_REPLAY_START, _daily_returns_map, _portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .ignition_validation_study import CORE_8_IGNITION, _extract_daily_s1_s5_targets


def _combine_sleeve_navs(
    weights_and_navs: list[tuple[float, dict[str, float]]],
) -> dict[str, float]:
    """Combine sleeve daily return streams at fixed capital sleeve weights (rebalanced daily on overlapping dates)."""
    ret_maps = [_daily_returns_map(nav) for _, nav in weights_and_navs]
    common = sorted(set.intersection(*(set(r) for r in ret_maps)))
    if not common:
        return {}
    nav = 1000.0
    out = {}
    for d in common:
        r_tot = sum(w * rm[d] for (w, _), rm in zip(weights_and_navs, ret_maps, strict=True))
        nav = max(1.0, nav * (1.0 + r_tot))
        out[d] = nav
    return out


def _pack_combo(name: str, nav: dict[str, float], base_rets: dict[str, float] | None, *, stress_iso: str) -> dict:
    up = (
        {"status": "BASELINE", "mean_uplift": 0.0, "ci_95": [0.0, 0.0]}
        if base_rets is None
        else paired_baseline_uplift(_daily_returns_map(nav), base_rets, simulations=499, seed=42)
    )
    return {
        "name": name,
        "full": _portfolio_metrics(nav),
        "stress": _portfolio_metrics({k: v for k, v in nav.items() if k >= stress_iso}),
        "uplift_vs_solo": up,
    }


def run_short_and_leverage_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Evaluate 2h short-ignition, event-scoped levered long-ignition, and 3-engine all-weather blends."""
    all_1h_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    con = open_readonly_market_db(db_path)
    try:
        panel_13_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_all_1h = {s: load_keyed_candles(con, s, "1h", limit=25000) for s in all_1h_syms}
    finally:
        con.close()

    sigs_13_1d = compute_slow_sleeves(panel_13_1d, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13_1d) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_breadth = {}
    for ts, d in sigs_13_1d.items():
        first = next(iter(d.values()), None)
        if first and first.crypto_breadth is not None:
            daily_breadth[ts.date().isoformat()] = first.crypto_breadth

    p_18_2h_0 = {s: resample_hourly_to_bucket(panel_all_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    p_18_2h_1 = {s: resample_hourly_to_bucket(panel_all_1h[s], 2, offset_hours=1) for s in IGNITION_18_CRYPTO}
    p_8_2h_0 = {s: p_18_2h_0[s] for s in CORE_8_IGNITION}
    p_8_2h_1 = {s: p_18_2h_1[s] for s in CORE_8_IGNITION}

    # Part 1: Event-Scoped Leverage on 2h Long Ignition (1.0x vs 1.5x vs 2.0x, Nobitex 16 bps & Wallex 25 bps)
    l_1x_16, nav_l1_16 = simulate_levered_ignition(p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="LONG_IGN18_2H_1.0X_NBX16", side="LONG", leverage=1.0, leg_cost=0.0016)
    l_15x_16, nav_l15_16 = simulate_levered_ignition(p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="LONG_IGN18_2H_1.5X_NBX16", side="LONG", leverage=1.5, leg_cost=0.0016)
    l_2x_16, nav_l2_16 = simulate_levered_ignition(p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="LONG_IGN18_2H_2.0X_NBX16", side="LONG", leverage=2.0, leg_cost=0.0016)
    l_15x_shift_16, _ = simulate_levered_ignition(p_18_2h_1, IGNITION_18_CRYPTO, daily_breadth, label="LONG_IGN18_2H_1.5X_1HSHIFT_NBX16", side="LONG", leverage=1.5, offset_hours=1, leg_cost=0.0016)
    l_15x_25, nav_l15_25 = simulate_levered_ignition(p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="LONG_IGN18_2H_1.5X_WLX25", side="LONG", leverage=1.5, leg_cost=0.0025)
    l_2x_25, _ = simulate_levered_ignition(p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="LONG_IGN18_2H_2.0X_WLX25", side="LONG", leverage=2.0, leg_cost=0.0025)
    l8_15x_16, _ = simulate_levered_ignition(p_8_2h_0, CORE_8_IGNITION, daily_breadth, label="LONG_IGN8_2H_1.5X_NBX16", side="LONG", leverage=1.5, leg_cost=0.0016)

    # Part 2: 2h Downward Capitulation Short-Ignition (8 & 18 markets, 1.0x & 1.5x, 0h & +1h shift, 16 & 25 bps)
    s8_1x_16, nav_s8_1x_16 = simulate_levered_ignition(p_8_2h_0, CORE_8_IGNITION, daily_breadth, label="SHORT_IGN8_2H_1.0X_NBX16", side="SHORT", leverage=1.0, leg_cost=0.0016, hold_hours=36)
    s8_1x_shift_16, _ = simulate_levered_ignition(p_8_2h_1, CORE_8_IGNITION, daily_breadth, label="SHORT_IGN8_2H_1.0X_1HSHIFT_NBX16", side="SHORT", leverage=1.0, offset_hours=1, leg_cost=0.0016, hold_hours=36)
    s8_15x_16, nav_s8_15_16 = simulate_levered_ignition(p_8_2h_0, CORE_8_IGNITION, daily_breadth, label="SHORT_IGN8_2H_1.5X_NBX16", side="SHORT", leverage=1.5, leg_cost=0.0016, hold_hours=36)
    s18_1x_16, nav_s18_1x_16 = simulate_levered_ignition(p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="SHORT_IGN18_2H_1.0X_NBX16", side="SHORT", leverage=1.0, leg_cost=0.0016, hold_hours=36)
    s18_1x_shift_16, _ = simulate_levered_ignition(p_18_2h_1, IGNITION_18_CRYPTO, daily_breadth, label="SHORT_IGN18_2H_1.0X_1HSHIFT_NBX16", side="SHORT", leverage=1.0, offset_hours=1, leg_cost=0.0016, hold_hours=36)
    s18_15x_16, nav_s18_15_16 = simulate_levered_ignition(p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="SHORT_IGN18_2H_1.5X_NBX16", side="SHORT", leverage=1.5, leg_cost=0.0016, hold_hours=36)
    s18_1x_25, nav_s18_1x_25 = simulate_levered_ignition(p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="SHORT_IGN18_2H_1.0X_WLX25", side="SHORT", leverage=1.0, leg_cost=0.0025, hold_hours=36)
    s18_15x_25, _ = simulate_levered_ignition(p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="SHORT_IGN18_2H_1.5X_WLX25", side="SHORT", leverage=1.5, leg_cost=0.0025, hold_hours=36)

    # Part 3: Correlation Matrix & 3-Engine All-Weather Blends (Core 1d S1+S5 + Long 2h Ignition + Short 2h Ignition)
    daily_sched_13 = _extract_daily_s1_s5_targets(panel_13_1d, sigs_13_1d, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0013"))
    solo_16 = run_shared_ledger_1h_blend(panel_all_1h, all_1h_syms, daily_sched_13, {}, slow_weight=1.0, ignition_weight=0.0, fee_rate=Decimal("0.0016"))
    solo_25 = run_shared_ledger_1h_blend(panel_all_1h, all_1h_syms, daily_sched_13, {}, slow_weight=1.0, ignition_weight=0.0, fee_rate=Decimal("0.0025"))

    solo16_nav = solo_16["nav_by_date"]
    solo25_nav = solo_25["nav_by_date"]
    solo16_rets = _daily_returns_map(solo16_nav)
    solo25_rets = _daily_returns_map(solo25_nav)
    stress_iso = STRESS_REPLAY_START.date().isoformat()

    corrs = {
        "s1s5_vs_short18_1x": pearson_correlation(solo16_rets, _daily_returns_map(nav_s18_1x_16)),
        "s1s5_vs_short8_1x": pearson_correlation(solo16_rets, _daily_returns_map(nav_s8_1x_16)),
        "long18_vs_short18": pearson_correlation(_daily_returns_map(nav_l1_16), _daily_returns_map(nav_s18_1x_16)),
    }

    combos = [
        _pack_combo("SOLO_100_S1S5_NBX16", solo16_nav, None, stress_iso=stress_iso),
        _pack_combo("BLEND_70_S1S5_30_LONG18_1.0X_NBX16", _combine_sleeve_navs([(0.70, solo16_nav), (0.30, nav_l1_16)]), solo16_rets, stress_iso=stress_iso),
        _pack_combo("BLEND_70_S1S5_30_LONG18_1.5X_NBX16", _combine_sleeve_navs([(0.70, solo16_nav), (0.30, nav_l15_16)]), solo16_rets, stress_iso=stress_iso),
        _pack_combo("BLEND_70_S1S5_30_LONG18_2.0X_NBX16", _combine_sleeve_navs([(0.70, solo16_nav), (0.30, nav_l2_16)]), solo16_rets, stress_iso=stress_iso),
        _pack_combo("ALL_WEATHER_60_S1S5_25_LONG1.5X_15_SHORT1.0X_NBX16", _combine_sleeve_navs([(0.60, solo16_nav), (0.25, nav_l15_16), (0.15, nav_s18_1x_16)]), solo16_rets, stress_iso=stress_iso),
        _pack_combo("ALL_WEATHER_60_S1S5_25_LONG1.5X_15_SHORT1.5X_NBX16", _combine_sleeve_navs([(0.60, solo16_nav), (0.25, nav_l15_16), (0.15, nav_s18_15_16)]), solo16_rets, stress_iso=stress_iso),
        _pack_combo("SOLO_100_S1S5_WLX25", solo25_nav, None, stress_iso=stress_iso),
        _pack_combo("BLEND_70_S1S5_30_LONG18_1.5X_WLX25", _combine_sleeve_navs([(0.70, solo25_nav), (0.30, nav_l15_25)]), solo25_rets, stress_iso=stress_iso),
        _pack_combo("ALL_WEATHER_60_S1S5_25_LONG1.5X_15_SHORT1.0X_WLX25", _combine_sleeve_navs([(0.60, solo25_nav), (0.25, nav_l15_25), (0.15, nav_s18_1x_25)]), solo25_rets, stress_iso=stress_iso),
    ]

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "correlations": corrs,
        "part1_levered_long_ignition": [asdict(x) for x in (l_1x_16, l_15x_16, l_2x_16, l_15x_shift_16, l_15x_25, l_2x_25, l8_15x_16)],
        "part2_short_ignition": [asdict(x) for x in (s8_1x_16, s8_1x_shift_16, s8_15x_16, s18_1x_16, s18_1x_shift_16, s18_15x_16, s18_1x_25, s18_15x_25)],
        "part3_all_weather_blends": combos,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, summary)
    return summary


def _write_markdown(report_path: Path, summary: dict) -> None:
    c = summary["correlations"]
    lines = [
        "# Unlocking Short-Selling & Event-Scoped Leverage via Rare 2h Ignition",
        "",
        f"- **Generated:** `{summary['generated_at']}`",
        f"- **Correlations:** `S1+S5` vs `SHORT_IGN18` = **`{c['s1s5_vs_short18_1x']:+.4f}`**, `S1+S5` vs `SHORT_IGN8` = **`{c['s1s5_vs_short8_1x']:+.4f}`**, `LONG_IGN18` vs `SHORT_IGN18` = **`{c['long18_vs_short18']:+.4f}`**",
        "- **Margin Terms Modeled:** Exact Wallex `0.015%/4h` (`32.85%/yr`) borrow on borrowed leg + intra-bar `high`/`low` liquidation checks + live all-in spread/fee (`16 bps` Nobitex / `25 bps` Wallex).",
        "- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`",
        "",
        "## 1. Part 1 — Event-Scoped Leverage on Rare 2h Long Ignition (`1.0x` vs `1.5x` vs `2.0x`)",
        "",
        "| Arm | Lev | Mkts | Offset | Cost (bps) | Ending NAV | Ret % | Bear Stress % | Ann. Sharpe | MaxDD % | Entries | Win % | Liq | Avg Hold | Borrow ($) | Fees ($) |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in summary["part1_levered_long_ignition"]:
        lines.append(
            f"| `{r['label']}` | `{r['leverage']:.1f}x` | `{r['markets']}` | `+{r['offset_hours']}h` | `{r['cost_bps']:.1f}` | "
            f"`${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | "
            f"`{r['max_dd_pct']:.2f}%` | `{r['entries']}` | `{r['win_rate_pct']:.1f}%` | `{r['liquidations']}` | "
            f"`{r['avg_hold_hours']:.1f}h` | `${r['total_borrow_usdt']:.2f}` | `${r['total_fees_usdt']:.2f}` |"
        )

    lines.extend([
        "",
        "## 2. Part 2 — Rare 2h Downward Capitulation Short-Ignition (`1.0x` & `1.5x`, `8` & `18` Markets)",
        "",
        "| Arm | Lev | Mkts | Offset | Cost (bps) | Ending NAV | Ret % | Bear Stress % | Ann. Sharpe | MaxDD % | Entries | Win % | Liq | Avg Hold | Borrow ($) | Fees ($) |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in summary["part2_short_ignition"]:
        lines.append(
            f"| `{r['label']}` | `{r['leverage']:.1f}x` | `{r['markets']}` | `+{r['offset_hours']}h` | `{r['cost_bps']:.1f}` | "
            f"`${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | "
            f"`{r['max_dd_pct']:.2f}%` | `{r['entries']}` | `{r['win_rate_pct']:.1f}%` | `{r['liquidations']}` | "
            f"`{r['avg_hold_hours']:.1f}h` | `${r['total_borrow_usdt']:.2f}` | `${r['total_fees_usdt']:.2f}` |"
        )

    lines.extend([
        "",
        "## 3. Part 3 — 3-Engine All-Weather Blends (`1d S1+S5` + `2h Levered Long Ignition` + `2h Short Ignition`)",
        "",
        "| Portfolio | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Paired Uplift vs Solo (bps/day, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for r in summary["part3_all_weather_blends"]:
        mf, ms, up = r["full"], r["stress"], r["uplift_vs_solo"]
        up_bps = float(up.get("mean_uplift", 0.0)) * 10000.0
        ci = up.get("ci_95", [0.0, 0.0])
        lines.append(
            f"| `{r['name']}` | `${mf['ending_nav']:.2f}` | `{mf['ret_pct']:+.2f}%` | `{mf['ann_sharpe']:.3f}` | "
            f"`{mf['max_dd_pct']:.2f}%` | `{ms['ret_pct']:+.2f}%` | "
            f"`{up_bps:+.2f}` `[{ci[0]*10000:+.2f}, {ci[1]*10000:+.2f}]` (`{up.get('status')}`) |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
