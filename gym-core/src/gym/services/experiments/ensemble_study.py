"""Structured First Paper Experiment service: slow sleeves (S1/S2/S5), controls & veto-only logistic challenger."""
from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.async_covariance import coarse_bar_shrunk_covariance_aligned
from ...domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    portfolio_utility,
    solve_convex_portfolio,
)
from ...domain.meta_gateway import (
    AdaptiveVoteGateway,
    LogisticVetoGateway,
    evaluate_shadow_veto,
    extract_gateway_features,
    run_synthetic_falsification_checks,
)
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.statistical_inference import paired_baseline_uplift
from ...domain.strategy_sleeves import SleeveSignal, compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .bar_parity import audit_bar_parity_and_coverage

COHORT_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "BNBUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "TRXUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "AAVEUSDT",
    "XAUTUSDT",
)
STRESS_REPLAY_START = datetime(2025, 11, 24, 0, 0, tzinfo=UTC)


def _sleeve_score(sig: SleeveSignal, mode: str, vote_gw: AdaptiveVoteGateway | None = None) -> float:
    if mode == "FIXED_S1":
        return float(sig.s1_trend or 0.0)
    if mode == "DROP_S1":
        parts = [v for v in (sig.s2_residual_mom, sig.s5_defensive_gold) if v is not None]
        return sum(parts) / len(parts) if parts else 0.0
    if mode == "DROP_S2":
        parts = [v for v in (sig.s1_trend, sig.s5_defensive_gold) if v is not None]
        return sum(parts) / len(parts) if parts else 0.0
    if mode == "DROP_S5":
        parts = [v for v in (sig.s1_trend, sig.s2_residual_mom) if v is not None]
        return sum(parts) / len(parts) if parts else 0.0
    if mode == "ADAPTIVE_VOTE" and vote_gw is not None:
        return vote_gw.combine_signal(sig)
    parts = [v for v in (sig.s1_trend, sig.s2_residual_mom, sig.s5_defensive_gold) if v is not None]
    return sum(parts) / len(parts) if parts else 0.0


def _portfolio_metrics(nav_by_date: dict[str, float], *, starting_nav: float | None = None) -> dict:
    dates = sorted(nav_by_date)
    if len(dates) < 5:
        return {"days": len(dates), "ending_nav": 1000.0, "ret_pct": 0.0, "ann_sharpe": 0.0, "max_dd_pct": 0.0}
    navs = [nav_by_date[d] for d in dates]
    rets = [(navs[i] / navs[i - 1] - 1.0) for i in range(1, len(navs)) if navs[i - 1] > 0]
    mean_r = sum(rets) / len(rets)
    var_r = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
    sr = (mean_r / math.sqrt(var_r)) * math.sqrt(365.0) if var_r > 1e-14 else 0.0
    peak, max_dd = (starting_nav if starting_nav is not None else navs[0]), 0.0
    for v in navs:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    base_nav = starting_nav if (starting_nav is not None and starting_nav > 0) else navs[0]
    return {
        "days": len(dates),
        "ending_nav": round(navs[-1], 2),
        "ret_pct": round((navs[-1] / base_nav - 1.0) * 100.0, 2),
        "ann_sharpe": round(sr, 3),
        "max_dd_pct": round(max_dd * 100.0, 2),
    }


portfolio_metrics = _portfolio_metrics


def _daily_returns_map(nav_by_date: dict[str, float]) -> dict[str, float]:
    dates = sorted(nav_by_date)
    return {
        dates[i]: (nav_by_date[dates[i]] / nav_by_date[dates[i - 1]] - 1.0)
        for i in range(1, len(dates))
        if nav_by_date[dates[i - 1]] > 0
    }


daily_returns_map = _daily_returns_map


