"""Deep-dive research studies on standing leader (S1+S5), S2 hysteresis, 2x2 entry/exit, and causal execution."""
from __future__ import annotations

import json
import random
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import (
    load_book_and_trades,
    load_keyed_candles,
    open_readonly_market_db,
)
from ...domain.execution_schedule import (
    causal_spread_quantile_bps,
    compare_execution_timing_arms,
)
from ...domain.leader_attribution import (
    apply_s2_incumbent_hysteresis,
    decompose_factor_attribution,
)
from ...domain.model import parse_ts
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import SleeveSignal, compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint
from ...domain.venue_contracts import wallex_l1_fee_schedule
from .ensemble_study import (
    COHORT_SYMBOLS,
    STRESS_REPLAY_START,
    _daily_returns_map,
    _exec_prices_and_tradable,
    _portfolio_metrics,
    _run_self_financing_arm,
)

EXECUTION_USDT_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "XAUTUSDT",
    "PEPEUSDT",
)


def _s1_s5_score(sig: SleeveSignal) -> float:
    parts = [v for v in (sig.s1_trend, sig.s5_defensive_gold) if v is not None]
    return sum(parts) / len(parts) if parts else 0.0


def _run_rule_based_entry_exit(
    panel: dict[str, list[BarPoint]],
    signals: dict[datetime, dict[str, SleeveSignal]],
    eval_dates: list[datetime],
    *,
    entry_mode: str,
    exit_mode: str,
    fee_rate: Decimal = Decimal("0.0013"),
    fixed_hold_days: int = 20,
    seed: int = 42,
) -> dict:
    """Run one cell of the 2x2 entry-vs-exit decomposition on the exact SelfFinancingLedger."""
    rng = random.Random(seed)
    by_sym_start = {s: {b.ts_start: b for b in panel.get(s, [])} for s in COHORT_SYMBOLS}
    by_sym_avail = {s: {b.ts_avail: b for b in panel.get(s, [])} for s in COHORT_SYMBOLS}
    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)

    held_age: dict[str, int] = {}
    nav_by_date: dict[str, float] = {}
    gross_exposures: list[float] = []

    for idx in range(len(eval_dates) - 1):
        t_avail = eval_dates[idx]
        day_sigs = signals.get(t_avail, {})
        exec_prices, tradable = _exec_prices_and_tradable(by_sym_start, by_sym_avail, t_avail)

        for sym in list(held_age):
            held_age[sym] += 1
            sig = day_sigs.get(sym)
            score = _s1_s5_score(sig) if sig is not None else 0.0
            should_exit = (
                (exit_mode == "FIXED_CLOCK" and held_age[sym] >= fixed_hold_days)
                or (exit_mode == "SLEEVE_EXIT" and score <= 0.0)
            )
            if should_exit:
                del held_age[sym]

        real_entries = [
            sym
            for sym in COHORT_SYMBOLS
            if sym in tradable
            and sym not in held_age
            and sym in day_sigs
            and _s1_s5_score(day_sigs[sym]) > 0.15
        ]
        if entry_mode == "REAL_ENTRY":
            chosen = real_entries
        else:
            pool = [sym for sym in COHORT_SYMBOLS if sym in tradable and sym not in held_age and sym in day_sigs]
            k = min(len(real_entries), len(pool))
            chosen = rng.sample(pool, k) if k > 0 else []

        for sym in chosen:
            held_age[sym] = 0

        n_held = len(held_age)
        w_each = min(0.25, 0.95 / n_held) if n_held > 0 else 0.0
        targets = {s: (w_each if s in held_age else 0.0) for s in COHORT_SYMBOLS}
        ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
        nav = float(ledger.mark_nav(exec_prices))
        nav_by_date[t_avail.date().isoformat()] = nav
        cash_frac = float(ledger.cash / ledger.mark_nav(exec_prices)) if nav > 0 else 1.0
        gross_exposures.append(max(0.0, 1.0 - cash_frac))

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    return {
        "metrics_full": _portfolio_metrics(nav_by_date),
        "metrics_stress": _portfolio_metrics({k: v for k, v in nav_by_date.items() if k >= stress_iso}),
        "avg_gross_exposure": round(sum(gross_exposures) / max(1, len(gross_exposures)), 3),
        "total_fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "turnover_multiple": round(float(ledger.cumulative_turnover_quote / ledger.starting_cash), 2),
    }


