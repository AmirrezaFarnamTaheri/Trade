"""Post-Repair Microstructure & Treasury Study (Menu Ideas 1, 6, and 11 + Dual-Clock Audit).

Implements the first three high-return post-repair paper experiments from
docs/architecture/2026-11-25-last-42-commits-review.md on the corrected zero-lookahead engine:
  - Idea 1: Signal expiry time / execution delay decay (0, 1, 2, 4 bars) on slow 1d trend vs 2h ignition.
  - Idea 6: Pricing the option to hold idle cash when slow spot and fast 2h ignition compete for capital.
  - Idea 11: Data-feed value ablation (masking L2-L5 depth, thinning snapshots 2x/5x) on live books.
  - Dual-Clock Readiness (Ideas 7 + 12): Coverage & timestamp audit for venue price discovery + prefunding.

Strictly read-only against market.db / multi_venue_quotes.sqlite3; DISARMED ($0 funded budget).
"""
from __future__ import annotations

import json
from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import mean, median

from ...adapters.candle_reader import load_keyed_candles, open_readonly_market_db
from ...domain.instrument_resolver import InstrumentOffer
from ...domain.model import dec, parse_ts
from ...domain.multi_asset_research import BASE_13_SYMBOLS
from ...domain.multi_horizon_book import MultiHorizonBook
from ...domain.paper_ledger import SelfFinancingLedger
from ...domain.short_and_levered_ignition import (
    _breakdown_or_breakout_z,
    _check_margin_exit,
)
from ...domain.strategy_sleeves import compute_slow_sleeves
from ...domain.timeframe_panel import BarPoint, resample_hourly_to_bucket
from .admm_helpers import extract_daily_breadth
from .champion_v2_verification import _extract_daily_s1_s5_targets
from .ensemble_study import STRESS_REPLAY_START, _portfolio_metrics
from .ignition_expansion_study import IGNITION_18_CRYPTO
from .smart_execution_sim import _evaluate_symbol_orders, _parse_levels
from .unified_book_helpers import (
    latest_signal_date,
    nav_ts_to_daily,
    resolve_bar_prices,
)