def _dated_returns(panel: dict[str, list[BarPoint]]) -> dict[str, dict[datetime, float]]:
    out: dict[str, dict[datetime, float]] = {s: {} for s in COHORT_SYMBOLS}
    for s in COHORT_SYMBOLS:
        bars = panel.get(s, [])
        for i in range(1, len(bars)):
            if bars[i - 1].close > 0:
                out[s][bars[i].ts_avail] = (bars[i].close - bars[i - 1].close) / bars[i - 1].close
    return out


def _exec_prices_and_tradable(
    by_sym_start: dict[str, dict[datetime, BarPoint]],
    by_sym_avail: dict[str, dict[datetime, BarPoint]],
    t_avail: datetime,
) -> tuple[dict[str, Decimal], set[str]]:
    prices: dict[str, Decimal] = {}
    tradable: set[str] = set()
    for sym in COHORT_SYMBOLS:
        nxt = by_sym_start[sym].get(t_avail)
        cur = by_sym_avail[sym].get(t_avail)
        if nxt is not None and nxt.open > 0:
            prices[sym] = Decimal(str(nxt.open))
            if cur is not None and cur.entry_eligible:
                tradable.add(sym)
        elif cur is not None and cur.close > 0:
            prices[sym] = Decimal(str(cur.close))
    return prices, tradable


def _solve_arm_targets(
    arm_name: str,
    day_sigs: dict[str, SleeveSignal],
    ledger: SelfFinancingLedger,
    exec_prices: dict[str, Decimal],
    dated_rets: dict[str, dict[datetime, float]],
    t_avail: datetime,
    *,
    fee_rate: Decimal,
    holding_horizon_days: float,
    vote_gw: AdaptiveVoteGateway | None,
    logistic_gw: LogisticVetoGateway | None,
    by_sym_start: dict[str, dict[datetime, BarPoint]],
    eval_dates: list[datetime],
    idx: int,
    shadow_outcomes: list[tuple[bool, float]],
) -> dict[str, float]:
    active_syms = tuple(s for s in COHORT_SYMBOLS if s in day_sigs and s in exec_prices)
    if len(active_syms) < 2:
        return {}
    cur_w = ledger.current_weights(active_syms, exec_prices)
    win_trimmed = {
        s: dict(sorted((dt, r) for dt, r in dated_rets[s].items() if dt <= t_avail)[-60:])
        for s in active_syms
    }
    cov_d = coarse_bar_shrunk_covariance_aligned(win_trimmed, active_syms, shrinkage=0.25)
    cov_h = tuple(tuple(v * holding_horizon_days for v in row) for row in cov_d)
    sqrt_h = math.sqrt(holding_horizon_days)

    mu_gross: list[float] = []
    for sym, cw in zip(active_syms, cur_w, strict=True):
        sig = day_sigs[sym]
        raw_score = _sleeve_score(sig, arm_name, vote_gw)
        if (
            arm_name == "LOGISTIC_VETO"
            and logistic_gw is not None
            and t_avail >= STRESS_REPLAY_START
            and raw_score > 0.05
            and cw < 0.01
        ):
            feats = extract_gateway_features(sig, consensus_score=raw_score)
            # Labels in _train_dev_logistic_veto are already fee-net, so do not subtract round-trip fee twice.
            accept, _, _ = logistic_gw.should_accept(feats, incremental_cost_bps=0.0)
            if idx + 5 < len(eval_dates):
                f_bar = by_sym_start[sym].get(eval_dates[idx + 5])
                n_bar = by_sym_start[sym].get(t_avail)
                if f_bar and n_bar and n_bar.open > 0:
                    sh_net = ((f_bar.open - n_bar.open) / n_bar.open - float(fee_rate) * 2.0) * 10000.0
                    shadow_outcomes.append((accept, sh_net))
            if not accept:
                raw_score = 0.0
        vol_h_bps = sig.yang_zhang_vol * sqrt_h * 10000.0
        mu_bps = forecast_to_expected_return_bps(raw_score * 20.0, ic_prior=0.08, horizon_vol_bps=vol_h_bps)
        mu_gross.append(mu_bps / 10000.0)

    prob = OptimizationProblem(
        symbols=active_syms,
        expected_returns=tuple(mu_gross),
        current_weights=cur_w,
        covariance=cov_h,
        l1_fee_costs=(float(fee_rate),) * len(active_syms),
        l2_impact_costs=(0.0020,) * len(active_syms),
        risk_aversion=2.0,
        max_weight=0.30,
        cash_buffer=0.05,
    )
    solved = solve_convex_portfolio(prob).weights
    return {s: w for s, w in zip(active_syms, solved, strict=True)}


