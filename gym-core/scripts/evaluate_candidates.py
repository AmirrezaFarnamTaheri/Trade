"""Optimized walk-forward development evaluation of Candidates A, B, and C on real Wallex market.db.

Runs strictly read-only against data/live/market.db and outputs a reproducible decision packet:
- Candidate A (Track A): 6-Triangle Leave-One-Out FX Basis + Kalman Filter with anti-churn hurdle
  on a chronological 50/50 train/OOS split (comparing Wallex 20 bps vs Nobitex 14 bps maker RT).
- Candidate B (Track B): Horizon-Matched Convex L1 Optimizer (25-day holding horizon matching EWMAC)
  vs simple 10% no-trade band vs equal-weight buy-and-hold on BOTH the 5-asset 2024-2026 gold+crypto
  panel (with chronological 50/50 OOS split) AND the 4-year 2022-2026 crypto core panel.
- Candidate C (Track B): Preview-reconciled TMN-Borrow Carry vs unlevered 1x spot on historical
  USDTTMN & XAUTTMN daily series + 0%/25%/50% FX appreciation scenario sweep.
"""
from __future__ import annotations

import argparse
import math
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from gym.adapters.candle_reader import open_readonly_market_db
from gym.adapters.mix_journal_store import append_mix_journal_v2
from gym.domain.async_covariance import (
    align_covariance_to_symbols,
    coarse_bar_shrunk_covariance,
)
from gym.domain.convex_optimizer import (
    OptimizationProblem,
    forecast_to_expected_return_bps,
    simple_no_trade_band_allocator,
    solve_convex_portfolio,
)
from gym.domain.forecast_graph import (
    CrossMarketBreadthRegimeNode,
    MultiHorizonEwmacNode,
    run_2x2_attribution,
)
from gym.domain.kalman_models import (
    DUAL_QUOTED_COINS,
    KalmanBasisFilter,
    leave_one_out_fx_interval,
)
from gym.domain.model import BookTop, dec, parse_ts
from gym.domain.signal_gatekeeper import (
    build_mix_journal_v2_entry,
    check_causality_perturbation,
    deflated_sharpe_probability,
    run_path_preserving_placebo,
    simulate_joint_gate_power,
)
from gym.domain.tmn_carry import (
    TmnBorrowTerms,
    compare_fx_appreciation_scenarios,
    simulate_tmn_borrow_carry,
)
from gym.domain.volatility_models import OhlcBar, yang_zhang_volatility

CANDIDATE_B_GOLD_CRYPTO = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XAUTUSDT")
CANDIDATE_B_4YR_CRYPTO = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")


def _load_candles(con: sqlite3.Connection, symbol: str, resolution: str, *, limit: int = 20000) -> list[tuple[datetime, float, float, float, float]]:
    inst = con.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (symbol,)).fetchone()
    if inst is None:
        return []
    rows = con.execute(
        "SELECT t, o, h, l, c FROM venue_candles "
        "WHERE instrument_id = ? AND resolution = ? ORDER BY t DESC LIMIT ?",
        (inst[0], resolution, limit),
    ).fetchall()
    rows.reverse()
    out: list[tuple[datetime, float, float, float, float]] = []
    for ts_s, o, h, lo, c in rows:
        if o is None or h is None or lo is None or c is None:
            continue
        fo, fh, fl, fc = float(o), float(h), float(lo), float(c)
        if fo > 0 and fh > 0 and fl > 0 and fc > 0:
            out.append((parse_ts(ts_s), fo, fh, fl, fc))
    return out


def _sharpe_and_dsr(returns: list[float], n_trials: int = 21) -> tuple[float, float, float, float]:
    n = len(returns)
    if n < 5:
        return 0.0, 0.0, 0.0, 0.0
    mean_r = sum(returns) / n
    var_r = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = math.sqrt(max(var_r, 1e-12))
    sr = mean_r / std_r
    dsr = deflated_sharpe_probability(sr, n, n_trials)
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        cum *= (1.0 + r)
        if cum > peak:
            peak = cum
        dd = (peak - cum) / peak
        if dd > max_dd:
            max_dd = dd
    return sr, dsr, (cum - 1.0) * 100.0, max_dd * 100.0