def _simulate_slow_with_delay(
    panel_1d: dict[str, list[BarPoint]],
    daily_targets: dict[datetime, dict[str, float]],
    delay_bars: int,
    *,
    fee_rate: Decimal = Decimal("0.0016"),
) -> dict:
    """Replay slow 1d S1+S5 targets executed after `delay_bars` daily bars (causal open fill)."""
    by_start = {s: {b.ts_start: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    by_avail = {s: {b.ts_avail: b for b in panel_1d.get(s, [])} for s in BASE_13_SYMBOLS}
    dates = sorted(daily_targets)
    ledger = SelfFinancingLedger(Decimal("1000"), fee_rate=fee_rate, fee_in_received_asset=True)
    nav_by_date: dict[str, float] = {}
    last_px: dict[str, float] = {}

    for idx, ts in enumerate(dates):
        exec_f, tradable = resolve_bar_prices(BASE_13_SYMBOLS, by_start, by_avail, ts, last_px)
        exec_px = {s: Decimal(str(p)) for s, p in exec_f.items()}
        src_idx = idx - delay_bars
        if src_idx >= 0:
            tgt = daily_targets[dates[src_idx]]
            ledger.rebalance_to_targets(ts, tgt, exec_px, tradable_symbols=tradable)
        nav_by_date[ts.date().isoformat()] = float(ledger.mark_nav(exec_px))

    m = _portfolio_metrics(nav_by_date)
    return {
        "sleeve": "SLOW_1D_S1_S5",
        "delay_bars": delay_bars,
        "delay_hours": delay_bars * 24,
        "ending_nav": m["ending_nav"],
        "ret_pct": m["ret_pct"],
        "ann_sharpe": m["ann_sharpe"],
        "max_dd_pct": m["max_dd_pct"],
        "fills": len(ledger.fills),
        "fees_usdt": round(float(ledger.total_fees_quote_equiv), 2),
    }


def _simulate_ignition_with_delay(
    panel_2h: dict[str, list[BarPoint]],
    daily_breadth: dict[str, float],
    delay_bars: int,
    *,
    leg_cost: float = 0.0016,
    max_hold_bars: int = 24,
) -> dict:
    """Replay identical 2h ignition intents delayed by `delay_bars` while keeping original exit deadline."""
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in IGNITION_18_CRYPTO}
    all_ts = sorted({t for d in by_avail.values() for t in d})

    ret_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
    vol_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
    high_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
    low_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
    prev_c: dict[str, float] = {}

    # Pending delayed orders: list of (exec_bar_index, sym, b_vol, orig_deadline_idx)
    pending: list[tuple[int, str, float, int]] = []
    equity = 1000.0
    active: dict[str, dict] = {}
    nav_by_date: dict[str, float] = {}
    entries = missed = wins = closed = 0
    total_fees = 0.0

    for bar_idx, ts in enumerate(all_ts):
        cands = []
        for sym in IGNITION_18_CRYPTO:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_c[sym]) / prev_c[sym]) if (sym in prev_c and prev_c[sym] > 0) else 0.0
            if cur.entry_eligible and nxt and nxt.open > 0 and sym not in active:
                hit = _breakdown_or_breakout_z(
                    cur, r, high_h[sym][-72:], low_h[sym][-72:], ret_h[sym][-36:], vol_h[sym][-36:],
                    side="LONG", breakout_bars=72, vol_lookback=36, z_threshold=3.0, vol_mult=2.5,
                )
                if hit is not None:
                    cands.append((hit[0], sym, hit[1]))
            if sym in prev_c and prev_c[sym] > 0:
                ret_h[sym].append(r)
            prev_c[sym] = cur.close
            vol_h[sym].append(cur.volume)
            high_h[sym].append(cur.high)
            low_h[sym].append(cur.low)

        # Exit active positions (respecting original deadline)
        for sym in list(active):
            pos = active[sym]
            rem_max = max(1, pos["deadline_idx"] - pos["entry_idx"])
            is_c, _, pnl, brw, fee = _check_margin_exit(
                pos, by_avail[sym].get(ts), by_start[sym].get(ts),
                side="LONG", leverage=1.0, max_hold_bars=rem_max, trail_stop_mult=2.5,
                hard_stop_pct=0.04, leg_cost=leg_cost, borrow_per_bar=0.0,
            )
            equity -= brw
            total_fees += fee
            if is_c:
                equity = max(0.0, equity + pnl)
                closed += 1
                if pnl - pos["entry_fee"] > 0:
                    wins += 1
                del active[sym]

        # Queue new signals at bar_idx + delay_bars with fixed original deadline bar_idx + max_hold_bars
        if daily_breadth.get(ts.date().isoformat(), 0.0) >= 0.45 and cands:
            cands.sort(key=lambda x: (-x[0], x[1]))
            for _, sym, b_vol in cands[:3]:
                pending.append((bar_idx + delay_bars, sym, b_vol, bar_idx + max_hold_bars))

        # Execute due orders
        due = [p for p in pending if p[0] <= bar_idx]
        pending = [p for p in pending if p[0] > bar_idx]
        for _, sym, b_vol, deadline_idx in due:
            if sym in active or len(active) >= 3 or equity <= 100.0:
                missed += 1
                continue
            nxt = by_start[sym].get(ts)
            if nxt is None or nxt.open <= 0 or bar_idx >= deadline_idx:
                missed += 1
                continue
            free_c = max(0.0, equity - sum(p["collateral"] for p in active.values()))
            col = min(equity * 0.30, free_c)
            if col < 25.0:
                missed += 1
                continue
            ef = col * leg_cost
            equity = max(0.0, equity - ef)
            total_fees += ef
            active[sym] = {
                "collateral": col, "notional": col, "qty": col / nxt.open,
                "entry_px": nxt.open, "entry_fee": ef, "extreme": nxt.open,
                "b_vol": b_vol, "liq_price": 0.0, "age": 0,
                "entry_idx": bar_idx, "deadline_idx": deadline_idx,
            }
            entries += 1

        mark_u = sum(
            max(-p["collateral"], p["qty"] * (by_avail[s][ts].close - p["entry_px"]))
            for s, p in active.items() if ts in by_avail[s] and by_avail[s][ts].close > 0
        )
        nav_by_date[ts.date().isoformat()] = max(0.0, equity + mark_u)

    m = _portfolio_metrics(nav_by_date)
    return {
        "sleeve": "IGNITION_2H_SPOT",
        "delay_bars": delay_bars,
        "delay_hours": delay_bars * 2,
        "ending_nav": m["ending_nav"],
        "ret_pct": m["ret_pct"],
        "ann_sharpe": m["ann_sharpe"],
        "max_dd_pct": m["max_dd_pct"],
        "entries": entries,
        "missed_or_expired": missed,
        "win_rate_pct": round(wins / max(1, closed) * 100.0, 1),
        "fees_usdt": round(total_fees, 2),
    }


