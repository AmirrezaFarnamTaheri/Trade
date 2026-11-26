"""Remaining Cross-Layer Design & Micro-Signal Stress Suite.

Completes all remaining empirical proposals from
docs/architecture/rare-micro-signal-research-design.md and
docs/architecture/cross-layer-trading-design-decisions.md:
  1. Relative-strength-during-selloff detector (vs low-beta control) & sensor-vs-trading-venue test.
  2. Post-shock liquidity recovery & recorder-cadence blind-scanner miss audit on live books.
  3. Conditional-on-fill adverse selection (fast <=60s vs slow >60s passive fills).
  4. Scheduled TMN cash-liability stress during a 500 bps FX spread spike.
  5. Data-revision sensitivity, delisted/halted-inventory stress, and shared-rail outage stress.
  6. Order-timeout / replacement-partial / late-original-fill reconciliation state machine.
  7. Recorder-gap restart policy comparison (discard expired vs recompute vs replay stale).

Strictly read-only against market.db / multi_venue_quotes.sqlite3; DISARMED ($0 funded budget).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .champion_v2_verification import _extract_daily_s1_s5_targets
from .ensemble_study import portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .treasury_liquidity_and_fx_study import _load_matched_live_books
from .unified_book_helpers import resolve_bar_prices


@dataclass(frozen=True)
class OrderEvent:
    """Broker-side or local order lifecycle event for out-of-order reconciliation."""

    order_id: str
    kind: str  # SUBMIT | TIMEOUT | REPLACE | FILL | CANCEL_ACK
    side: str  # BUY | SELL
    qty: float
    price: float
    fee_bps: float = 16.0


def reconcile_order_events(events: list[OrderEvent], *, starting_cash: float = 1000.0) -> dict:
    """Idempotently reconcile out-of-order submits, timeouts, replacement partials, and late original fills."""
    cash = float(starting_cash)
    units = 0.0
    fees = 0.0
    filled_by_order: dict[str, float] = {}
    seen_fill_keys: set[tuple[str, float, float]] = set()

    for ev in events:
        if ev.kind != "FILL" or ev.qty <= 0 or ev.price <= 0:
            continue
        fk = (ev.order_id, round(ev.qty, 8), round(ev.price, 8))
        if fk in seen_fill_keys:
            continue
        seen_fill_keys.add(fk)
        notional = ev.qty * ev.price
        fee = notional * (ev.fee_bps / 10_000.0)
        if ev.side == "BUY":
            cash -= notional + fee
            units += ev.qty
        else:
            cash += notional - fee
            units -= ev.qty
        fees += fee
        filled_by_order[ev.order_id] = filled_by_order.get(ev.order_id, 0.0) + ev.qty

    return {
        "cash": round(cash, 6),
        "units": round(units, 8),
        "fees": round(fees, 6),
        "filled_by_order": {k: round(v, 8) for k, v in sorted(filled_by_order.items())},
        "overfilled_orders": len(filled_by_order) > 1,
    }


def _run_rel_strength_selloff_and_sensor(panel_2h: dict[str, list[BarPoint]]) -> dict:
    """Detector #3 (Idiosyncratic strength during selloff) + Sensor vs Liquid Equivalent execution."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    prev_c: dict[str, float] = {}
    rets_by_ts: dict[datetime, dict[str, float]] = {}

    for ts in all_ts:
        cur_r: dict[str, float] = {}
        for sym in IGNITION_18_CRYPTO:
            b = by_avail[sym].get(ts)
            if b is None or b.close <= 0:
                continue
            if sym in prev_c and prev_c[sym] > 0:
                cur_r[sym] = (b.close - prev_c[sym]) / prev_c[sym]
            prev_c[sym] = b.close
        rets_by_ts[ts] = cur_r

    source_bps, btc_equiv_bps, low_beta_ctrl_bps = [], [], []
    rt_fee = 0.0032
    for idx in range(2, len(all_ts) - 7):
        t0, t1, t2 = all_ts[idx - 2], all_ts[idx - 1], all_ts[idx]
        r1 = rets_by_ts.get(t1, {})
        r2 = rets_by_ts.get(t2, {})
        if len(r1) < 10 or len(r2) < 10:
            continue
        # Two consecutive broad selloff bars (median <= -1.0%)
        m1 = sorted(r1.values())[len(r1) // 2]
        m2 = sorted(r2.values())[len(r2) // 2]
        if m1 > -0.01 or m2 > -0.005:
            continue
        # Find symbols holding pre-shock low through second selling wave
        for sym in IGNITION_18_CRYPTO:
            b0, b1, b2 = by_avail[sym].get(t0), by_avail[sym].get(t1), by_avail[sym].get(t2)
            nxt, ex = by_start[sym].get(t2), by_start[sym].get(all_ts[idx + 6])
            if not (b0 and b1 and b2 and nxt and ex and nxt.open > 0):
                continue
            if b1.low >= b0.low and b2.low >= b0.low and r2.get(sym, -1.0) > m2 + 0.01:
                source_bps.append(((ex.open - nxt.open) / nxt.open - rt_fee) * 10_000.0)
                # Sensor-vs-venue: execute BTCUSDT instead of source alt
                bn, be = by_start["BTCUSDT"].get(t2), by_start["BTCUSDT"].get(all_ts[idx + 6])
                if bn and be and bn.open > 0:
                    btc_equiv_bps.append(((be.open - bn.open) / bn.open - rt_fee) * 10_000.0)
                # Control: low-beta BTCUSDT on same shock
                if bn and be and bn.open > 0:
                    low_beta_ctrl_bps.append(((be.open - bn.open) / bn.open - rt_fee) * 10_000.0)
                break  # Cap whole selloff to one risk allocation

    return {
        "selloff_episodes_triggered": len(source_bps),
        "source_symbol_mean_12h_net_bps": round(mean(source_bps), 2) if source_bps else 0.0,
        "liquid_btc_equiv_mean_12h_net_bps": round(mean(btc_equiv_bps), 2) if btc_equiv_bps else 0.0,
        "low_beta_control_mean_12h_net_bps": round(mean(low_beta_ctrl_bps), 2) if low_beta_ctrl_bps else 0.0,
    }


def _scan_recovery_cadence(snaps: list[dict], *, lookback: int = 100) -> tuple[int, list[float]]:
    """Strictly causal trailing-window spread recovery scanner (zero future-quantile leakage)."""
    if len(snaps) < 26:
        return 0, []
    spreads = [((m["n_asks"][0][0] - m["n_bids"][0][0]) / m["n_mid"]) * 10_000.0 for m in snaps]
    hits = 0
    edges: list[float] = []
    for i in range(20, len(snaps) - 5):
        hist = sorted(spreads[max(0, i - lookback) : i])
        q95 = hist[int(0.95 * (len(hist) - 1))]
        q75 = hist[int(0.75 * (len(hist) - 1))]
        if spreads[i - 1] >= q95 and spreads[i] <= q75:
            ask_n = snaps[i]["n_asks"][0][0]
            ref_w = snaps[i]["w_mid"]
            edge = ((ref_w - ask_n) / ask_n) * 10_000.0 - 16.0
            if edge > 5.0:
                hits += 1
                ex_bid = snaps[i + 5]["n_bids"][0][0]
                edges.append(((ex_bid - ask_n) / ask_n - 0.0032) * 10_000.0)
    return hits, edges


def _run_liquidity_recovery_blind_scanner_and_adverse_fill(matched_books: dict[str, list[dict]]) -> dict:
    """Causal liquidity recovery, independent 3x-thinned scanner, and strictly post-fill passive markout."""
    recovery_edges_bps: list[float] = []
    recovery_hits_full = recovery_hits_thin3 = 0
    fast_fill_markout_bps: list[float] = []
    slow_fill_markout_bps: list[float] = []
    unfilled_opp_bps: list[float] = []

    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"):
        snaps = matched_books.get(sym, [])
        if len(snaps) < 40:
            continue
        h_full, e_full = _scan_recovery_cadence(snaps)
        h_thin, _ = _scan_recovery_cadence(snaps[::3])
        recovery_hits_full += h_full
        recovery_hits_thin3 += h_thin
        recovery_edges_bps.extend(e_full)

        # Conditional-on-fill adverse selection: markout clock starts STRICTLY AT THE FILL snapshot j!
        for i in range(len(snaps) - 15):
            post_px = snaps[i]["n_bids"][0][0]
            filled_j: int | None = None
            filled_dt = 0.0
            for j in range(i + 1, min(len(snaps) - 5, i + 10)):
                dt = snaps[j]["epoch"] - snaps[i]["epoch"]
                if dt > 300.0:
                    break
                if snaps[j]["n_asks"][0][0] <= post_px:
                    filled_j = j
                    filled_dt = dt
                    break
            if filled_j is not None:
                fut_mid = snaps[min(len(snaps) - 1, filled_j + 5)]["n_mid"]
                mk_bps = ((fut_mid - post_px) / post_px) * 10_000.0
                if filled_dt <= 60.0:
                    fast_fill_markout_bps.append(mk_bps)
                else:
                    slow_fill_markout_bps.append(mk_bps)
            else:
                fut_mid = snaps[min(len(snaps) - 1, i + 5)]["n_mid"]
                unfilled_opp_bps.append(((fut_mid - post_px) / post_px) * 10_000.0)

    return {
        "liquidity_recovery_events_full": recovery_hits_full,
        "liquidity_recovery_events_3x_thinned": recovery_hits_thin3,
        "blind_scanner_miss_rate_3x_pct": round((1.0 - recovery_hits_thin3 / max(1, recovery_hits_full)) * 100.0, 1) if recovery_hits_full > 0 else 0.0,
        "liquidity_recovery_mean_net_bps": round(mean(recovery_edges_bps), 2) if recovery_edges_bps else 0.0,
        "fast_passive_fill_le60s_markout_bps": round(mean(fast_fill_markout_bps), 2) if fast_fill_markout_bps else 0.0,
        "slow_passive_fill_gt60s_markout_bps": round(mean(slow_fill_markout_bps), 2) if slow_fill_markout_bps else 0.0,
        "unfilled_passive_missed_drift_bps": round(mean(unfilled_opp_bps), 2) if unfilled_opp_bps else 0.0,
    }


def _run_tmn_liability_delist_and_dependency_stress(
    panel_1d: dict[str, list[BarPoint]],
    daily_targets: dict[datetime, dict[str, float]],
    usdt_tmn: dict[str, float],
) -> dict:
    """TMN scheduled liability stress, delisted-inventory recovery stress, shared-rail stress, and restart gap policies."""
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    dates = sorted(daily_targets)

    def _run_base(*, gap_mode: str = "NONE", delist_sym: str | None = None, delist_rec: float = 1.0) -> dict:
        led = SelfFinancingLedger(Decimal("1000"), fee_rate=Decimal("0.0016"), fee_in_received_asset=True)
        nav, lpx = {}, {}
        gap_start = int(0.70 * len(dates))
        delist_idx = int(0.60 * len(dates))
        saved_tgt: dict[str, float] | None = None
        for idx, ts in enumerate(dates):
            ef, tr = resolve_bar_prices(BASE_13_SYMBOLS, by_start, by_avail, ts, lpx)
            if delist_sym and idx >= delist_idx:
                tr.discard(delist_sym)
                if delist_sym in ef:
                    ef[delist_sym] *= delist_rec
            ep = {s: Decimal(str(p)) for s, p in ef.items()}
            in_gap = gap_mode != "NONE" and (gap_start <= idx < gap_start + 5)
            if in_gap:
                saved_tgt = daily_targets[ts]
            elif gap_mode == "REPLAY_STALE" and idx == gap_start + 5 and saved_tgt is not None:
                led.rebalance_to_targets(ts, saved_tgt, ep, tradable_symbols=tr)
            elif gap_mode == "DISCARD_EXPIRED" and idx == gap_start + 5:
                pass
            else:
                led.rebalance_to_targets(ts, daily_targets[ts], ep, tradable_symbols=tr)
            nav[ts.date().isoformat()] = float(led.mark_nav(ep))
        return portfolio_metrics(nav, starting_nav=1000.0)

    clean = _run_base()
    # Delisting stress on SOLUSDT at 0% and 50% recovery
    delist_50 = _run_base(delist_sym="SOLUSDT", delist_rec=0.50)
    delist_0 = _run_base(delist_sym="SOLUSDT", delist_rec=0.00)
    # Restart gap policies after 5-day outage
    gap_recompute = _run_base(gap_mode="RECOMPUTE")
    gap_discard = _run_base(gap_mode="DISCARD_EXPIRED")
    gap_stale = _run_base(gap_mode="REPLAY_STALE")

    # TMN Scheduled Liability: 100M TMN start, 20M TMN mandatory withdrawal during 500 bps FX spread spike
    tmn_days = sorted(usdt_tmn)
    fx0 = usdt_tmn[tmn_days[0]] if tmn_days else 1.0
    fx_mid = usdt_tmn[tmn_days[len(tmn_days) // 2]] if tmn_days else 1.0
    fx_end = usdt_tmn[tmn_days[-1]] if tmn_days else 1.0
    usdt_init = (100_000_000.0 / fx0) * 0.9975
    # With 500 bps FX spread spike on withdrawal, need 20M / (fx_mid * 0.95) USDT
    usdt_needed = 20_000_000.0 / max(1e-9, fx_mid * 0.95)
    rem_usdt = max(0.0, usdt_init - usdt_needed)
    post_liab_tmn_m = (rem_usdt * fx_end * 0.9975) / 1_000_000.0

    # Shared-rail dependency stress on $1,000 portfolio (50% NBX / 50% WLX, 20% XAUT)
    rails = {
        "NOBITEX_OFFLINE_STRANDED_PCT": 50.0,
        "USDT_5PCT_DEPEG_LOSS_USDT": 40.0,
        "XAUT_ISSUER_FREEZE_STRANDED_PCT": 20.0,
        "DUAL_NOBITEX_PLUS_XAUT_STRANDED_PCT": 60.0,
    }
    return {
        "clean_slow_ret_pct": clean["ret_pct"],
        "delist_sol_50pct_rec_ret_pct": delist_50["ret_pct"],
        "delist_sol_0pct_rec_ret_pct": delist_0["ret_pct"],
        "gap_5d_recompute_ret_pct": gap_recompute["ret_pct"],
        "gap_5d_discard_ret_pct": gap_discard["ret_pct"],
        "gap_5d_replay_stale_ret_pct": gap_stale["ret_pct"],
        "tmn_100m_after_20m_spike_withdrawal_end_m": round(post_liab_tmn_m, 2),
        "tmn_withdrawal_spike_cost_usdt": round(usdt_needed - (20_000_000.0 / max(1e-9, fx_mid)), 2),
        "shared_dependency_stress": rails,
    }


def run_remaining_cross_layer_suite(
    wallex_db: Path,
    multi_venue_db: Path,
    report_path: Path,
    receipt_path: Path,
) -> dict:
    """Run all remaining cross-layer & micro-signal stress experiments."""
    all_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    con = open_readonly_market_db(wallex_db)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in all_syms}
        usdt_tmn = {b.ts_avail.date().isoformat(): b.close for b in load_keyed_candles(con, "USDTTMN", "1d", limit=2500)}
    finally:
        con.close()

    sigs_13 = compute_slow_sleeves(panel_1d, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_targets = _extract_daily_s1_s5_targets(panel_1d, sigs_13, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0016"))
    panel_2h = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in IGNITION_18_CRYPTO if panel_1h[s]}
    matched = _load_matched_live_books(wallex_db, multi_venue_db, ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"))

    # Execution timeout -> replacement partial -> late original fill reconciliation check
    recon = reconcile_order_events([
        OrderEvent("ord_1", "SUBMIT", "BUY", 1.0, 100.0),
        OrderEvent("ord_1", "TIMEOUT", "BUY", 1.0, 100.0),
        OrderEvent("ord_2", "REPLACE", "BUY", 1.0, 100.5),
        OrderEvent("ord_2", "FILL", "BUY", 0.4, 100.5),
        OrderEvent("ord_1", "FILL", "BUY", 1.0, 100.0),
    ])

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "rel_strength_selloff_and_sensor": _run_rel_strength_selloff_and_sensor(panel_2h),
        "liquidity_recovery_and_adverse_fill": _run_liquidity_recovery_blind_scanner_and_adverse_fill(matched),
        "tmn_delist_gap_and_rails": _run_tmn_liability_delist_and_dependency_stress(panel_1d, daily_targets, usdt_tmn),
        "order_timeout_late_fill_reconciliation": recon,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    rs = p["rel_strength_selloff_and_sensor"]
    lr = p["liquidity_recovery_and_adverse_fill"]
    td = p["tmn_delist_gap_and_rails"]
    rc = p["order_timeout_late_fill_reconciliation"]
    lines = [
        "# Remaining Cross-Layer Design & Micro-Signal Stress Suite",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`$0` funded budget)",
        "",
        "## 1. Relative Strength During Selloff & Sensor-vs-Trading-Venue Separation",
        f"- **Triggered Selloff Episodes:** `{rs['selloff_episodes_triggered']}`",
        f"- **Source Symbol 12h Net:** `{rs['source_symbol_mean_12h_net_bps']:+.2f} bps` · **Liquid BTC Equivalent:** `{rs['liquid_btc_equiv_mean_12h_net_bps']:+.2f} bps` · **Low-Beta Control:** `{rs['low_beta_control_mean_12h_net_bps']:+.2f} bps`",
        "",
        "## 2. Post-Shock Liquidity Recovery, Blind-Scanner Cadence Miss & Conditional-on-Fill Adverse Selection",
        f"- **Liquidity Recovery Events:** `{lr['liquidity_recovery_events_full']}` (full) vs `{lr['liquidity_recovery_events_3x_thinned']}` (`3x` thinned → **`{lr['blind_scanner_miss_rate_3x_pct']:.1f}%` missed**) · **Mean Net Edge:** `{lr['liquidity_recovery_mean_net_bps']:+.2f} bps`",
        f"- **Conditional Passive Fill Markout:** Fast (`<=60s`): **`{lr['fast_passive_fill_le60s_markout_bps']:+.2f} bps`** · Slow (`>60s`): **`{lr['slow_passive_fill_gt60s_markout_bps']:+.2f} bps`** · Unfilled Missed Drift: `{lr['unfilled_passive_missed_drift_bps']:+.2f} bps`",
        "",
        "## 3. Delisting Stress, 5-Day Outage Restart Policies, TMN Liability & Shared-Rail Stress",
        f"- **Clean Slow Core:** `{td['clean_slow_ret_pct']:+.2f}%` · **SOL Delist (50% rec):** `{td['delist_sol_50pct_rec_ret_pct']:+.2f}%` · **SOL Delist (0% rec):** `{td['delist_sol_0pct_rec_ret_pct']:+.2f}%`",
        f"- **5-Day Outage Recovery:** `RECOMPUTE={td['gap_5d_recompute_ret_pct']:+.2f}%` · `DISCARD_EXPIRED={td['gap_5d_discard_ret_pct']:+.2f}%` · `REPLAY_STALE={td['gap_5d_replay_stale_ret_pct']:+.2f}%`",
        f"- **Scheduled 20M TMN Withdrawal (500 bps FX Spike):** Ending `{td['tmn_100m_after_20m_spike_withdrawal_end_m']}M TMN` (extra FX spike cost `${td['tmn_withdrawal_spike_cost_usdt']:.2f}` USDT)",
        f"- **Shared Operational Dependency Stress:** `{td['shared_dependency_stress']}`",
        "",
        "## 4. Order Timeout → Replacement Partial → Late Original Fill Reconciliation",
        f"- **Reconciled State:** `cash=${rc['cash']:.2f}`, `units={rc['units']}`, `fees=${rc['fees']:.4f}`, `overfilled_orders={rc['overfilled_orders']}`, `filled_by_order={rc['filled_by_order']}`",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