def _run_candidate_a_slice(
    series: dict[str, dict[datetime, float]],
    timestamps: list[datetime],
    *,
    z_entry: float = 3.0,
    min_conv_bps: float = 45.0,
    min_hold_min: int = 15,
    max_hold_min: int = 240,
) -> dict:
    """Replay anti-churn Kalman basis strategy on a chronological slice, comparing Wallex 20 bps vs Nobitex 14 bps."""
    arm_wlx_taker = 0.0
    arm_wlx_maker = 0.0
    arm_nbx_maker = 0.0
    per_coin: list[dict] = []
    daily_rets_wlx: dict[str, float] = {}
    pos_btc: list[float] = []
    ret_btc: list[float] = []

    for coin in DUAL_QUOTED_COINS:
        kf = KalmanBasisFilter(z_entry=z_entry, round_trip_usdt_maker_bps=min_conv_bps)
        holding = False
        entry_px = 0.0
        entry_at: datetime | None = None
        trades = 0
        wlx_m = 0.0
        wlx_t = 0.0
        nbx_m = 0.0
        prev_px: float | None = None

        for t in timestamps:
            sym_tmn, sym_usdt = f"{coin}TMN", f"{coin}USDT"
            if t not in series[sym_tmn] or t not in series[sym_usdt]:
                continue
            px_tmn = Decimal(str(series[sym_tmn][t]))
            px_usdt = Decimal(str(series[sym_usdt][t]))

            quotes: dict[str, BookTop] = {}
            for peer in DUAL_QUOTED_COINS:
                if t in series[f"{peer}TMN"] and t in series[f"{peer}USDT"]:
                    pt = Decimal(str(series[f"{peer}TMN"][t]))
                    pu = Decimal(str(series[f"{peer}USDT"][t]))
                    quotes[f"{peer}TMN"] = BookTop(f"{peer}TMN", t, pt * Decimal("0.9995"), pt * Decimal("1.0005"), Decimal("10"), Decimal("10"), frozenset())
                    quotes[f"{peer}USDT"] = BookTop(f"{peer}USDT", t, pu * Decimal("0.9995"), pu * Decimal("1.0005"), Decimal("10"), Decimal("10"), frozenset())

            est = leave_one_out_fx_interval(coin, quotes, t, max_skew_seconds=5.0, min_peers=4)
            if est.fx_center is None:
                continue
            out = kf.update(as_of=t, coin_tmn_mid=px_tmn, coin_usdt_mid=px_usdt, peer_fx_center=est.fx_center)
            px_f = float(px_usdt)

            if prev_px is not None and prev_px > 0:
                ret = (px_f - prev_px) / prev_px
                pos = 1.0 if holding else 0.0
                if coin == "BTC":
                    pos_btc.append(pos)
                    ret_btc.append(ret)
                dk = t.date().isoformat()
                daily_rets_wlx[dk] = daily_rets_wlx.get(dk, 0.0) + (pos * ret) / len(DUAL_QUOTED_COINS)
            prev_px = px_f

            if not holding and out.forecast_usdt_leg > 0:
                holding = True
                entry_px = px_f
                entry_at = t
            elif holding and entry_at is not None:
                held_min = (t - entry_at).total_seconds() / 60.0
                if (held_min >= min_hold_min and out.z_score <= 0.0) or held_min >= max_hold_min:
                    gross_bps = (px_f - entry_px) / entry_px * 10000.0
                    wlx_m += gross_bps - 20.0
                    wlx_t += gross_bps - 26.0
                    nbx_m += gross_bps - 14.0
                    trades += 1
                    holding = False
                    entry_at = None

        arm_wlx_taker += wlx_t
        arm_wlx_maker += wlx_m
        arm_nbx_maker += nbx_m
        per_coin.append({"coin": coin, "trades": trades, "wlx_maker_bps": round(wlx_m, 2), "nbx_maker_bps": round(nbx_m, 2)})

    attr = run_2x2_attribution(Decimal("0"), Decimal(str(round(arm_wlx_taker, 2))), Decimal("0"), Decimal(str(round(arm_wlx_maker, 2))))
    day_rets = [daily_rets_wlx[k] for k in sorted(daily_rets_wlx)]
    sr, dsr, _, _ = _sharpe_and_dsr(day_rets, n_trials=21)
    placebo_p = round(run_path_preserving_placebo(ret_btc, pos_btc, replications=500).p_value, 4) if len(ret_btc) >= 20 else None
    return {
        "minutes": len(timestamps),
        "days": len(day_rets),
        "total_trades": sum(c["trades"] for c in per_coin),
        "wlx_maker_bps": round(arm_wlx_maker, 2),
        "wlx_taker_bps": round(arm_wlx_taker, 2),
        "nbx_maker_bps": round(arm_nbx_maker, 2),
        "interaction_bps": float(attr.interaction_effect),
        "daily_sharpe": round(sr, 4),
        "dsr_prob": round(dsr, 4),
        "placebo_p": placebo_p,
        "per_coin": per_coin,
    }