def _step_ignition_lots_and_reserve(
    fast_book: MultiHorizonBook,
    exec_px: dict[str, float],
    leg_fee_bps: float,
) -> None:
    """Advance age and evaluate trailing/hard stops for active ignition_2h lots."""
    for key in list(fast_book.lots):
        if key[1] != "ignition_2h":
            continue
        lot = fast_book.lots[key]
        lot.age_bars += 1
        px = exec_px.get(lot.symbol, lot.entry_price)
        lot.peak_price = max(lot.peak_price, px)
        hit_stop = px <= lot.stop_price or px <= lot.peak_price * (1.0 - 2.5 * lot.entry_bar_vol)
        if lot.age_bars >= 24 or hit_stop:
            fast_book.close_lot(key, px, leg_fee_bps)


def _compute_reserve_frac(
    ts: datetime,
    trigger_times: list[datetime],
    *,
    fixed_reserve_frac: float | None,
    adaptive_arrival: bool,
    separate_accounts: bool,
) -> float:
    if separate_accounts:
        return 0.05
    if adaptive_arrival:
        cutoff = ts - timedelta(days=14)
        recent_n = sum(1 for t in trigger_times if t >= cutoff)
        return min(0.35, 0.05 + 0.06 * (recent_n / 14.0))
    return float(fixed_reserve_frac or 0.0)


