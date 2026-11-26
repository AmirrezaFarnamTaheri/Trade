"""Ignition expansion study: (A) 8 vs 18 liquid crypto markets on 1h/2h + shared-ledger 70/30 blend, (B) 15m/30m sub-hourly probe."""
from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.family_and_ignition import (
    _ignition_candidate_z,
    _manage_ignition_exits,
)
from ...domain.ignition_and_intraday_exit import (
    pearson_correlation,
    run_shared_ledger_1h_blend,
    simulate_ignition_detailed,
)
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import (
    BarPoint,
    resample_1min_to_minutes,
    resample_hourly_to_bucket,
)
from .ensemble_study import STRESS_REPLAY_START, _daily_returns_map
from .ignition_validation_study import (
    CORE_8_IGNITION,
    _extract_daily_s1_s5_targets,
    _pack_arm,
)

IGNITION_18_CRYPTO = CORE_8_IGNITION + (
    "LTCUSDT",
    "BCHUSDT",
    "TRXUSDT",
    "AAVEUSDT",
    "AVAXUSDT",
    "NEARUSDT",
    "UNIUSDT",
    "ATOMUSDT",
    "DOTUSDT",
    "FILUSDT",
)

SUBHOURLY_8_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "SUIUSDT",
    "ARBUSDT",
    "LTCUSDT",
    "DASHUSDT",
    "XAUTUSDT",
)