def evaluate_candidate_a(con: sqlite3.Connection) -> dict:
    """Candidate A (Track A): Chronological 50/50 train/OOS walk-forward with anti-churn hurdle."""
    series: dict[str, dict[datetime, float]] = {}
    for coin in DUAL_QUOTED_COINS:
        for q in ("TMN", "USDT"):
            sym = f"{coin}{q}"
            rows = _load_candles(con, sym, "1min", limit=8000)
            series[sym] = {t: c for t, _, _, _, c in rows}

    all_ts = sorted({t for d in series.values() for t in d})
    aligned = [t for t in all_ts if sum(1 for c in DUAL_QUOTED_COINS if t in series[f"{c}TMN"] and t in series[f"{c}USDT"]) >= 5]
    if len(aligned) < 120:
        return {"status": "INSUFFICIENT_DATA", "aligned_minutes": len(aligned)}

    split = len(aligned) // 2
    train_res = _run_candidate_a_slice(series, aligned[:split])
    oos_res = _run_candidate_a_slice(series, aligned[split:])
    verdict = "CANDIDATE_FOR_PREREG" if (oos_res["wlx_maker_bps"] > 0 and oos_res["dsr_prob"] >= 0.95) else "RETIRE_ON_WALLEX_TEST_NOBITEX"
    return {"status": "OK", "train": train_res, "oos": oos_res, "verdict": verdict}