def _simulate_cash_option_reserve(
    panel_2h: dict[str, list[BarPoint]],
    daily_targets: dict[datetime, dict[str, float]],
    daily_breadth: dict[str, float],
    *,
    label: str,
    fixed_reserve_frac: float | None = None,
    adaptive_arrival: bool = False,
    separate_accounts: bool = False,
    leg_fee_bps: float = 16.0,
) -> dict:
    """Idea 6: Compare fixed cash reserves, arrival-rate adaptive reserve, and separate 70/30 accounts."""
    all_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    by_avail = {s: {b.ts_avail: b for b in panel_2h.get(s, [])} for s in all_syms}
    by_start = {s: {b.ts_start: b for b in panel_2h.get(s, [])} for s in all_syms}
    all_ts = sorted({t for d in by_avail.values() for t in d})
    sig_dates = sorted(daily_targets)

    ret_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
    vol_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
    high_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
    low_h: dict[str, list[float]] = {s: [] for s in IGNITION_18_CRYPTO}
    prev_c: dict[str, float] = {}
    trigger_times: list[datetime] = []

    book = MultiHorizonBook(free_cash=700.0 if separate_accounts else 1000.0)
    fast_book = MultiHorizonBook(free_cash=300.0) if separate_accounts else book
    last_px: dict[str, float] = {}
    last_sig_applied: datetime | None = None
    nav_ts: dict[datetime, float] = {}
    idle_fracs: list[float] = []
    blocked_count = executed_ign = 0
    blocked_24h_rets: list[float] = []
    last_ts_idx = {t: i for i, t in enumerate(all_ts)}

    for _idx, ts in enumerate(all_ts):
        exec_px, tradable = resolve_bar_prices(all_syms, by_start, by_avail, ts, last_px)

        # Update ignition feature histories
        cands = []
        for sym in IGNITION_18_CRYPTO:
            cur, nxt = by_avail[sym].get(ts), by_start[sym].get(ts)
            if cur is None or cur.close <= 0:
                continue
            r = ((cur.close - prev_c[sym]) / prev_c[sym]) if (sym in prev_c and prev_c[sym] > 0) else 0.0
            if cur.entry_eligible and nxt and nxt.open > 0:
                hit = _breakdown_or_breakout_z(
                    cur, r, high_h[sym][-72:], low_h[sym][-72:], ret_h[sym][-36:], vol_h[sym][-36:],
                    side="LONG", breakout_bars=72, vol_lookback=36, z_threshold=3.0, vol_mult=2.5,
                )
                if hit is not None:
                    cands.append((hit[0], sym, hit[1]))
            if sym in prev_c and prev_c[sym] > 0:
                ret_h[sym].append(r)
            prev_c[sym] = cur.close
            vol_h[sym].append(cur.volume)
            high_h[sym].append(cur.high)
            low_h[sym].append(cur.low)

        _step_ignition_lots_and_reserve(fast_book, exec_px, leg_fee_bps)

        # Rebalance slow core daily with reserve floor
        cur_sig = latest_signal_date(sig_dates, ts)
        if cur_sig is not None and cur_sig != last_sig_applied:
            last_sig_applied = cur_sig
            reserve = _compute_reserve_frac(
                ts, trigger_times,
                fixed_reserve_frac=fixed_reserve_frac,
                adaptive_arrival=adaptive_arrival,
                separate_accounts=separate_accounts,
            )
            scale = max(0.0, 1.0 - reserve)
            scaled_tgt = {s: w * scale for s, w in daily_targets[cur_sig].items()}
            book.rebalance_slow_spot_targets(scaled_tgt, exec_px, tradable, ts, leg_fee_bps=leg_fee_bps)

        # Attempt fast ignition entries
        if daily_breadth.get(ts.date().isoformat(), 0.0) >= 0.45 and cands:
            trigger_times.append(ts)
            cands.sort(key=lambda x: (-x[0], x[1]))
            active_ign = sum(1 for k in fast_book.lots if k[1] == "ignition_2h")
            total_eq = book.mark_equity(exec_px) + (fast_book.mark_equity(exec_px) if separate_accounts else 0.0)
            for _, sym, b_vol in cands:
                if active_ign >= 3 or (sym, "ignition_2h") in fast_book.lots:
                    continue
                px = exec_px.get(sym, 0.0)
                if px <= 0:
                    continue
                req_col = (0.30 * fast_book.mark_equity(exec_px)) if separate_accounts else (0.10 * total_eq)
                if fast_book.free_cash < max(25.0, req_col * 0.5):
                    blocked_count += 1
                    # Counterfactual 24h net return of displaced trade
                    fut_i = min(len(all_ts) - 1, last_ts_idx[ts] + 12)
                    fut_bar = by_start[sym].get(all_ts[fut_i])
                    if fut_bar and fut_bar.open > 0:
                        r24 = (fut_bar.open - px) / px - (2.0 * leg_fee_bps / 10_000.0)
                        blocked_24h_rets.append(r24 * 100.0)
                    continue
                offer = InstrumentOffer(
                    venue="nobitex", symbol=sym, instrument_type="SPOT", direction=1,
                    allowed_leverages=(1.0,), entry_cost_bps=leg_fee_bps, exit_cost_bps=leg_fee_bps,
                    carry_model="NONE", carry_rate_bps=0.0,
                )
                ok = fast_book.open_fast_margin_lot(
                    symbol=sym, thesis_id="ignition_2h", direction=1, leverage=1.0,
                    target_collateral=req_col, entry_px=px, stop_bps=400.0, take_profit_bps=0.0,
                    offer=offer, ts=ts, entry_bar_vol=b_vol, entry_gru_score=0.0,
                    allow_internal_short_offset=False,
                )
                if ok:
                    executed_ign += 1
                    active_ign += 1

        eq_now = book.mark_equity(exec_px) + (fast_book.mark_equity(exec_px) if separate_accounts else 0.0)
        cash_now = book.free_cash + (fast_book.free_cash if separate_accounts else 0.0)
        if eq_now > 0:
            idle_fracs.append(cash_now / eq_now)
        nav_ts[ts] = eq_now

    daily = nav_ts_to_daily(nav_ts)
    m = _portfolio_metrics(daily)
    stress_iso = STRESS_REPLAY_START.date().isoformat()
    ms = _portfolio_metrics({k: v for k, v in daily.items() if k >= stress_iso})
    return {
        "label": label,
        "ending_nav": m["ending_nav"],
        "ret_pct": m["ret_pct"],
        "stress_ret_pct": ms["ret_pct"],
        "ann_sharpe": m["ann_sharpe"],
        "max_dd_pct": m["max_dd_pct"],
        "executed_ign": executed_ign,
        "blocked_ign": blocked_count,
        "blocked_mean_24h_net_pct": round(mean(blocked_24h_rets), 3) if blocked_24h_rets else 0.0,
        "avg_idle_cash_pct": round(mean(idle_fracs) * 100.0, 1) if idle_fracs else 0.0,
        "fees_usdt": round(book.total_fees + (fast_book.total_fees if separate_accounts else 0.0), 2),
    }