def _average_seeded_cells(cells: list[dict]) -> dict:
    n = len(cells)
    return {
        "seeds": n,
        "ending_nav": round(sum(c["metrics_full"]["ending_nav"] for c in cells) / n, 2),
        "ret_pct": round(sum(c["metrics_full"]["ret_pct"] for c in cells) / n, 2),
        "ann_sharpe": round(sum(c["metrics_full"]["ann_sharpe"] for c in cells) / n, 3),
        "max_dd_pct": round(sum(c["metrics_full"]["max_dd_pct"] for c in cells) / n, 2),
        "stress_ret_pct": round(sum(c["metrics_stress"]["ret_pct"] for c in cells) / n, 2),
        "avg_gross_exposure": round(sum(c["avg_gross_exposure"] for c in cells) / n, 3),
        "total_fees_usdt": round(sum(c["total_fees_usdt"] for c in cells) / n, 2),
    }


def _run_causal_execution_study(con, *, lookback_hours: int = 72, samples_per_side: int = 12) -> list[dict]:
    latest_row = con.execute("SELECT MAX(ts_avail) FROM book_top").fetchone()
    latest_ts = parse_ts(latest_row[0]) if latest_row and latest_row[0] else datetime.now(UTC)
    since_iso = (latest_ts - timedelta(hours=lookback_hours)).isoformat().replace("+00:00", "Z")
    sched = wallex_l1_fee_schedule("USDT")
    rows: list[dict] = []

    for sym in EXECUTION_USDT_SYMBOLS:
        books, trades = load_book_and_trades(con, sym, since_iso)
        valid = [b for b in books if b.bid and b.ask and b.bid > 0 and b.ask > 0]
        if len(valid) < 80:
            continue
        start_i = 50
        end_i = len(valid) - 10
        step = max(1, (end_i - start_i) // samples_per_side)
        sample_indices = list(range(start_i, end_i, step))[:samples_per_side]

        for side in ("BUY", "SELL"):
            imm_costs, fp_costs, opp_costs = [], [], []
            imm_unfilled, fp_unfilled, opp_unfilled = 0, 0, 0
            p35_vals = []
            for idx in sample_indices:
                top = valid[idx]
                assert top.bid is not None and top.ask is not None
                mid = (top.bid + top.ask) / Decimal(2)
                qty = (Decimal("250") / mid).quantize(Decimal("0.000001"))
                p35 = causal_spread_quantile_bps(valid, top.ts_avail)
                p35_vals.append(float(p35))
                comp = compare_execution_timing_arms(
                    sym,
                    side,
                    qty,
                    top.ts_avail,
                    300.0,
                    valid,
                    trades,
                    sched,
                    p35_spread_bps=p35,
                    duplicate_print_mode="adversarial_lower_bound",
                    enforce_displayed_size=True,
                )
                imm_costs.append(float(comp.immediate.total_cost_bps))
                fp_costs.append(float(comp.fixed_passive.total_cost_bps))
                opp_costs.append(float(comp.opportunistic_recovery.total_cost_bps))
                imm_unfilled += int(comp.immediate.unfilled_qty > 0)
                fp_unfilled += int(comp.fixed_passive.unfilled_qty > 0)
                opp_unfilled += int(comp.opportunistic_recovery.unfilled_qty > 0)

            n = len(sample_indices)
            mean_imm = sum(imm_costs) / n
            mean_fp = sum(fp_costs) / n
            mean_opp = sum(opp_costs) / n
            rows.append(
                {
                    "symbol": sym,
                    "side": side,
                    "samples": n,
                    "mean_causal_p35_bps": round(sum(p35_vals) / n, 2),
                    "immediate_cost_bps": round(mean_imm, 2),
                    "fixed_passive_cost_bps": round(mean_fp, 2),
                    "opportunistic_cost_bps": round(mean_opp, 2),
                    "fixed_passive_savings_bps": round(mean_imm - mean_fp, 2),
                    "opportunistic_savings_bps": round(mean_imm - mean_opp, 2),
                    "unfilled_counts": {"imm": imm_unfilled, "fp": fp_unfilled, "opp": opp_unfilled},
                }
            )
    return rows


def run_leader_deep_dive(db_path: Path, report_path: Path, receipt_path: Path) -> dict:
    """Execute Study A (S2 hysteresis), Study B (factor + 2x2 entry/exit), and Study C (causal execution)."""
    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {sym: load_keyed_candles(con, sym, "1d", limit=2500) for sym in COHORT_SYMBOLS}
        exec_rows = _run_causal_execution_study(con)
    finally:
        con.close()

    signals_raw = compute_slow_sleeves(panel_1d, COHORT_SYMBOLS)
    eval_dates = [d for d in sorted(signals_raw) if d >= datetime(2022, 6, 1, tzinfo=UTC)]

    # Study A: Standing Leader (DROP_S2) vs Unbuffered S2 vs Hysteresis S2 bands
    arm_drop_s2 = _run_self_financing_arm("DROP_S2", panel_1d, signals_raw, eval_dates)
    arm_raw_ens = _run_self_financing_arm("FIXED_ENSEMBLE_S1_S2_S5", panel_1d, signals_raw, eval_dates)
    arm_static = _run_self_financing_arm("STATIC_GOLD_AND_CRYPTO", panel_1d, signals_raw, eval_dates)

    sig_hyst_55 = apply_s2_incumbent_hysteresis(signals_raw, entry_top_frac=0.25, hold_top_frac=0.55)
    sig_hyst_70 = apply_s2_incumbent_hysteresis(signals_raw, entry_top_frac=0.25, hold_top_frac=0.70)
    arm_hyst_55 = _run_self_financing_arm("FIXED_ENSEMBLE_S1_S2_S5", panel_1d, sig_hyst_55, eval_dates)
    arm_hyst_70 = _run_self_financing_arm("FIXED_ENSEMBLE_S1_S2_S5", panel_1d, sig_hyst_70, eval_dates)

    base_rets = _daily_returns_map(arm_drop_s2["nav_by_date"])
    hyst_comparison = {}
    for label, res in (
        ("DROP_S2_LEADER", arm_drop_s2),
        ("RAW_S1_S2_S5", arm_raw_ens),
        ("S2_HYSTERESIS_25_55", arm_hyst_55),
        ("S2_HYSTERESIS_25_70", arm_hyst_70),
    ):
        cand_rets = _daily_returns_map(res["nav_by_date"])
        uplift = (
            paired_baseline_uplift(cand_rets, base_rets, simulations=499, seed=42)
            if label != "DROP_S2_LEADER"
            else {"status": "BASELINE", "mean_uplift": 0.0, "ci_95": [0.0, 0.0]}
        )
        hyst_comparison[label] = {
            "metrics_full": res["metrics_full"],
            "metrics_stress": res["metrics_stress"],
            "total_fees_usdt": res["total_fees_usdt"],
            "turnover_multiple": res["turnover_multiple"],
            "uplift_vs_drop_s2_bps": uplift,
        }

    # Study B1: Factor attribution (BTC + Gold OLS)
    btc_nav = {b.ts_avail.date().isoformat(): b.close for b in panel_1d["BTCUSDT"] if b.close > 0}
    gold_nav = {b.ts_avail.date().isoformat(): b.close for b in panel_1d["XAUTUSDT"] if b.close > 0}
    btc_rets = _daily_returns_map(btc_nav)
    gold_rets = _daily_returns_map(gold_nav)
    factor_attr = {
        label: asdict(decompose_factor_attribution(_daily_returns_map(res["nav_by_date"]), btc_rets, gold_rets))
        for label, res in (
            ("DROP_S2_LEADER", arm_drop_s2),
            ("RAW_S1_S2_S5", arm_raw_ens),
            ("S2_HYSTERESIS_25_55", arm_hyst_55),
            ("STATIC_GOLD_AND_CRYPTO", arm_static),
        )
    }

    # Study B2: 2x2 Entry vs Exit decomposition on S1+S5
    cell_real_sleeve = _run_rule_based_entry_exit(
        panel_1d, signals_raw, eval_dates, entry_mode="REAL_ENTRY", exit_mode="SLEEVE_EXIT"
    )
    cell_real_fixed = _run_rule_based_entry_exit(
        panel_1d, signals_raw, eval_dates, entry_mode="REAL_ENTRY", exit_mode="FIXED_CLOCK"
    )
    cell_rand_sleeve = _average_seeded_cells([
        _run_rule_based_entry_exit(
            panel_1d, signals_raw, eval_dates, entry_mode="RANDOM_ENTRY", exit_mode="SLEEVE_EXIT", seed=s
        )
        for s in range(42, 47)
    ])
    cell_rand_fixed = _average_seeded_cells([
        _run_rule_based_entry_exit(
            panel_1d, signals_raw, eval_dates, entry_mode="RANDOM_ENTRY", exit_mode="FIXED_CLOCK", seed=s
        )
        for s in range(42, 47)
    ])

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "eval_days": len(eval_dates),
        "study_a_s2_hysteresis": hyst_comparison,
        "study_b_factor_attribution": factor_attr,
        "study_b_entry_exit_2x2": {
            "REAL_ENTRY_SLEEVE_EXIT": cell_real_sleeve,
            "REAL_ENTRY_FIXED_20D_EXIT": cell_real_fixed,
            "RANDOM_ENTRY_SLEEVE_EXIT_5SEED_AVG": cell_rand_sleeve,
            "RANDOM_ENTRY_FIXED_20D_EXIT_5SEED_AVG": cell_rand_fixed,
        },
        "study_c_causal_execution": exec_rows,
    }

    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_markdown_report(report_path, summary)
    return summary


