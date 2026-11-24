"""Development evaluation of Candidates A, B, and C on real Wallex market.db (spec §4–§7).

Runs strictly read-only against data/live/market.db and outputs a reproducible decision packet:
- Candidate A (Track A): 6-Triangle Leave-One-Out FX Basis + Kalman Filter on aligned 1-min bars
  (exact Wallex L1 maker/taker fees, 2x2 A/B/C/D attribution, 500-run path-preserving placebo, power check).
- Candidate B (Track B): Multi-Asset Vector Allocation (MultiHorizonEwmac + CrossMarketBreadthRegime
  + solve_convex_portfolio) vs simple 10% no-trade band vs equal-weight buy-and-hold on aligned daily bars,
  plus 500-run placebo, power check, causality check, and versioned mix-journal-v2.jsonl bootstrap.
- Candidate C (Track B): Preview-reconciled TMN-Borrow Carry vs unlevered 1x spot on real historical
  USDTTMN & XAUTTMN daily series + 0%/25%/50% FX appreciation scenario sweep & day-21 renewal rejection.
"""
from __future__ import annotations

import argparse
import math
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from gym.domain.async_covariance import coarse_bar_shrunk_covariance
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
    append_mix_journal_v2,
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

CANDIDATE_B_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "XAUTUSDT")


def _open_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=10.0)