def _run_feed_value_ablation(wallex_db: Path, multi_venue_db: Path, *, max_skew_s: float = 15.0) -> dict:
    """Idea 11 + Dual-Clock Readiness: Mask L2-L5 depth and thin snapshots 2x/5x on matched live books."""
    if not wallex_db.exists() or not multi_venue_db.exists():
        return {"status": "MISSING_DB", "arms": [], "dual_clock": {}}

    wcon = open_readonly_market_db(wallex_db)
    mcon = open_readonly_market_db(multi_venue_db)
    try:
        cols = [r[1] for r in mcon.execute("PRAGMA table_info(venue_quotes)").fetchall()]
        vcounts = mcon.execute("SELECT venue, COUNT(*), MIN(ts_avail), MAX(ts_avail) FROM venue_quotes GROUP BY venue").fetchall()
        dual_clock = {
            "venue_quotes_columns": cols,
            "has_exchange_ts_event": "ts_event" in cols,
            "has_local_receipt_ts": "ts_avail" in cols,
            "venue_coverage": [
                {"venue": v, "rows": int(c), "min_ts": mn, "max_ts": mx} for v, c, mn, mx in vcounts
            ],
        }
        nbx_raw = mcon.execute(
            "SELECT symbol, ts_avail, bid, ask, bid_qty, ask_qty, depth_json "
            "FROM venue_quotes WHERE venue = 'nobitex' AND symbol LIKE '%USDT' ORDER BY ts_avail ASC"
        ).fetchall()
        by_sym: dict[str, list] = {}
        for rec in nbx_raw:
            by_sym.setdefault(rec[0], []).append(rec)

        matched_by_sym: dict[str, list[dict]] = {}
        for sym, n_list in sorted(by_sym.items()):
            inst = wcon.execute("SELECT instrument_id FROM instruments WHERE symbol = ?", (sym,)).fetchone()
            if inst is None:
                continue
            min_ts = (parse_ts(n_list[0][1]) - timedelta(seconds=max_skew_s)).isoformat().replace("+00:00", "Z")
            w_raw = wcon.execute(
                "SELECT ts_avail, bid, ask, bid_qty, ask_qty, depth "
                "FROM book_top WHERE instrument_id = ? AND ts_avail >= ? "
                "AND bid IS NOT NULL AND ask IS NOT NULL ORDER BY ts_avail ASC",
                (inst[0], min_ts),
            ).fetchall()
            if not w_raw:
                continue
            w_epochs = [parse_ts(r[0]).timestamp() for r in w_raw]
            matched: list[dict] = []
            for _, ts_s, nb, na, nbq, naq, ndepth in n_list:
                t_ep = parse_ts(ts_s).timestamp()
                cand = bisect_right(w_epochs, t_ep) - 1
                if cand < 0 or (t_ep - w_epochs[cand]) > max_skew_s:
                    continue
                _, wb_s, wa_s, wbq_s, waq_s, wdepth = w_raw[cand]
                wb, wa = float(dec(wb_s)), float(dec(wa_s))
                nb_f, na_f = float(dec(nb)), float(dec(na))
                w_bids, w_asks = _parse_levels(wdepth, wb, wa, float(dec(wbq_s or "0")), float(dec(waq_s or "0")))
                n_bids, n_asks = _parse_levels(ndepth, nb_f, na_f, float(dec(nbq or "0")), float(dec(naq or "0")))
                matched.append({
                    "epoch": t_ep, "w_mid": 0.5 * (wb + wa), "n_mid": 0.5 * (nb_f + na_f),
                    "w_bids": w_bids, "w_asks": w_asks, "n_bids": n_bids, "n_asks": n_asks,
                })
            if len(matched) >= 10:
                matched_by_sym[sym] = matched
    finally:
        wcon.close()
        mcon.close()

    arms_out: list[dict] = []
    for notional in (250.0, 1000.0):
        for arm_name, l1_only, step in (
            ("FULL_L5_1X", False, 1),
            ("MASK_L2_L5_L1_ONLY", True, 1),
            ("THIN_SNAPSHOTS_2X", False, 2),
            ("THIN_SNAPSHOTS_5X", False, 5),
        ):
            buy_smart, buy_asym, buy_pfill, nbx_fill, wlx_fill, nbx_win = [], [], [], [], [], []
            total_samps = 0
            for sym, ms in matched_by_sym.items():
                sub = ms[::step]
                if l1_only:
                    sub = [
                        {**m, "w_bids": m["w_bids"][:1], "w_asks": m["w_asks"][:1], "n_bids": m["n_bids"][:1], "n_asks": m["n_asks"][:1]}
                        for m in sub
                    ]
                if len(sub) < 5:
                    continue
                ev = _evaluate_symbol_orders(
                    sub, symbol=sym, notional=notional,
                    w_maker_bps=20.0, w_taker_bps=25.0, n_maker_bps=8.5, n_taker_bps=16.0,
                )
                total_samps += ev["samples"]
                buy_smart.append(ev["buy"]["smart_taker_bps"])
                buy_asym.append(ev["buy"]["asym_router_bps"])
                buy_pfill.append(ev["buy"]["passive_buy_fill_pct"])
                nbx_fill.append(ev["buy"]["nobitex_depth_fill_pct"])
                wlx_fill.append(ev["buy"]["wallex_depth_fill_pct"])
                nbx_win.append(ev["buy"]["nobitex_cheaper_pct"])
            arms_out.append({
                "notional_usdt": notional,
                "arm": arm_name,
                "symbols": len(buy_smart),
                "total_samples": total_samps,
                "med_smart_taker_bps": round(median(buy_smart), 2) if buy_smart else 0.0,
                "med_asym_router_bps": round(median(buy_asym), 2) if buy_asym else 0.0,
                "mean_passive_fill_pct": round(mean(buy_pfill), 1) if buy_pfill else 0.0,
                "mean_nbx_depth_fill_pct": round(mean(nbx_fill), 1) if nbx_fill else 0.0,
                "mean_wlx_depth_fill_pct": round(mean(wlx_fill), 1) if wlx_fill else 0.0,
                "mean_nbx_cheaper_pct": round(mean(nbx_win), 1) if nbx_win else 0.0,
            })
    return {"status": "OK", "arms": arms_out, "dual_clock": dual_clock}