def _evaluate_allocation_panel(
    con: sqlite3.Connection,
    symbols: tuple[str, ...],
    *,
    holding_horizon_days: float = 25.0,
    ic_prior: float = 0.08,
    risk_aversion: float = 1.5,
) -> dict:
    """Horizon-matched Convex L1 Optimizer vs 10% Band vs Equal-Weight with chronological 50/50 OOS split."""
    candles_by_sym: dict[str, dict[datetime, tuple[float, float, float, float]]] = {}
    for sym in symbols:
        rows = _load_candles(con, sym, "1d", limit=3000)
        candles_by_sym[sym] = {t: (o, h, lo, c) for t, o, h, lo, c in rows}

    common_dates = sorted(set.intersection(*(set(d.keys()) for d in candles_by_sym.values())))
    if len(common_dates) < 120:
        return {"status": "INSUFFICIENT_DATA", "common_days": len(common_dates)}

    ewmac_nodes = {sym: MultiHorizonEwmacNode(pairs=((8, 32), (16, 64), (32, 128))) for sym in symbols}
    regime_node = CrossMarketBreadthRegimeNode()
    w_convex = [0.0] * len(symbols)
    w_band = [0.0] * len(symbols)

    rets_convex: list[float] = []
    rets_band: list[float] = []
    rets_eq: list[float] = []
    pos_lead: list[float] = []
    mkt_lead: list[float] = []
    ret_hist: dict[str, list[float]] = {s: [] for s in symbols}
    ohlc_hist: dict[str, list[OhlcBar]] = {s: [] for s in symbols}
    fee_oneway = 0.0013  # Wallex USDT L1 taker
    turn_convex = 0.0
    turn_band = 0.0
    sqrt_h = math.sqrt(holding_horizon_days)

    for idx in range(1, len(common_dates)):
        t_prev = common_dates[idx - 1]
        t_curr = common_dates[idx]
        day_r = []
        for sym in symbols:
            o, h, lo, c = candles_by_sym[sym][t_curr]
            c_prev = candles_by_sym[sym][t_prev][3]
            r = (c - c_prev) / c_prev
            day_r.append(r)
            ret_hist[sym].append(r)
            ohlc_hist[sym].append(OhlcBar(o, h, lo, c))

        r_conv = sum(w * r for w, r in zip(w_convex, day_r, strict=True))
        r_bnd = sum(w * r for w, r in zip(w_band, day_r, strict=True))
        r_eq = sum(day_r) / len(symbols)

        raw_f = [ewmac_nodes[sym].update(candles_by_sym[sym][t_curr][3]) for sym in symbols]
        pos_frac = sum(1 for f in raw_f if f > 0) / len(symbols)
        reg_mult = regime_node.evaluate(pos_frac, floor=0.25)

        if idx >= 65:
            window_rets = {s: ret_hist[s][-60:] for s in symbols}
            cov_syms, cov_daily_raw = coarse_bar_shrunk_covariance(window_rets, shrinkage=0.25)
            cov_daily = align_covariance_to_symbols(symbols, cov_syms, cov_daily_raw)
            # Horizon-matched covariance (H * Sigma_daily) & expected return (sqrt(H) * sigma_daily)
            cov_h = tuple(tuple(v * holding_horizon_days for v in row) for row in cov_daily)
            vols_h_bps = [yang_zhang_volatility(ohlc_hist[s][-20:]) * sqrt_h * 10000.0 for s in symbols]
            mu_h = tuple(
                forecast_to_expected_return_bps(f * reg_mult, ic_prior=ic_prior, horizon_vol_bps=vb) / 10000.0
                for f, vb in zip(raw_f, vols_h_bps, strict=True)
            )
            prob = OptimizationProblem(
                symbols=symbols,
                expected_returns=mu_h,
                current_weights=tuple(w_convex),
                covariance=cov_h,
                l1_fee_costs=(fee_oneway,) * len(symbols),
                l2_impact_costs=(0.0020,) * len(symbols),
                risk_aversion=risk_aversion,
                max_weight=0.35,
                cash_buffer=0.05,
            )
            new_conv = list(solve_convex_portfolio(prob).weights)

            pos_raw = [max(0.0, f * reg_mult) for f in raw_f]
            s_pos = sum(pos_raw)
            desired_band = tuple((0.95 * x / s_pos) if s_pos > 0 else 0.0 for x in pos_raw)
            new_band = list(simple_no_trade_band_allocator(tuple(w_band), desired_band, band=0.10))

            tc_conv = sum(abs(a - b) for a, b in zip(new_conv, w_convex, strict=True)) * fee_oneway
            tc_band = sum(abs(a - b) for a, b in zip(new_band, w_band, strict=True)) * fee_oneway
            turn_convex += sum(abs(a - b) for a, b in zip(new_conv, w_convex, strict=True))
            turn_band += sum(abs(a - b) for a, b in zip(new_band, w_band, strict=True))

            rets_convex.append(r_conv - tc_conv)
            rets_band.append(r_bnd - tc_band)
            rets_eq.append(r_eq)
            pos_lead.append(w_convex[0])
            mkt_lead.append(day_r[0])

            w_convex = new_conv
            w_band = new_band

    half = len(rets_convex) // 2
    sr_c, dsr_c, ret_c, dd_c = _sharpe_and_dsr(rets_convex, n_trials=21)
    sr_c_oos, dsr_c_oos, ret_c_oos, dd_c_oos = _sharpe_and_dsr(rets_convex[half:], n_trials=21)
    sr_b, dsr_b, ret_b, dd_b = _sharpe_and_dsr(rets_band, n_trials=21)
    sr_b_oos, dsr_b_oos, ret_b_oos, dd_b_oos = _sharpe_and_dsr(rets_band[half:], n_trials=21)
    sr_e, _, ret_e, dd_e = _sharpe_and_dsr(rets_eq, n_trials=21)
    sr_e_oos, _, ret_e_oos, dd_e_oos = _sharpe_and_dsr(rets_eq[half:], n_trials=21)

    placebo = run_path_preserving_placebo(mkt_lead, pos_lead, replications=500)
    power = simulate_joint_gate_power(rets_convex, edge_bps_per_step=12.0, horizon_steps=365, n_trials=21, replications=200)

    btc_closes = [candles_by_sym[symbols[0]][d][3] for d in common_dates[:150]]

    def _stateful_ewmac(ps: list[float]) -> list[float]:
        node = MultiHorizonEwmacNode(pairs=((8, 32), (16, 64)))
        return [node.update(p) for p in ps]

    causal_ok = check_causality_perturbation(_stateful_ewmac, btc_closes, cutoff_index=100)
    return {
        "status": "OK",
        "start_date": common_dates[65].date().isoformat(),
        "oos_start_date": common_dates[65 + half].date().isoformat(),
        "end_date": common_dates[-1].date().isoformat(),
        "eval_days": len(rets_convex),
        "oos_days": len(rets_convex) - half,
        "convex": {"ann_sharpe": round(sr_c * math.sqrt(365), 3), "dsr": round(dsr_c, 4), "ret_pct": round(ret_c, 2), "max_dd_pct": round(dd_c, 2), "turnover": round(turn_convex, 2)},
        "convex_oos": {"ann_sharpe": round(sr_c_oos * math.sqrt(365), 3), "dsr": round(dsr_c_oos, 4), "ret_pct": round(ret_c_oos, 2), "max_dd_pct": round(dd_c_oos, 2)},
        "band": {"ann_sharpe": round(sr_b * math.sqrt(365), 3), "dsr": round(dsr_b, 4), "ret_pct": round(ret_b, 2), "max_dd_pct": round(dd_b, 2), "turnover": round(turn_band, 2)},
        "band_oos": {"ann_sharpe": round(sr_b_oos * math.sqrt(365), 3), "dsr": round(dsr_b_oos, 4), "ret_pct": round(ret_b_oos, 2), "max_dd_pct": round(dd_b_oos, 2)},
        "eq": {"ann_sharpe": round(sr_e * math.sqrt(365), 3), "ret_pct": round(ret_e, 2), "max_dd_pct": round(dd_e, 2)},
        "eq_oos": {"ann_sharpe": round(sr_e_oos * math.sqrt(365), 3), "ret_pct": round(ret_e_oos, 2), "max_dd_pct": round(dd_e_oos, 2)},
        "placebo_p": round(placebo.p_value, 4),
        "power_365d_12bps": round(power.dsr_pass_rate, 3),
        "causality_ok": causal_ok,
        "latest_weights": {s: round(w, 4) for s, w in zip(symbols, w_convex, strict=True)},
    }