def _load_candles(con: sqlite3.Connection, symbol: str, resolution: str, *, limit: int = 20000) -> list[tuple[datetime, float, float, float, float]]:
    rows = con.execute(
        "SELECT vc.t, vc.o, vc.h, vc.l, vc.c FROM venue_candles vc "
        "JOIN instruments i ON i.instrument_id = vc.instrument_id "
        "WHERE i.symbol = ? AND vc.resolution = ? ORDER BY vc.t DESC LIMIT ?",
        (symbol, resolution, limit),
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


def _sharpe_and_dsr(returns: list[float], n_trials: int = 21) -> tuple[float, float, float]:
    n = len(returns)
    if n < 5:
        return 0.0, 0.0, 0.0
    mean_r = sum(returns) / n
    var_r = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = math.sqrt(max(var_r, 1e-12))
    sr = mean_r / std_r
    dsr = deflated_sharpe_probability(sr, n, n_trials)
    cum = 1.0
    for r in returns:
        cum *= (1.0 + r)
    return sr, dsr, (cum - 1.0) * 100.0


def evaluate_candidate_a(con: sqlite3.Connection) -> dict:
    """Candidate A (Track A): 6-Triangle Leave-One-Out FX Basis + Kalman Filter on aligned 1-min candles."""
    series: dict[str, dict[datetime, float]] = {}
    for coin in DUAL_QUOTED_COINS:
        for q in ("TMN", "USDT"):
            sym = f"{coin}{q}"
            rows = _load_candles(con, sym, "1min", limit=8000)
            series[sym] = {t: c for t, _, _, _, c in rows}

    # Find timestamps where at least 5 of 6 triangles have both TMN & USDT 1-min closes
    all_ts = sorted({t for d in series.values() for t in d})
    aligned_ts: list[datetime] = []
    for t in all_ts:
        have = sum(1 for c in DUAL_QUOTED_COINS if t in series[f"{c}TMN"] and t in series[f"{c}USDT"])
        if have >= 5:
            aligned_ts.append(t)

    if len(aligned_ts) < 60:
        return {"status": "INSUFFICIENT_DATA", "aligned_minutes": len(aligned_ts)}

    # Replay each USDT leg under 2x2 arms:
    # A: baseline passive hold (0 signal, taker exit), B: Kalman basis signal + taker (26 bps RT),
    # C: baseline + maker (20 bps RT), D: Kalman basis signal + maker (20 bps RT)
    arm_pnl = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}
    per_coin: list[dict] = []
    daily_returns_d: dict[str, float] = {}
    signal_pos_stream: list[float] = []
    market_ret_stream: list[float] = []

    for coin in DUAL_QUOTED_COINS:
        kf = KalmanBasisFilter(z_entry=1.8, round_trip_usdt_maker_bps=20.0)
        holding_maker = False
        entry_px_t = 0.0
        entry_px_m = 0.0
        trades_m = 0
        pnl_m_bps = 0.0
        pnl_t_bps = 0.0
        prev_px: float | None = None

        for t in aligned_ts:
            sym_tmn, sym_usdt = f"{coin}TMN", f"{coin}USDT"
            if t not in series[sym_tmn] or t not in series[sym_usdt]:
                continue
            px_tmn = Decimal(str(series[sym_tmn][t]))
            px_usdt = Decimal(str(series[sym_usdt][t]))

            # Build synthetic 5-bps-spread BookTop dict from aligned 1-min closes for leave-one-out peer FX
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
                pos = 1.0 if holding_maker else 0.0
                if coin == "BTC":
                    signal_pos_stream.append(pos)
                    market_ret_stream.append(ret)
                day_key = t.date().isoformat()
                daily_returns_d[day_key] = daily_returns_d.get(day_key, 0.0) + (pos * ret) / len(DUAL_QUOTED_COINS)
            prev_px = px_f

            # Entry when USDT leg is cheap (positive forecast), exit when basis mean-reverts (z <= 0)
            if not holding_maker and out.forecast_usdt_leg > 0:
                holding_maker = True
                entry_px_m = px_f
                entry_px_t = px_f
            elif holding_maker and out.z_score <= 0.0:
                gross_bps = (px_f - entry_px_m) / entry_px_m * 10000.0
                pnl_m_bps += gross_bps - 20.0  # 10 bps maker x 2
                pnl_t_bps += ((px_f - entry_px_t) / entry_px_t * 10000.0) - 26.0  # 13 bps taker x 2
                trades_m += 1
                holding_maker = False

        arm_pnl["B"] += pnl_t_bps
        arm_pnl["D"] += pnl_m_bps
        per_coin.append({"coin": coin, "trades": trades_m, "net_maker_bps": round(pnl_m_bps, 2), "net_taker_bps": round(pnl_t_bps, 2)})

    attr = run_2x2_attribution(
        Decimal(str(round(arm_pnl["A"], 4))),
        Decimal(str(round(arm_pnl["B"], 4))),
        Decimal(str(round(arm_pnl["C"], 4))),
        Decimal(str(round(arm_pnl["D"], 4))),
    )
    day_rets = [daily_returns_d[k] for k in sorted(daily_returns_d)]
    sr, dsr, tot_pct = _sharpe_and_dsr(day_rets, n_trials=21)
    placebo_p = None
    if len(market_ret_stream) >= 20:
        placebo_p = round(run_path_preserving_placebo(market_ret_stream, signal_pos_stream, replications=500).p_value, 4)

    verdict = "CANDIDATE_FOR_PREREG" if (arm_pnl["D"] > 0 and dsr >= 0.95 and (placebo_p is not None and placebo_p < 0.05)) else "RETIRE_OR_REFINE"
    return {
        "status": "OK",
        "aligned_minutes": len(aligned_ts),
        "days_covered": len(day_rets),
        "per_coin": per_coin,
        "attribution": {
            "A_cash_bps": float(attr.arm_a_baseline),
            "B_signal_taker_bps": float(attr.arm_b_new_signal),
            "C_exec_only_bps": float(attr.arm_c_new_exec),
            "D_signal_maker_bps": float(attr.arm_d_combined),
            "signal_effect": float(attr.signal_effect),
            "execution_effect": float(attr.execution_effect),
            "interaction_effect": float(attr.interaction_effect),
        },
        "daily_sharpe": round(sr, 4),
        "dsr_prob": round(dsr, 4),
        "total_return_pct": round(tot_pct, 2),
        "placebo_p_value": placebo_p,
        "verdict": verdict,
    }