def _write_markdown_report(report_path: Path, summary: dict) -> None:
    lines = [
        "# Standing Leader Deep-Dive: S2 Hysteresis, Factor & 2x2 Entry/Exit Attribution, and Causal Execution",
        "",
        f"- **Generated:** `{summary['generated_at']}`",
        f"- **Eval Days:** `{summary['eval_days']}` (`1d` cohort panel from `2022-06-01`, exact `SelfFinancingLedger`, `$1,000` start, `13 bps` Wallex L1 fee)",
        "",
        "## 1. Study A — Low-Turnover S2 Incumbent Retention Hysteresis Band",
        "",
        "| Arm | Full Ending NAV | Full Ret % | Ann. Sharpe | MaxDD % | Bear Stress Ret % | Fees ($) | Turnover | Mean Uplift vs DROP_S2 (bps/day) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in summary["study_a_s2_hysteresis"].items():
        mf = row["metrics_full"]
        ms = row["metrics_stress"]
        up = row["uplift_vs_drop_s2_bps"]
        up_bps = float(up.get("mean_uplift", 0.0)) * 10000.0
        ci = up.get("ci_95", [0.0, 0.0])
        ci_str = f"[{ci[0] * 10000.0:+.2f}, {ci[1] * 10000.0:+.2f}] ({up.get('status', 'N/A')})"
        lines.append(
            f"| `{name}` | `${mf['ending_nav']:.2f}` | `{mf['ret_pct']:+.2f}%` | `{mf['ann_sharpe']:.3f}` | "
            f"`{mf['max_dd_pct']:.2f}%` | `{ms['ret_pct']:+.2f}%` | `${row['total_fees_usdt']:.2f}` | "
            f"`{row['turnover_multiple']:.1f}x` | `{up_bps:+.2f}` {ci_str} |"
        )

    lines.extend([
        "",
        "## 2. Study B1 — BTC + Gold Factor Attribution (OLS on Daily Returns)",
        "",
        "| Arm | Obs | Ann. Alpha % | Beta BTC | Beta Gold | R² | Residual Ann. Sharpe | Total Ann. Sharpe |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for name, fa in summary["study_b_factor_attribution"].items():
        lines.append(
            f"| `{name}` | `{fa['observations']}` | `{fa['ann_alpha_pct']:+.2f}%` | `{fa['beta_btc']:.3f}` | "
            f"`{fa['beta_gold']:.3f}` | `{fa['r_squared']:.3f}` | `{fa['residual_ann_sharpe']:.3f}` | `{fa['portfolio_ann_sharpe']:.3f}` |"
        )

    lines.extend([
        "",
        "## 3. Study B2 — 2x2 Entry vs. Exit Decomposition on `S1 + S5`",
        "",
        "| Cell | Ending NAV | Ret % | Ann. Sharpe | MaxDD % | Bear Stress Ret % | Avg Gross Exp | Fees ($) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    ex2 = summary["study_b_entry_exit_2x2"]
    for label in ("REAL_ENTRY_SLEEVE_EXIT", "REAL_ENTRY_FIXED_20D_EXIT"):
        c = ex2[label]
        mf, ms = c["metrics_full"], c["metrics_stress"]
        lines.append(
            f"| `{label}` | `${mf['ending_nav']:.2f}` | `{mf['ret_pct']:+.2f}%` | `{mf['ann_sharpe']:.3f}` | "
            f"`{mf['max_dd_pct']:.2f}%` | `{ms['ret_pct']:+.2f}%` | `{c['avg_gross_exposure']:.3f}` | `${c['total_fees_usdt']:.2f}` |"
        )
    for label in ("RANDOM_ENTRY_SLEEVE_EXIT_5SEED_AVG", "RANDOM_ENTRY_FIXED_20D_EXIT_5SEED_AVG"):
        c = ex2[label]
        lines.append(
            f"| `{label}` | `${c['ending_nav']:.2f}` | `{c['ret_pct']:+.2f}%` | `{c['ann_sharpe']:.3f}` | "
            f"`{c['max_dd_pct']:.2f}%` | `{c['stress_ret_pct']:+.2f}%` | `{c['avg_gross_exposure']:.3f}` | `${c['total_fees_usdt']:.2f}` |"
        )

    lines.extend([
        "",
        "## 4. Study C — Causal Execution-Policy Comparison (Zero Lookahead `p35`, BUY & SELL, Displayed Size)",
        "",
        "| Symbol | Side | N | Causal p35 (bps) | Immediate (bps) | Fixed Passive (bps) | Opportunistic (bps) | FP Savings (bps) | Opp Savings (bps) | Unfilled (I/F/O) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for r in summary["study_c_causal_execution"]:
        u = r["unfilled_counts"]
        lines.append(
            f"| `{r['symbol']}` | `{r['side']}` | `{r['samples']}` | `{r['mean_causal_p35_bps']:.2f}` | "
            f"`{r['immediate_cost_bps']:.2f}` | `{r['fixed_passive_cost_bps']:.2f}` | `{r['opportunistic_cost_bps']:.2f}` | "
            f"`{r['fixed_passive_savings_bps']:+.2f}` | `{r['opportunistic_savings_bps']:+.2f}` | `{u['imm']}/{u['fp']}/{u['opp']}` |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