def run_signal_expiry_cash_and_feed_study(
    wallex_db: Path,
    multi_venue_db: Path,
    report_path: Path,
    receipt_path: Path,
) -> dict:
    """Execute Menu Ideas 1, 6, and 11 + Dual-Clock readiness audit on the corrected zero-lookahead engine."""
    all_syms = tuple(dict.fromkeys(BASE_13_SYMBOLS + IGNITION_18_CRYPTO))
    con = open_readonly_market_db(wallex_db)
    try:
        panel_1d = {s: load_keyed_candles(con, s, "1d", limit=2500) for s in BASE_13_SYMBOLS}
        panel_1h = {s: load_keyed_candles(con, s, "1h", limit=26000) for s in all_syms}
    finally:
        con.close()

    sigs_13 = compute_slow_sleeves(panel_1d, BASE_13_SYMBOLS)
    eval_dates = [d for d in sorted(sigs_13) if d >= datetime(2022, 6, 1, tzinfo=UTC)]
    daily_breadth = extract_daily_breadth(sigs_13)
    daily_targets = _extract_daily_s1_s5_targets(panel_1d, sigs_13, eval_dates, BASE_13_SYMBOLS, fee_rate=Decimal("0.0016"))
    panel_2h = {s: resample_hourly_to_bucket(panel_1h[s], 2, offset_hours=0) for s in all_syms if panel_1h[s]}

    # Idea 1: Signal Expiry Decay (0, 1, 2, 4 bars)
    expiry_slow = [_simulate_slow_with_delay(panel_1d, daily_targets, d) for d in (0, 1, 2, 4)]
    expiry_ign = [_simulate_ignition_with_delay(panel_2h, daily_breadth, d) for d in (0, 1, 2, 4)]

    # Idea 6: Cash Option Value (fixed reserve grid, adaptive arrival reserve, separate 70/30 accounts)
    cash_arms = [
        _simulate_cash_option_reserve(panel_2h, daily_targets, daily_breadth, label="RESERVE_0PCT", fixed_reserve_frac=0.00),
        _simulate_cash_option_reserve(panel_2h, daily_targets, daily_breadth, label="RESERVE_10PCT", fixed_reserve_frac=0.10),
        _simulate_cash_option_reserve(panel_2h, daily_targets, daily_breadth, label="RESERVE_20PCT", fixed_reserve_frac=0.20),
        _simulate_cash_option_reserve(panel_2h, daily_targets, daily_breadth, label="RESERVE_30PCT", fixed_reserve_frac=0.30),
        _simulate_cash_option_reserve(panel_2h, daily_targets, daily_breadth, label="ADAPTIVE_ARRIVAL_RESERVE", adaptive_arrival=True),
        _simulate_cash_option_reserve(panel_2h, daily_targets, daily_breadth, label="SEPARATE_ACCOUNTS_70_30", separate_accounts=True),
    ]

    # Idea 11 + Dual-Clock Readiness
    feed_ablation = _run_feed_value_ablation(wallex_db, multi_venue_db)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "executor_state": "DISARMED",
        "idea_1_signal_expiry_slow_1d": expiry_slow,
        "idea_1_signal_expiry_ignition_2h": expiry_ign,
        "idea_6_cash_option_value": cash_arms,
        "idea_11_feed_value_ablation": feed_ablation,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report_path, payload)
    return payload