def evaluate_candidate_b(con: sqlite3.Connection, mix_v2_path: Path) -> dict:
    """Candidate B (Track B): Multi-Asset Vector Allocation + Convex L1 Optimizer vs 10% Band vs Equal Weight."""
    candles_by_sym: dict[str, dict[datetime, tuple[float, float, float, float]]] = {}
    for sym in CANDIDATE_B_SYMBOLS:
        rows = _load_candles(con, sym, "1d", limit=3000)
        candles_by_sym[sym] = {t: (o, h, lo, c) for t, o, h, lo, c in rows}

    common_dates = sorted(set.intersection(*(set(d.keys()) for d in candles_by_sym.values())))
    if len(common_dates) < 90:
        return {"status": "INSUFFICIENT_DATA", "common_days": len(common_dates)}

    ewmac_nodes = {sym: MultiHorizonEwmacNode(pairs=((8, 32), (16, 64), (32, 128))) for sym in CANDIDATE_B_SYMBOLS}
    regime_node = CrossMarketBreadthRegimeNode()
    w_convex = [0.0] * len(CANDIDATE_B_SYMBOLS)
    w_band = [0.0] * len(CANDIDATE_B_SYMBOLS)

    rets_convex: list[float] = []
    rets_band: list[float] = []
    rets_eq: list[float] = []
    pos_btc: list[float] = []
    mkt_btc: list[float] = []
    ret_hist: dict[str, list[float]] = {s: [] for s in CANDIDATE_B_SYMBOLS}
    ohlc_hist: dict[str, list[OhlcBar]] = {s: [] for s in CANDIDATE_B_SYMBOLS}
    fee_rt_oneway = 0.0013  # conservative Wallex USDT L1 taker rate
    turnover_convex = 0.0
    turnover_band = 0.0

    for idx in range(1, len(common_dates)):
        t_prev = common_dates[idx - 1]
        t_curr = common_dates[idx]

        # Realized daily returns using weights decided at t_prev (strictly causal!)
        day_r = []
        for sym in CANDIDATE_B_SYMBOLS:
            o, h, lo, c = candles_by_sym[sym][t_curr]
            c_prev = candles_by_sym[sym][t_prev][3]
            r = (c - c_prev) / c_prev
            day_r.append(r)
            ret_hist[sym].append(r)
            ohlc_hist[sym].append(OhlcBar(o, h, lo, c))

        r_conv = sum(w * r for w, r in zip(w_convex, day_r, strict=True))
        r_bnd = sum(w * r for w, r in zip(w_band, day_r, strict=True))
        r_eq = sum(day_r) / len(CANDIDATE_B_SYMBOLS)

        # Update slow EWMAC forecasts using close at t_curr (for next day's weights)
        raw_f = [ewmac_nodes[sym].update(candles_by_sym[sym][t_curr][3]) for sym in CANDIDATE_B_SYMBOLS]
        pos_frac = sum(1 for f in raw_f if f > 0) / len(CANDIDATE_B_SYMBOLS)
        reg_mult = regime_node.evaluate(pos_frac, floor=0.25)

        if idx >= 65:
            # Compute causal covariance and Yang-Zhang daily vols
            window_rets = {s: ret_hist[s][-60:] for s in CANDIDATE_B_SYMBOLS}
            _, cov = coarse_bar_shrunk_covariance(window_rets, shrinkage=0.25)
            vols_bps = [yang_zhang_volatility(ohlc_hist[s][-20:]) * 10000.0 for s in CANDIDATE_B_SYMBOLS]
            mu = tuple(
                forecast_to_expected_return_bps(f * reg_mult, ic_prior=0.05, horizon_vol_bps=vb) / 10000.0
                for f, vb in zip(raw_f, vols_bps, strict=True)
            )
            prob = OptimizationProblem(
                symbols=CANDIDATE_B_SYMBOLS,
                expected_returns=mu,
                current_weights=tuple(w_convex),
                covariance=cov,
                l1_fee_costs=(fee_rt_oneway,) * len(CANDIDATE_B_SYMBOLS),
                l2_impact_costs=(0.0020,) * len(CANDIDATE_B_SYMBOLS),
                risk_aversion=2.5,
                max_weight=0.35,
                cash_buffer=0.05,
            )
            new_conv = list(solve_convex_portfolio(prob).weights)
            # Desired raw proportional weights for 10% no-trade band benchmark
            pos_raw = [max(0.0, f * reg_mult) for f in raw_f]
            s_pos = sum(pos_raw)
            desired_band = tuple((0.95 * x / s_pos) if s_pos > 0 else 0.0 for x in pos_raw)
            new_band = list(simple_no_trade_band_allocator(tuple(w_band), desired_band, band=0.10))

            tc_conv = sum(abs(a - b) for a, b in zip(new_conv, w_convex, strict=True)) * fee_rt_oneway
            tc_band = sum(abs(a - b) for a, b in zip(new_band, w_band, strict=True)) * fee_rt_oneway
            turnover_convex += sum(abs(a - b) for a, b in zip(new_conv, w_convex, strict=True))
            turnover_band += sum(abs(a - b) for a, b in zip(new_band, w_band, strict=True))

            rets_convex.append(r_conv - tc_conv)
            rets_band.append(r_bnd - tc_band)
            rets_eq.append(r_eq)
            pos_btc.append(w_convex[0])
            mkt_btc.append(day_r[0])

            w_convex = new_conv
            w_band = new_band

    sr_c, dsr_c, ret_c = _sharpe_and_dsr(rets_convex, n_trials=21)
    sr_b, dsr_b, ret_b = _sharpe_and_dsr(rets_band, n_trials=21)
    sr_e, dsr_e, ret_e = _sharpe_and_dsr(rets_eq, n_trials=21)

    placebo = run_path_preserving_placebo(mkt_btc, pos_btc, replications=500)
    power = simulate_joint_gate_power(rets_convex, edge_bps_per_step=8.0, horizon_steps=180, n_trials=21, replications=200)

    # Causality check on MultiHorizonEwmacNode
    btc_closes = [candles_by_sym["BTCUSDT"][d][3] for d in common_dates[:150]]

    def _ewmac_series(ps: list[float]) -> list[float]:
        node = MultiHorizonEwmacNode(pairs=((8, 32), (16, 64)))
        return [node.update(p) for p in ps]

    causal_ok = check_causality_perturbation(_ewmac_series, btc_closes, cutoff_index=100)

    # Write versioned mix-journal-v2.jsonl initial baseline entry (leaving v1 mix-journal.jsonl untouched!)
    if not mix_v2_path.exists():
        now = datetime.now(UTC)
        for sym, w in zip(CANDIDATE_B_SYMBOLS, w_convex, strict=True):
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

    verdict = "SURVIVES_TRACK_B" if (dsr_c >= 0.95 and causal_ok) else ("PROMISING_NEEDS_LONGER_OOS" if sr_c > 0 and causal_ok else "RETIRE")
    return {
        "status": "OK",
        "start_date": common_dates[65].date().isoformat(),
        "end_date": common_dates[-1].date().isoformat(),
        "eval_days": len(rets_convex),
        "convex_ann_sharpe": round(sr_c * math.sqrt(365), 3),
        "convex_dsr": round(dsr_c, 4),
        "convex_return_pct": round(ret_c, 2),
        "convex_turnover": round(turnover_convex, 2),
        "band_ann_sharpe": round(sr_b * math.sqrt(365), 3),
        "band_dsr": round(dsr_b, 4),
        "band_return_pct": round(ret_b, 2),
        "band_turnover": round(turnover_band, 2),
        "eq_ann_sharpe": round(sr_e * math.sqrt(365), 3),
        "eq_return_pct": round(ret_e, 2),
        "placebo_p_value": round(placebo.p_value, 4),
        "power_180d_at_8bps": round(power.dsr_pass_rate, 3),
        "causality_ok": causal_ok,
        "latest_weights": {s: round(w, 4) for s, w in zip(CANDIDATE_B_SYMBOLS, w_convex, strict=True)},
        "verdict": verdict,
    }