def evaluate_candidate_b(con: sqlite3.Connection, mix_v2_path: Path) -> dict:
    p_gold = _evaluate_allocation_panel(con, CANDIDATE_B_GOLD_CRYPTO)
    p_4yr = _evaluate_allocation_panel(con, CANDIDATE_B_4YR_CRYPTO)

    if p_gold.get("status") == "OK" and not mix_v2_path.exists():
        now = datetime.now(UTC)
        for sym, w in p_gold["latest_weights"].items():
            entry = build_mix_journal_v2_entry(
                as_of=now,
                cohort_start=now,
                symbol=sym,
                intended_size_usdt=Decimal(str(round(w * 1000.0, 2))),
                displayed_depth_usdt=Decimal("5000.00"),
                fee_vintage="PUBLISHED_STRUCTURED_FEE_L1",
                missed_qty_usdt=Decimal("0"),
                tracking_error_bps=Decimal("0"),
                status="RECORDED",
            )
            append_mix_journal_v2(mix_v2_path, entry)

    best_dsr = max(p_gold.get("convex", {}).get("dsr", 0.0), p_4yr.get("convex", {}).get("dsr", 0.0))
    verdict = "READY_FOR_TRACK_B_PREREG" if best_dsr >= 0.95 else "TRACK_B_CANDIDATE_MONITOR"
    return {"gold_crypto_2yr": p_gold, "crypto_4yr": p_4yr, "verdict": verdict}