def _write_markdown(report_path: Path, p: dict) -> None:
    lines = [
        "# Post-Repair Microstructure & Treasury Study — Signal Expiry (Idea 1), Cash Option Value (Idea 6), Feed Ablation (Idea 11) & Dual-Clock Readiness",
        "",
        f"- **Generated:** `{p['generated_at']}` · **Executor:** `{p['executor_state']}` (`$0` funded budget)",
        "- **Engine:** Strictly post-repair zero-lookahead causal open execution & exact equity conservation.",
        "",
        "## Part 1 — Idea 1: Signal Expiry Time (Delay = 0, 1, 2, 4 Bars)",
        "",
        "### Slow 1d Trend (`BASE_13` S1+S5)",
        "| Delay (bars / h) | Ending NAV | Return | Ann. Sharpe | MaxDD | Fills | Fees ($) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in p["idea_1_signal_expiry_slow_1d"]:
        lines.append(
            f"| `{r['delay_bars']}d ({r['delay_hours']}h)` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['fills']}` | `${r['fees_usdt']:.2f}` |"
        )
    lines.extend([
        "",
        "### Fast 2h Ignition (`IGNITION_18_CRYPTO`, Fixed Original Exit Deadline)",
        "| Delay (bars / h) | Ending NAV | Return | Ann. Sharpe | MaxDD | Entries | Missed/Expired | Win% | Fees ($) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in p["idea_1_signal_expiry_ignition_2h"]:
        lines.append(
            f"| `{r['delay_bars']}b ({r['delay_hours']}h)` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['entries']}` | `{r['missed_or_expired']}` | `{r['win_rate_pct']:.1f}%` | `${r['fees_usdt']:.2f}` |"
        )
    lines.extend([
        "",
        "## Part 2 — Idea 6: Pricing the Option to Hold Idle Cash (Slow Spot vs. Fast 2h Ignition)",
        "",
        "| Policy | Ending NAV | Return | Bear Stress | Ann. Sharpe | MaxDD | Ign Exec | Ign Blocked | Blocked 24h Net | Avg Idle Cash | Fees ($) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in p["idea_6_cash_option_value"]:
        lines.append(
            f"| `{r['label']}` | `${r['ending_nav']:.2f}` | `{r['ret_pct']:+.2f}%` | `{r['stress_ret_pct']:+.2f}%` | `{r['ann_sharpe']:.3f}` | `{r['max_dd_pct']:.2f}%` | `{r['executed_ign']}` | `{r['blocked_ign']}` | `{r['blocked_mean_24h_net_pct']:+.3f}%` | `{r['avg_idle_cash_pct']:.1f}%` | `${r['fees_usdt']:.2f}` |"
        )
    lines.extend([
        "",
        "## Part 3 — Idea 11: Data-Feed Value Ablation (Mask L2-L5 & Thin Snapshots on Live Matched Books)",
        "",
        "| Notional | Feed Arm | Symbols | Samples | Med Smart Taker | Med Asym Router | Passive BUY Fill% | NBX Depth Fill% | WLX Depth Fill% | NBX Cheaper% |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for r in p["idea_11_feed_value_ablation"].get("arms", []):
        lines.append(
            f"| `${r['notional_usdt']:.0f}` | `{r['arm']}` | `{r['symbols']}` | `{r['total_samples']}` | `{r['med_smart_taker_bps']:+.2f}bp` | `{r['med_asym_router_bps']:+.2f}bp` | `{r['mean_passive_fill_pct']:.1f}%` | `{r['mean_nbx_depth_fill_pct']:.1f}%` | `{r['mean_wlx_depth_fill_pct']:.1f}%` | `{r['mean_nbx_cheaper_pct']:.1f}%` |"
        )
    dc = p["idea_11_feed_value_ablation"].get("dual_clock", {})
    lines.extend([
        "",
        "## Part 4 — Dual-Clock Readiness Audit (Ideas 7 + 12: Venue Price Discovery + Prefunding)",
        "",
        f"- **`venue_quotes` columns:** `{dc.get('venue_quotes_columns')}`",
        f"- **Exchange event clock (`ts_event`) present:** `{dc.get('has_exchange_ts_event')}` · **Local receipt clock (`ts_avail`) present:** `{dc.get('has_local_receipt_ts')}`",
    ])
    for vc in dc.get("venue_coverage", []):
        lines.append(f"- **`{vc['venue']}`:** `{vc['rows']:,}` quotes (`{vc['min_ts']}` -> `{vc['max_ts']}`)")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