def _update_adaptive_vote(
    vote_gw: AdaptiveVoteGateway,
    day_sigs: dict[str, SleeveSignal],
    dated_rets: dict[str, dict[datetime, float]],
    next_avail: datetime,
) -> None:
    for sym in COHORT_SYMBOLS:
        sig = day_sigs.get(sym)
        r_nxt = dated_rets[sym].get(next_avail)
        if sig is None or r_nxt is None:
            continue
        if sig.s1_trend is not None and sig.s1_trend > 0.1:
            vote_gw.update_realized_outcome("s1", r_nxt)
        if sig.s2_residual_mom is not None and sig.s2_residual_mom > 0.1:
            vote_gw.update_realized_outcome("s2", r_nxt)
        if sig.s5_defensive_gold is not None and sig.s5_defensive_gold > 0.1:
            vote_gw.update_realized_outcome("s5", r_nxt)


def _run_self_financing_arm(
    arm_name: str,
    panel: dict[str, list[BarPoint]],
    signals: dict[datetime, dict[str, SleeveSignal]],
    eval_dates: list[datetime],
    *,
    fee_rate: Decimal = Decimal("0.0013"),
    logistic_gw: LogisticVetoGateway | None = None,
    holding_horizon_days: float = 20.0,
) -> dict:
    by_sym_start = {s: {b.ts_start: b for b in panel.get(s, [])} for s in COHORT_SYMBOLS}
    by_sym_avail = {s: {b.ts_avail: b for b in panel.get(s, [])} for s in COHORT_SYMBOLS}
    dated_rets = _dated_returns(panel)

    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    vote_gw = AdaptiveVoteGateway() if arm_name == "ADAPTIVE_VOTE" else None
    nav_by_date: dict[str, float] = {}
    shadow_outcomes: list[tuple[bool, float]] = []

    for idx in range(len(eval_dates) - 1):
        t_avail = eval_dates[idx]
        day_sigs = signals.get(t_avail, {})
        exec_prices, tradable = _exec_prices_and_tradable(by_sym_start, by_sym_avail, t_avail)

        if arm_name == "CASH_USDT":
            targets = {s: 0.0 for s in COHORT_SYMBOLS}
            ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
        elif arm_name == "STATIC_GOLD_AND_CRYPTO":
            # Passive buy-and-hold: allocate once on the first eligible day, then hold without daily churn.
            if not any(u > 0 for u in ledger.units.values()):
                elig = [s for s in COHORT_SYMBOLS if s in tradable]
                if elig:
                    w_eq = 0.95 / len(elig)
                    targets = {s: (w_eq if s in elig else 0.0) for s in COHORT_SYMBOLS}
                    ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)
        else:
            targets = _solve_arm_targets(
                arm_name, day_sigs, ledger, exec_prices, dated_rets, t_avail,
                fee_rate=fee_rate, holding_horizon_days=holding_horizon_days,
                vote_gw=vote_gw, logistic_gw=logistic_gw,
                by_sym_start=by_sym_start, eval_dates=eval_dates, idx=idx, shadow_outcomes=shadow_outcomes,
            )
            ledger.rebalance_to_targets(t_avail, targets, exec_prices, tradable_symbols=tradable)

        nav_by_date[t_avail.date().isoformat()] = float(ledger.mark_nav(exec_prices))
        if vote_gw is not None and idx + 1 < len(eval_dates):
            _update_adaptive_vote(vote_gw, day_sigs, dated_rets, eval_dates[idx + 1])

    stress_iso = STRESS_REPLAY_START.date().isoformat()
    return {
        "arm": arm_name,
        "nav_by_date": nav_by_date,
        "metrics_full": _portfolio_metrics(nav_by_date),
        "metrics_dev": _portfolio_metrics({k: v for k, v in nav_by_date.items() if k < stress_iso}),
        "metrics_stress": _portfolio_metrics({k: v for k, v in nav_by_date.items() if k >= stress_iso}),
        "fills": len(ledger.fills),
        "total_fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
        "turnover_multiple": round(float(ledger.cumulative_turnover_quote / ledger.starting_cash), 2),
        "shadow_veto": evaluate_shadow_veto(shadow_outcomes) if shadow_outcomes else None,
    }