def evaluate_candidate_c(con: sqlite3.Connection) -> dict:
    historical: list[dict] = []
    for sym in ("USDTTMN", "XAUTTMN"):
        rows = _load_candles(con, sym, "1d", limit=400)
        if len(rows) < 60:
            continue
        books = [
            BookTop(sym, t, dec(str(c)) * Decimal("0.9990"), dec(str(c)) * Decimal("1.0010"), Decimal("10000"), Decimal("10000"), frozenset())
            for t, _, _, _, c in rows[-365:]
        ]
        for lev in (Decimal("1.5"), Decimal("2.0")):
            terms = TmnBorrowTerms(sym, Decimal("100000000"), lev, allow_renewal_at_expiry=True)
            res = simulate_tmn_borrow_carry(terms, books)
            historical.append(
                {
                    "symbol": sym,
                    "days": len(books),
                    "leverage": str(lev),
                    "status": res.status,
                    "levered_ret_pct": round(float((res.final_levered_equity_tmn / res.initial_collateral_tmn - 1) * 100), 2),
                    "unlevered_1x_ret_pct": round(float((res.final_unlevered_1x_equity_tmn / res.initial_collateral_tmn - 1) * 100), 2),
                    "excess_over_1x_pct": round(float((res.excess_over_1x_tmn / res.initial_collateral_tmn) * 100), 2),
                    "rolls": res.roll_count,
                    "warnings": res.warning_events,
                }
            )

    scen_terms = TmnBorrowTerms("USDTTMN", Decimal("100000000"), Decimal("1.5"), allow_renewal_at_expiry=True)
    scen = compare_fx_appreciation_scenarios(
        scen_terms,
        start_at=datetime(2026, 11, 24, tzinfo=UTC),
        horizon_days=180,
        annual_fx_rates=(Decimal("0.00"), Decimal("0.25"), Decimal("0.50"), Decimal("0.75")),
    )
    scenarios = [
        {
            "annual_fx_pct": int(rate * 100),
            "levered_ret_pct": round(float((r.final_levered_equity_tmn / r.initial_collateral_tmn - 1) * 100), 2),
            "unlevered_1x_ret_pct": round(float((r.final_unlevered_1x_equity_tmn / r.initial_collateral_tmn - 1) * 100), 2),
            "excess_over_1x_pct": round(float((r.excess_over_1x_tmn / r.initial_collateral_tmn) * 100), 2),
        }
        for rate, r in scen.items()
    ]
    return {"historical": historical, "scenarios_180d": scenarios}


def _append_panel_md(lines: list[str], title: str, p: dict) -> None:
    lines += [f"### {title}", ""]
    if p.get("status") != "OK":
        lines.append(f"- Status: `{p}`")
        return
    c, co = p["convex"], p["convex_oos"]
    b, bo = p["band"], p["band_oos"]
    e, eo = p["eq"], p["eq_oos"]
    lines += [
        f"- **Full:** `{p['start_date']} .. {p['end_date']}` (`{p['eval_days']}d`) · **OOS Second Half:** `{p['oos_start_date']} .. {p['end_date']}` (`{p['oos_days']}d`) · **Causality:** `{p['causality_ok']}` · **Placebo p:** `{p['placebo_p']}`",
        f"- **Latest Horizon-Matched Convex Weights:** `{p['latest_weights']}`",
        "",
        "| Allocator | Full Ann. Sharpe | Full DSR (`N=21`) | Full Ret (%) | Full MaxDD (%) | Turnover | OOS Ann. Sharpe | OOS Ret (%) | OOS MaxDD (%) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| **Horizon-Matched Convex L1 (`G1+G4`)** | {c['ann_sharpe']} | {c['dsr']} | {c['ret_pct']}% | {c['max_dd_pct']}% | {c['turnover']} | {co['ann_sharpe']} | {co['ret_pct']}% | {co['max_dd_pct']}% |",
        f"| Simple `10%` No-Trade Band | {b['ann_sharpe']} | {b['dsr']} | {b['ret_pct']}% | {b['max_dd_pct']}% | {b['turnover']} | {bo['ann_sharpe']} | {bo['ret_pct']}% | {bo['max_dd_pct']}% |",
        f"| Equal-Weight Buy & Hold | {e['ann_sharpe']} | — | {e['ret_pct']}% | {e['max_dd_pct']}% | 0.0 | {eo['ann_sharpe']} | {eo['ret_pct']}% | {eo['max_dd_pct']}% |",
        "",
    ]