def _simulate_subhourly_ignition(
    panel_m: dict[str, list[BarPoint]],
    symbols: tuple[str, ...],
    *,
    label: str,
    minutes: int,
    fee_rate: Decimal,
    z_threshold: float = 3.2,
    vol_mult: float = 3.0,
    breakout_hours: int = 24,
    hold_hours: int = 8,
    max_slots: int = 3,
    slot_weight: float = 0.30,
) -> dict:
    """Strictly causal sub-hourly (15m/30m) rare ignition probe over the 25-day live 1min archive."""
    bph = max(1, 60 // minutes)
    breakout_bars = max(12, breakout_hours * bph)
    max_hold_bars = max(4, hold_hours * bph)
    vol_lookback = max(24, 12 * bph)

    by_avail = {s: {b.ts_avail: b for b in panel_m.get(s, [])} for s in symbols}
    by_start = {s: {b.ts_start: b for b in panel_m.get(s, [])} for s in symbols}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    vol_hist: dict[str, list[float]] = {s: [] for s in symbols}
    high_hist: dict[str, list[float]] = {s: [] for s in symbols}
    prev_close: dict[str, float] = {}

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    last_mark: dict[str, Decimal] = {}
    open_pos: dict[str, tuple[float, float, float, int]] = {}
    nav_by_date: dict[str, float] = {}
    entries, closed_wins, closed_total = 0, 0, 0

    for ts in all_ts:
        exec_prices: dict[str, Decimal] = {}
        tradable: set[str] = set()
        candidates: list[tuple[float, str, float]] = []
        for sym in symbols:
            cur = by_avail[sym].get(ts)
            nxt = by_start[sym].get(ts)
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

            if cur is None or cur.close <= 0:
                continue
            bar_ret = ((cur.close - prev_close[sym]) / prev_close[sym]) if (sym in prev_close and prev_close[sym] > 0) else 0.0
            if sym in tradable and sym not in open_pos:
                hit = _ignition_candidate_z(
                    cur,
                    bar_ret,
                    high_hist[sym][-breakout_bars:],
                    ret_hist[sym][-vol_lookback:],
                    vol_hist[sym][-vol_lookback:],
                    breakout_bars=breakout_bars,
                    vol_lookback=vol_lookback,
                    z_threshold=z_threshold,
                    vol_mult=vol_mult,
                )
                if hit is not None:
                    candidates.append((hit[0], sym, hit[1]))
            if sym in prev_close and prev_close[sym] > 0:
                ret_hist[sym].append(bar_ret)
            prev_close[sym] = cur.close
            vol_hist[sym].append(cur.volume)
            high_hist[sym].append(cur.high)

        w_inc, t_inc = _manage_ignition_exits(
            open_pos,
            by_avail,
            by_start,
            ts,
            max_hold_bars=max_hold_bars,
            trail_stop_mult=2.5,
            hard_stop_pct=0.025,
            fee_rate=fee_rate,
        )
        closed_wins += w_inc
        closed_total += t_inc

        if candidates and len(open_pos) < max_slots:
            candidates.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in candidates:
                if len(open_pos) >= max_slots:
                    break
                nxt = by_start[sym].get(ts)
                if nxt is not None and nxt.open > 0:
                    open_pos[sym] = (nxt.open, nxt.open, b_vol, 0)
                    entries += 1

        targets = {s: (slot_weight if s in open_pos else 0.0) for s in symbols}
        if open_pos or any(q > 0 for q in ledger.units.values()):
            ledger.rebalance_to_targets(ts, targets, exec_prices, tradable_symbols=tradable)
        nav_by_date[ts.date().isoformat()] = float(ledger.mark_nav(exec_prices))

    dates = sorted(nav_by_date)
    navs = [nav_by_date[d] for d in dates] if dates else [1000.0]
    rets = [(navs[i] / navs[i - 1] - 1.0) for i in range(1, len(navs)) if navs[i - 1] > 0]
    mean_r = sum(rets) / max(1, len(rets))
    var_r = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
    sr = (mean_r / math.sqrt(var_r)) * math.sqrt(365.0) if var_r > 1e-14 else 0.0
    peak, max_dd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    return {
        "label": label,
        "bar": f"{minutes}m",
        "cost_bps": round(float(fee_rate) * 10000.0, 1),
        "days": len(dates),
        "ending_nav": round(navs[-1], 2),
        "ret_pct": round((navs[-1] / navs[0] - 1.0) * 100.0, 2),
        "ann_sharpe": round(sr, 3),
        "max_dd_pct": round(max_dd * 100.0, 2),
        "entries": entries,
        "win_rate_pct": round((closed_wins / closed_total * 100.0) if closed_total else 0.0, 1),
        "fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
    }


def _expand_2h_targets_to_1h(
    targets_2h: dict[datetime, dict[str, float]],
    all_1h_ts: list[datetime],
    symbols: tuple[str, ...],
) -> dict[datetime, dict[str, float]]:
    """Forward-hold 2h ignition targets onto the 1h execution clock with zero lookahead."""
    out: dict[datetime, dict[str, float]] = {}
    cur = {s: 0.0 for s in symbols}
    for ts in all_1h_ts:
        if ts in targets_2h:
            cur = targets_2h[ts]
        out[ts] = cur
    return out


def run_ignition_expansion_study(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Evaluate 18-market 1h/2h ignition + 70/30 shared-ledger blend + 15m/30m sub-hourly probe."""
    all_1h_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    con = open_readonly_market_db(db_path)
    try:
        panel_13_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_all_1h = {s: load_keyed_candles(con, s, "1h", limit=25000) for s in all_1h_syms}
        panel_sub_1m = {s: load_keyed_candles(con, s, "1min", limit=25000) for s in SUBHOURLY_8_SYMBOLS}
    finally:
        con.close()

    sigs_13_1d = compute_slow_sleeves(panel_13_1d, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13_1d) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_breadth = {}
    for ts, d in sigs_13_1d.items():
        first = next(iter(d.values()), None)
        if first and first.crypto_breadth is not None:
            daily_breadth[ts.date().isoformat()] = first.crypto_breadth

    # A. 18-market 1h & 2h (+0h and +1h offset) at Nobitex 16 bps & Wallex 25 bps
    p_18_1h = {s: panel_all_1h[s] for s in IGNITION_18_CRYPTO}
    p_18_2h_0 = {s: resample_hourly_to_bucket(panel_all_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO}
    p_18_2h_1 = {s: resample_hourly_to_bucket(panel_all_1h[s], 2, offset_hours=1) for s in IGNITION_18_CRYPTO}
    p_8_2h_0 = {s: p_18_2h_0[s] for s in CORE_8_IGNITION}

    ig18_1h_16, nav_18_1h_16, t_18_1h_16 = simulate_ignition_detailed(
        p_18_1h, IGNITION_18_CRYPTO, daily_breadth, label="IGN18_1H_NOBITEX_16BPS", bucket_hours=1, fee_rate=Decimal("0.0016")
    )
    ig18_1h_25, _, _ = simulate_ignition_detailed(
        p_18_1h, IGNITION_18_CRYPTO, daily_breadth, label="IGN18_1H_WALLEX_25BPS", bucket_hours=1, fee_rate=Decimal("0.0025")
    )
    ig18_2h0_16, nav_18_2h0_16, t_18_2h0_16 = simulate_ignition_detailed(
        p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="IGN18_2H_0H_NOBITEX_16BPS", bucket_hours=2, offset_hours=0, fee_rate=Decimal("0.0016")
    )
    ig18_2h1_16, _, _ = simulate_ignition_detailed(
        p_18_2h_1, IGNITION_18_CRYPTO, daily_breadth, label="IGN18_2H_1H_SHIFT_NOBITEX_16BPS", bucket_hours=2, offset_hours=1, fee_rate=Decimal("0.0016")
    )
    ig18_2h0_25, _, t_18_2h0_25 = simulate_ignition_detailed(
        p_18_2h_0, IGNITION_18_CRYPTO, daily_breadth, label="IGN18_2H_0H_WALLEX_25BPS", bucket_hours=2, offset_hours=0, fee_rate=Decimal("0.0025")
    )
    ig18_2h1_25, _, _ = simulate_ignition_detailed(
        p_18_2h_1, IGNITION_18_CRYPTO, daily_breadth, label="IGN18_2H_1H_SHIFT_WALLEX_25BPS", bucket_hours=2, offset_hours=1, fee_rate=Decimal("0.0025")
    )
    _, _, t_8_2h0_16 = simulate_ignition_detailed(
        p_8_2h_0, CORE_8_IGNITION, daily_breadth, label="IGN8_2H_0H_NOBITEX_16BPS", bucket_hours=2, offset_hours=0, fee_rate=Decimal("0.0016")
    )

    # B. Single Shared-Ledger Blends (70% BASE_13_S1_S5 + 30% IGNITION_2H_8MKT / 18MKT)
    daily_sched_13 = _extract_daily_s1_s5_targets(panel_13_1d, sigs_13_1d, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0013"))
    all_1h_ts = sorted({b.ts_avail for bars in panel_all_1h.values() for b in bars})
    stress_iso = STRESS_REPLAY_START.date().isoformat()

    solo_16 = run_shared_ledger_1h_blend(panel_all_1h, all_1h_syms, daily_sched_13, {}, slow_weight=1.0, ignition_weight=0.0, fee_rate=Decimal("0.0016"))
    blend_8_2h_16 = run_shared_ledger_1h_blend(
        panel_all_1h,
        all_1h_syms,
        daily_sched_13,
        _expand_2h_targets_to_1h(t_8_2h0_16, all_1h_ts, all_1h_syms),
        slow_weight=0.70,
        ignition_weight=0.30,
        fee_rate=Decimal("0.0016"),
    )
    blend_18_2h_16 = run_shared_ledger_1h_blend(
        panel_all_1h,
        all_1h_syms,
        daily_sched_13,
        _expand_2h_targets_to_1h(t_18_2h0_16, all_1h_ts, all_1h_syms),
        slow_weight=0.70,
        ignition_weight=0.30,
        fee_rate=Decimal("0.0016"),
    )
    blend_18_1h_16 = run_shared_ledger_1h_blend(
        panel_all_1h,
        all_1h_syms,
        daily_sched_13,
        t_18_1h_16,
        slow_weight=0.70,
        ignition_weight=0.30,
        fee_rate=Decimal("0.0016"),
    )
    solo_25 = run_shared_ledger_1h_blend(panel_all_1h, all_1h_syms, daily_sched_13, {}, slow_weight=1.0, ignition_weight=0.0, fee_rate=Decimal("0.0025"))
    blend_18_2h_25 = run_shared_ledger_1h_blend(
        panel_all_1h,
        all_1h_syms,
        daily_sched_13,
        _expand_2h_targets_to_1h(t_18_2h0_25, all_1h_ts, all_1h_syms),
        slow_weight=0.70,
        ignition_weight=0.30,
        fee_rate=Decimal("0.0025"),
    )

    solo_16_rets = _daily_returns_map(solo_16["nav_by_date"])
    solo_25_rets = _daily_returns_map(solo_25["nav_by_date"])
    blend_rows = [
        _pack_arm("SOLO_100_S1S5_NOBITEX_16BPS", solo_16, None, stress_iso=stress_iso),
        _pack_arm("BLEND_70_30_IGN8_2H_NOBITEX_16BPS", blend_8_2h_16, solo_16_rets, stress_iso=stress_iso),
        _pack_arm("BLEND_70_30_IGN18_2H_NOBITEX_16BPS", blend_18_2h_16, solo_16_rets, stress_iso=stress_iso),
        _pack_arm("BLEND_70_30_IGN18_1H_NOBITEX_16BPS", blend_18_1h_16, solo_16_rets, stress_iso=stress_iso),
        _pack_arm("SOLO_100_S1S5_WALLEX_25BPS", solo_25, None, stress_iso=stress_iso),
        _pack_arm("BLEND_70_30_IGN18_2H_WALLEX_25BPS", blend_18_2h_25, solo_25_rets, stress_iso=stress_iso),
    ]

    # C. Sub-hourly 15m & 30m probe (25-day live 1min archive)
    p_15m = {s: resample_1min_to_minutes(panel_sub_1m[s], 15) for s in SUBHOURLY_8_SYMBOLS}
    p_30m = {s: resample_1min_to_minutes(panel_sub_1m[s], 30) for s in SUBHOURLY_8_SYMBOLS}
    subhourly_rows = [
        _simulate_subhourly_ignition(p_30m, SUBHOURLY_8_SYMBOLS, label="IGN_30M_NOBITEX_16BPS", minutes=30, fee_rate=Decimal("0.0016")),
        _simulate_subhourly_ignition(p_30m, SUBHOURLY_8_SYMBOLS, label="IGN_30M_WALLEX_25BPS", minutes=30, fee_rate=Decimal("0.0025")),
        _simulate_subhourly_ignition(p_15m, SUBHOURLY_8_SYMBOLS, label="IGN_15M_NOBITEX_16BPS", minutes=15, fee_rate=Decimal("0.0016")),
        _simulate_subhourly_ignition(p_15m, SUBHOURLY_8_SYMBOLS, label="IGN_15M_WALLEX_25BPS", minutes=15, fee_rate=Decimal("0.0025")),
    ]

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "corr_s1s5_vs_ign18_2h": pearson_correlation(solo_16_rets, _daily_returns_map(nav_18_2h0_16)),
        "corr_s1s5_vs_ign18_1h": pearson_correlation(solo_16_rets, _daily_returns_map(nav_18_1h_16)),
        "part_a_18_market_ignition": [
            asdict(ig18_1h_16),
            asdict(ig18_1h_25),
            asdict(ig18_2h0_16),
            asdict(ig18_2h1_16),
            asdict(ig18_2h0_25),
            asdict(ig18_2h1_25),
        ],
        "part_b_shared_ledger_2h_and_18mkt_blends": blend_rows,
        "part_c_subhourly_15m_30m_25d_probe": subhourly_rows,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, summary)
    return summary


def _write_markdown(report_path: Path, summary: dict) -> None:
    lines = [
        "# Ignition Expansion Study: 18-Market 1h/2h Scanner, 70/30 Shared-Ledger Blends, and 15m/30m Sub-Hourly Probe",
        "",
        f"- **Generated:** `{summary['generated_at']}`",
        f"- **Correlation vs `S1+S5`:** `IGN18_2H` = **`{summary['corr_s1s5_vs_ign18_2h']:+.4f}`**, `IGN18_1H` = **`{summary['corr_s1s5_vs_ign18_1h']:+.4f}`**",
        "- **Authority:** `PAPER_ONLY` · `TradingGYMExecutor DISARMED ($0 funded budget)`",
        "",
        "## 1. Part A — 18-Market Rare Ignition (`1h` & `2h`, `0h`/`+1h` Offset, Live All-In Spread+Fee)",
        "",
        "| Sleeve | Bar | Offset | All-In Cost (bps) | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Entries | Win % | Fees+Spread ($) |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in summary["part_a_18_market_ignition"]:
        lines.append(
            f"| `{r['label']}` | `{r['bucket_hours']}h` | `+{r['offset_hours']}h` | `{r['fee_bps']:.1f}` | "
            f"`${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | "
            f"`{r['entries']}` | `{r['win_rate_pct']:.1f}%` | `${r['fees_usdt']:.2f}` |"
        )

    lines.extend([
        "",
        "## 2. Part B — Single Shared-Ledger Blends (`70% BASE_13_S1_S5 + 30% IGNITION_2H` / `18MKT`)",
        "",
        "| Arm | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress % | Fees ($) | Turnover | Paired Uplift vs Solo (bps/day, 95% CI) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for r in summary["part_b_shared_ledger_2h_and_18mkt_blends"]:
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
        "## 3. Part C — Sub-Hourly `15m` & `30m` Probe (25-Day Live `1min` Archive, `2026-10-30..2026-11-24`)",
        "",
        "| Sleeve | Bar | Cost (bps) | Days | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Entries | Win % | Fees ($) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in summary["part_c_subhourly_15m_30m_25d_probe"]:
        lines.append(
            f"| `{r['label']}` | `{r['bar']}` | `{r['cost_bps']:.1f}` | `{r['days']}` | "
            f"`${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | "
            f"`{r['entries']}` | `{r['win_rate_pct']:.1f}%` | `${r['fees_usdt']:.2f}` |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