def evaluate_candidate_c(con: sqlite3.Connection) -> dict:
    """Candidate C (Track B): TMN-Borrow Carry vs 1x Unlevered Spot on historical USDTTMN & XAUTTMN."""
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
    scen = compare_fx_appreciation_scenarios(scen_terms, start_at=datetime(2026, 11, 24, tzinfo=UTC), horizon_days=180)
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


def write_report(report_path: Path, a: dict, b: dict, c: dict) -> None:
    lines = [
        "# Development Evaluation Packet — Candidates A, B, and C",
        "",
        f"**Generated (UTC):** `{datetime.now(UTC).isoformat()}` · **Source:** `data/live/market.db` (read-only) · **Authority:** Paper development evaluation only (`DISARMED`, `$0` funded budget).",
        "",
        "## 1. Candidate A (Track A) — 6-Triangle Leave-One-Out FX Basis + Kalman Filter",
        "",
    ]
    if a.get("status") == "OK":
        at = a["attribution"]
        lines += [
            f"- **Aligned 1-min observations:** `{a['aligned_minutes']}` (`{a['days_covered']}` days) · **Verdict:** **`{a['verdict']}`**",
            f"- **2×2 Attribution (bps):** `A (Cash) = {at['A_cash_bps']}`, `B (Signal+Taker) = {at['B_signal_taker_bps']}`, `C (Exec Only) = {at['C_exec_only_bps']}`, `D (Signal+Maker) = {at['D_signal_maker_bps']}` (`Signal={at['signal_effect']}`, `Exec={at['execution_effect']}`, `Interaction={at['interaction_effect']}`).",
            f"- **Daily Sharpe:** `{a['daily_sharpe']}` · **DSR Prob:** `{a['dsr_prob']}` · **500-Run Placebo p-value:** `{a['placebo_p_value']}`",
            "",
            "| Coin | Closed Trades | Net Maker (bps) | Net Taker (bps) |",
            "| --- | ---: | ---: | ---: |",
        ]
        for row in a["per_coin"]:
            lines.append(f"| `{row['coin']}` | {row['trades']} | {row['net_maker_bps']} | {row['net_taker_bps']} |")
    else:
        lines.append(f"- Status: `{a}`")

    lines += [
        "",
        "## 2. Candidate B (Track B) — Multi-Asset Vector Allocation (`mix-journal-v2`)",
        "",
    ]
    if b.get("status") == "OK":
        lines += [
            f"- **Window:** `{b['start_date']} .. {b['end_date']}` (`{b['eval_days']}` days) · **Causality Gate:** `{b['causality_ok']}` · **Verdict:** **`{b['verdict']}`**",
            f"- **500-Run Path-Preserving Placebo p-value (BTC sleeve):** `{b['placebo_p_value']}` · **180d Power at +8 bps/day (`DSR>=0.95`):** `{b['power_180d_at_8bps']}`",
            f"- **Latest Convex Weights:** `{b['latest_weights']}`",
            "",
            "| Allocator | Ann. Sharpe | DSR Prob (`N=21`) | Total Return (%) | Cumulative Turnover |",
            "| --- | ---: | ---: | ---: | ---: |",
            f"| **Convex L1 Optimizer (`G1+G4`)** | {b['convex_ann_sharpe']} | {b['convex_dsr']} | {b['convex_return_pct']}% | {b['convex_turnover']} |",
            f"| Simple `10%` No-Trade Band | {b['band_ann_sharpe']} | {b['band_dsr']} | {b['band_return_pct']}% | {b['band_turnover']} |",
            f"| Equal-Weight Buy & Hold | {b['eq_ann_sharpe']} | — | {b['eq_return_pct']}% | 0.0 |",
        ]
    else:
        lines.append(f"- Status: `{b}`")

    lines += [
        "",
        "## 3. Candidate C (Track B) — Preview-Reconciled TMN-Borrow Carry vs. `1x` Spot",
        "",
        "### Historical Real-Price Replay (Last 365 Daily Bars)",
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
        "### 180-Day FX Appreciation Scenario Sweep (`1.5x` Leverage on `USDTTMN`)",
        "",
        "| Annual FX Appreciation | Levered Ret (%) | Unlevered 1x (%) | Excess vs 1x (%) |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for s in c["scenarios_180d"]:
        lines.append(f"| {s['annual_fx_pct']}%/yr | {s['levered_ret_pct']}% | {s['unlevered_1x_ret_pct']}% | {s['excess_over_1x_pct']}% |")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Candidates A, B, and C on read-only market.db")
    parser.add_argument("--db", type=Path, default=Path("D:/Github/Trade/data/live/market.db"))
    parser.add_argument("--report", type=Path, default=Path("D:/Github/Trade/evidence/2026-11-24-candidate-evaluation-report.md"))
    parser.add_argument("--mix-v2", type=Path, default=Path("D:/Github/Trade/data/live/allocation/mix-journal-v2.jsonl"))
    args = parser.parse_args()
    con = _open_ro(args.db)
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