def write_report(report_path: Path, a: dict, b: dict, c: dict) -> None:
    lines = [
        "# Optimized Walk-Forward Development Evaluation — Candidates A, B, and C",
        "",
        f"**Generated (UTC):** `{datetime.now(UTC).isoformat()}` · **Source:** `data/live/market.db` (read-only) · **Authority:** Paper development evaluation only (`DISARMED`, `$0` funded budget).",
        "",
        "## 1. Candidate A (Track A) — Anti-Churn 6-Triangle FX Basis (`z >= 3.0`, `>= 45 bps` hurdle, 50/50 Walk-Forward)",
        "",
    ]
    if a.get("status") == "OK":
        tr, oos = a["train"], a["oos"]
        lines += [
            f"- **Verdict:** **`{a['verdict']}`**",
            "",
            "| Split | Minutes | Trades | Wallex Maker (bps) | Wallex Taker (bps) | Nobitex -30% Maker (bps) | Daily Sharpe | DSR Prob | Placebo p |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            f"| Train (first 50%) | {tr['minutes']} | {tr['total_trades']} | {tr['wlx_maker_bps']} | {tr['wlx_taker_bps']} | {tr['nbx_maker_bps']} | {tr['daily_sharpe']} | {tr['dsr_prob']} | {tr['placebo_p']} |",
            f"| **OOS (second 50%)** | {oos['minutes']} | {oos['total_trades']} | {oos['wlx_maker_bps']} | {oos['wlx_taker_bps']} | {oos['nbx_maker_bps']} | {oos['daily_sharpe']} | {oos['dsr_prob']} | {oos['placebo_p']} |",
            "",
        ]
    else:
        lines.append(f"- Status: `{a}`")

    lines += [f"## 2. Candidate B (Track B) — Horizon-Matched Multi-Asset Vector Allocation (`verdict={b['verdict']}`)", ""]
    _append_panel_md(lines, "Panel 1: 5-Asset Gold + Crypto Core (`BTC, ETH, SOL, XRP, XAUT`)", b["gold_crypto_2yr"])
    _append_panel_md(lines, "Panel 2: 4-Year Crypto Core (`BTC, ETH, SOL, XRP`)", b["crypto_4yr"])

    lines += [
        "## 3. Candidate C (Track B) — Preview-Reconciled TMN-Borrow Carry vs. `1x` Spot",
        "",
        "| Symbol | Days | Leverage | Status | Levered Ret (%) | Unlevered 1x (%) | Excess vs 1x (%) | 21d Rolls | Warnings |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in c["historical"]:
        lines.append(
            f"| `{r['symbol']}` | {r['days']} | {r['leverage']}x | `{r['status']}` | {r['levered_ret_pct']}% | {r['unlevered_1x_ret_pct']}% | {r['excess_over_1x_pct']}% | {r['rolls']} | {r['warnings']} |"
        )
    lines += [
        "",
        "### 180-Day FX Appreciation Break-Even Sweep (`1.5x` Leverage on `USDTTMN`)",
        "",
        "| Annual FX Appreciation | Levered Ret (%) | Unlevered 1x (%) | Excess vs 1x (%) |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for s in c["scenarios_180d"]:
        lines.append(f"| {s['annual_fx_pct']}%/yr | {s['levered_ret_pct']}% | {s['unlevered_1x_ret_pct']}% | {s['excess_over_1x_pct']}% |")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimized walk-forward evaluation of Candidates A, B, and C")
    parser.add_argument("--db", type=Path, default=Path("../data/live/market.db"))
    parser.add_argument("--report", type=Path, default=Path("../evidence/archive/audits/2026-11-24-candidate-evaluation-report.md"))
    parser.add_argument("--mix-v2", type=Path, default=Path("../data/live/allocation/mix-journal-v2.jsonl"))
    args = parser.parse_args()
    con = open_readonly_market_db(args.db)
    try:
        res_a = evaluate_candidate_a(con)
        res_b = evaluate_candidate_b(con, args.mix_v2)
        res_c = evaluate_candidate_c(con)
    finally:
        con.close()
    write_report(args.report, res_a, res_b, res_c)
    print(f"Wrote {args.report} | A={res_a.get('verdict')} | B={res_b.get('verdict')} | C_hist={len(res_c['historical'])}")


if __name__ == "__main__":
    main()