def _train_dev_logistic_veto(
    panel: dict[str, list[BarPoint]],
    signals: dict[datetime, dict[str, SleeveSignal]],
    dev_dates: list[datetime],
    *,
    fee_rate: Decimal = Decimal("0.0013"),
    label_horizon_days: int = 5,
) -> tuple[LogisticVetoGateway, dict]:
    by_sym_start = {s: {b.ts_start: b for b in panel.get(s, [])} for s in COHORT_SYMBOLS}
    by_sym_avail = {s: {b.ts_avail: b for b in panel.get(s, [])} for s in COHORT_SYMBOLS}
    feats_list: list[list[float]] = []
    net_rets_bps: list[float] = []
    weights_list: list[float] = []
    ts_list: list[datetime] = []
    rt_fee = float(fee_rate) * 2.0

    for idx in range(len(dev_dates) - label_horizon_days - 1):
        t_avail, t_exit = dev_dates[idx], dev_dates[idx + label_horizon_days]
        if t_exit >= STRESS_REPLAY_START:
            break
        day_candidates: list[tuple[list[float], float]] = []
        for sym, sig in signals.get(t_avail, {}).items():
            if not sig.eligible_for_entry:
                continue
            score = _sleeve_score(sig, "FIXED_ENSEMBLE_S1_S2_S5")
            if score <= 0.05:
                continue
            b_cur = by_sym_avail[sym].get(t_avail)
            b_ent, b_ext = by_sym_start[sym].get(t_avail), by_sym_start[sym].get(t_exit)
            if not b_cur or not b_cur.entry_eligible or not b_ent or not b_ext or b_ent.open <= 0:
                continue
            net_bps = ((b_ext.open - b_ent.open) / b_ent.open - rt_fee) * 10000.0
            day_candidates.append((extract_gateway_features(sig, consensus_score=score), net_bps))
        if not day_candidates:
            continue
        w_u = 1.0 / len(day_candidates)
        for f_row, nbps in day_candidates:
            feats_list.append(f_row)
            net_rets_bps.append(nbps)
            weights_list.append(w_u)
            ts_list.append(t_avail)

    gw = LogisticVetoGateway(c_reg=0.2, safety_margin_bps=5.0)
    cal = gw.fit(
        feats_list,
        net_rets_bps,
        sample_weights=weights_list,
        purge_gap=label_horizon_days,
        timestamps=ts_list,
    )
    return gw, {
        "train_proposals": len(feats_list),
        "inner_cal_brier": round(cal.brier_score, 4),
        "inner_cal_bss": round(cal.brier_skill_score, 4),
        "inner_cal_ece": round(cal.ece, 4),
    }


def _solver_reconciliation_receipt() -> dict:
    p_bind = OptimizationProblem(
        symbols=("A", "B"),
        expected_returns=(0.02, 0.06),
        current_weights=(0.5, 0.5),
        covariance=((0.01, 0.0), (0.0, 0.01)),
        l1_fee_costs=(0.001, 0.001),
        l2_impact_costs=(0.0, 0.0),
        risk_aversion=1.0,
        max_weight=1.0,
        cash_buffer=0.0,
    )
    res = solve_convex_portfolio(p_bind)
    return {
        "binding_counterexample_weights": [round(w, 6) for w in res.weights],
        "binding_counterexample_utility": round(portfolio_utility(res.weights, p_bind), 6),
        "converged": res.converged,
        "kkt_residual": round(res.kkt_residual, 9),
    }


def run_first_ensemble_experiment(db_path: Path) -> dict:
    """Single structured service entry point executing the First Paper Experiment read-only."""
    con = open_readonly_market_db(db_path)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in COHORT_SYMBOLS}
        parity = audit_bar_parity_and_coverage(
            con,
            ("BTCUSDT", "ETHUSDT", "SOLUSDT", "AAVEUSDT", "XAUTUSDT"),
            start_at=datetime(2025, 1, 1, tzinfo=UTC),
            end_at=datetime(2025, 11, 23, tzinfo=UTC),
        )
        panel_1h_24 = {
            s: resample_hourly_to_bucket(load_keyed_candles(con, s, "1h", limit=20000), 24)
            for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XAUTUSDT")
        }
    finally:
        con.close()

    signals = compute_slow_sleeves(panel_1d, COHORT_SYMBOLS)
    eval_dates = [d for d in sorted(signals) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    dev_dates = [d for d in eval_dates if d < STRESS_REPLAY_START]

    gw_log, train_meta = _train_dev_logistic_veto(panel_1d, signals, dev_dates)
    arms_order = (
        "CASH_USDT",
        "STATIC_GOLD_AND_CRYPTO",
        "FIXED_S1",
        "FIXED_ENSEMBLE_S1_S2_S5",
        "ADAPTIVE_VOTE",
        "LOGISTIC_VETO",
    )
    results = {
        arm: _run_self_financing_arm(arm, panel_1d, signals, eval_dates, logistic_gw=(gw_log if arm == "LOGISTIC_VETO" else None))
        for arm in arms_order
    }
    loso = {arm: _run_self_financing_arm(arm, panel_1d, signals, eval_dates)["metrics_full"] for arm in ("DROP_S1", "DROP_S2", "DROP_S5")}

    base_rets = _daily_returns_map(results["FIXED_ENSEMBLE_S1_S2_S5"]["nav_by_date"])
    log_rets = _daily_returns_map(results["LOGISTIC_VETO"]["nav_by_date"])
    paired_full = paired_baseline_uplift(log_rets, base_rets, simulations=499, seed=42)
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    paired_stress = paired_baseline_uplift(
        {k: v for k, v in log_rets.items() if k >= stress_iso},
        {k: v for k, v in base_rets.items() if k >= stress_iso},
        simulations=499,
        seed=42,
    )
    nbx_counterfactual = _run_self_financing_arm("FIXED_ENSEMBLE_S1_S2_S5", panel_1d, signals, eval_dates, fee_rate=Decimal("0.00091"))["metrics_full"]

    sub_5 = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XAUTUSDT")
    sigs_1h = compute_slow_sleeves(panel_1h_24, sub_5, warmup_bars=60)
    common_1h_dates = sorted(d for d in sigs_1h if d >= datetime(2025, 3, 15, tzinfo=UTC))
    res_1h_sens = (
        _run_self_financing_arm("FIXED_S1", {s: panel_1h_24.get(s, []) for s in COHORT_SYMBOLS}, sigs_1h, common_1h_dates)["metrics_full"]
        if len(common_1h_dates) >= 30 else None
    )

    synthetic = run_synthetic_falsification_checks()
    solver_check = _solver_reconciliation_receipt()
    log_end = results["LOGISTIC_VETO"]["metrics_full"]["ending_nav"]
    ens_end = results["FIXED_ENSEMBLE_S1_S2_S5"]["metrics_full"]["ending_nav"]
    if not (synthetic["null_panel"]["rejected_noise"] and synthetic["planted_edge_panel"]["recovered_planted_edge"]):
        verdict = "INVALID_RUN"
    elif paired_full.get("status") == "POSITIVE_EXPLORATORY" and log_end > ens_end:
        verdict = "ADVANCE_TO_INDEPENDENT_EVAL"
    elif log_end <= ens_end:
        verdict = "RETIRE_INCREMENT"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "schema": "first-ensemble-experiment-receipt/1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "bar_source_primary": "NATIVE_1D",
        "cohort_estimand": "RETROSPECTIVE_CURATED_LIQUID_WALLEX_USDT_COHORT",
        "stress_replay_label": "BEAR_STRESS_REPLAY_SEEN (2025-11-24..2026-11-23)",
        "verdict": verdict,
        "solver_reconciliation": solver_check,
        "synthetic_falsification": synthetic,
        "logistic_train_meta": train_meta,
        "bar_parity_2025": parity,
        "arms": {
            arm: {
                "full": r["metrics_full"],
                "dev": r["metrics_dev"],
                "stress_seen": r["metrics_stress"],
                "fills": r["fills"],
                "fees_usdt": r["total_fees_usdt"],
                "turnover": r["turnover_multiple"],
                "shadow_veto": r["shadow_veto"].__dict__ if r["shadow_veto"] else None,
            }
            for arm, r in results.items()
        },
        "leave_one_sleeve_out_full": loso,
        "paired_logistic_vs_fixed_ensemble_full": {
            "status": paired_full.get("status"),
            "mean_uplift": paired_full.get("mean_uplift"),
            "ci_95": paired_full.get("ci_95"),
        },
        "paired_logistic_vs_fixed_ensemble_stress": {
            "status": paired_stress.get("status"),
            "mean_uplift": paired_stress.get("mean_uplift"),
            "ci_95": paired_stress.get("ci_95"),
        },
        "nobitex_fee_counterfactual_fixed_ensemble": nbx_counterfactual,
        "resampled_1h_sensitivity_fixed_s1": res_1h_sens,
    }


def render_first_ensemble_markdown(r: dict) -> str:
    """Render deterministic Markdown report from a structured experiment receipt."""
    lines = [
        "# First Paper Experiment — Slow Sleeves, Fixed Controls & Veto-Only Calibrated Logistic Challenger",
        "",
        f"**Generated (UTC):** `{r['generated_at_utc']}` · **Primary Bar Source:** `{r['bar_source_primary']}` · **Estimand:** `{r['cohort_estimand']}` · **Disposition:** **`{r['verdict']}`**",
        f"**Stress Window Classification:** `{r['stress_replay_label']}` (previously seen — never counted as untouched final holdout). **Executor:** `DISARMED` (`$0` funded budget).",
        "",
        "## 1. Repaired Solver & Synthetic Falsification Gate",
        "",
        f"- **Binding-Budget Solver Check (`(0.5, 0.5) -> (0.0, 1.0)`):** weights=`{r['solver_reconciliation']['binding_counterexample_weights']}`, utility=`{r['solver_reconciliation']['binding_counterexample_utility']}` (expected `0.0540`), converged=`{r['solver_reconciliation']['converged']}`.",
        f"- **Synthetic Null Panel:** `rejected_noise={r['synthetic_falsification']['null_panel']['rejected_noise']}`, `BSS={r['synthetic_falsification']['null_panel']['oos_brier_skill_score']}`, `accept_rate={r['synthetic_falsification']['null_panel']['oos_acceptance_rate']}`.",
        f"- **Synthetic Planted-Edge Panel:** `recovered={r['synthetic_falsification']['planted_edge_panel']['recovered_planted_edge']}`, `BSS={r['synthetic_falsification']['planted_edge_panel']['oos_brier_skill_score']}`, `veto_uplift=+{r['synthetic_falsification']['planted_edge_panel']['net_veto_uplift_bps']} bps`.",
        "",
        "## 2. Arm-by-Arm Self-Financing Wallex Spot Comparison (`$1,000` Starting Cash, Exact Received-Asset Fees)",
        "",
        "| Arm | Full Ending ($) | Full Ret (%) | Full Sharpe | Full MaxDD (%) | Dev Ret (%) | Stress-Seen Ret (%) | Stress MaxDD (%) | Fills | Fees ($) | Turnover |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm, d in r["arms"].items():
        f, dv, st = d["full"], d["dev"], d["stress_seen"]
        lines.append(
            f"| `{arm}` | {f['ending_nav']} | {f['ret_pct']}% | {f['ann_sharpe']} | {f['max_dd_pct']}% | {dv['ret_pct']}% | {st['ret_pct']}% | {st['max_dd_pct']}% | {d['fills']} | {d['fees_usdt']} | {d['turnover']}x |"
        )
    sh = r["arms"]["LOGISTIC_VETO"]["shadow_veto"]
    lines += [
        "",
        "### Paired Bootstrap & Logistic Veto Shadow Diagnostics",
        "",
        f"- **Logistic Train Calibration (Chronological Inner Fold):** `proposals={r['logistic_train_meta']['train_proposals']}`, `Brier={r['logistic_train_meta']['inner_cal_brier']}`, `BSS={r['logistic_train_meta']['inner_cal_bss']}`, `ECE={r['logistic_train_meta']['inner_cal_ece']}`.",
        f"- **Paired `LOGISTIC_VETO - FIXED_ENSEMBLE_S1_S2_S5` (Full):** status=`{r['paired_logistic_vs_fixed_ensemble_full']['status']}`, CI95=`{r['paired_logistic_vs_fixed_ensemble_full']['ci_95']}`.",
        f"- **Paired `LOGISTIC_VETO - FIXED_ENSEMBLE_S1_S2_S5` (Bear Stress):** status=`{r['paired_logistic_vs_fixed_ensemble_stress']['status']}`, CI95=`{r['paired_logistic_vs_fixed_ensemble_stress']['ci_95']}`.",
        f"- **Shadow Veto Audit:** `{sh}`",
        f"- **Wallex Path Under Hypothetical Nobitex `-30%` Fee Counterfactual (`FIXED_ENSEMBLE_S1_S2_S5`):** `{r['nobitex_fee_counterfactual_fixed_ensemble']}`",
        "",
        "## 3. Leave-One-Sleeve-Out Marginal Contribution (`FIXED_ENSEMBLE_S1_S2_S5`)",
        "",
        "| Ablation | Ending ($) | Full Ret (%) | Ann. Sharpe | MaxDD (%) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for k, m in r["leave_one_sleeve_out_full"].items():
        lines.append(f"| `{k}` | {m['ending_nav']} | {m['ret_pct']}% | {m['ann_sharpe']} | {m['max_dd_pct']}% |")
    lines += [
        "",
        "## 4. 2025 Coverage & Native `1d` vs Resampled `1h` Bar-Parity Audit",
        "",
        "| Symbol | Daily Bars | Zero-Vol Days | Hourly Bars | Zero-Vol Hours | Complete Days Compared | Unequal Open Days | Max Open Gap (bps) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for sym, p in r["bar_parity_2025"].items():
        lines.append(
            f"| `{sym}` | {p['daily_bars']} | {p['zero_vol_days']} | {p['hourly_bars']} | {p['zero_vol_hours']} | {p['complete_days_compared']} | {p['unequal_open_days']} | {p['max_open_gap_bps']} |"
        )
    lines.append(f"\n- **Bar-Source Sensitivity (`FIXED_S1` on `RESAMPLED_1H` 2025–2026):** `{r['resampled_1h_sensitivity_fixed_s1']}`")
    return "\n".join(lines) + "\n"
